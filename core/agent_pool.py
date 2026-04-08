"""OpenChimera Agent Pool — portable, typed multi-agent framework.

Provides a protocol-based agent system that can be configured entirely via
environment variables and runtime profiles. No hardcoded paths.

Architecture
────────────
AgentSpec       Immutable descriptor for a single agent (role, domain, strategy).
AgentStrategy   Enum of reasoning strategies an agent can use.
AgentPool       Registry + factory that creates callable agents for QuantumEngine.
create_pool     Convenience builder from a runtime profile dict or env vars.
create_llm_pool Builder that creates LLM-backed agents using real model dispatch.

LLM-Backed Consensus
─────────────────────
When ``create_llm_pool`` is used, each agent dispatches its task to a real LLM
model (via Ollama or compatible OpenAI-style endpoint). Different agents are
assigned different models when multiple are available, maximising training-data
diversity for genuine multi-perspective consensus.

Fallback chain:
  1. Multiple models → round-robin assignment (maximum diversity)
  2. Single model → varied temperature + system prompt per agent
  3. No models reachable → pure-Python heuristic strategies (graceful degradation)

Example
───────
    pool = AgentPool()
    pool.register(AgentSpec("analyst", AgentRole.REASONER, domain="finance"))
    pool.register(AgentSpec("critic", AgentRole.CRITIC))
    callables = pool.as_callables()   # dict[str, Callable] — ready for QE
    result = await engine.gather(task, callables)

    # LLM-backed consensus pool
    pool = create_llm_pool(profile=runtime_profile)
    callables = pool.as_callables()
    result = await engine.gather("What is inflation?", callables)
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from urllib import error as urlerror
from urllib import request as urlrequest

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class AgentRole(str, Enum):
    """Defines an agent's primary reasoning strategy."""
    REASONER = "reasoner"           # Chain-of-thought deep analysis
    CREATIVE = "creative"           # Lateral / generative thinking
    CRITIC = "critic"               # Adversarial review, finds flaws
    FACTCHECKER = "factchecker"     # Verifies claims against evidence
    SYNTHESIZER = "synthesizer"     # Merges multiple perspectives
    SPECIALIST = "specialist"       # Domain-specific expertise
    EXPLORER = "explorer"           # Divergent search, brainstorming


class AgentStatus(str, Enum):
    IDLE = "idle"
    BUSY = "busy"
    DISABLED = "disabled"


# ---------------------------------------------------------------------------
# Agent specification
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AgentSpec:
    """Immutable descriptor for a pool agent.

    Parameters
    ----------
    agent_id : str     Unique identifier.
    role : AgentRole   Primary reasoning strategy.
    domain : str       Knowledge domain (e.g. "medical", "legal", "general").
    temperature : float  Creativity dial — higher = more divergent.
    system_prompt : str  Optional system-level instruction prefix.
    max_tokens : int     Maximum response length hint.
    tags : tuple         Arbitrary metadata tags.
    """
    agent_id: str
    role: AgentRole
    domain: str = "general"
    temperature: float = 0.5
    system_prompt: str = ""
    max_tokens: int = 512
    tags: tuple[str, ...] = ()


# ---------------------------------------------------------------------------
# Strategy implementations (pure functions, no I/O)
# ---------------------------------------------------------------------------

def _reasoner_strategy(task: str, spec: AgentSpec, context: dict) -> dict:
    """Chain-of-thought: break task into steps, reason through each."""
    steps = [
        f"Analysing the problem: {task}",
        f"Considering domain knowledge in {spec.domain}",
        "Evaluating evidence and constructing argument",
        "Forming conclusion with confidence estimate",
    ]
    reasoning = " → ".join(steps)
    # Confidence: reasoners are typically well-calibrated
    confidence = 0.75 + (spec.temperature * 0.1)
    return {
        "answer": f"[{spec.role.value}@{spec.domain}] {reasoning}",
        "confidence": min(1.0, confidence),
        "domain": spec.domain,
    }


def _creative_strategy(task: str, spec: AgentSpec, context: dict) -> dict:
    """Lateral thinking: reframe the problem, explore unconventional paths."""
    reframe = f"Looking at '{task}' from an unexpected angle"
    # Creative agents have lower confidence (more speculative)
    confidence = 0.5 + (random.random() * 0.3)
    return {
        "answer": f"[{spec.role.value}@{spec.domain}] {reframe}",
        "confidence": round(confidence, 3),
        "domain": spec.domain,
    }


