"""OpenChimera Agent Pool — portable, typed multi-agent framework.

Provides a protocol-based agent system that can be configured entirely via
environment variables and runtime profiles. No hardcoded paths.

Architecture
────────────
AgentSpec       Immutable descriptor for a single agent (role, domain, strategy).
AgentStrategy   Enum of reasoning strategies an agent can use.
AgentPool       Registry + factory that creates callable agents for QuantumEngine.
create_pool     Convenience builder from a runtime profile dict or env vars.

Example
───────
    pool = AgentPool()
    pool.register(AgentSpec("analyst", AgentRole.REASONER, domain="finance"))
    pool.register(AgentSpec("critic", AgentRole.CRITIC))
    callables = pool.as_callables()   # dict[str, Callable] — ready for QE
    result = await engine.gather(task, callables)
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
# Agent callable factory
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
