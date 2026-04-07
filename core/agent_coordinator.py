"""OpenChimera AgentCoordinator — Multi-agent task orchestration.

Coordinates multiple agents working on related tasks, manages agent
lifecycle, and aggregates results.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger(__name__)


@dataclass
class AgentTask:
    """A task assigned to an agent."""
    task_id: str
    agent_id: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"  # pending, running, completed, failed
    result: Any = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None


class AgentCoordinator:
    """Coordinates multiple agents working on related tasks.
    
    Features:
    - Task assignment to agents
    - Agent lifecycle management
    - Result aggregation
    - Load balancing
    """
    
    def __init__(self, bus: Any | None = None) -> None:
        self._bus = bus
        self._agents: dict[str, dict[str, Any]] = {}  # agent_id -> metadata
        self._tasks: dict[str, AgentTask] = {}
        self._lock = threading.RLock()
        log.info("AgentCoordinator initialized")
    
    def register_agent(
        self,
        agent_id: str,
        capabilities: list[str],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Register an agent with capabilities."""
        with self._lock:
            self._agents[agent_id] = {
                "capabilities": capabilities,
                "metadata": metadata or {},
                "registered_at": time.time(),
                "task_count": 0,
                "active": True,
            }
            log.info("Registered agent %s with capabilities: %s", agent_id, capabilities)
    
    def assign_task(
        self,
        agent_id: str,
        description: str,
        parameters: dict[str, Any] | None = None,
    ) -> AgentTask:
        """Assign a task to an agent."""
        with self._lock:
            if agent_id not in self._agents:
                raise ValueError(f"Agent {agent_id} not registered")
            
            task_id = f"task_{uuid.uuid4().hex[:8]}"
            task = AgentTask(
                task_id=task_id,
                agent_id=agent_id,
                description=description,
                parameters=parameters or {},
            )
            
            self._tasks[task_id] = task
            self._agents[agent_id]["task_count"] += 1
            
            if self._bus:
                self._bus.publish_nowait("agent/task_assigned", {
                    "task_id": task_id,
                    "agent_id": agent_id,
                })
            
            return task
    
    def update_task(
        self,
        task_id: str,
        status: str,
        result: Any = None,
        error: str | None = None,
    ) -> bool:
        """Update task status."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return False
            
            if status == "running" and task.started_at is None:
                task.started_at = time.time()
            
            task.status = status
            task.result = result
            task.error = error
            
            if status in ("completed", "failed"):
                task.completed_at = time.time()
            
            return True
    
    def get_task(self, task_id: str) -> AgentTask | None:
        """Get a task by ID."""
        with self._lock:
            return self._tasks.get(task_id)
    
    def list_agent_tasks(self, agent_id: str, status: str | None = None) -> list[AgentTask]:
        """List tasks for an agent, optionally filtered by status."""
        with self._lock:
            tasks = [t for t in self._tasks.values() if t.agent_id == agent_id]
            if status:
                tasks = [t for t in tasks if t.status == status]
            return tasks
    
    def find_agent_for_capability(self, capability: str) -> str | None:
        """Find an active agent with the specified capability."""
        with self._lock:
            for agent_id, info in self._agents.items():
                if info["active"] and capability in info["capabilities"]:
                    return agent_id
            return None
    
    def status(self) -> dict[str, Any]:
        """Get coordinator status."""
        with self._lock:
            return {
                "total_agents": len(self._agents),
                "active_agents": sum(1 for a in self._agents.values() if a["active"]),
                "total_tasks": len(self._tasks),
                "pending_tasks": sum(1 for t in self._tasks.values() if t.status == "pending"),
                "running_tasks": sum(1 for t in self._tasks.values() if t.status == "running"),
                "completed_tasks": sum(1 for t in self._tasks.values() if t.status == "completed"),
                "failed_tasks": sum(1 for t in self._tasks.values() if t.status == "failed"),
            }