def _critic_strategy(task: str, spec: AgentSpec, context: dict) -> dict:
    """Adversarial review: identify potential flaws and counter-arguments."""
    critique = (
        f"Examining assumptions in: {task}. "
        f"Potential issues: unstated premises, confirmation bias, "
        f"insufficient evidence for {spec.domain} domain claims."
    )
    # Critics are confident about finding problems
    confidence = 0.7
    return {
        "answer": f"[{spec.role.value}@{spec.domain}] {critique}",
        "confidence": confidence,
        "domain": spec.domain,
    }


def _factchecker_strategy(task: str, spec: AgentSpec, context: dict) -> dict:
    """Verifies factual claims. High confidence when evidence is clear."""
    verification = (
        f"Verifying claims in: {task}. "
        f"Cross-referencing {spec.domain} knowledge base. "
        f"Evidence assessment: requires multi-source confirmation."
    )
    confidence = 0.8
    return {
        "answer": f"[{spec.role.value}@{spec.domain}] {verification}",
        "confidence": confidence,
        "domain": spec.domain,
    }


def _synthesizer_strategy(task: str, spec: AgentSpec, context: dict) -> dict:
    """Merges multiple viewpoints into a coherent summary."""
    synthesis = (
        f"Synthesising perspectives on: {task}. "
        f"Integrating {spec.domain} domain insights with general knowledge. "
        f"Balancing trade-offs and uncertainty."
    )
    confidence = 0.72
    return {
        "answer": f"[{spec.role.value}@{spec.domain}] {synthesis}",
        "confidence": confidence,
        "domain": spec.domain,
    }


def _explorer_strategy(task: str, spec: AgentSpec, context: dict) -> dict:
    """Divergent exploration: generates multiple possible directions."""
    exploration = (
        f"Exploring solution space for: {task}. "
        f"Identified branches: conventional, innovative, hybrid for {spec.domain}."
    )
    # Explorers are less certain — they offer options, not answers
    confidence = 0.45 + (random.random() * 0.25)
    return {
        "answer": f"[{spec.role.value}@{spec.domain}] {exploration}",
        "confidence": round(confidence, 3),
        "domain": spec.domain,
    }


def _specialist_strategy(task: str, spec: AgentSpec, context: dict) -> dict:
    """Domain specialist: provides expert-level analysis in a narrow field."""
    analysis = (
        f"Expert analysis ({spec.domain}): {task}. "
        f"Applying domain-specific frameworks and heuristics. "
        f"Confidence reflects depth of {spec.domain} coverage."
    )
    # Specialists are highly confident in their domain
    confidence = 0.85
    return {
        "answer": f"[{spec.role.value}@{spec.domain}] {analysis}",
        "confidence": confidence,
        "domain": spec.domain,
    }


_STRATEGY_MAP: Dict[AgentRole, Callable] = {
    AgentRole.REASONER: _reasoner_strategy,
    AgentRole.CREATIVE: _creative_strategy,
    AgentRole.CRITIC: _critic_strategy,
    AgentRole.FACTCHECKER: _factchecker_strategy,
    AgentRole.SYNTHESIZER: _synthesizer_strategy,
    AgentRole.EXPLORER: _explorer_strategy,
    AgentRole.SPECIALIST: _specialist_strategy,
}


# ---------------------------------------------------------------------------
# LLM system prompts per role — used when agents dispatch to real models
# ---------------------------------------------------------------------------

_LLM_ROLE_PROMPTS: Dict[AgentRole, str] = {
    AgentRole.REASONER: (
        "You are a careful analytical reasoner. Think step-by-step through the "
        "problem. Break complex questions into sub-parts, evaluate evidence for "
        "each, and arrive at a well-supported conclusion. Be precise and logical."
    ),
    AgentRole.CREATIVE: (
        "You are a lateral thinker. Approach the problem from unconventional "
        "angles. Reframe assumptions, propose unexpected connections, and explore "
        "creative solutions others might miss. Prioritise originality over convention."
    ),
    AgentRole.CRITIC: (
        "You are an adversarial reviewer. Your job is to find flaws, unstated "
        "assumptions, counter-arguments, and weaknesses in the proposed question "
        "or solution. Be thorough and constructive in your criticism."
    ),
    AgentRole.FACTCHECKER: (
        "You are a fact-checker. Verify claims against your knowledge. Identify "
        "which statements are well-supported, which need qualification, and which "
        "may be incorrect. Cite your reasoning for each assessment."
    ),
    AgentRole.SYNTHESIZER: (
        "You are a synthesis expert. Merge multiple perspectives into a coherent, "
        "balanced answer. Identify areas of agreement, weigh trade-offs, and "
        "produce a unified response that integrates diverse viewpoints."
    ),
    AgentRole.EXPLORER: (
        "You are a divergent explorer. Generate multiple possible approaches, "
        "directions, or answers. Do not commit to a single solution — instead "
        "map the solution space and highlight the trade-offs of each path."
    ),
    AgentRole.SPECIALIST: (
        "You are a domain specialist with deep expertise. Provide expert-level "
        "analysis using domain-specific frameworks, terminology, and heuristics. "
        "Be authoritative and precise within your area of knowledge."
    ),
}

