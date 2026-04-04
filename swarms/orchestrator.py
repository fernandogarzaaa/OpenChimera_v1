"""SwarmOrchestrator — dispatches tasks to registered SwarmAgents.

Uses QuantumEngine for multi-agent consensus when more than one agent
is selected for a task.
"""
from __future__ import annotations

import asyncio
import time
from typing import Dict, List, Optional

from swarms.agent import SwarmAgent
from swarms.result import SwarmResult


class SwarmOrchestrator:
    """
    Holds a registry of :class:`SwarmAgent` instances and dispatches
    tasks to them, optionally aggregating via QuantumEngine consensus.
    """

    def __init__(self) -> None:
        self._agents: Dict[str, SwarmAgent] = {}
        self._quantum_engine = None  # lazy-loaded to avoid heavy import at module load

    # ------------------------------------------------------------------
    # Registry management
    # ------------------------------------------------------------------

    def register(self, agent: SwarmAgent) -> None:
        """Register an agent by its agent_id."""
        self._agents[agent.agent_id] = agent

    def get_agent(self, agent_id: str) -> Optional[SwarmAgent]:
        return self._agents.get(agent_id)

    def list_agents(self) -> List[SwarmAgent]:
        return list(self._agents.values())

    def agent_ids(self) -> List[str]:
        return list(self._agents.keys())

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def dispatch(
        self,
        task: str,
        agent_ids: Optional[List[str]] = None,
        context: Optional[dict] = None,
        use_consensus: bool = True,
    ) -> SwarmResult:
        """
        Synchronous façade — runs the async dispatch on the event loop.
        """
        return asyncio.run(self._dispatch_async(task, agent_ids, context, use_consensus))

    async def _dispatch_async(
        self,
        task: str,
        agent_ids: Optional[List[str]] = None,
        context: Optional[dict] = None,
        use_consensus: bool = True,
    ) -> SwarmResult:
        selected_ids = agent_ids if agent_ids else list(self._agents.keys())
        selected = [self._agents[aid] for aid in selected_ids if aid in self._agents]

        if not selected:
            return SwarmResult(
                objective=task,
                selected_agents=selected_ids,
                outputs=[],
                consensus_answer="",
                confidence=0.0,
                latency_ms=0.0,
                error="No agents found for dispatch",
            )

        t0 = time.perf_counter()

        if len(selected) == 1 or not use_consensus:
            # Single agent — no consensus overhead needed
            agent = selected[0]
            try:
                answer = await agent.execute(task, context or {})
            except Exception as exc:
                answer = f"[error] {exc}"

            latency_ms = (time.perf_counter() - t0) * 1000
            return SwarmResult(
                objective=task,
                selected_agents=[a.agent_id for a in selected],
                outputs=[{"agent_id": agent.agent_id, "output": answer}],
                consensus_answer=answer,
                confidence=1.0,
                latency_ms=latency_ms,
            )

        # Multi-agent — use QuantumEngine if available, else simple majority
        if use_consensus:
            try:
                answer, confidence, outputs = await self._quantum_dispatch(task, selected, context or {})
            except Exception as exc:
                answer, confidence, outputs = await self._simple_dispatch(task, selected, context or {})
                confidence = max(0.0, confidence - 0.1)
        else:
            answer, confidence, outputs = await self._simple_dispatch(task, selected, context or {})

        latency_ms = (time.perf_counter() - t0) * 1000
        return SwarmResult(
            objective=task,
            selected_agents=[a.agent_id for a in selected],
            outputs=outputs,
            consensus_answer=answer,
            confidence=confidence,
            latency_ms=latency_ms,
        )

    async def _simple_dispatch(
        self,
        task: str,
        agents: List[SwarmAgent],
        context: dict,
    ) -> tuple[str, float, List[dict]]:
        """Run all agents concurrently and pick first successful answer."""
        coros = [agent.execute(task, context) for agent in agents]
        results = await asyncio.gather(*coros, return_exceptions=True)
        outputs = []
        answers = []
        for agent, result in zip(agents, results):
            if isinstance(result, Exception):
                outputs.append({"agent_id": agent.agent_id, "output": f"[error] {result}"})
            else:
                outputs.append({"agent_id": agent.agent_id, "output": result})
                answers.append(result)

        answer = answers[0] if answers else ""
        confidence = len(answers) / max(len(agents), 1)
        return answer, confidence, outputs

    async def _quantum_dispatch(
        self,
        task: str,
        agents: List[SwarmAgent],
        context: dict,
    ) -> tuple[str, float, List[dict]]:
        """Use QuantumEngine consensus across agents."""
        from core.quantum_engine import QuantumEngine  # local import to keep module light

        if self._quantum_engine is None:
            self._quantum_engine = QuantumEngine(
                quorum=max(1, len(agents) // 2),
                early_exit_conf=0.75,
                hard_timeout_ms=8000,
            )

        def _make_async_callable(agent: SwarmAgent):
            async def _call(task: str, ctx: dict) -> str:
                return await agent.execute(task, ctx)
            return _call

        agent_callables = {agent.agent_id: _make_async_callable(agent) for agent in agents}

        result = await self._quantum_engine.gather(task, agent_callables, context)

        # Rebuild outputs list with agent-level answers from vote_breakdown proxy
        outputs = [
            {"agent_id": aid, "output": str(result.answer)}
            for aid in agent_callables
        ]
        return str(result.answer), float(result.confidence), outputs

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> dict:
        return {
            "registered_agents": len(self._agents),
            "agent_ids": list(self._agents.keys()),
            "quantum_engine_loaded": self._quantum_engine is not None,
        }
