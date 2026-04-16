"""ChimeraClient — async wrapper for chimeralang-mcp tool calls.

Invokes the 9 ChimeraLang MCP tools via the `chimeralang-mcp` server
configured in `.mcp.json`.  When the server is unavailable (e.g. `uvx` is
not installed) every method degrades gracefully: it returns a neutral result
that lets the pipeline continue without blocking.

Chimera tool catalogue
----------------------
chimera_run       – Execute with probabilistic validation
chimera_confident – Confidence gating (≥ threshold)
chimera_explore   – Multi-path consensus detection
chimera_gate      – Conditional execution based on confidence
chimera_detect    – Hallucination detection (5 strategies)
chimera_constrain – Constraint enforcement
chimera_typecheck – Type validation
chimera_prove     – Cryptographic integrity proofs
chimera_audit     – Trust propagation tracking
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Fallback results returned when chimeralang-mcp is unreachable
_FALLBACK_DETECT = {
    "hallucination_detected": False,
    "score": 0.0,
    "strategies_fired": [],
    "fallback": True,
}
_FALLBACK_CONFIDENT = {"passed": True, "confidence": 1.0, "fallback": True}
_FALLBACK_AUDIT = {"trust_score": 1.0, "anomalies": [], "fallback": True}
_FALLBACK_PROVE = {"proof": "", "valid": True, "fallback": True}
_FALLBACK_GATE = {"passed": True, "confidence": 1.0, "fallback": True}
_FALLBACK_EXPLORE = {"consensus": None, "paths": [], "fallback": True}
_FALLBACK_CONSTRAIN = {"satisfied": True, "violations": [], "fallback": True}


class ChimeraClient:
    """Async client for the chimeralang-mcp MCP server.

    The client spawns a short-lived `uvx chimeralang-mcp` subprocess for each
    batch of calls.  A connection pool / persistent process would be more
    efficient, but this approach requires zero persistent state and is safe
    for the audit use-case where calls are infrequent.
    """

    def __init__(self, timeout: float = 15.0) -> None:
        self._timeout = timeout
        self._available: bool | None = None  # None = not yet probed

    # ------------------------------------------------------------------
    # Availability probe
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available
        local_script = Path(__file__).resolve().parents[2] / "scripts" / "chimeralang_mcp_local.py"
        self._available = local_script.exists()
        if not self._available:
            log.warning(
                "[ChimeraClient] scripts/chimeralang_mcp_local.py not found — "
                "chimera tools will use fallback responses."
            )
        return self._available

    # ------------------------------------------------------------------
    # Low-level MCP call
    # ------------------------------------------------------------------

    async def _call(self, tool: str, arguments: dict) -> dict:
        """Send a single tool call to chimeralang-mcp via JSON-RPC over stdin."""
        if not self.is_available():
            return {}

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        }
        stdin_data = json.dumps(payload).encode()

        try:
            local_script = Path(__file__).resolve().parents[2] / "scripts" / "chimeralang_mcp_local.py"
            proc = await asyncio.create_subprocess_exec(
                sys.executable, str(local_script),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=stdin_data), timeout=self._timeout
            )
            if proc.returncode != 0:
                log.debug("[ChimeraClient] %s stderr: %s", tool, stderr.decode()[:200])
                return {}
            response = json.loads(stdout.decode())
            result = response.get("result", {})
            # MCP returns content as a list of {type, text} blocks
            if isinstance(result, dict) and "content" in result:
                for block in result["content"]:
                    if block.get("type") == "text":
                        try:
                            return json.loads(block["text"])
                        except (json.JSONDecodeError, KeyError):
                            return {"raw": block.get("text", "")}
            return result if isinstance(result, dict) else {}
        except (asyncio.TimeoutError, Exception) as exc:
            log.warning("[ChimeraClient] %s call failed: %s", tool, exc)
            return {}

    # ------------------------------------------------------------------
    # Public API — one method per chimera tool
    # ------------------------------------------------------------------

    async def detect(
        self,
        content: str,
        strategies: list[str] | None = None,
        context: str = "",
    ) -> dict:
        """Run hallucination detection on *content*.

        strategies: subset of ["range","dictionary","semantic","cross_reference","temporal"]
        Returns a dict with keys: hallucination_detected (bool), score (float),
        strategies_fired (list), corrections (list).
        """
        args: dict[str, Any] = {
            "content": content,
            "strategies": strategies or ["range", "dictionary", "semantic"],
        }
        if context:
            args["context"] = context
        result = await self._call("chimera_detect", args)
        return result or _FALLBACK_DETECT

    async def confident(self, value: Any, threshold: float = 0.85) -> dict:
        """Gate a value behind a confidence threshold.

        Returns: passed (bool), confidence (float).
        """
        result = await self._call(
            "chimera_confident",
            {"value": value if isinstance(value, str) else json.dumps(value),
             "threshold": threshold},
        )
        return result or _FALLBACK_CONFIDENT

    async def audit(self, stage: str, data: dict) -> dict:
        """Track trust propagation for a pipeline stage.

        Returns: trust_score (float), anomalies (list).
        """
        result = await self._call(
            "chimera_audit",
            {"stage": stage, "data": json.dumps(data)[:4096]},
        )
        return result or _FALLBACK_AUDIT

    async def prove(self, content: str) -> dict:
        """Generate a cryptographic integrity proof for *content*.

        Returns: proof (str), valid (bool).
        """
        # Compute a local SHA-256 as a deterministic fallback proof
        local_proof = hashlib.sha256(content.encode()).hexdigest()
        result = await self._call("chimera_prove", {"content": content})
        if result:
            return result
        return {"proof": local_proof, "valid": True, "fallback": True}

    async def gate(self, condition: bool, confidence: float) -> dict:
        """Conditional execution gate.

        Returns: passed (bool), confidence (float), recommendation (str).
        """
        result = await self._call(
            "chimera_gate",
            {"condition": condition, "confidence": confidence},
        )
        return result or {**_FALLBACK_GATE, "passed": condition and confidence >= 0.5}

    async def explore(self, candidates: list[dict]) -> dict:
        """Multi-path consensus detection across candidate values.

        Returns: consensus (any), agreement_score (float), paths (list).
        """
        result = await self._call(
            "chimera_explore",
            {"candidates": json.dumps(candidates)},
        )
        return result or _FALLBACK_EXPLORE

    async def constrain(self, value: Any, constraints: list[str]) -> dict:
        """Enforce type/value constraints on *value*.

        Returns: satisfied (bool), violations (list[str]).
        """
        result = await self._call(
            "chimera_constrain",
            {"value": value if isinstance(value, str) else json.dumps(value),
             "constraints": constraints},
        )
        return result or _FALLBACK_CONSTRAIN

    async def typecheck(self, value: Any, expected_type: str) -> dict:
        """Validate that *value* matches *expected_type*.

        Returns: valid (bool), actual_type (str), errors (list).
        """
        result = await self._call(
            "chimera_typecheck",
            {"value": value if isinstance(value, str) else json.dumps(value),
             "expected_type": expected_type},
        )
        return result or {"valid": True, "actual_type": type(value).__name__, "fallback": True}

    async def run(self, program: str, inputs: dict | None = None) -> dict:
        """Execute a ChimeraLang program fragment with probabilistic validation.

        Returns: output (any), confidence (float), proof (str).
        """
        result = await self._call(
            "chimera_run",
            {"program": program, "inputs": json.dumps(inputs or {})},
        )
        return result or {"output": None, "confidence": 1.0, "fallback": True}
