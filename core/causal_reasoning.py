"""OpenChimera Causal Reasoning — causal inference over the knowledge graph.

Extends the associative NetworkX-backed SemanticMemory with causal edges,
intervention simulation (do-calculus), counterfactual reasoning, and
structural causal model primitives.

Fully portable — builds on top of EventBus and an optional SemanticMemory
reference. All state is in-memory with export/import support.

Architecture
────────────
CausalEdge             Immutable descriptor for a cause→effect relationship.
InterventionResult     Result of "do(X=x)" type queries.
CounterfactualResult   Result of "what if X had been x?" queries.
CausalGraph            The structural causal model (SCM) graph.
CausalReasoning        Main engine combining graph with reasoning operations.

Key capabilities:
1. Causal edge management — directed cause→effect with strength + confidence
2. Intervention simulation — do(X=x): propagate effects through graph
3. Counterfactual reasoning — "what if?" queries with rollback
4. Causal pathway discovery — find all causal chains between two nodes
5. Confounding detection — identify common causes (back-door criterion)
"""
from __future__ import annotations

import itertools
import logging
import math
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

from core._bus_fallback import EventBus

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class EdgeType(str, Enum):
    """Type of causal relationship."""
    CAUSES = "causes"             # X causes Y
    PREVENTS = "prevents"         # X prevents Y
    ENABLES = "enables"           # X is necessary for Y
    MODULATES = "modulates"       # X modifies strength of Y


class ConfidenceLevel(str, Enum):
    """How confident we are in a causal claim."""
    OBSERVED = "observed"         # From direct observation
    INFERRED = "inferred"         # Statistically inferred
    HYPOTHESISED = "hypothesised" # Speculative


# ---------------------------------------------------------------------------
# Data objects
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CausalEdge:
    """A directed causal relationship between two variables."""
    cause: str
    effect: str
    edge_type: EdgeType
    strength: float               # -1..1, negative for PREVENTS
    confidence: float             # 0..1
    confidence_level: ConfidenceLevel
    evidence_count: int = 0
    created_at: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class InterventionResult:
    """Result of a do(X=x) intervention simulation."""
    target_variable: str
    intervention_value: float
    affected_variables: Dict[str, float]  # variable → predicted effect
    total_effect: float
    causal_paths_used: int
    confidence: float


@dataclass(frozen=True)
class CounterfactualResult:
    """Result of a 'what if?' counterfactual query."""
    query: str
    factual_value: float
    counterfactual_value: float
    delta: float
    affected_downstream: Dict[str, float]
    explanation: str
    confidence: float


@dataclass(frozen=True)
class CausalPathway:
    """A single causal path from source to target."""
    source: str
    target: str
    path: Tuple[str, ...]
    cumulative_strength: float
    min_confidence: float
    length: int


# ---------------------------------------------------------------------------
# Causal Graph — structural causal model
# ---------------------------------------------------------------------------

