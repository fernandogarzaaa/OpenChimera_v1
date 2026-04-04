from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import networkx as nx

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Hypothesis:
    """Represents a single hypothesis in the deliberation graph."""

    id: str
    claim: str
    perspective: str
    confidence: float
    evidence: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class Contradiction:
    """Represents a contradiction between two hypotheses."""

    id: str
    hypothesis_a: str
    hypothesis_b: str
    reason: str
    severity: float


class DeliberationGraph:
    """
    A directed hypothesis graph for multi-perspective reasoning.

    Manages hypotheses as nodes, support relationships as edges, and detects
    contradictions between competing claims.
    """

    def __init__(self, bus: Any | None = None) -> None:
        """
        Initialize the deliberation graph.

        Args:
            bus: Optional EventBus instance for publishing events.
        """
        self._graph = nx.DiGraph()
        self._hypotheses: dict[str, Hypothesis] = {}
        self._contradictions: dict[str, Contradiction] = {}
        self._lock = threading.RLock()
        self._bus = bus

    def add_hypothesis(
        self,
        claim: str,
        perspective: str,
        confidence: float = 0.5,
        evidence: list[str] | None = None,
    ) -> Hypothesis:
        """
        Add a new hypothesis to the graph.

        Args:
            claim: The hypothesis claim.
            perspective: The perspective/agent proposing this hypothesis.
            confidence: Confidence level (0-1).
            evidence: List of supporting evidence/facts.

        Returns:
            The created Hypothesis object.
        """
        if not 0 <= confidence <= 1:
            log.warning(f"Confidence {confidence} out of range, clamping to [0, 1]")
            confidence = max(0, min(1, confidence))

        hyp_id = uuid.uuid4().hex
        evidence = evidence or []

        hypothesis = Hypothesis(
            id=hyp_id,
            claim=claim,
            perspective=perspective,
            confidence=confidence,
            evidence=evidence,
            timestamp=time.time(),
        )

        with self._lock:
            self._hypotheses[hyp_id] = hypothesis
            self._graph.add_node(hyp_id, hypothesis=hypothesis)

        if self._bus:
            try:
                self._bus.publish(
                    "deliberation.hypothesis.added",
                    {
                        "hypothesis_id": hyp_id,
                        "claim": claim,
                        "perspective": perspective,
                        "confidence": confidence,
                    },
                )
            except Exception as e:
                log.error(f"Failed to publish hypothesis.added event: {e}")

        log.debug(f"Added hypothesis {hyp_id}: {claim[:50]}...")
        return hypothesis

    def add_support(self, from_id: str, to_id: str, weight: float = 1.0) -> None:
        """
        Add a support edge from one hypothesis to another.

        Meaning: hypothesis `from_id` supports hypothesis `to_id`.

        Args:
            from_id: ID of the supporting hypothesis.
            to_id: ID of the supported hypothesis.
            weight: Edge weight (default 1.0).
        """
        if weight <= 0:
            log.warning(f"Support weight {weight} must be positive, ignoring")
            return

        with self._lock:
            if from_id not in self._hypotheses or to_id not in self._hypotheses:
                log.error(
                    f"Cannot add support: hypothesis {from_id} or {to_id} not found"
                )
                return

            self._graph.add_edge(from_id, to_id, weight=weight)

        log.debug(f"Added support edge {from_id} -> {to_id} (weight={weight})")

    def add_contradiction(
        self,
        hyp_a_id: str,
        hyp_b_id: str,
        reason: str,
        severity: float = 0.5,
    ) -> Contradiction | None:
        """
        Record a contradiction between two hypotheses.

        Args:
            hyp_a_id: ID of first hypothesis.
            hyp_b_id: ID of second hypothesis.
            reason: Reason for the contradiction.
            severity: Severity level (0-1).

        Returns:
            The created Contradiction object, or None if validation fails.
        """
        if not 0 <= severity <= 1:
            log.warning(f"Severity {severity} out of range, clamping to [0, 1]")
            severity = max(0, min(1, severity))

        with self._lock:
            if hyp_a_id not in self._hypotheses or hyp_b_id not in self._hypotheses:
                log.error("Cannot add contradiction: hypothesis not found")
                return None

            contradiction_id = uuid.uuid4().hex

            contradiction = Contradiction(
                id=contradiction_id,
                hypothesis_a=hyp_a_id,
                hypothesis_b=hyp_b_id,
                reason=reason,
                severity=severity,
            )

            self._contradictions[contradiction_id] = contradiction

        if self._bus:
            try:
                self._bus.publish(
                    "deliberation.contradiction.found",
                    {
                        "contradiction_id": contradiction_id,
                        "hypothesis_a": hyp_a_id,
                        "hypothesis_b": hyp_b_id,
                        "reason": reason,
                        "severity": severity,
                    },
                )
            except Exception as e:
                log.error(f"Failed to publish contradiction.found event: {e}")

        log.debug(f"Recorded contradiction {contradiction_id}: {reason[:50]}...")
        return contradiction

    def detect_contradictions(self, threshold: float = 0.3) -> list[Contradiction]:
        """
        Detect contradictions between hypotheses.

        Returns existing contradictions where severity >= threshold.

        Args:
            threshold: Severity threshold (0-1).

        Returns:
            List of contradictions above threshold.
        """
        with self._lock:
            contradictions = [
                c
                for c in self._contradictions.values()
                if c.severity >= threshold
            ]
        return contradictions

    def max_flow_consensus(self) -> dict[str, Any]:
        """
        Compute consensus using maximum flow algorithm.

        Creates a flow network:
        - Virtual source connected to root hypotheses (no incoming support)
        - Virtual sink connected to leaf hypotheses (no outgoing support)
        - Edge capacities = confidence x support weight

        Falls back to ranked_hypotheses()[0] if max flow computation fails.

        Returns:
            Dict with keys:
            - "winning_hypothesis": The consensus Hypothesis
            - "flow_value": Maximum flow value
            - "path": List of hypothesis IDs in winning path
            - "all_flows": Dict of all flows by edge
        """
        with self._lock:
            if not self._hypotheses:
                log.warning("No hypotheses in graph, cannot compute consensus")
                return {
                    "winning_hypothesis": None,
                    "flow_value": 0,
                    "path": [],
                    "all_flows": {},
                }

            # Create a copy of the graph for flow computation
            flow_graph = self._graph.copy()

            # Find root nodes (no incoming edges)
            roots = [
                node
                for node in flow_graph.nodes()
                if flow_graph.in_degree(node) == 0
            ]

            # Find leaf nodes (no outgoing edges)
            leaves = [
                node
                for node in flow_graph.nodes()
                if flow_graph.out_degree(node) == 0
            ]

            # If no roots or leaves, fall back
            if not roots or not leaves:
                log.warning("Graph has no clear roots/leaves, using ranked consensus")
                ranked = self._rank_hypotheses_internal()
                if ranked:
                    top = ranked[0]
                    return {
                        "winning_hypothesis": top["hypothesis"],
                        "flow_value": top["score"],
                        "path": [top["hypothesis"].id],
                        "all_flows": {},
                    }
                return {
                    "winning_hypothesis": None,
                    "flow_value": 0,
                    "path": [],
                    "all_flows": {},
                }

            # Add virtual source and sink
            source = "__source__"
            sink = "__sink__"
            flow_graph.add_node(source)
            flow_graph.add_node(sink)

            # Connect source to roots with capacity = confidence
            for root in roots:
                hyp = self._hypotheses.get(root)
                if hyp:
                    flow_graph.add_edge(source, root, capacity=hyp.confidence)

            # Connect leaves to sink with capacity = confidence
            for leaf in leaves:
                hyp = self._hypotheses.get(leaf)
                if hyp:
                    flow_graph.add_edge(leaf, sink, capacity=hyp.confidence)

            # Set capacities on existing edges: confidence x weight
            for from_node, to_node, data in flow_graph.edges(data=True):
                if from_node != source and to_node != sink:
                    from_hyp = self._hypotheses.get(from_node)
                    weight = data.get("weight", 1.0)
                    if from_hyp:
                        capacity = from_hyp.confidence * weight
                        flow_graph[from_node][to_node]["capacity"] = capacity

            try:
                # Compute maximum flow
                flow_value, flow_dict = nx.maximum_flow(flow_graph, source, sink)

                # Find the path with maximum contribution
                winning_hypothesis = None
                max_contribution = 0
                winning_path: list[str] = []

                # Trace paths from roots through the network
                for root in roots:
                    if root in flow_dict and source in flow_dict:
                        flow_from_source = flow_dict[source].get(root, 0)
                        if flow_from_source > max_contribution:
                            max_contribution = flow_from_source
                            winning_hypothesis = self._hypotheses.get(root)
                            winning_path = [root]

                log.debug(
                    f"Max flow consensus: flow_value={flow_value}, "
                    f"winning={winning_hypothesis.id if winning_hypothesis else None}"
                )

                return {
                    "winning_hypothesis": winning_hypothesis,
                    "flow_value": flow_value,
                    "path": winning_path,
                    "all_flows": flow_dict,
                }

            except Exception as e:
                log.warning(
                    f"Max flow computation failed ({e}), falling back to ranking"
                )
                ranked = self._rank_hypotheses_internal()
                if ranked:
                    top = ranked[0]
                    return {
                        "winning_hypothesis": top["hypothesis"],
                        "flow_value": top["score"],
                        "path": [top["hypothesis"].id],
                        "all_flows": {},
                    }
                return {
                    "winning_hypothesis": None,
                    "flow_value": 0,
                    "path": [],
                    "all_flows": {},
                }

    def _rank_hypotheses_internal(self) -> list[dict[str, Any]]:
        """
        Internal ranking method that does not acquire lock (caller must hold it).

        Returns:
            List of ranked hypothesis dicts sorted by score (descending).
        """
        results = []

        for hyp_id, hypothesis in self._hypotheses.items():
            # Count incoming support edges (who supports this hypothesis)
            support_count = self._graph.in_degree(hyp_id)

            # Count contradictions involving this hypothesis
            contradiction_count = sum(
                1
                for c in self._contradictions.values()
                if c.hypothesis_a == hyp_id or c.hypothesis_b == hyp_id
            )

            # Compute score
            score = (
                hypothesis.confidence
                * (1 + support_count)
                / (1 + contradiction_count)
            )

            results.append(
                {
                    "hypothesis": hypothesis,
                    "score": score,
                    "support_count": support_count,
                    "contradiction_count": contradiction_count,
                }
            )

        # Sort by score descending
        results.sort(key=lambda x: x["score"], reverse=True)
        return results

    def ranked_hypotheses(self) -> list[dict[str, Any]]:
        """
        Rank all hypotheses by a composite score.

        Score = confidence x (1 + support_count) / (1 + contradiction_count)

        Returns:
            List of dicts sorted by score (descending):
            - "hypothesis": Hypothesis object
            - "score": Computed rank score
            - "support_count": Number of hypotheses supporting this one
            - "contradiction_count": Number of contradictions involving this one
        """
        with self._lock:
            return self._rank_hypotheses_internal()

    def get_hypothesis(self, hyp_id: str) -> Hypothesis | None:
        """
        Retrieve a hypothesis by ID.

        Args:
            hyp_id: Hypothesis ID.

        Returns:
            Hypothesis object or None if not found.
        """
        with self._lock:
            return self._hypotheses.get(hyp_id)

    def get_supporters(self, hyp_id: str) -> list[Hypothesis]:
        """
        Get all hypotheses that support the given hypothesis.

        Args:
            hyp_id: Hypothesis ID.

        Returns:
            List of supporting hypotheses (predecessors in graph).
        """
        with self._lock:
            if hyp_id not in self._graph:
                return []

            supporter_ids = list(self._graph.predecessors(hyp_id))
            return [
                self._hypotheses[sid]
                for sid in supporter_ids
                if sid in self._hypotheses
            ]

    def get_supported(self, hyp_id: str) -> list[Hypothesis]:
        """
        Get all hypotheses supported by the given hypothesis.

        Args:
            hyp_id: Hypothesis ID.

        Returns:
            List of supported hypotheses (successors in graph).
        """
        with self._lock:
            if hyp_id not in self._graph:
                return []

            supported_ids = list(self._graph.successors(hyp_id))
            return [
                self._hypotheses[sid]
                for sid in supported_ids
                if sid in self._hypotheses
            ]

    def all_hypotheses(self) -> list[Hypothesis]:
        """
        Get all hypotheses in the graph.

        Returns:
            List of all hypotheses.
        """
        with self._lock:
            return list(self._hypotheses.values())

    def all_contradictions(self) -> list[Contradiction]:
        """
        Get all recorded contradictions.

        Returns:
            List of all contradictions.
        """
        with self._lock:
            return list(self._contradictions.values())

    def clear(self) -> None:
        """Clear all hypotheses and contradictions from the graph."""
        with self._lock:
            self._graph.clear()
            self._hypotheses.clear()
            self._contradictions.clear()

        log.debug("Deliberation graph cleared")

    def summary(self) -> dict[str, Any]:
        """
        Get a summary of the graph state.

        Returns:
            Dict with keys:
            - "total_hypotheses": Number of hypotheses
            - "total_contradictions": Number of contradictions
            - "top_hypothesis": Top-ranked hypothesis (or None)
            - "graph_density": NetworkX graph density
        """
        with self._lock:
            hypotheses_count = len(self._hypotheses)
            contradictions_count = len(self._contradictions)

            # Get top hypothesis
            top_hypothesis = None
            ranked = self._rank_hypotheses_internal()
            if ranked:
                top_hypothesis = ranked[0]["hypothesis"]

            # Compute graph density
            density = nx.density(self._graph) if len(self._graph) > 1 else 0.0

            return {
                "total_hypotheses": hypotheses_count,
                "total_contradictions": contradictions_count,
                "top_hypothesis": top_hypothesis,
                "graph_density": density,
            }
