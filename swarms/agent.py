"""SwarmAgent — an individual agent entity within a swarm."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import List, Literal


AgentStatus = Literal["idle", "active", "done", "failed"]


@dataclass
class SwarmAgent:
    """Represents a single swarm agent with identity, role, and offline execute capability."""

    agent_id: str
    role: str
    description: str
    capabilities: List[str] = field(default_factory=list)
    status: AgentStatus = "idle"

    async def execute(self, task: str, context: dict | None = None) -> str:  # noqa: ARG002
        """
        Simulate task execution.

        In offline / no-LLM mode returns a deterministic string.
        A live integration would replace this body with a real LLM call.
        """
        self.status = "active"
        # Yield control so the event loop can run multiple agents concurrently.
        await asyncio.sleep(0)
        self.status = "done"
        return f"{self.role} completed: {task[:50]}"

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "role": self.role,
            "description": self.description,
            "capabilities": list(self.capabilities),
            "status": self.status,
        }
