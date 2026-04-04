"""SimNode — wraps a QuantumEngine instance with network latency simulation."""
from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Dict, Optional

from core.quantum_engine import AgentReputation, ConsensusResult, QuantumEngine


class SimNode:
    """A simulated distributed node wrapping a QuantumEngine.

    Simulates per-hop network latency before forwarding the query to the
    local QuantumEngine. Tracks per-node metrics and supports online/offline
    state toggling for failure simulation.

    Parameters
    ----------
    node_id : str
        Unique identifier for this node.
    engine : QuantumEngine, optional
        Pre-built engine; a default one is created if not supplied.
    latency_ms : float
        Simulated one-way network latency in milliseconds added before each
        query is dispatched to the engine.
    """

    def __init__(
        self,
        node_id: str,
        engine: Optional[QuantumEngine] = None,
        latency_ms: float = 0.0,
    ) -> None:
        self.node_id = node_id
        self.engine: QuantumEngine = engine if engine is not None else QuantumEngine()
        self.latency_ms = float(latency_ms)
        self.online: bool = True
        self._query_count: int = 0
        self._total_latency_ms: float = 0.0
        self._total_confidence: float = 0.0

    async def query(
        self,
        task: Any,
        agents: Dict[str, Callable[..., Any]],
    ) -> ConsensusResult:
        """Run consensus on this node.

        Raises RuntimeError if the node is offline.
        Simulates network latency before dispatching to the local engine.

        Returns
        -------
        ConsensusResult
            The consensus outcome from the local engine.
        """
        if not self.online:
            raise RuntimeError(f"SimNode '{self.node_id}' is offline")

        if self.latency_ms > 0.0:
            await asyncio.sleep(self.latency_ms / 1000.0)

        t0 = time.perf_counter()
        result = await self.engine.gather(task, agents)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0 + self.latency_ms

        self._query_count += 1
        self._total_latency_ms += elapsed_ms
        self._total_confidence += result.confidence

        return result

    def set_online(self, online: bool) -> None:
        """Toggle node availability (True = online, False = offline)."""
        self.online = online

    def stats(self) -> Dict[str, Any]:
        """Return a snapshot of per-node statistics (immutable dict)."""
        n = self._query_count
        return {
            "node_id": self.node_id,
            "online": self.online,
            "query_count": n,
            "avg_latency_ms": round(self._total_latency_ms / n, 2) if n else 0.0,
            "avg_confidence": round(self._total_confidence / n, 4) if n else 0.0,
        }
