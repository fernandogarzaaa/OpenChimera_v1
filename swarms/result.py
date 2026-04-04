"""SwarmResult — immutable output envelope for swarm task execution."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class SwarmResult:
    """Immutable result returned by SwarmOrchestrator and GodSwarm."""

    objective: str
    selected_agents: List[str]
    outputs: List[dict]
    consensus_answer: str
    confidence: float
    latency_ms: float
    error: Optional[str] = None

    def succeeded(self) -> bool:
        return self.error is None

    def summary(self) -> dict:
        return {
            "objective": self.objective[:120],
            "agents": self.selected_agents,
            "confidence": round(self.confidence, 3),
            "latency_ms": round(self.latency_ms, 1),
            "answer_preview": self.consensus_answer[:200],
            "error": self.error,
        }