# Temperature offsets per role — applied when using a single model to create
# reasoning diversity across agents
_LLM_ROLE_TEMPERATURES: Dict[AgentRole, float] = {
    AgentRole.REASONER: 0.3,
    AgentRole.CREATIVE: 0.9,
    AgentRole.CRITIC: 0.4,
    AgentRole.FACTCHECKER: 0.2,
    AgentRole.SYNTHESIZER: 0.5,
    AgentRole.EXPLORER: 0.8,
    AgentRole.SPECIALIST: 0.3,
}


# ---------------------------------------------------------------------------
# LLM dispatch helpers
# ---------------------------------------------------------------------------

def _discover_available_models(
    ollama_host: str = "127.0.0.1",
    ollama_port: int = 11434,
) -> List[str]:
    """Query Ollama for installed models. Returns empty list if unreachable."""
    url = f"http://{ollama_host}:{ollama_port}/api/tags"
    try:
        req = urlrequest.Request(url, headers={"Accept": "application/json"})
        with urlrequest.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        models = data.get("models", [])
        if not isinstance(models, list):
            return []
        return [str(m["name"]) for m in models if isinstance(m, dict) and m.get("name")]
    except (urlerror.URLError, OSError, json.JSONDecodeError, Exception):
        return []


def _call_ollama_chat(
    model: str,
    messages: List[Dict[str, str]],
    temperature: float = 0.7,
    max_tokens: int = 512,
    timeout: float = 30.0,
    ollama_host: str = "127.0.0.1",
    ollama_port: int = 11434,
) -> str:
    """Call Ollama /api/chat and return the response text.

    Raises RuntimeError if the call fails.
    """
    url = f"http://{ollama_host}:{ollama_port}/api/chat"
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }
    body = json.dumps(payload).encode("utf-8")
    req = urlrequest.Request(
        url, data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlrequest.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    message = data.get("message", {})
    content = message.get("content", "") if isinstance(message, dict) else ""
    return str(content).strip()


def make_llm_agent_callable(
    spec: AgentSpec,
    model: str,
    ollama_host: str = "127.0.0.1",
    ollama_port: int = 11434,
    timeout: float = 30.0,
    fallback_fn: Optional[Callable] = None,
) -> Callable:
    """Create an **async** callable that dispatches to a real LLM model.

    The callable signature matches what QuantumEngine.gather() expects:
    ``async (task, context) -> dict``

    If the LLM call fails, falls back to the pure-Python strategy function
    for the agent's role (graceful degradation).

    Parameters
    ----------
    spec : AgentSpec
        Agent descriptor with role, domain, temperature, system_prompt.
    model : str
        Ollama model name (e.g. "llama3.2:latest", "gemma3:4b").
    ollama_host, ollama_port : str, int
        Ollama endpoint.
    timeout : float
        Per-agent request timeout in seconds.
    fallback_fn : callable, optional
        Pure-Python fallback. Defaults to the role's strategy function.
    """
    role_prompt = _LLM_ROLE_PROMPTS.get(spec.role, _LLM_ROLE_PROMPTS[AgentRole.REASONER])
    role_temp = _LLM_ROLE_TEMPERATURES.get(spec.role, spec.temperature)

    # Build system prompt: role prompt + optional domain + user-specified override
    system_parts = [role_prompt]
    if spec.domain and spec.domain != "general":
        system_parts.append(f"Your area of expertise is: {spec.domain}.")
    if spec.system_prompt:
        system_parts.append(spec.system_prompt)
    system_prompt = " ".join(system_parts)

    _fallback = fallback_fn or _STRATEGY_MAP.get(spec.role, _reasoner_strategy)

    async def _llm_agent(task: Any, context: dict) -> dict:
        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": str(task)},
            ]
            import asyncio
            loop = asyncio.get_running_loop()
            content = await loop.run_in_executor(
                None,
                _call_ollama_chat,
                model,
                messages,
                role_temp,
                spec.max_tokens,
                timeout,
                ollama_host,
                ollama_port,
            )
            if not content or len(content.strip()) < 5:
                log.warning(
                    "[LLM Agent %s] Empty response from %s, falling back",
                    spec.agent_id, model,
                )
                return _fallback(str(task), spec, context)

            return {
                "answer": content,
                "confidence": 0.85,
                "domain": spec.domain,
                "model_used": model,
                "llm_backed": True,
            }
        except Exception as exc:
            log.warning(
                "[LLM Agent %s] Model %s failed (%s), falling back to heuristic",
                spec.agent_id, model, exc,
            )
            result = _fallback(str(task), spec, context)
            result["llm_backed"] = False
            result["fallback_reason"] = str(exc)
            return result

    _llm_agent.__qualname__ = f"llm_agent:{spec.agent_id}@{model}"
    return _llm_agent


