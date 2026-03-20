from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional
from token_optimizer_bridge import optimize_context


class ProcessMode(str, Enum):
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    HIERARCHICAL = "hierarchical"


@dataclass
class AgentState:
    status: str = "idle"
    current_task: Optional[str] = None
    output: Any = None


@dataclass
class SwarmState:
    swarm_id: str
    mode: ProcessMode
    status: str = "idle"
    agents: Dict[str, AgentState] = field(default_factory=dict)
    handoffs: Dict[str, str] = field(default_factory=dict)
    results: Dict[str, Any] = field(default_factory=dict)


class SwarmOrchestrator:
    def __init__(self, swarm_id: str, process_mode: ProcessMode = ProcessMode.SEQUENTIAL):
        self.swarm_id = swarm_id
        self.process_mode = process_mode
        self.agents: Dict[str, Dict[str, Any]] = {}
        self.state = SwarmState(swarm_id=swarm_id, mode=process_mode)

    def register_agent(self, agent_id: str, name: str, handler: Callable[..., Any]) -> None:
        self.agents[agent_id] = {"id": agent_id, "name": name, "handler": handler}
        self.state.agents.setdefault(agent_id, AgentState())

    def set_handoff(self, source_agent_id: str, target_agent_id: str) -> None:
        self.state.handoffs[source_agent_id] = target_agent_id

    def _emit(self, _: Dict[str, Any]) -> None:
        return

    def _get_agent_chain(self) -> list[str]:
        if not self.agents:
            return []

        incoming = {target for target in self.state.handoffs.values()}
        starters = [agent_id for agent_id in self.agents.keys() if agent_id not in incoming]

        if starters:
            chain: list[str] = []
            visited = set()
            current = starters[0]
            while current and current not in visited and current in self.agents:
                chain.append(current)
                visited.add(current)
                current = self.state.handoffs.get(current)
            for agent_id in self.agents.keys():
                if agent_id not in visited:
                    chain.append(agent_id)
            return chain

        return list(self.agents.keys())

    async def execute_task(self, task: str, context: Optional[dict] = None) -> dict:
        self.state.status = "running"
        self.state.mode = self.process_mode
        try:
            if self.process_mode == ProcessMode.PARALLEL:
                results = await self._execute_parallel(task, context or {})
            elif self.process_mode == ProcessMode.HIERARCHICAL:
                results = await self._execute_hierarchical(task, context or {})
            else:
                results = await self._execute_sequential(task, context or {})
            return results
        finally:
            self.state.status = "complete"

    async def _execute_parallel(self, task: str, context: dict) -> dict:
        context = optimize_context(context or {}, token_threshold=4000)
        async def run_one(agent_id: str, agent: dict) -> tuple[str, Any]:
            self.state.agents[agent_id].status = "working"
            self.state.agents[agent_id].current_task = task
            handler = agent["handler"]
            if asyncio.iscoroutinefunction(handler):
                output = await handler(task, context, self.state.results)
            else:
                output = handler(task, context, self.state.results)
            self.state.agents[agent_id].status = "complete"
            self.state.agents[agent_id].output = output
            return agent_id, output

        pairs = await asyncio.gather(*(run_one(aid, agent) for aid, agent in self.agents.items()))
        self.state.results = {agent_id: output for agent_id, output in pairs}
        return self.state.results

    async def _execute_hierarchical(self, task: str, context: dict) -> dict:
        return await self._execute_sequential(task, context)

    async def _execute_sequential(self, task: str, context: dict) -> dict:
        results = {}
        agent_order = self._get_agent_chain()
        current_context = optimize_context(context or {}, token_threshold=4000)

        for agent_id in agent_order:
            agent = self.agents[agent_id]
            self.state.agents[agent_id].status = "working"
            self.state.agents[agent_id].current_task = task
            self._emit({"type": "agent_start", "agent": agent_id, "task": task})

            handler = agent["handler"]
            if asyncio.iscoroutinefunction(handler):
                output = await handler(task, current_context, results)
            else:
                output = handler(task, current_context, results)

            self.state.agents[agent_id].output = output
            self.state.agents[agent_id].status = "complete"
            results[agent_id] = output
            current_context = {"last_agent_output": output}
            current_context = optimize_context(current_context, token_threshold=4000)
            self._emit({"type": "agent_complete", "agent": agent_id, "output": output})

        self.state.results = results
        return results

    def get_status(self) -> dict:
        return {
            "swarm_id": self.swarm_id,
            "status": self.state.status,
            "mode": self.process_mode.value,
            "agents": {
                agent_id: {
                    "status": agent_state.status,
                    "current_task": agent_state.current_task,
                }
                for agent_id, agent_state in self.state.agents.items()
            },
            "results_count": len(self.state.results),
        }