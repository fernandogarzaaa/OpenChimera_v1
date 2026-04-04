"""GodSwarm — the 10-agent meta-orchestrator.

Implements the GOD_SWARM architecture documented in swarms/GOD_SWARM.md.

Core agents (6):   Omniscient, Architect, Demiurge, Chronos, Arbiter, Scribe
Supporting agents (4): Oracle, Alchemist, Reaper, Librarian
"""
from __future__ import annotations

from swarms.agent import SwarmAgent
from swarms.orchestrator import SwarmOrchestrator
from swarms.result import SwarmResult

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
    """

    CORE_AGENT_IDS = [a["agent_id"] for a in _CORE_AGENTS]
    SUPPORTING_AGENT_IDS = [a["agent_id"] for a in _SUPPORTING_AGENTS]
    ALL_AGENT_IDS = CORE_AGENT_IDS + SUPPORTING_AGENT_IDS

    def __init__(self) -> None:
        super().__init__()
        for spec in _CORE_AGENTS + _SUPPORTING_AGENTS:
            self.register(SwarmAgent(**spec))

    # ------------------------------------------------------------------
    # Public API
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
        return base