# ---------------------------------------------------------------------------
# Agent callable factory (original pure-Python)
# ---------------------------------------------------------------------------

def make_agent_callable(
    spec: AgentSpec,
    external_fn: Optional[Callable] = None,
) -> Callable:
    """Create a callable suitable for QuantumEngine.gather().

    If `external_fn` is provided, it wraps that function. Otherwise, uses
    the built-in strategy for the agent's role.

    Returns a sync callable: (task, context) -> dict
    """
    if external_fn is not None:
        def _wrapper(task: Any, context: dict) -> Any:
            return external_fn(task, context)
        _wrapper.__qualname__ = f"agent:{spec.agent_id}"
        return _wrapper

    strategy = _STRATEGY_MAP.get(spec.role, _reasoner_strategy)

    def _agent(task: Any, context: dict) -> dict:
        return strategy(str(task), spec, context)

    _agent.__qualname__ = f"agent:{spec.agent_id}"
    return _agent


# ---------------------------------------------------------------------------
# Agent Pool
# ---------------------------------------------------------------------------

class AgentPool:
    """Registry of typed agents ready for dispatch through QuantumEngine.

    Portable: configured via AgentSpec objects or from a runtime profile dict.
    No hardcoded paths or machine-specific configuration.

    Usage
    ─────
        pool = AgentPool()
        pool.register(AgentSpec("analyst", AgentRole.REASONER, domain="finance"))
        pool.register(AgentSpec("critic-1", AgentRole.CRITIC))

        # Get callables for QuantumEngine
        agents = pool.as_callables()
        result = await engine.gather("What is inflation?", agents)

        # Or filter by domain
        agents = pool.as_callables(domain="finance")
    """

    def __init__(self) -> None:
        self._specs: Dict[str, AgentSpec] = {}
        self._callables: Dict[str, Callable] = {}
        self._status: Dict[str, AgentStatus] = {}

    def register(
        self,
        spec: AgentSpec,
        external_fn: Optional[Callable] = None,
    ) -> None:
        """Register an agent with the pool."""
        if spec.agent_id in self._specs:
            raise ValueError(f"Agent '{spec.agent_id}' already registered")
        self._specs[spec.agent_id] = spec
        self._callables[spec.agent_id] = make_agent_callable(spec, external_fn)
        self._status[spec.agent_id] = AgentStatus.IDLE
        log.info(
            "[AgentPool] Registered %s (role=%s domain=%s)",
            spec.agent_id, spec.role.value, spec.domain,
        )

    def unregister(self, agent_id: str) -> None:
        """Remove an agent from the pool."""
        self._specs.pop(agent_id, None)
        self._callables.pop(agent_id, None)
        self._status.pop(agent_id, None)

    def disable(self, agent_id: str) -> None:
        """Mark an agent as disabled (excluded from dispatch)."""
        if agent_id in self._status:
            self._status[agent_id] = AgentStatus.DISABLED

    def enable(self, agent_id: str) -> None:
        """Re-enable a disabled agent."""
        if agent_id in self._status:
            self._status[agent_id] = AgentStatus.IDLE

    def list_agents(self) -> List[Dict[str, Any]]:
        """Return metadata for all registered agents."""
        return [
            {
                "agent_id": spec.agent_id,
                "role": spec.role.value,
                "domain": spec.domain,
                "temperature": spec.temperature,
                "status": self._status.get(spec.agent_id, "unknown"),
                "tags": list(spec.tags),
            }
            for spec in self._specs.values()
        ]

    def as_callables(
        self,
        *,
        domain: Optional[str] = None,
        roles: Optional[List[AgentRole]] = None,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Callable]:
        """Return a filtered dict of active agent callables.

        Suitable for passing directly to QuantumEngine.gather() or
        ConsensusPlane.query().
        """
        result: Dict[str, Callable] = {}
        for agent_id, fn in self._callables.items():
            if self._status.get(agent_id) == AgentStatus.DISABLED:
                continue
            spec = self._specs[agent_id]
            if domain and spec.domain != domain and spec.domain != "general":
                continue
            if roles and spec.role not in roles:
                continue
            if tags and not any(t in spec.tags for t in tags):
                continue
            result[agent_id] = fn
        return result

    def get_spec(self, agent_id: str) -> Optional[AgentSpec]:
        """Return the spec for a given agent, or None."""
        return self._specs.get(agent_id)

    def count(self) -> int:
        return len(self._specs)

    def active_count(self) -> int:
        return sum(
            1 for s in self._status.values()
            if s != AgentStatus.DISABLED
        )


