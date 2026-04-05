"""GodSwarm — the 10-agent meta-orchestrator.

Implements the GOD_SWARM architecture documented in swarms/GOD_SWARM.md.

Core agents (6):   Omniscient, Architect, Demiurge, Chronos, Arbiter, Scribe
Supporting agents (4): Oracle, Alchemist, Reaper, Librarian
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from swarms.agent import SwarmAgent
from swarms.orchestrator import SwarmOrchestrator
from swarms.result import SwarmResult

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Agent definitions extracted from GOD_SWARM.md
# ---------------------------------------------------------------------------

_CORE_AGENTS: list[dict] = [
    {
        "agent_id": "omniscient",
        "role": "Requirement Analyzer",
        "description": "Deeply understands user intent, constraints, and success criteria.",
        "capabilities": ["requirement-parsing", "intent-detection", "constraint-analysis"],
    },
    {
        "agent_id": "architect",
        "role": "Swarm Composer",
        "description": "Designs swarm topology, selects agent types, and plans dependencies.",
        "capabilities": ["topology-design", "agent-selection", "dependency-planning"],
    },
    {
        "agent_id": "demiurge",
        "role": "Swarm Creator",
        "description": "Spawns sub-swarms, assigns objectives, and provisions resources.",
        "capabilities": ["swarm-spawning", "resource-provisioning", "objective-assignment"],
    },
    {
        "agent_id": "chronos",
        "role": "Progress Monitor",
        "description": "Tracks swarm activities, detects stalls and failures, enforces timeouts.",
        "capabilities": ["progress-tracking", "failure-detection", "timeout-enforcement"],
    },
    {
        "agent_id": "arbiter",
        "role": "Conflict Resolver",
        "description": "Resolves disputes between swarms and handles resource contention.",
        "capabilities": ["conflict-resolution", "resource-scheduling", "negotiation"],
    },
    {
        "agent_id": "scribe",
        "role": "Context Keeper",
        "description": "Maintains shared state and ensures continuity across swarm handoffs.",
        "capabilities": ["state-management", "context-persistence", "handoff-continuity"],
    },
]

_SUPPORTING_AGENTS: list[dict] = [
    {
        "agent_id": "oracle",
        "role": "Pattern Recognizer",
        "description": "Matches objectives to known swarm patterns from history.",
        "capabilities": ["pattern-matching", "history-lookup", "swarm-recommendation"],
    },
    {
        "agent_id": "alchemist",
        "role": "Swarm Optimizer",
        "description": "Tweaks swarm composition based on real-time performance signals.",
        "capabilities": ["performance-monitoring", "composition-tuning", "optimization"],
    },
    {
        "agent_id": "reaper",
        "role": "Cleanup Manager",
        "description": "Destroys completed or failed swarms and archives learnings.",
        "capabilities": ["swarm-teardown", "artifact-archival", "learning-capture"],
    },
    {
        "agent_id": "librarian",
        "role": "Knowledge Curator",
        "description": "Updates swarm registry with new patterns and improvements.",
        "capabilities": ["registry-update", "knowledge-indexing", "pattern-curation"],
    },
]


class GodSwarm(SwarmOrchestrator):
    """
    Meta-orchestrator swarm with the full 10-agent architecture.

    All agents are registered at initialisation time.  In offline mode the
    agents use the simulated :meth:`SwarmAgent.execute` path.

    Phase 4 additions:
    - Event bus integration (emit events on agent spawn, coordination)
    - spawn_agent(agent_config) — dynamic agent creation and registration
    - coordinate(task) — multi-agent task coordination with event emission
    - wire_to_kernel(kernel) — hook into kernel boot sequence
    """

    CORE_AGENT_IDS = [a["agent_id"] for a in _CORE_AGENTS]
    SUPPORTING_AGENT_IDS = [a["agent_id"] for a in _SUPPORTING_AGENTS]
    ALL_AGENT_IDS = CORE_AGENT_IDS + SUPPORTING_AGENT_IDS

    def __init__(self, bus: Any | None = None) -> None:
        super().__init__()
        self._bus = bus
        self._kernel: Any | None = None
        self._dynamic_agents: dict[str, dict[str, Any]] = {}

        for spec in _CORE_AGENTS + _SUPPORTING_AGENTS:
            self.register(SwarmAgent(**spec))

    # ------------------------------------------------------------------
    # Event bus integration helpers
    # ------------------------------------------------------------------

    def _emit(self, topic: str, payload: dict[str, Any]) -> None:
        if self._bus is None:
            return
        try:
            self._bus.publish_nowait(topic, payload)
        except Exception as exc:
            log.warning("[GodSwarm] Event bus emit failed (topic=%s): %s", topic, exc)

    # ------------------------------------------------------------------
    # spawn_agent — dynamic agent creation
    # ------------------------------------------------------------------

    def spawn_agent(self, agent_config: dict[str, Any]) -> dict[str, Any]:
        """Create and register a dynamic agent from a config dict.

        Emits a ``god_swarm.agent.spawned`` event on success.
        Config keys: agent_id (optional), role, description, capabilities (list).
        """
        agent_id = str(agent_config.get("agent_id") or f"dyn-{uuid.uuid4().hex[:8]}")
        role = str(agent_config.get("role", "Dynamic Agent"))
        description = str(agent_config.get("description", "Dynamically spawned agent."))
        capabilities = list(agent_config.get("capabilities", []))

        agent = SwarmAgent(
            agent_id=agent_id,
            role=role,
            description=description,
            capabilities=capabilities,
        )
        self.register(agent)
        record = {
            "agent_id": agent_id,
            "role": role,
            "description": description,
            "capabilities": capabilities,
            "spawned_at": time.time(),
        }
        self._dynamic_agents[agent_id] = record
        self._emit("god_swarm.agent.spawned", record)
        log.info("[GodSwarm] Spawned agent: %s (%s)", agent_id, role)
        return record

    # ------------------------------------------------------------------
    # coordinate — multi-agent task coordination
    # ------------------------------------------------------------------

    def coordinate(self, task: str, agent_ids: list[str] | None = None) -> SwarmResult:
        """Coordinate a task across the specified agents (or all agents).

        Emits coordination_start and coordination_complete events.
        """
        ids = agent_ids or self.ALL_AGENT_IDS
        coord_id = uuid.uuid4().hex[:12]

        self._emit("god_swarm.coordination.start", {
            "coord_id": coord_id,
            "task": task[:200],
            "agent_count": len(ids),
        })
        log.info("[GodSwarm] Coordination %s started: %d agents, task=%r", coord_id, len(ids), task[:80])

        result = self.dispatch(
            task=task,
            agent_ids=ids,
            context={"coord_id": coord_id, "phase": "coordinate"},
            use_consensus=True,
        )

        self._emit("god_swarm.coordination.complete", {
            "coord_id": coord_id,
            "task": task[:200],
            "agent_count": len(ids),
            "result_type": type(result).__name__,
        })
        log.info("[GodSwarm] Coordination %s complete", coord_id)
        return result

    # ------------------------------------------------------------------
    # wire_to_kernel — kernel boot sequence integration
    # ------------------------------------------------------------------

    def wire_to_kernel(self, kernel: Any) -> None:
        """Wire this GodSwarm into the kernel boot sequence.

        Stores the kernel reference and emits a wired event.
        The kernel is expected to expose an event bus via kernel.bus.
        """
        self._kernel = kernel
        # Prefer kernel's bus if available and no bus already set
        if self._bus is None and hasattr(kernel, "bus"):
            self._bus = kernel.bus
        self._emit("god_swarm.kernel.wired", {
            "kernel_type": type(kernel).__name__,
            "agent_count": len(self.ALL_AGENT_IDS),
            "dynamic_agents": len(self._dynamic_agents),
        })
        log.info("[GodSwarm] Wired to kernel: %s", type(kernel).__name__)

    # ------------------------------------------------------------------
    # Public API (pre-existing)
    # ------------------------------------------------------------------

    def analyze_and_dispatch(self, objective: str) -> SwarmResult:
        """
        Full god-swarm workflow:
        1. Omniscient analyses the objective.
        2. Oracle checks for known patterns.
        3. Architect designs the composition.
        4. All remaining agents contribute to the consensus answer.
        """
        # Phase 1 — analysis agents build shared context
        analysis_agents = ["omniscient", "oracle", "architect"]

        # Phase 2 — full swarm answers
        execution_agents = self.ALL_AGENT_IDS

        return self.dispatch(
            task=objective,
            agent_ids=execution_agents,
            context={"objective": objective, "phase": "god_swarm_full"},
            use_consensus=True,
        )

    def status(self) -> dict:
        base = super().status()
        base["core_agents"] = self.CORE_AGENT_IDS
        base["supporting_agents"] = self.SUPPORTING_AGENT_IDS
        base["dynamic_agents"] = list(self._dynamic_agents.values())
        base["kernel_wired"] = self._kernel is not None
        return base

# ---------------------------------------------------------------------------
# Agent definitions extracted from GOD_SWARM.md
# ---------------------------------------------------------------------------

_CORE_AGENTS: list[dict] = [
    {
        "agent_id": "omniscient",
        "role": "Requirement Analyzer",
        "description": "Deeply understands user intent, constraints, and success criteria.",
        "capabilities": ["requirement-parsing", "intent-detection", "constraint-analysis"],
    },
    {
        "agent_id": "architect",
        "role": "Swarm Composer",
        "description": "Designs swarm topology, selects agent types, and plans dependencies.",
        "capabilities": ["topology-design", "agent-selection", "dependency-planning"],
    },
    {
        "agent_id": "demiurge",
        "role": "Swarm Creator",
        "description": "Spawns sub-swarms, assigns objectives, and provisions resources.",
        "capabilities": ["swarm-spawning", "resource-provisioning", "objective-assignment"],
    },
    {
        "agent_id": "chronos",
        "role": "Progress Monitor",
        "description": "Tracks swarm activities, detects stalls and failures, enforces timeouts.",
        "capabilities": ["progress-tracking", "failure-detection", "timeout-enforcement"],
    },
    {
        "agent_id": "arbiter",
        "role": "Conflict Resolver",
        "description": "Resolves disputes between swarms and handles resource contention.",
        "capabilities": ["conflict-resolution", "resource-scheduling", "negotiation"],
    },
    {
        "agent_id": "scribe",
        "role": "Context Keeper",
        "description": "Maintains shared state and ensures continuity across swarm handoffs.",
        "capabilities": ["state-management", "context-persistence", "handoff-continuity"],
    },
]

_SUPPORTING_AGENTS: list[dict] = [
    {
        "agent_id": "oracle",
        "role": "Pattern Recognizer",
        "description": "Matches objectives to known swarm patterns from history.",
        "capabilities": ["pattern-matching", "history-lookup", "swarm-recommendation"],
    },
    {
        "agent_id": "alchemist",
        "role": "Swarm Optimizer",
        "description": "Tweaks swarm composition based on real-time performance signals.",
        "capabilities": ["performance-monitoring", "composition-tuning", "optimization"],
    },
    {
        "agent_id": "reaper",
        "role": "Cleanup Manager",
        "description": "Destroys completed or failed swarms and archives learnings.",
        "capabilities": ["swarm-teardown", "artifact-archival", "learning-capture"],
    },
    {
        "agent_id": "librarian",
        "role": "Knowledge Curator",
        "description": "Updates swarm registry with new patterns and improvements.",
        "capabilities": ["registry-update", "knowledge-indexing", "pattern-curation"],
    },
]


# ---------------------------------------------------------------------------
# Phase 5 — EmergentSwarm
# ---------------------------------------------------------------------------

import threading as _threading  # noqa: E402


class EmergentSwarm:
    """Emergent multi-agent coordination with collective decision-making.

    Agents cast weighted votes on topics.  Votes are tallied using confidence-
    weighted majority, and recurring high-confidence outcomes are recorded as
    *emergent behaviors* — stable collective patterns the swarm has learned.

    Parameters
    ----------
    agents  List of agent name strings participating in the swarm.
    bus     Optional event bus for publishing coordination events.
    """

    def __init__(self, agents: list[str], bus: "Any | None" = None) -> None:
        self._agents = list(agents)
        self._bus = bus
        # topic -> list of {agent, vote, confidence, ts}
        self._votes: dict[str, list[dict[str, Any]]] = {}
        self._emergent_behaviors: list[dict[str, Any]] = []
        self._lock = _threading.Lock()

    # ------------------------------------------------------------------
    # Voting
    # ------------------------------------------------------------------

    def cast_vote(
        self,
        topic: str,
        agent: str,
        vote: str,
        confidence: float = 0.5,
    ) -> None:
        """Record a vote from *agent* on *topic*."""
        confidence = max(0.0, min(1.0, float(confidence)))
        entry: dict[str, Any] = {
            "agent": agent,
            "vote": vote,
            "confidence": confidence,
            "ts": time.time(),
        }
        with self._lock:
            self._votes.setdefault(topic, []).append(entry)

    # ------------------------------------------------------------------
    # Tallying
    # ------------------------------------------------------------------

    def tally(self, topic: str) -> dict[str, Any]:
        """Tally votes for *topic* using confidence-weighted voting.

        Returns dict with keys: topic, winner, confidence, vote_count, breakdown.
        """
        with self._lock:
            votes = list(self._votes.get(topic, []))

        if not votes:
            return {
                "topic": topic,
                "winner": "",
                "confidence": 0.0,
                "vote_count": 0,
                "breakdown": {},
            }

        breakdown: dict[str, float] = {}
        for v in votes:
            breakdown[v["vote"]] = breakdown.get(v["vote"], 0.0) + v["confidence"]

        winner = max(breakdown, key=lambda k: breakdown[k])
        total_weight = sum(breakdown.values())
        win_confidence = round(breakdown[winner] / total_weight, 4) if total_weight else 0.0

        return {
            "topic": topic,
            "winner": winner,
            "confidence": win_confidence,
            "vote_count": len(votes),
            "breakdown": {k: round(v, 4) for k, v in breakdown.items()},
        }

    # ------------------------------------------------------------------
    # Emergent pattern detection
    # ------------------------------------------------------------------

    def detect_emergent_pattern(self, topic: str) -> "dict[str, Any] | None":
        """Detect if a stable emergent pattern has formed.

        Returns dict with behavior/confidence/agents_involved, or None.
        """
        result = self.tally(topic)
        if result["confidence"] <= 0.7 or not result["winner"]:
            return None

        behavior_record: dict[str, Any] = {
            "behavior": result["winner"],
            "topic": topic,
            "confidence": result["confidence"],
            "agents_involved": result["vote_count"],
            "detected_at": time.time(),
        }

        with self._lock:
            already = any(
                b["topic"] == topic and b["behavior"] == result["winner"]
                for b in self._emergent_behaviors
            )
            if not already:
                self._emergent_behaviors.append(behavior_record)

        return {
            "behavior": behavior_record["behavior"],
            "confidence": behavior_record["confidence"],
            "agents_involved": behavior_record["agents_involved"],
        }

    # ------------------------------------------------------------------
    # Collective reasoning cycle
    # ------------------------------------------------------------------

    def run_collective_reasoning(
        self,
        query: str,
        agent_perspectives: dict[str, str],
    ) -> dict[str, Any]:
        """Run a full emergent reasoning cycle and return decision dict."""
        topic = query

        for agent, perspective in agent_perspectives.items():
            vote_label = perspective.strip()[:80] or "no_opinion"
            raw_conf = min(1.0, len(perspective) / 200.0)
            self.cast_vote(topic=topic, agent=agent, vote=vote_label, confidence=raw_conf)

        tally_result = self.tally(topic)
        emergent = self.detect_emergent_pattern(topic)

        return {
            "query": query,
            "decision": tally_result.get("winner", ""),
            "confidence": tally_result.get("confidence", 0.0),
            "emergent": emergent,
            "perspectives": dict(agent_perspectives),
        }

    # ------------------------------------------------------------------
    # Behavior listing
    # ------------------------------------------------------------------

    def list_behaviors(self) -> list[dict[str, Any]]:
        """Return all detected emergent behaviors (snapshot)."""
        with self._lock:
            return list(self._emergent_behaviors)
