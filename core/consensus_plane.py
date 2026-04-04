"""OpenChimera Consensus Plane — multi-agent consensus orchestration.

Wraps QuantumEngine to provide a control-plane-friendly interface for
dispatching inference tasks through multiple local and remote agents with
weighted voting, reputation tracking, and early-exit optimisation.

Usage (from Kernel or ApiServer):
    from core.consensus_plane import ConsensusPlanePlane
    plane = ConsensusPlane(profile=..., inference_plane=..., bus=...)
    result = await plane.query("What is pi?", query_type="reasoning")
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from core.quantum_engine import (
    AgentReputation,
    AgentResponse,
    ConsensusFailure,
    ConsensusProfiler,
    ConsensusResult,
    QuantumEngine,
)

log = logging.getLogger(__name__)

_DEFAULT_QUORUM = 1
_DEFAULT_EARLY_CONF = 0.75
_DEFAULT_TIMEOUT_MS = 8000


class ConsensusPlane:
    """
    Wraps QuantumEngine with OpenChimera-specific agent wiring.

    Agents are callables with signature: (task: str, context: dict) -> str
    Each callable can be a local stub, an Ollama shim, a minimind call, etc.
    """

    def __init__(
        self,
        *,
        profile: dict[str, Any],
        bus: Any,
        quorum: int = _DEFAULT_QUORUM,
        early_exit_conf: float = _DEFAULT_EARLY_CONF,
        hard_timeout_ms: int = _DEFAULT_TIMEOUT_MS,
    ) -> None:
        self._profile = profile
        self._bus = bus
        self._reputation = AgentReputation()
        self._profiler = ConsensusProfiler()
        self._engine = QuantumEngine(
            quorum=quorum,
            early_exit_conf=early_exit_conf,
            hard_timeout_ms=hard_timeout_ms,
            reputation=self._reputation,
        )
        self._agents: Dict[str, Callable[..., Any]] = {}

    # ------------------------------------------------------------------
    # Agent registration
    # ------------------------------------------------------------------

    def register_agent(self, agent_id: str, fn: Callable[..., Any]) -> None:
        """Register a callable agent (sync or async) with an identifier."""
        if not agent_id or not callable(fn):
            raise ValueError("agent_id must be non-empty and fn must be callable")
        self._agents[agent_id] = fn
        log.info("[ConsensusPlane] Registered agent: %s", agent_id)

    def unregister_agent(self, agent_id: str) -> None:
        self._agents.pop(agent_id, None)

    def list_agents(self) -> List[str]:
        return sorted(self._agents.keys())

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    async def query(
        self,
        task: str,
        *,
        query_type: str = "general",
        context: Optional[dict] = None,
        agents: Optional[Dict[str, Callable[..., Any]]] = None,
    ) -> dict[str, Any]:
        """
        Run consensus voting across registered (or supplied) agents.

        Returns a result dict with: answer, confidence, participating,
        total_invited, latency_ms, early_exit, profiler_summary.
        """
        target_agents = agents if agents is not None else dict(self._agents)
        if not target_agents:
            return {
                "answer": None,
                "confidence": 0.0,
                "error": "No agents registered in ConsensusPlane",
                "participating": 0,
                "total_invited": 0,
                "latency_ms": 0.0,
            }

        started = time.perf_counter()
        try:
            result: ConsensusResult = await self._engine.gather(
                task=task,
                agents=target_agents,
                context=context or {"query_type": query_type},
            )
            self._profiler.record(result)
            self._bus.publish_nowait(
                "llm/consensus",
                {
                    "query_type": query_type,
                    "confidence": result.confidence,
                    "participating": result.participating,
                    "early_exit": result.early_exit,
                    "latency_ms": result.latency_ms,
                },
            )
            return {
                "answer": result.answer,
                "confidence": result.confidence,
                "participating": result.participating,
                "total_invited": result.total_invited,
                "latency_ms": result.latency_ms,
                "early_exit": result.early_exit,
                "partial": result.partial,
                "vote_breakdown": result.vote_breakdown,
                "profiler": self._profiler.summary(),
                "error": None,
            }
        except ConsensusFailure as exc:
            latency_ms = (time.perf_counter() - started) * 1000.0
            log.error("[ConsensusPlane] Consensus failure: %s", exc)
            return {
                "answer": None,
                "confidence": 0.0,
                "error": str(exc),
                "participating": 0,
                "total_invited": len(target_agents),
                "latency_ms": latency_ms,
            }

    def feedback(self, agent_id: str, correct: bool) -> None:
        """Provide correctness feedback to update agent reputation."""
        self._reputation.update(agent_id, correct)

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        rep_snapshot = self._reputation.snapshot()
        return {
            "agents": self.list_agents(),
            "reputation": rep_snapshot,
            "profiler": self._profiler.summary(),
            "engine": {
                "quorum": self._engine.quorum,
                "early_exit_conf": self._engine.early_exit_conf,
                "hard_timeout_ms": self._engine.hard_timeout_ms,
            },
        }