class CausalGraph:
    """
    Directed graph of causal relationships.

    Uses adjacency dict representation (no external dependency beyond stdlib).
    Thread-safe via RLock.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # cause → {effect → CausalEdge}
        self._forward: Dict[str, Dict[str, CausalEdge]] = {}
        # effect → {cause → CausalEdge}
        self._backward: Dict[str, Dict[str, CausalEdge]] = {}
        # All known variables
        self._variables: Set[str] = set()

    # ------------------------------------------------------------------
    # Edge management
    # ------------------------------------------------------------------

    def add_edge(self, edge: CausalEdge) -> None:
        """Add or replace a causal edge."""
        with self._lock:
            self._forward.setdefault(edge.cause, {})[edge.effect] = edge
            self._backward.setdefault(edge.effect, {})[edge.cause] = edge
            self._variables.add(edge.cause)
            self._variables.add(edge.effect)

    def remove_edge(self, cause: str, effect: str) -> bool:
        """Remove an edge. Returns True if it existed."""
        with self._lock:
            fwd = self._forward.get(cause, {})
            if effect not in fwd:
                return False
            del fwd[effect]
            bwd = self._backward.get(effect, {})
            bwd.pop(cause, None)
            return True

    def get_edge(self, cause: str, effect: str) -> Optional[CausalEdge]:
        """Return the edge from cause to effect, or None."""
        with self._lock:
            return self._forward.get(cause, {}).get(effect)

    def get_effects(self, cause: str) -> List[CausalEdge]:
        """All direct effects of a variable."""
        with self._lock:
            return list(self._forward.get(cause, {}).values())

    def get_causes(self, effect: str) -> List[CausalEdge]:
        """All direct causes of a variable."""
        with self._lock:
            return list(self._backward.get(effect, {}).values())

    @property
    def variables(self) -> Set[str]:
        with self._lock:
            return set(self._variables)

    @property
    def edge_count(self) -> int:
        with self._lock:
            return sum(len(d) for d in self._forward.values())

    # ------------------------------------------------------------------
    # Path finding
    # ------------------------------------------------------------------

    def find_causal_paths(
        self,
        source: str,
        target: str,
        max_length: int = 6,
    ) -> List[CausalPathway]:
        """
        Find all causal paths from source to target up to max_length.

        Uses BFS with cycle detection.
        """
        with self._lock:
            if source not in self._variables or target not in self._variables:
                return []
            return self._bfs_paths(source, target, max_length)

    def _bfs_paths(
        self, source: str, target: str, max_length: int,
    ) -> List[CausalPathway]:
        """BFS path enumeration (caller holds _lock)."""
        results: List[CausalPathway] = []
        # queue items: (current_node, path_so_far, cumulative_strength, min_confidence)
        queue: deque[Tuple[str, List[str], float, float]] = deque()
        queue.append((source, [source], 1.0, 1.0))

        while queue:
            node, path, cum_strength, min_conf = queue.popleft()
            if len(path) > max_length + 1:
                continue

            for effect, edge in self._forward.get(node, {}).items():
                if effect in path:
                    continue  # cycle avoidance

                new_strength = cum_strength * edge.strength
                new_conf = min(min_conf, edge.confidence)
                new_path = path + [effect]

                if effect == target:
                    results.append(CausalPathway(
                        source=source,
                        target=target,
                        path=tuple(new_path),
                        cumulative_strength=round(new_strength, 6),
                        min_confidence=round(new_conf, 4),
                        length=len(new_path) - 1,
                    ))
                else:
                    queue.append((effect, new_path, new_strength, new_conf))

        return results

    # ------------------------------------------------------------------
    # Confounding detection
    # ------------------------------------------------------------------

    def find_confounders(self, var_a: str, var_b: str) -> List[str]:
        """
        Find common causes of var_a and var_b (potential confounders).

        These are variables Z such that Z→...→A and Z→...→B.
        Uses the back-door criterion: Z must be a common ancestor.
        """
        with self._lock:
            ancestors_a = self._find_ancestors(var_a)
            ancestors_b = self._find_ancestors(var_b)
            common = ancestors_a & ancestors_b
            common.discard(var_a)
            common.discard(var_b)
            return sorted(common)

    def _find_ancestors(self, var: str) -> Set[str]:
        """Find all ancestors (upstream causes) of a variable."""
        ancestors: Set[str] = set()
        visited: Set[str] = set()
        queue: deque[str] = deque([var])
        while queue:
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            for cause, _ in self._backward.get(current, {}).items():
                ancestors.add(cause)
                queue.append(cause)
        return ancestors

    # ------------------------------------------------------------------
    # Export / import
    # ------------------------------------------------------------------

    def export_edges(self) -> List[Dict[str, Any]]:
        """Export all edges as serialisable dicts."""
        with self._lock:
            result: List[Dict[str, Any]] = []
            for cause_dict in self._forward.values():
                for edge in cause_dict.values():
                    result.append({
                        "cause": edge.cause,
                        "effect": edge.effect,
                        "edge_type": edge.edge_type.value,
                        "strength": edge.strength,
                        "confidence": edge.confidence,
                        "confidence_level": edge.confidence_level.value,
                        "evidence_count": edge.evidence_count,
                        "created_at": edge.created_at,
                    })
            return result

    def import_edges(self, edges: List[Dict[str, Any]]) -> int:
        """Import edges from export_edges() output. Returns count loaded."""
        count = 0
        for e in edges:
            try:
                self.add_edge(CausalEdge(
                    cause=e["cause"],
                    effect=e["effect"],
                    edge_type=EdgeType(e["edge_type"]),
                    strength=e["strength"],
                    confidence=e["confidence"],
                    confidence_level=ConfidenceLevel(e.get("confidence_level", "hypothesised")),
                    evidence_count=e.get("evidence_count", 0),
                    created_at=e.get("created_at", 0.0),
                ))
                count += 1
            except (KeyError, ValueError) as exc:
                log.warning("Skipped invalid edge during import: %s", exc)
        return count

    def clear(self) -> None:
        """Remove all edges and variables."""
        with self._lock:
            self._forward.clear()
            self._backward.clear()
            self._variables.clear()


# ---------------------------------------------------------------------------
# Causal Reasoning engine
# ---------------------------------------------------------------------------

class CausalReasoning:
    """
    Main causal inference engine. Combines CausalGraph with intervention
    simulation, counterfactual reasoning, and causal strength estimation.

    Thread-safe. Publishes reasoning events to EventBus.

    Parameters
    ──────────
    bus         EventBus for publishing events.
    graph       Optional pre-built CausalGraph (creates new if None).
    """

    def __init__(
        self,
        bus: EventBus,
        graph: Optional[CausalGraph] = None,
    ) -> None:
        self._bus = bus
        self._graph = graph or CausalGraph()
        self._lock = threading.RLock()

        # Variable state: variable_name → current_value
        self._state: Dict[str, float] = {}

        # Observation log for causal inference
        self._observations: List[Tuple[float, str, float]] = []

        log.info("CausalReasoning initialised")

    @property
    def graph(self) -> CausalGraph:
        return self._graph

    # ------------------------------------------------------------------
    # State management
    # ------------------------------------------------------------------

    def set_variable(self, name: str, value: float) -> None:
        """Set the current observed value of a variable."""
        with self._lock:
            self._state[name] = value
            self._observations.append((time.time(), name, value))
            if len(self._observations) > 5000:
                self._observations = self._observations[-2500:]

    def get_variable(self, name: str) -> Optional[float]:
        """Get the current observed value of a variable."""
        with self._lock:
            return self._state.get(name)

    # ------------------------------------------------------------------
    # Causal edge management (delegated)
    # ------------------------------------------------------------------

    def add_cause(
        self,
        cause: str,
        effect: str,
        edge_type: EdgeType = EdgeType.CAUSES,
        strength: float = 0.5,
        confidence: float = 0.5,
        confidence_level: ConfidenceLevel = ConfidenceLevel.HYPOTHESISED,
        evidence_count: int = 0,
    ) -> CausalEdge:
        """Add a causal relationship."""
        edge = CausalEdge(
            cause=cause,
            effect=effect,
            edge_type=edge_type,
            strength=max(-1.0, min(1.0, strength)),
            confidence=max(0.0, min(1.0, confidence)),
            confidence_level=confidence_level,
            evidence_count=evidence_count,
            created_at=time.time(),
        )
        self._graph.add_edge(edge)
        self._bus.publish("causal.edge_added", {
            "cause": cause, "effect": effect, "type": edge_type.value,
        })
        return edge

    # ------------------------------------------------------------------
    # Intervention simulation — do(X=x)
    # ------------------------------------------------------------------

    def intervene(
        self,
        variable: str,
        value: float,
        max_depth: int = 5,
    ) -> InterventionResult:
        """
        Simulate do(variable=value).

        Sets the variable to a fixed value and propagates the effect
        downstream through causal edges. In the "do" operator, all
        incoming edges to the intervened variable are severed (graph surgery).
        """
        with self._lock:
            old_value = self._state.get(variable, 0.0)
            intervention_delta = value - old_value

        # Propagate effects (BFS from variable, ignoring incoming edges)
        affected: Dict[str, float] = {}
        visited: Set[str] = {variable}
        queue: deque[Tuple[str, float, int]] = deque()

        # Start with direct effects of the intervened variable
        for edge in self._graph.get_effects(variable):
            queue.append((edge.effect, intervention_delta * edge.strength, 1))

        total_effect = 0.0
        paths_used = 0

        while queue:
            node, effect_size, depth = queue.popleft()
            if depth > max_depth:
                continue
            if node in visited:
                # Accumulate rather than skip (multiple paths)
                affected[node] = affected.get(node, 0.0) + effect_size
                total_effect += abs(effect_size)
                paths_used += 1
                continue

            visited.add(node)
            affected[node] = affected.get(node, 0.0) + effect_size
            total_effect += abs(effect_size)
            paths_used += 1

            # Propagate further downstream
            for downstream_edge in self._graph.get_effects(node):
                if downstream_edge.effect not in visited or depth + 1 <= max_depth:
                    queue.append((
                        downstream_edge.effect,
                        effect_size * downstream_edge.strength,
                        depth + 1,
                    ))

        # Compute confidence as average edge confidence along paths
        all_edges = list(self._graph.export_edges())
        relevant_confidences = [
            e["confidence"] for e in all_edges
            if e["cause"] in visited and e["effect"] in visited
        ]
        avg_conf = (
            sum(relevant_confidences) / len(relevant_confidences)
            if relevant_confidences else 0.5
        )

        result = InterventionResult(
            target_variable=variable,
            intervention_value=value,
            affected_variables=dict(sorted(affected.items())),
            total_effect=round(total_effect, 6),
            causal_paths_used=paths_used,
            confidence=round(avg_conf, 4),
        )

        self._bus.publish("causal.intervention", {
            "variable": variable, "value": value,
            "affected_count": len(affected),
        })
        return result

    # ------------------------------------------------------------------
    # Counterfactual reasoning
    # ------------------------------------------------------------------

    def counterfactual(
        self,
        variable: str,
        counterfactual_value: float,
        observe_variable: str,
    ) -> CounterfactualResult:
        """
        Answer: "What would observe_variable be if variable had been
        counterfactual_value instead of its actual value?"

        Steps (simplified Pearl's three-step):
        1. Abduction — record current state
        2. Action — apply do(variable=counterfactual_value)
        3. Prediction — propagate to observe_variable
        """
        with self._lock:
            factual_v = self._state.get(variable, 0.0)
            factual_obs = self._state.get(observe_variable, 0.0)

        # Intervene and check the propagated effect on observe_variable
        intervention = self.intervene(variable, counterfactual_value)
        cf_delta = intervention.affected_variables.get(observe_variable, 0.0)
        cf_obs = factual_obs + cf_delta

        # Build explanation
        paths = self._graph.find_causal_paths(variable, observe_variable)
        if paths:
            best_path = max(paths, key=lambda p: abs(p.cumulative_strength))
            path_str = " → ".join(best_path.path)
            explanation = (
                f"Changing {variable} from {factual_v:.2f} to "
                f"{counterfactual_value:.2f} would propagate via "
                f"[{path_str}] with cumulative strength "
                f"{best_path.cumulative_strength:.4f}, shifting "
                f"{observe_variable} by {cf_delta:+.4f}."
            )
        else:
            explanation = (
                f"No causal path found from {variable} to "
                f"{observe_variable}."
            )

        result = CounterfactualResult(
            query=f"What if {variable} had been {counterfactual_value}?",
            factual_value=factual_obs,
            counterfactual_value=round(cf_obs, 6),
            delta=round(cf_delta, 6),
            affected_downstream=intervention.affected_variables,
            explanation=explanation,
            confidence=intervention.confidence,
        )

        self._bus.publish("causal.counterfactual", {
            "variable": variable,
            "cf_value": counterfactual_value,
            "observe": observe_variable,
            "delta": cf_delta,
        })
        return result

    # ------------------------------------------------------------------
    # Causal strength estimation from observations
    # ------------------------------------------------------------------

    def estimate_strength(
        self,
        cause: str,
        effect: str,
        observations: Optional[List[Tuple[float, float]]] = None,
    ) -> float:
        """
        Estimate causal strength between two variables using
        correlation of observed changes.

        If `observations` is provided, use those (cause_value, effect_value) pairs.
        Otherwise, use internally recorded observations.

        Returns a value in [-1, 1].
        """
        if observations is not None:
            pairs = observations
        else:
            # Extract from internal observation log
            with self._lock:
                cause_vals = [
                    (ts, val) for ts, var, val in self._observations
                    if var == cause
                ]
                effect_vals = [
                    (ts, val) for ts, var, val in self._observations
                    if var == effect
                ]

            # Match by nearest timestamp
            pairs = self._match_observations(cause_vals, effect_vals)

        if len(pairs) < 3:
            return 0.0

        # Pearson correlation
        return self._pearson([p[0] for p in pairs], [p[1] for p in pairs])

    # ------------------------------------------------------------------
    # Causal pathway analysis
    # ------------------------------------------------------------------

    def strongest_pathway(
        self, source: str, target: str,
    ) -> Optional[CausalPathway]:
        """Return the strongest causal path from source to target."""
        paths = self._graph.find_causal_paths(source, target)
        if not paths:
            return None
        return max(paths, key=lambda p: abs(p.cumulative_strength))

    def total_causal_effect(self, source: str, target: str) -> float:
        """
        Sum of all causal path strengths from source to target.
        Corresponds to Pearl's total effect under linearity.
        """
        paths = self._graph.find_causal_paths(source, target)
        return sum(p.cumulative_strength for p in paths)

    def confounders_between(self, var_a: str, var_b: str) -> List[str]:
        """Find potential confounders between two variables."""
        return self._graph.find_confounders(var_a, var_b)

    # ------------------------------------------------------------------
    # Summary / introspection
    # ------------------------------------------------------------------

    def summary(self) -> Dict[str, Any]:
        """Production summary of the causal model."""
        with self._lock:
            return {
                "variables": sorted(self._graph.variables),
                "variable_count": len(self._graph.variables),
                "edge_count": self._graph.edge_count,
                "observed_variables": sorted(self._state.keys()),
                "observation_count": len(self._observations),
            }

    # ------------------------------------------------------------------
    # Export / import
    # ------------------------------------------------------------------

    def export_state(self) -> Dict[str, Any]:
        """Full export of causal model state."""
        with self._lock:
            return {
                "edges": self._graph.export_edges(),
                "state": dict(self._state),
                "observations": [
                    {"ts": ts, "var": v, "val": val}
                    for ts, v, val in self._observations[-500:]
                ],
            }

    def import_state(self, data: Dict[str, Any]) -> None:
        """Restore from export_state() dict."""
        edges = data.get("edges", [])
        self._graph.import_edges(edges)
        with self._lock:
            self._state.update(data.get("state", {}))

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _match_observations(
        a_vals: List[Tuple[float, float]],
        b_vals: List[Tuple[float, float]],
        max_gap_s: float = 60.0,
    ) -> List[Tuple[float, float]]:
        """Match observations from two variables by nearest timestamp."""
        if not a_vals or not b_vals:
            return []
        pairs: List[Tuple[float, float]] = []
        b_sorted = sorted(b_vals, key=lambda x: x[0])
        for a_ts, a_val in a_vals:
            # Find closest b
            best_b = min(b_sorted, key=lambda x: abs(x[0] - a_ts))
            if abs(best_b[0] - a_ts) <= max_gap_s:
                pairs.append((a_val, best_b[1]))
        return pairs

    @staticmethod
    def _pearson(x: List[float], y: List[float]) -> float:
        """Pearson correlation coefficient."""
        n = len(x)
        if n < 3 or n != len(y):
            return 0.0
        mean_x = sum(x) / n
        mean_y = sum(y) / n
        cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
        std_x = math.sqrt(sum((xi - mean_x) ** 2 for xi in x))
        std_y = math.sqrt(sum((yi - mean_y) ** 2 for yi in y))
        if std_x == 0.0 or std_y == 0.0:
            return 0.0
        return cov / (std_x * std_y)