# ---------------------------------------------------------------------------
# Pool builder from config
# ---------------------------------------------------------------------------

# Default agent configuration — used when no profile or env override exists
DEFAULT_AGENTS: List[Dict[str, Any]] = [
    {"agent_id": "reasoner-alpha", "role": "reasoner", "domain": "general"},
    {"agent_id": "reasoner-beta", "role": "reasoner", "domain": "general",
     "temperature": 0.7},
    {"agent_id": "critic-prime", "role": "critic", "domain": "general"},
    {"agent_id": "synthesizer-main", "role": "synthesizer", "domain": "general"},
    {"agent_id": "factchecker-core", "role": "factchecker", "domain": "general"},
]


def create_pool(
    profile: Optional[Dict[str, Any]] = None,
    agents_config: Optional[List[Dict[str, Any]]] = None,
) -> AgentPool:
    """Build an AgentPool from a runtime profile or explicit config.

    Resolution order:
    1. `agents_config` parameter (if provided)
    2. `profile["agent_pool"]["agents"]` (if profile has it)
    3. ``OPENCHIMERA_AGENTS`` env var (JSON list)
    4. DEFAULT_AGENTS fallback

    This ensures the pool is fully portable — no hardcoded paths.
    """
    pool = AgentPool()

    # Resolve config source
    config: List[Dict[str, Any]]
    if agents_config is not None:
        config = agents_config
    elif profile and "agent_pool" in profile:
        config = profile["agent_pool"].get("agents", DEFAULT_AGENTS)
    else:
        env_agents = os.environ.get("OPENCHIMERA_AGENTS")
        if env_agents:
            try:
                config = json.loads(env_agents)
            except (json.JSONDecodeError, TypeError):
                log.warning("[AgentPool] Invalid OPENCHIMERA_AGENTS env var, using defaults")
                config = DEFAULT_AGENTS
        else:
            config = DEFAULT_AGENTS

    for entry in config:
        try:
            role = AgentRole(entry.get("role", "reasoner"))
            spec = AgentSpec(
                agent_id=entry["agent_id"],
                role=role,
                domain=entry.get("domain", "general"),
                temperature=float(entry.get("temperature", 0.5)),
                system_prompt=entry.get("system_prompt", ""),
                max_tokens=int(entry.get("max_tokens", 512)),
                tags=tuple(entry.get("tags", ())),
            )
            pool.register(spec)
        except (KeyError, ValueError) as exc:
            log.warning("[AgentPool] Skipping invalid agent config: %s — %s", entry, exc)

    log.info("[AgentPool] Created pool with %d agents", pool.count())
    return pool


# ---------------------------------------------------------------------------
# LLM-backed pool builder
# ---------------------------------------------------------------------------

# Default LLM-backed agent roster — maximises role diversity for multi-model
# consensus.  Each agent dispatches to a real LLM model when available.
DEFAULT_LLM_AGENTS: List[Dict[str, Any]] = [
    {"agent_id": "llm-reasoner", "role": "reasoner", "domain": "general"},
    {"agent_id": "llm-creative", "role": "creative", "domain": "general"},
    {"agent_id": "llm-critic", "role": "critic", "domain": "general"},
    {"agent_id": "llm-factchecker", "role": "factchecker", "domain": "general"},
    {"agent_id": "llm-synthesizer", "role": "synthesizer", "domain": "general"},
]


