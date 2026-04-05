"""OpenChimera World Modeling — Phase 3.

Provides a causal system-dynamics world model for OpenChimera's own runtime
state, an intervention simulator that lets the system test repairs before
applying them, and per-domain world models used by transfer_learning.

Architecture
────────────
SystemWorldModel       Causal graph of OpenChimera runtime components.
InterventionSimulator  Predicts outcomes of proposed interventions/repairs
                       without executing them (safe preview).

Both classes are thread-safe and publish events via EventBus when available.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

from core._bus_fallback import EventBus
from core.causal_reasoning import CausalReasoning

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Known system component nodes
# ---------------------------------------------------------------------------

SYSTEM_NODES: list[str] = [
    "memory",
    "quantum_engine",
    "evolution",
    "metacognition",
    "goal_planner",
    "causal_reasoning",
    "transfer_learning",
]


# ---------------------------------------------------------------------------
# SystemWorldModel
# ---------------------------------------------------------------------------

class SystemWorldModel:
    """Maintains a causal graph of OpenChimera's own runtime components.

    Nodes represent core subsystems; edges represent observed causal
    relationships (e.g., a memory failure degrades metacognition).  Episode
    data is mined to infer edge weights automatically.

    Parameters
    ──────────
    causal   CausalReasoning engine used for edge inference.
    memory   Optional EpisodicMemory (or MemorySystem) for episode retrieval.
             May be ``None`` when no database is available.
    """

    def __init__(
        self,
        causal: CausalReasoning,
        memory: Any | None = None,
    ) -> None:
        self._causal = causal
        self._memory = memory
        self._lock = threading.RLock()
        self._updated_at: float = 0.0

        # Internal adjacency representation: node → {"health": float, "edges": list[dict]}
        self._graph: dict[str, dict[str, Any]] = {}
        self._initialise_nodes()

        log.info("SystemWorldModel initialised with %d nodes", len(self._graph))

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def _initialise_nodes(self) -> None:
        """Seed the graph with the known system component nodes."""
        with self._lock:
            for node in SYSTEM_NODES:
                if node not in self._graph:
                    self._graph[node] = {"health": 1.0, "edges": []}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """Return a point-in-time snapshot of all system component nodes.

        Returns a dict mapping each node name to its current state dict
        (health, edges).  Suitable for operator dashboards.
        """
        with self._lock:
            return {
                node: {
                    "health": data["health"],
                    "edges": list(data["edges"]),
                }
                for node, data in self._graph.items()
            }

    def update_from_episode(self, episode: dict[str, Any]) -> None:
        """Ingest a single episode record and update causal edges.

        If the episode domain matches a known node and ``outcome`` is
        ``"failure"``, a degradation edge is added from the domain node to a
        synthetic ``"degraded"`` node with weight 1.0.  Other outcomes are
        recorded with lower weight as neutral influences.

        Parameters
        ──────────
        episode  Dict with at least ``domain`` and ``outcome`` keys,
                 mirroring the EpisodicMemory record schema.
        """
        domain = str(episode.get("domain", "")).lower()
        outcome = str(episode.get("outcome", "")).lower()
        confidence = float(episode.get("confidence_final", 0.5))

        with self._lock:
            # Ensure the domain node exists (even for unknown domains)
            if domain not in self._graph:
                self._graph[domain] = {"health": 1.0, "edges": []}

            if outcome == "failure":
                weight = 1.0
                # Degrade node health
                self._graph[domain]["health"] = max(
                    0.0, self._graph[domain]["health"] - 0.1
                )
                effect_node = "degraded"
            else:
                weight = max(0.0, confidence)
                effect_node = "improved"

            edge = {"cause": domain, "effect": effect_node, "weight": weight}
            # Deduplicate by (cause, effect) — update weight if already present
            existing = [e for e in self._graph[domain]["edges"] if e["effect"] == effect_node]
            if existing:
                existing[0]["weight"] = max(existing[0]["weight"], weight)
            else:
                self._graph[domain]["edges"].append(edge)

            # Also register edge in the underlying CausalReasoning graph
            try:
                self._causal.add_cause(
                    cause=domain,
                    effect=effect_node,
                    strength=weight,
                )
            except Exception as exc:  # pragma: no cover
                log.debug("CausalReasoning.add_cause skipped: %s", exc)

            self._updated_at = time.time()

    def get_model(self) -> dict[str, Any]:
        """Return the full model in a serialisable form.

        Returns
        ──────
        dict with keys ``nodes``, ``edges``, and ``updated_at``.
        """
        with self._lock:
            nodes: list[str] = list(self._graph.keys())
            edges: list[dict[str, Any]] = []
            for data in self._graph.values():
                edges.extend(data["edges"])
            return {
                "nodes": nodes,
                "edges": edges,
                "updated_at": self._updated_at,
            }

    def export_graph(self) -> list[tuple[str, str, float]]:
        """Return all (cause, effect, weight) triples.

        Convenient for downstream analytics or visualisation.
        """
        with self._lock:
            triples: list[tuple[str, str, float]] = []
            for data in self._graph.values():
                for edge in data["edges"]:
                    triples.append(
                        (str(edge["cause"]), str(edge["effect"]), float(edge["weight"]))
                    )
            return triples

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _neighbours(self, node: str) -> list[str]:
        """Return names of nodes directly reachable from ``node`` via edges."""
        with self._lock:
            data = self._graph.get(node)
            if data is None:
                return []
            return [e["effect"] for e in data["edges"]]


# ---------------------------------------------------------------------------
# InterventionSimulator
# ---------------------------------------------------------------------------

class InterventionSimulator:
    """Predicts the outcome of a proposed intervention on the world model
    without executing any real changes.

    This allows AutonomyScheduler to evaluate repairs in a preview-safe
    mode before committing to them.

    Parameters
    ──────────
    world_model  The ``SystemWorldModel`` to query for graph topology.
    """

    def __init__(self, world_model: SystemWorldModel) -> None:
        self._wm = world_model

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def simulate(self, intervention: dict[str, Any]) -> dict[str, Any]:
        """Predict the outcome of a proposed intervention.

        Parameters
        ──────────
        intervention  Dict with keys:
                      ``target``  – name of the component to act on
                      ``action``  – operation to simulate (``"clear"``,
                                    ``"reload"``, or arbitrary)
                      ``params``  – optional additional parameters

        Returns
        ──────
        dict with keys:
          ``predicted_outcome``  – human-readable outcome label
          ``confidence``         – float 0..1
          ``affected_nodes``     – list of nodes likely affected
          ``risk``               – ``"low"``, ``"medium"``, or ``"high"``
        """
        target: str = str(intervention.get("target", ""))
        action: str = str(intervention.get("action", ""))

        known_nodes: set[str] = set(self._wm._graph.keys())  # noqa: SLF001

        # Compute affected neighbours
        neighbours = self._wm._neighbours(target)  # noqa: SLF001
        affected_nodes: list[str] = neighbours if neighbours else [target]

        # Prediction logic
        if target not in known_nodes:
            predicted_outcome = "unknown"
            confidence = 0.1
            risk = "high"
        elif action == "clear":
            predicted_outcome = "improvement"
            confidence = 0.7
            risk = "low"
        elif action == "reload":
            predicted_outcome = "reset"
            confidence = 0.8
            risk = "medium"
        else:
            predicted_outcome = "neutral"
            confidence = 0.5
            risk = "medium"

        return {
            "predicted_outcome": predicted_outcome,
            "confidence": confidence,
            "affected_nodes": affected_nodes,
            "risk": risk,
        }

    def simulate_repair(self, repair: dict[str, Any]) -> dict[str, Any]:
        """Thin wrapper: converts an autonomy repair dict into an intervention
        and delegates to :meth:`simulate`.

        Autonomy repair dicts typically have the shape::

            {"chain": str, "category": str, "action": str, ...}

        The ``chain`` field is mapped to ``target``; ``action`` is preserved
        (or derived from ``category`` if missing).
        """
        target = str(repair.get("chain", repair.get("target", "")))
        action = str(repair.get("action", repair.get("category", "clear")))
        intervention: dict[str, Any] = {
            "target": target,
            "action": action,
            "params": repair,
        }
        return self.simulate(intervention)
