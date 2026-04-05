"""OpenChimera Multi-Agent Orchestrator — parallel agent deployment through QE.

Wires AgentPool → QuantumEngine → MemorySystem → MetacognitionEngine into a
single orchestration loop. Fully portable — configurable via env vars and
runtime profile with no hardcoded paths.

Architecture
────────────
MultiAgentOrchestrator   Main orchestrator class.
OrchestratorResult       Immutable result from an orchestration run.
run_orchestrated_task    One-shot convenience function.

Full Loop
─────────
1. Receive task
2. Select agents from pool (by domain/role/tags)
3. Deploy agents in parallel through QuantumEngine consensus
4. Record result in memory (episodic + working)
5. Run metacognition calibration check
6. Return comprehensive result with diagnostics
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from core._bus_fallback import EventBus
from core._database_fallback import DatabaseManager
from core.agent_pool import (
    AgentPool,
    AgentRole,
    AgentSpec,
    create_pool,
)
from core.quantum_engine import (
    AgentReputation,
    ConsensusFailure,
    ConsensusProfiler,
    ConsensusResult,
    QuantumEngine,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OrchestratorResult:
    """Immutable result from a multi-agent orchestration run."""
    task: str
    session_id: str
    answer: Any
    confidence: float
    participating: int
    total_invited: int
    latency_ms: float
    early_exit: bool
    partial: bool
    vote_breakdown: Dict[str, float]
    contradictions_found: int
    agents_used: List[str]
    domain: str
    metacognition: Dict[str, Any]
    memory_recorded: bool
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class MultiAgentOrchestrator:
    """Deploys multiple agents in parallel, runs consensus, and closes the
    recursive intelligence loop via memory + metacognition.

    Configuration is resolved from (in priority order):
    1. Constructor parameters
    2. Runtime profile dict
    3. Environment variables
    4. Sensible defaults

    This ensures portability across machines and CI systems.
    """

    def __init__(
        self,
        *,
        pool: Optional[AgentPool] = None,
        profile: Optional[Dict[str, Any]] = None,
        bus: Optional[EventBus] = None,
        db: Optional[DatabaseManager] = None,
        quorum: Optional[int] = None,
        early_exit_conf: Optional[float] = None,
        hard_timeout_ms: Optional[int] = None,
    ) -> None:
        # --- Resolve config ---
        self._profile = profile or {}
        orch_cfg = self._profile.get("orchestrator", {})

        self._quorum = quorum or int(
            os.environ.get(
                "OPENCHIMERA_QUORUM",
                orch_cfg.get("quorum", 2),
            )
        )
        self._early_exit_conf = early_exit_conf or float(
            os.environ.get(
                "OPENCHIMERA_EARLY_EXIT_CONF",
                orch_cfg.get("early_exit_conf", 0.75),
            )
        )
        self._timeout = hard_timeout_ms or int(
            os.environ.get(
                "OPENCHIMERA_CONSENSUS_TIMEOUT_MS",
                orch_cfg.get("hard_timeout_ms", 8000),
            )
        )

        # --- Core components ---
        self._bus = bus if bus is not None else EventBus()
        self._db = db if db is not None else DatabaseManager(":memory:")
        self._db.initialize()

        self._pool = pool if pool is not None else create_pool(profile)
        self._reputation = AgentReputation()
        self._profiler = ConsensusProfiler()
        self._engine = QuantumEngine(
            quorum=self._quorum,
            early_exit_conf=self._early_exit_conf,
            hard_timeout_ms=self._timeout,
            reputation=self._reputation,
        )

        # --- Optional intelligence loop components ---
        self._memory = None
        self._metacognition = None
        self._deliberation = None

        try:
            from core.memory_system import MemorySystem
            self._memory = MemorySystem(
                db=self._db, bus=self._bus, working_max_size=256,
            )
        except Exception as exc:
            log.warning("[Orchestrator] MemorySystem unavailable: %s", exc)

        try:
            from core.metacognition import MetacognitionEngine
            self._metacognition = MetacognitionEngine(
                db=self._db, bus=self._bus,
            )
        except Exception as exc:
            log.warning("[Orchestrator] MetacognitionEngine unavailable: %s", exc)

        log.info(
            "[Orchestrator] Initialised: %d agents, quorum=%d, timeout=%dms",
            self._pool.count(), self._quorum, self._timeout,
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def pool(self) -> AgentPool:
        return self._pool

    @property
    def engine(self) -> QuantumEngine:
        return self._engine

    @property
    def reputation(self) -> AgentReputation:
        return self._reputation

    # ------------------------------------------------------------------
    # Core orchestration
    # ------------------------------------------------------------------

    async def run(
        self,
        task: str,
        *,
        domain: Optional[str] = None,
        roles: Optional[List[AgentRole]] = None,
        tags: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> OrchestratorResult:
        """Execute a full multi-agent orchestration cycle.

        1. Selects agents from pool matching filters
        2. Dispatches them in parallel through QuantumEngine
        3. Records result in memory
        4. Runs metacognition check
        5. Publishes event on the bus

        Parameters
        ----------
        task : str
            The task/query to process.
        domain : str, optional
            Filter agents to this knowledge domain.
        roles : list of AgentRole, optional
            Filter agents to these roles.
        tags : list of str, optional
            Filter by metadata tags.
        context : dict, optional
            Extra context passed to each agent callable.

        Returns
        -------
        OrchestratorResult
            Comprehensive result with answer, confidence, diagnostics.
        """
        session_id = str(uuid.uuid4())
        started = time.perf_counter()
        ctx = context or {}
        ctx.setdefault("domain", domain or "general")
        ctx.setdefault("session_id", session_id)

        # 1. Select agents
        agents = self._pool.as_callables(
            domain=domain, roles=roles, tags=tags,
        )
        if not agents:
            return OrchestratorResult(
                task=task,
                session_id=session_id,
                answer=None,
                confidence=0.0,
                participating=0,
                total_invited=0,
                latency_ms=0.0,
                early_exit=False,
                partial=False,
                vote_breakdown={},
                contradictions_found=0,
                agents_used=[],
                domain=domain or "general",
                metacognition={},
                memory_recorded=False,
                error="No agents available matching filters",
            )

        agent_ids = sorted(agents.keys())
        log.info(
            "[Orchestrator] Dispatching %d agents for task: %s",
            len(agents), task[:80],
        )

        # 2. Run consensus (parallel agent execution)
        try:
            result: ConsensusResult = await self._engine.gather(
                task=task, agents=agents, context=ctx,
            )
            self._profiler.record(result)
        except ConsensusFailure as exc:
            latency = (time.perf_counter() - started) * 1000.0
            return OrchestratorResult(
                task=task,
                session_id=session_id,
                answer=None,
                confidence=0.0,
                participating=0,
                total_invited=len(agents),
                latency_ms=latency,
                early_exit=False,
                partial=False,
                vote_breakdown={},
                contradictions_found=0,
                agents_used=agent_ids,
                domain=domain or "general",
                metacognition={},
                memory_recorded=False,
                error=str(exc),
            )

        # 3. Record in memory
        memory_ok = False
        if self._memory is not None:
            try:
                self._memory.record_episode(
                    session_id=session_id,
                    goal=task,
                    outcome=str(result.answer),
                    confidence_initial=result.confidence,
                    confidence_final=result.confidence,
                    models_used=agent_ids,
                    reasoning_chain=list(result.vote_breakdown.keys()),
                    domain=domain or "general",
                )
                self._memory.cache_put(
                    f"last:{domain or 'general'}",
                    {"answer": str(result.answer), "confidence": result.confidence},
                )
                memory_ok = True
            except Exception as exc:
                log.warning("[Orchestrator] Memory recording failed: %s", exc)

        # 4. Metacognition check
        meta_report: Dict[str, Any] = {}
        if self._metacognition is not None:
            try:
                meta_report = self._metacognition.compute_ece(
                    domain=domain, limit=100,
                )
            except Exception as exc:
                log.warning("[Orchestrator] Metacognition check failed: %s", exc)

        # 5. Publish event
        self._bus.publish_nowait("orchestrator/result", {
            "session_id": session_id,
            "task": task[:200],
            "confidence": result.confidence,
            "participating": result.participating,
            "early_exit": result.early_exit,
            "contradictions_found": result.contradictions_found,
            "latency_ms": result.latency_ms,
        })

        return OrchestratorResult(
            task=task,
            session_id=session_id,
            answer=result.answer,
            confidence=result.confidence,
            participating=result.participating,
            total_invited=result.total_invited,
            latency_ms=result.latency_ms,
            early_exit=result.early_exit,
            partial=result.partial,
            vote_breakdown=result.vote_breakdown,
            contradictions_found=result.contradictions_found,
            agents_used=agent_ids,
            domain=domain or "general",
            metacognition=meta_report,
            memory_recorded=memory_ok,
        )

    async def run_batch(
        self,
        tasks: List[str],
        *,
        domain: Optional[str] = None,
        concurrency: int = 5,
    ) -> List[OrchestratorResult]:
        """Run multiple tasks concurrently with bounded parallelism.

        Parameters
        ----------
        tasks : list of str
            Tasks to process.
        domain : str, optional
            Domain filter for agent selection.
        concurrency : int
            Maximum number of tasks running simultaneously.

        Returns
        -------
        list of OrchestratorResult
        """
        semaphore = asyncio.Semaphore(concurrency)

        async def _bounded(t: str) -> OrchestratorResult:
            async with semaphore:
                return await self.run(t, domain=domain)

        return await asyncio.gather(*[_bounded(t) for t in tasks])

    def feedback(self, agent_id: str, correct: bool) -> None:
        """Provide correctness feedback to update reputation."""
        self._reputation.update(agent_id, correct)

    def status(self) -> Dict[str, Any]:
        """Return a diagnostic snapshot of the orchestrator."""
        return {
            "pool": {
                "total": self._pool.count(),
                "active": self._pool.active_count(),
                "agents": self._pool.list_agents(),
            },
            "engine": {
                "quorum": self._quorum,
                "early_exit_conf": self._early_exit_conf,
                "hard_timeout_ms": self._timeout,
            },
            "reputation": self._reputation.snapshot(),
            "profiler": self._profiler.summary(),
            "memory_available": self._memory is not None,
            "metacognition_available": self._metacognition is not None,
        }


# ---------------------------------------------------------------------------
# Convenience one-shot function
# ---------------------------------------------------------------------------

async def run_orchestrated_task(
    task: str,
    *,
    profile: Optional[Dict[str, Any]] = None,
    domain: Optional[str] = None,
    agents_config: Optional[List[Dict[str, Any]]] = None,
) -> OrchestratorResult:
    """One-shot: create an orchestrator, run a task, return result.

    Useful for scripts and testing. For production use,
    create a long-lived MultiAgentOrchestrator instance.
    """
    pool = create_pool(profile, agents_config)
    orch = MultiAgentOrchestrator(pool=pool, profile=profile)
    return await orch.run(task, domain=domain)
