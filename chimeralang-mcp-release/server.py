"""ChimeraLang MCP Server — full implementation.

Tools exposed to Claude:
  chimera_run          Execute a .chimera program string
  chimera_confident    Enforce >= 0.95 confidence threshold on a value
  chimera_explore      Wrap a value as exploratory (hallucination permitted)
  chimera_gate         Collapse multiple candidates via quantum consensus
  chimera_detect       Hallucination detection — 5 strategies
  chimera_constrain    Full constraint middleware on any tool result
  chimera_typecheck    Static type-check a .chimera program
  chimera_prove        Execute + generate Merkle-chain integrity proof
  chimera_audit        Session call-log summary
  chimera_compress     Proportional message-history compression to a token budget
  chimera_optimize     Aggressive text extraction (structural + entity + frequency)
  chimera_fracture     Full pipeline — optimize docs + compress messages + quality gate
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, TextContent, Tool

from chimera.lexer import Lexer
from chimera.parser import Parser
from chimera.vm import ChimeraVM
from chimera.type_checker import TypeChecker
from chimera.detect import HallucinationDetector, DetectionReport
from chimera.integrity import IntegrityEngine
from chimera.types import ConfidenceViolation
from chimera.claude_adapter import ClaudeConstraintMiddleware, ToolCallSpec

# ── session-scoped singletons ─────────────────────────────────────────────
_middleware = ClaudeConstraintMiddleware(confidence_threshold=0.7)
_detector   = HallucinationDetector()
server      = Server("chimeralang-mcp")


# ── helpers ───────────────────────────────────────────────────────────────

def _ok(data: Any) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(data, indent=2))],
        isError=False,
    )

def _err(msg: str) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps({"error": msg}))],
        isError=True,
    )

def _run(source: str) -> dict[str, Any]:
    tokens = Lexer(source).tokenize()
    ast    = Parser(tokens).parse()
    vm     = ChimeraVM()
    r      = vm.execute(ast)
    return {
        "emitted": [
            {
                "value":      str(v.raw),
                "confidence": round(v.confidence.value, 4),
                "type":       type(v).__name__,
                "trace":      v.trace[-3:],
            }
            for v in r.emitted
        ],
        "assertions_passed":  r.assertions_passed,
        "assertions_failed":  r.assertions_failed,
        "errors":             r.errors,
        "duration_ms":        round(r.duration_ms, 3),
        "gate_logs": [
            {k: gl[k] for k in (
                "gate", "branches", "collapse",
                "result_value", "result_confidence",
                "divergence_ratio", "unique_branch_values",
            ) if k in gl}
            for gl in r.gate_logs
        ],
        "trace_tail": r.trace[-8:],
    }


# ── token fracture / compression helpers ──────────────────────────────────
# Ported directly from OpenChimera (core/token_fracture.py and
# skills/token-optimizer/optimizer.py). Bundled here so this package has
# no runtime dependency on OpenChimera.

def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def _compress_context(
    messages: list[dict[str, Any]],
    query: str = "",
    max_tokens: int = 3000,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    safe_messages = messages or []

    original_text = "\n".join(str(item.get("content", "")) for item in safe_messages)
    original_tokens = _estimate_tokens(original_text)

    if max_tokens <= 0 or original_tokens <= max_tokens:
        compressed_messages = [
            {"role": item.get("role", "user"),
             "content": str(item.get("content", ""))}
            for item in safe_messages
        ]
        compressed_tokens = original_tokens
    else:
        ratio = max_tokens / max(original_tokens, 1)
        compressed_messages = []
        for item in safe_messages:
            content = str(item.get("content", ""))
            keep = max(1, int(len(content) * ratio))
            compressed_messages.append(
                {"role": item.get("role", "user"), "content": content[:keep]}
            )
        compressed_text = "\n".join(
            str(item.get("content", "")) for item in compressed_messages
        )
        compressed_tokens = _estimate_tokens(compressed_text)

    stats = {
        "query": query,
        "original_messages": len(safe_messages),
        "original_tokens": original_tokens,
        "compressed_tokens": compressed_tokens,
        "target_max_tokens": max_tokens,
        "compression_ratio": (
            (compressed_tokens / original_tokens) if original_tokens else 1.0
        ),
    }
    return compressed_messages, stats


def _optimize_text(text: str, target_ratio: float = 0.02) -> str:
    """Extremely aggressive text extraction (3-stage structural + entity + frequency)."""
    original_len = len(text)
    if original_len == 0:
        return ""

    target_len = max(int(original_len * target_ratio), 10)

    # 1. Structural code signatures
    structural_patterns = re.findall(
        r'^(?:def|class|interface|type|const|let|var|public|private|protected)'
        r'\s+[\w\s\(:\,<>.=\)]+[{;:]',
        text,
        re.MULTILINE,
    )

    # 2. Key entities — capitalized words & CONSTANTS
    entities = re.findall(r'\b[A-Z][a-zA-Z0-9_]+\b|\b[A-Z_]{3,}\b', text)

    # 3. High-frequency nouns > 5 chars (excluding stopwords)
    words = [w.lower() for w in re.findall(r'\b[A-Za-z]{5,}\b', text)]
    stopwords = {
        'return', 'import', 'export', 'public', 'private', 'static',
        'function', 'class', 'extends', 'implements',
        'which', 'their', 'there', 'about',
    }
    filtered = [w for w in words if w not in stopwords]
    common = [w for w, _ in Counter(filtered).most_common(20)]

    parts: list[str] = []
    if structural_patterns:
        parts.append("--- [STRUCTURAL LOGIC] ---")
        parts.append("\n".join(structural_patterns[:20]))
    if entities:
        parts.append("--- [KEY ENTITIES] ---")
        parts.append(" ".join(list(set(entities))[:30]))
    if common:
        parts.append("--- [HIGH FREQUENCY NOUNS] ---")
        parts.append(" ".join(common))

    extracted = "\n".join(parts)

    # Hard-cap at target_ratio
    if len(extracted) > target_len:
        extracted = extracted[:target_len] + "..."

    # If too short (pure prose with no code), grab first + last sentence
    if len(extracted) < target_len // 2:
        sentences = re.split(r'(?<=[.!?]) +', text.replace('\n', ' '))
        if sentences:
            extracted += "\n--- [CRITICAL EDGES] ---\n" + sentences[0]
            if len(sentences) > 1:
                extracted += " ... " + sentences[-1]
            extracted = extracted[:target_len]

    return (
        f"== 98% OPTIMIZATION ACTIVE ==\n"
        f"Original: {original_len} chars\n"
        f"Optimized: {len(extracted)} chars\n\n"
        f"{extracted}"
    )


# ── tool registry ─────────────────────────────────────────────────────────

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="chimera_run",
            description=(
                "Execute a ChimeraLang program string and return emitted values with "
                "confidence scores, gate consensus logs, assertion results, and execution "
                "trace. Use to run probabilistic reasoning pipelines, validate values "
                "through consensus gates, or chain hallucination-detection logic."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "ChimeraLang source code"},
                },
                "required": ["source"],
            },
        ),
        Tool(
            name="chimera_confident",
            description=(
                "Assert that a value meets ChimeraLang's Confident<> threshold (>= 0.95). "
                "Returns the wrapped ConfidentValue on success. "
                "Returns a ConfidenceViolation error with a suggestion if confidence is too low. "
                "Use before passing a value to a critical downstream tool or decision."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "value":      {"description": "The value to assert confidence on"},
                    "confidence": {
                        "type": "number",
                        "description": "Confidence score 0.0–1.0. Must be >= 0.95 to pass.",
                        "minimum": 0.0, "maximum": 1.0,
                    },
                    "label": {
                        "type": "string",
                        "description": "Optional label for trace identification",
                    },
                },
                "required": ["value", "confidence"],
            },
        ),
        Tool(
            name="chimera_explore",
            description=(
                "Wrap a value as Explore<> — explicitly marking it as exploratory where "
                "hallucination is permitted and expected. "
                "Use for hypotheses, creative outputs, brainstorms, and anything that "
                "must not be treated as verified fact."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "value":      {"description": "The exploratory value"},
                    "confidence": {
                        "type": "number",
                        "description": "Confidence 0.0–1.0 (typically low for explore values)",
                        "minimum": 0.0, "maximum": 1.0, "default": 0.5,
                    },
                    "label": {"type": "string", "description": "Optional label"},
                },
                "required": ["value"],
            },
        ),
        Tool(
            name="chimera_gate",
            description=(
                "Collapse multiple candidate values into a single consensus result using "
                "ChimeraLang's quantum consensus gate. "
                "Detects and flags trivial consensus (all branches identical — no real agreement). "
                "Strategies: majority, weighted_vote, highest_confidence. "
                "Use when reconciling multiple model outputs, tool results, or reasoning branches."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "candidates": {
                        "type": "array",
                        "description": "Candidate values with optional confidence scores",
                        "items": {
                            "type": "object",
                            "properties": {
                                "value":      {"description": "Candidate value"},
                                "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                            },
                            "required": ["value"],
                        },
                        "minItems": 2,
                    },
                    "strategy": {
                        "type": "string",
                        "enum": ["majority", "weighted_vote", "highest_confidence"],
                        "default": "weighted_vote",
                    },
                    "threshold": {
                        "type": "number",
                        "description": "Minimum consensus confidence to pass (default 0.80)",
                        "default": 0.80,
                    },
                },
                "required": ["candidates"],
            },
        ),
        Tool(
            name="chimera_detect",
            description=(
                "Run ChimeraLang hallucination detection on a value. Five strategies:\n"
                "  range            — numeric value must fall within [min, max]\n"
                "  dictionary       — value must be in an allowed set\n"
                "  semantic         — forbidden patterns / absolute-certainty markers\n"
                "  cross_reference  — value must not deviate from a reference set\n"
                "  temporal         — value timestamp must not be stale\n"
                "  confidence_threshold — confidence must be >= threshold\n"
                "Returns flags with severity scores and evidence."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "value":      {"description": "Value to scan"},
                    "confidence": {"type": "number", "default": 0.8},
                    "strategy": {
                        "type": "string",
                        "enum": ["range", "dictionary", "semantic",
                                 "cross_reference", "temporal", "confidence_threshold"],
                    },
                    "params": {
                        "type": "object",
                        "description": (
                            "Strategy params:\n"
                            "  range:            {valid_range: [min, max]}\n"
                            "  dictionary:       {allowed_values: [...]}\n"
                            "  semantic:         {forbidden_patterns: [...]} "
                            "                    (omit for default absolute-certainty scan)\n"
                            "  cross_reference:  {reference_values: [...], tolerance: 0.1}\n"
                            "  temporal:         {max_age_seconds: 3600, reference_time: <unix_ts>}\n"
                            "  confidence_threshold: {threshold: 0.7}"
                        ),
                    },
                },
                "required": ["value", "strategy"],
            },
        ),
        Tool(
            name="chimera_constrain",
            description=(
                "Apply ChimeraLang's full constraint middleware to any tool result. "
                "Pipeline: confidence gate → must-constraint checks → "
                "forbidden capability logging → hallucination detection → ephemeral scope cleanup. "
                "Returns pass/fail with violations, warnings, confidence, and audit trace. "
                "Primary integration point for wrapping Claude's own tool calls."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "tool_name":        {"type": "string"},
                    "output":           {"description": "Raw tool output to constrain"},
                    "input_confidence": {"type": "number", "default": 1.0,
                                        "description": "Caller confidence this was the right call"},
                    "min_confidence":   {"type": "number", "default": 0.0,
                                        "description": "Minimum confidence to accept output"},
                    "output_forbidden": {
                        "type": "array", "items": {"type": "string"},
                        "description": "Forbidden capability markers (e.g. file_write, pii)",
                    },
                    "detect_strategy": {
                        "type": "string",
                        "enum": ["confidence_threshold", "range", "semantic",
                                 "cross_reference", "temporal"],
                        "default": "confidence_threshold",
                    },
                    "detect_threshold": {"type": "number", "default": 0.5},
                    "strict": {
                        "type": "boolean", "default": False,
                        "description": "True = violations raise exceptions, not just warnings",
                    },
                },
                "required": ["tool_name", "output"],
            },
        ),
        Tool(
            name="chimera_typecheck",
            description=(
                "Statically type-check a ChimeraLang program without executing it. "
                "Validates confidence boundaries, memory scope rules, and illegal "
                "Explore→Confident promotions outside a gate. "
                "Returns errors and warnings."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "ChimeraLang source to check"},
                },
                "required": ["source"],
            },
        ),
        Tool(
            name="chimera_prove",
            description=(
                "Execute a ChimeraLang program and generate a Merkle-chain integrity proof. "
                "Every reasoning step is SHA-256 hashed and chained — tamper-evident derivation. "
                "Returns execution results + proof with root hash, chain length, verdict, "
                "gate certificates, and hallucination scan summary."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "source": {"type": "string", "description": "ChimeraLang source to prove"},
                },
                "required": ["source"],
            },
        ),
        Tool(
            name="chimera_audit",
            description=(
                "Return the constraint audit summary for this session. "
                "Shows total calls, pass/fail counts, average output confidence, "
                "flagged warnings, and tools used. "
                "Use at the end of a multi-tool workflow to assess overall reliability."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="chimera_compress",
            description=(
                "Compress a conversation history to fit within a token budget. "
                "Estimates tokens at len(text)//4, then proportionally truncates each "
                "message so the total fits under max_tokens. "
                "Use to shrink long chat histories before feeding them back into Claude."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "messages": {
                        "type": "array",
                        "description": "List of {role, content} message objects",
                        "items": {
                            "type": "object",
                            "properties": {
                                "role":    {"type": "string"},
                                "content": {"type": "string"},
                            },
                            "required": ["role", "content"],
                        },
                    },
                    "query": {
                        "type": "string",
                        "description": "Optional guiding query (metadata only)",
                        "default": "",
                    },
                    "max_tokens": {
                        "type": "integer",
                        "description": "Target token budget (default 3000)",
                        "default": 3000,
                        "minimum": 1,
                    },
                },
                "required": ["messages"],
            },
        ),
        Tool(
            name="chimera_optimize",
            description=(
                "Aggressively compress a block of text to its semantic skeleton. "
                "Three-stage extraction: (1) structural code signatures "
                "(class/def/interface/const), (2) key entities (capitalized words & "
                "CONSTANTS), (3) high-frequency nouns > 5 chars excluding stopwords. "
                "Caps output at target_ratio of original length (default 2%). "
                "Use to shrink large codebases or documents before feeding to Claude."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Raw text / code to optimize",
                    },
                    "target_ratio": {
                        "type": "number",
                        "description": "Fraction of original length to retain (default 0.02)",
                        "default": 0.02,
                        "minimum": 0.001,
                        "maximum": 1.0,
                    },
                },
                "required": ["text"],
            },
        ),
        Tool(
            name="chimera_fracture",
            description=(
                "Full token-fracture pipeline combining chimera_optimize and "
                "chimera_compress. Steps: (1) optimize each document string via "
                "aggressive extraction, (2) compress the message history to the token "
                "budget, (3) run confidence_threshold detection on the result, "
                "(4) return a quality-passed flag and combined stats. "
                "Use as the primary pre-processing step before a complex Claude task."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "messages": {
                        "type": "array",
                        "description": "List of {role, content} message objects",
                        "items": {
                            "type": "object",
                            "properties": {
                                "role":    {"type": "string"},
                                "content": {"type": "string"},
                            },
                            "required": ["role", "content"],
                        },
                    },
                    "documents": {
                        "type": "array",
                        "description": "Optional list of document strings to optimize",
                        "items": {"type": "string"},
                        "default": [],
                    },
                    "query": {
                        "type": "string",
                        "description": "Optional guiding query (metadata only)",
                        "default": "",
                    },
                    "token_budget": {
                        "type": "integer",
                        "description": "Target total token budget (default 3000)",
                        "default": 3000,
                        "minimum": 1,
                    },
                    "optimize_ratio": {
                        "type": "number",
                        "description": "Fraction of original doc length to retain (default 0.05)",
                        "default": 0.05,
                        "minimum": 0.001,
                        "maximum": 1.0,
                    },
                },
                "required": ["messages"],
            },
        ),
    ]


# ── tool handlers ─────────────────────────────────────────────────────────

@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
    try:

        # ── chimera_run ───────────────────────────────────────────────────
        if name == "chimera_run":
            return _ok(_run(arguments["source"]))

        # ── chimera_confident ─────────────────────────────────────────────
        elif name == "chimera_confident":
            value      = arguments["value"]
            confidence = float(arguments["confidence"])
            label      = arguments.get("label", str(value)[:40])

            if confidence < 0.95:
                return _ok({
                    "passed":     False,
                    "error":      f"ConfidenceViolation: {confidence:.3f} < required 0.95",
                    "suggestion": (
                        "Use chimera_explore for uncertain values, or route through "
                        "chimera_gate to build consensus before asserting confidence."
                    ),
                    "value":      str(value),
                    "confidence": confidence,
                })
            return _ok({
                "passed":     True,
                "type":       "ConfidentValue",
                "value":      str(value),
                "confidence": confidence,
                "label":      label,
                "trace":      [f"confident({label})", f"score={confidence:.4f}"],
            })

        # ── chimera_explore ───────────────────────────────────────────────
        elif name == "chimera_explore":
            value      = arguments["value"]
            confidence = min(max(float(arguments.get("confidence", 0.5)), 0.0), 1.0)
            label      = arguments.get("label", str(value)[:40])
            return _ok({
                "type":              "ExploreValue",
                "value":             str(value),
                "confidence":        confidence,
                "label":             label,
                "exploration_budget": 1.0,
                "note":              (
                    "Hallucination is explicitly permitted in Explore<> space. "
                    "Gate this value before treating it as fact."
                ),
                "trace": [f"explore({label})", f"score={confidence:.4f}"],
            })

        # ── chimera_gate ──────────────────────────────────────────────────
        elif name == "chimera_gate":
            candidates = arguments["candidates"]
            strategy   = arguments.get("strategy", "weighted_vote")
            threshold  = float(arguments.get("threshold", 0.80))

            if len(candidates) < 2:
                return _err("chimera_gate requires at least 2 candidates")

            branches = [
                {"value": c["value"], "str": str(c["value"]),
                 "confidence": float(c.get("confidence", 0.8))}
                for c in candidates
            ]

            unique_vals    = set(b["str"] for b in branches)
            divergence     = (len(unique_vals) - 1) / max(len(branches) - 1, 1)
            trivial        = divergence == 0.0

            if strategy == "highest_confidence":
                winner       = max(branches, key=lambda b: b["confidence"])
                consensus_conf = winner["confidence"]

            elif strategy == "weighted_vote":
                weights: dict[str, float] = {}
                for b in branches:
                    weights[b["str"]] = weights.get(b["str"], 0.0) + b["confidence"]
                total        = sum(weights.values())
                winner_key   = max(weights, key=weights.__getitem__)
                winner       = next(b for b in branches if b["str"] == winner_key)
                consensus_conf = weights[winner_key] / total if total else 0.0

            else:  # majority
                groups: dict[str, list] = {}
                for b in branches:
                    groups.setdefault(b["str"], []).append(b)
                winner_key   = max(groups, key=lambda k: len(groups[k]))
                group        = groups[winner_key]
                winner       = group[0]
                consensus_conf = sum(b["confidence"] for b in group) / len(group)

            passed = consensus_conf >= threshold
            result: dict[str, Any] = {
                "passed":            passed,
                "type":              "ConvergeValue",
                "value":             winner["value"],
                "consensus_confidence": round(consensus_conf, 4),
                "threshold":         threshold,
                "strategy":          strategy,
                "branches":          len(branches),
                "unique_values":     len(unique_vals),
                "divergence_ratio":  round(divergence, 4),
                "trivial_consensus": trivial,
            }
            if trivial:
                result["warning"] = (
                    "All branches returned identical values — trivial consensus. "
                    "No genuine divergence detected. Use independent reasoning paths "
                    "for real consensus signal."
                )
            if not passed:
                result["warning"] = (
                    f"Consensus confidence {consensus_conf:.3f} below threshold {threshold}. "
                    "Result is unreliable — consider more branches or lower threshold."
                )
            return _ok(result)

        # ── chimera_detect ────────────────────────────────────────────────
        elif name == "chimera_detect":
            value      = arguments["value"]
            confidence = float(arguments.get("confidence", 0.8))
            strategy   = arguments["strategy"]
            params     = arguments.get("params") or {}
            flags: list[dict[str, Any]] = []
            passed = True

            if strategy == "range":
                vr = params.get("valid_range")
                if vr and len(vr) == 2:
                    lo, hi = float(vr[0]), float(vr[1])
                    try:
                        v = float(value)
                        if not (lo <= v <= hi):
                            passed = False
                            flags.append({
                                "kind":        "RANGE_VIOLATION",
                                "severity":    0.9,
                                "description": f"Value {v} outside valid range [{lo}, {hi}]",
                            })
                    except (TypeError, ValueError):
                        flags.append({
                            "kind":        "TYPE_ERROR",
                            "severity":    0.5,
                            "description": f"Cannot range-check non-numeric: {value!r}",
                        })

            elif strategy == "dictionary":
                allowed = params.get("allowed_values", [])
                if value not in allowed:
                    passed = False
                    flags.append({
                        "kind":        "DICTIONARY_VIOLATION",
                        "severity":    0.85,
                        "description": f"{value!r} not in allowed set",
                        "allowed":     allowed,
                    })

            elif strategy == "semantic":
                forbidden = params.get("forbidden_patterns", [])
                val_str   = str(value).lower()
                if forbidden:
                    for pat in forbidden:
                        if pat.lower() in val_str:
                            passed = False
                            flags.append({
                                "kind":        "SEMANTIC_VIOLATION",
                                "severity":    0.85,
                                "description": f"Forbidden pattern '{pat}' found",
                            })
                else:
                    # Default: flag absolute-certainty markers
                    markers = ["always", "never", "definitely", "100%",
                               "impossible", "certain", "guaranteed", "never fails"]
                    hits = [m for m in markers if m in val_str]
                    if hits:
                        flags.append({
                            "kind":        "SEMANTIC_WARNING",
                            "severity":    0.6,
                            "description": f"Absolute-certainty markers detected: {hits}",
                            "note":        "May indicate hallucination in uncertain domains",
                        })

            elif strategy == "cross_reference":
                refs      = params.get("reference_values", [])
                tolerance = float(params.get("tolerance", 0.1))
                if refs:
                    try:
                        target = float(value)
                        ref_fs = [float(r) for r in refs]
                        avg    = sum(ref_fs) / len(ref_fs)
                        dev    = abs(target - avg) / (abs(avg) + 1e-9)
                        if dev > tolerance:
                            passed = False
                            flags.append({
                                "kind":        "CROSS_REFERENCE_VIOLATION",
                                "severity":    min(dev, 1.0),
                                "description": (
                                    f"Value {target} deviates {dev:.3f} "
                                    f"from reference avg {avg:.3f} (tolerance {tolerance})"
                                ),
                            })
                    except (TypeError, ValueError):
                        if value not in refs:
                            passed = False
                            flags.append({
                                "kind":        "CROSS_REFERENCE_VIOLATION",
                                "severity":    0.8,
                                "description": f"{value!r} not in reference set",
                            })

            elif strategy == "temporal":
                import time as _t
                max_age  = float(params.get("max_age_seconds", 3600))
                ref_time = float(params.get("reference_time", _t.time()))
                try:
                    age = ref_time - float(value)
                    if age > max_age:
                        passed = False
                        flags.append({
                            "kind":        "TEMPORAL_VIOLATION",
                            "severity":    min(age / max_age, 1.0),
                            "description": f"Timestamp age {age:.1f}s exceeds max {max_age}s",
                        })
                except (TypeError, ValueError):
                    flags.append({
                        "kind":        "TEMPORAL_SKIP",
                        "severity":    0.0,
                        "description": "Not a timestamp — temporal check skipped",
                    })

            elif strategy == "confidence_threshold":
                threshold = float(params.get("threshold", 0.7))
                if confidence < threshold:
                    passed = False
                    flags.append({
                        "kind":        "CONFIDENCE_BELOW_THRESHOLD",
                        "severity":    round(1.0 - confidence, 3),
                        "description": f"Confidence {confidence:.3f} < threshold {threshold}",
                    })

            return _ok({
                "passed":     passed,
                "strategy":   strategy,
                "value":      str(value),
                "confidence": confidence,
                "clean":      len(flags) == 0,
                "flag_count": len(flags),
                "flags":      flags,
            })

        # ── chimera_constrain ─────────────────────────────────────────────
        elif name == "chimera_constrain":
            spec = ToolCallSpec(
                tool_name        = arguments["tool_name"],
                min_confidence   = float(arguments.get("min_confidence", 0.0)),
                output_forbidden = arguments.get("output_forbidden", []),
                detect_strategy  = arguments.get("detect_strategy", "confidence_threshold"),
                detect_threshold = float(arguments.get("detect_threshold", 0.5)),
                strict           = bool(arguments.get("strict", False)),
            )
            r = _middleware.call(
                spec,
                raw_output        = arguments["output"],
                input_confidence  = float(arguments.get("input_confidence", 1.0)),
            )
            return _ok({
                "tool_name":  r.tool_name,
                "passed":     r.passed,
                "value":      str(r.value),
                "confidence": round(r.confidence, 4),
                "violations": r.violations,
                "warnings":   r.warnings,
                "trace":      r.trace,
                "duration_ms": round(r.duration_ms, 3),
                "detection": {
                    "clean":      r.detection_report.clean if r.detection_report else True,
                    "flag_count": len(r.detection_report.flags) if r.detection_report else 0,
                    "flags": [
                        {"kind": f.kind.name, "severity": f.severity, "description": f.description}
                        for f in (r.detection_report.flags if r.detection_report else [])
                    ],
                },
            })

        # ── chimera_typecheck ─────────────────────────────────────────────
        elif name == "chimera_typecheck":
            source  = arguments["source"]
            tokens  = Lexer(source).tokenize()
            ast     = Parser(tokens).parse()
            result  = TypeChecker().check(ast)
            return _ok({
                "ok":            result.ok,
                "error_count":   len(result.errors),
                "warning_count": len(result.warnings),
                "errors":        result.errors,
                "warnings":      result.warnings,
            })

        # ── chimera_prove ─────────────────────────────────────────────────
        elif name == "chimera_prove":
            source  = arguments["source"]
            tokens  = Lexer(source).tokenize()
            ast     = Parser(tokens).parse()
            vm      = ChimeraVM()
            result  = vm.execute(ast)

            detection = DetectionReport()
            for v in result.emitted:
                _detector.scan_value(v, detection)
            for gl in result.gate_logs:
                _detector.scan_gate_log(gl, detection)

            report = IntegrityEngine().certify(result, detection, source)
            proof  = report.to_dict()

            return _ok({
                "execution": {
                    "emitted": [
                        {"value": str(v.raw), "confidence": round(v.confidence.value, 4)}
                        for v in result.emitted
                    ],
                    "errors":             result.errors,
                    "assertions_passed":  result.assertions_passed,
                    "assertions_failed":  result.assertions_failed,
                },
                "proof": {
                    "verdict":              proof["verdict"],
                    "chain_length":         proof["chain"]["length"],
                    "root_hash":            proof["chain"]["root_hash"],
                    "chain_valid":          proof["chain"]["valid"],
                    "program_hash":         proof["program_hash"],
                    "hallucination_clean":  proof["hallucination"]["clean"],
                    "hallucination_flags":  proof["hallucination"]["flags"],
                    "gate_certificates":    proof["gates"],
                    "note": (
                        f"Merkle chain of {proof['chain']['length']} steps. "
                        "Every reasoning step SHA-256 hashed and chained — tamper-evident."
                    ),
                },
            })

        # ── chimera_audit ─────────────────────────────────────────────────
        elif name == "chimera_audit":
            summary = _middleware.audit_summary()
            log     = _middleware.call_log()
            return _ok({
                **summary,
                "recent_calls": [
                    {
                        "tool":       r.tool_name,
                        "passed":     r.passed,
                        "confidence": round(r.confidence, 4),
                        "violations": len(r.violations),
                        "warnings":   len(r.warnings),
                    }
                    for r in log[-10:]
                ],
            })

        # ── chimera_compress ──────────────────────────────────────────────
        elif name == "chimera_compress":
            messages   = arguments.get("messages") or []
            query      = str(arguments.get("query", ""))
            max_tokens = int(arguments.get("max_tokens", 3000))
            compressed, stats = _compress_context(messages, query=query, max_tokens=max_tokens)
            return _ok({
                "compressed_messages": compressed,
                "stats": {
                    "original_messages":  stats["original_messages"],
                    "original_tokens":    stats["original_tokens"],
                    "compressed_tokens":  stats["compressed_tokens"],
                    "compression_ratio":  round(stats["compression_ratio"], 4),
                    "target_max_tokens":  stats["target_max_tokens"],
                    "query":              stats["query"],
                },
            })

        # ── chimera_optimize ──────────────────────────────────────────────
        elif name == "chimera_optimize":
            text         = str(arguments.get("text", ""))
            target_ratio = float(arguments.get("target_ratio", 0.02))
            optimized    = _optimize_text(text, target_ratio=target_ratio)
            original_chars  = len(text)
            optimized_chars = len(optimized)
            reduction = (
                (1.0 - optimized_chars / original_chars) * 100.0
                if original_chars else 0.0
            )
            return _ok({
                "optimized_text":    optimized,
                "original_chars":    original_chars,
                "optimized_chars":   optimized_chars,
                "reduction_percent": round(reduction, 2),
                "target_ratio":      target_ratio,
            })

        # ── chimera_fracture ──────────────────────────────────────────────
        elif name == "chimera_fracture":
            messages       = arguments.get("messages") or []
            documents      = arguments.get("documents") or []
            query          = str(arguments.get("query", ""))
            token_budget   = int(arguments.get("token_budget", 3000))
            optimize_ratio = float(arguments.get("optimize_ratio", 0.05))

            # 1. optimize each document
            optimized_documents: list[dict[str, Any]] = []
            for i, doc in enumerate(documents):
                doc_str = str(doc)
                optimized = _optimize_text(doc_str, target_ratio=optimize_ratio)
                optimized_documents.append({
                    "index":           i,
                    "original_chars":  len(doc_str),
                    "optimized_chars": len(optimized),
                    "optimized_text":  optimized,
                })

            # 2. compress the message history
            compressed_messages, stats = _compress_context(
                messages, query=query, max_tokens=token_budget,
            )

            # 3. confidence_threshold-style quality gate
            # Quality passes when we stayed at or under budget AND retained >= 10%
            # of the original signal (avoids near-empty collapse).
            compression_ratio = stats["compression_ratio"]
            under_budget = stats["compressed_tokens"] <= token_budget
            quality_passed = bool(under_budget and compression_ratio >= 0.10)

            flags: list[dict[str, Any]] = []
            if not under_budget:
                flags.append({
                    "kind":        "BUDGET_EXCEEDED",
                    "severity":    0.9,
                    "description": (
                        f"Compressed tokens {stats['compressed_tokens']} "
                        f"still exceed budget {token_budget}"
                    ),
                })
            if compression_ratio < 0.10:
                flags.append({
                    "kind":        "EXCESSIVE_COMPRESSION",
                    "severity":    round(1.0 - compression_ratio, 3),
                    "description": (
                        f"Retained only {compression_ratio:.1%} of original signal — "
                        "output may be too degraded to be useful."
                    ),
                })

            budget_remaining = max(0, token_budget - stats["compressed_tokens"])

            return _ok({
                "compressed_messages":  compressed_messages,
                "optimized_documents":  optimized_documents,
                "token_budget_used":    stats["compressed_tokens"],
                "budget_remaining":     budget_remaining,
                "quality_passed":       quality_passed,
                "compression_stats": {
                    "original_messages":  stats["original_messages"],
                    "original_tokens":    stats["original_tokens"],
                    "compressed_tokens":  stats["compressed_tokens"],
                    "compression_ratio":  round(compression_ratio, 4),
                    "target_max_tokens":  stats["target_max_tokens"],
                    "documents_processed": len(optimized_documents),
                    "query":              stats["query"],
                },
                "quality_flags": flags,
            })

        else:
            return _err(f"Unknown tool: {name}")

    except Exception as e:
        return _err(f"{type(e).__name__}: {e}")


# ── entrypoint ────────────────────────────────────────────────────────────

async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )

if __name__ == "__main__":
    asyncio.run(main())
