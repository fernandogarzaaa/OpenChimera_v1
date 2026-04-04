"""SimCluster — round-robin load balancer over SimNodes."""
from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, List

from core.quantum_engine import ConsensusResult

from .node import SimNode


class SimCluster:
    """Holds multiple SimNodes and routes queries with round-robin load balancing.

    Collects aggregate statistics across all completed queries.

    Parameters
    ----------
    nodes : list of SimNode
        Must contain at least one node.
    """

    def __init__(self, nodes: List[SimNode]) -> None:
        if not nodes:
            raise ValueError("SimCluster requires at least one node")
        self.nodes: List[SimNode] = list(nodes)
        self._rr_index: int = 0
        self._all_results: List[ConsensusResult] = []
        self._failed_queries: int = 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _next_online_node(self) -> SimNode | None:
        """Round-robin over online nodes; returns None when all are offline."""
        n = len(self.nodes)
        for _ in range(n):
            candidate = self.nodes[self._rr_index % n]
            self._rr_index += 1
            if candidate.online:
                return candidate
        return None

    # ------------------------------------------------------------------
    # Public query surface
    # ------------------------------------------------------------------

    async def query(
        self,
        task: Any,
        agents: Dict[str, Callable[..., Any]],
    ) -> ConsensusResult:
        """Route a query to the next available (online) node.

        Uses round-robin selection and falls back to the next online node if
        the chosen one is offline.

        Raises RuntimeError when no online nodes are available.
        """
        node = self._next_online_node()
        if node is None:
            self._failed_queries += 1
            raise RuntimeError("SimCluster: all nodes are offline")

        try:
            result = await node.query(task, agents)
            self._all_results.append(result)
            return result
        except RuntimeError:
            self._failed_queries += 1
            raise

    async def broadcast(
        self,
        task: Any,
        agents: Dict[str, Callable[..., Any]],
    ) -> List[ConsensusResult]:
        """Send the same query to ALL online nodes concurrently.

        Returns the list of successful ConsensusResults (failed nodes are
        silently excluded from the return value, counted in failed_queries).
        """
        online_nodes = [n for n in self.nodes if n.online]
        if not online_nodes:
            raise RuntimeError("SimCluster: all nodes are offline")

        raw = await asyncio.gather(
            *[node.query(task, agents) for node in online_nodes],
            return_exceptions=True,
        )
        good: List[ConsensusResult] = [
            r for r in raw if isinstance(r, ConsensusResult)
        ]
        failed_count = len(raw) - len(good)
        self._failed_queries += failed_count
        self._all_results.extend(good)
        return good

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def online_count(self) -> int:
        """Number of currently online nodes."""
        return sum(1 for n in self.nodes if n.online)

    def stats(self) -> Dict[str, Any]:
        """Aggregate statistics across all completed queries."""
        n = len(self._all_results)
        if n == 0:
            return {
                "total_queries": 0,
                "failed_queries": self._failed_queries,
                "avg_latency_ms": 0.0,
                "avg_confidence": 0.0,
                "early_exit_rate": 0.0,
                "partial_rate": 0.0,
                "node_stats": [nd.stats() for nd in self.nodes],
            }
        avg_lat = sum(r.latency_ms for r in self._all_results) / n
        avg_conf = sum(r.confidence for r in self._all_results) / n
        early_rate = sum(1 for r in self._all_results if r.early_exit) / n
        partial_rate = sum(1 for r in self._all_results if r.partial) / n
        return {
            "total_queries": n,
            "failed_queries": self._failed_queries,
            "avg_latency_ms": round(avg_lat, 2),
            "avg_confidence": round(avg_conf, 4),
            "early_exit_rate": round(early_rate, 4),
            "partial_rate": round(partial_rate, 4),
            "node_stats": [nd.stats() for nd in self.nodes],
        }