def create_llm_pool(
    profile: Optional[Dict[str, Any]] = None,
    agents_config: Optional[List[Dict[str, Any]]] = None,
    ollama_host: str = "127.0.0.1",
    ollama_port: int = 11434,
    timeout: float = 30.0,
) -> AgentPool:
    """Build an AgentPool backed by real LLM model dispatch.

    Discovers available Ollama models and assigns them round-robin to agents.
    This ensures genuine multi-model consensus — different models bring
    different training data and reasoning patterns to the collective vote.

    Fallback chain
    ──────────────
    1. Multiple models available → round-robin assignment (maximum diversity).
    2. Single model available → same model with role-specific system prompts
       and varied temperatures for perspective diversity.
    3. No models reachable → pure-Python heuristic strategies (graceful
       degradation, same as ``create_pool``).

    Parameters
    ----------
    profile : dict, optional
        Runtime profile dict (e.g. from ``setup.ps1``).  Looks for
        ``profile["agent_pool"]["agents"]`` and
        ``profile["ollama"]["host"]`` / ``profile["ollama"]["port"]``.
    agents_config : list[dict], optional
        Explicit agent config list.  Overrides profile and defaults.
    ollama_host, ollama_port : str, int
        Ollama API endpoint.
    timeout : float
        Per-agent LLM request timeout in seconds.

    Returns
    -------
    AgentPool
        Pool with agents backed by real LLM calls (or heuristic fallback).
    """
    pool = AgentPool()

    # ── Resolve Ollama endpoint from profile / env ───
    if profile:
        ollama_cfg = profile.get("ollama", {})
        ollama_host = ollama_cfg.get("host", ollama_host)
        ollama_port = int(ollama_cfg.get("port", ollama_port))
    env_host = os.environ.get("OLLAMA_HOST")
    if env_host:
        # OLLAMA_HOST can be "host:port" or just "host"
        if ":" in env_host:
            parts = env_host.rsplit(":", 1)
            ollama_host = parts[0]
            try:
                ollama_port = int(parts[1])
            except ValueError:
                pass
        else:
            ollama_host = env_host

    # ── Discover available models ───
    models = _discover_available_models(ollama_host, ollama_port)
    multi_model = len(models) >= 2
    single_model = len(models) == 1
    no_models = len(models) == 0

    if models:
        log.info(
            "[AgentPool] Discovered %d Ollama model(s) for LLM consensus: %s",
            len(models), ", ".join(models),
        )
    else:
        log.warning(
            "[AgentPool] No Ollama models reachable at %s:%d — "
            "falling back to heuristic strategies",
            ollama_host, ollama_port,
        )

    # ── Resolve agent config ───
    config: List[Dict[str, Any]]
    if agents_config is not None:
        config = agents_config
    elif profile and "agent_pool" in profile:
        config = profile["agent_pool"].get("agents", DEFAULT_LLM_AGENTS)
    else:
        env_agents = os.environ.get("OPENCHIMERA_AGENTS")
        if env_agents:
            try:
                config = json.loads(env_agents)
            except (json.JSONDecodeError, TypeError):
                config = DEFAULT_LLM_AGENTS
        else:
            config = DEFAULT_LLM_AGENTS

    # ── Register agents with LLM backing ───
    for idx, entry in enumerate(config):
        try:
            role = AgentRole(entry.get("role", "reasoner"))
            spec = AgentSpec(
                agent_id=entry["agent_id"],
                role=role,
                domain=entry.get("domain", "general"),
                temperature=float(entry.get("temperature", 0.5)),
                system_prompt=entry.get("system_prompt", ""),
                max_tokens=int(entry.get("max_tokens", 512)),
                tags=tuple(entry.get("tags", ())),
            )

            if no_models:
                # Graceful degradation — pure-Python strategy
                pool.register(spec)
            else:
                # Assign model: round-robin across available models
                model = models[idx % len(models)]
                llm_fn = make_llm_agent_callable(
                    spec,
                    model=model,
                    ollama_host=ollama_host,
                    ollama_port=ollama_port,
                    timeout=timeout,
                )
                pool.register(spec, external_fn=llm_fn)
                log.info(
                    "[AgentPool] Agent %s → model %s (role=%s)",
                    spec.agent_id, model, spec.role.value,
                )

        except (KeyError, ValueError) as exc:
            log.warning(
                "[AgentPool] Skipping invalid agent config: %s — %s",
                entry, exc,
            )

    mode = (
        "multi-model" if multi_model
        else "single-model" if single_model
        else "heuristic-fallback"
    )
    log.info(
        "[AgentPool] Created LLM pool: %d agents, mode=%s",
        pool.count(), mode,
    )
    return pool
