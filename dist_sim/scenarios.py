"""Pre-built simulation scenarios for OpenChimera distributed consensus.

Each scenario function is async, creates its own cluster, runs tasks, and
returns a result dict with at minimum:
  - name: str
  - passed: bool

Scenarios
---------
split_brain          Two-node cluster where agents are split; majority wins.
high_load            100 concurrent tasks across a 3-node cluster.
cascading_failure    Nodes go offline one by one; last node offline → error.
consensus_recovery   Partial failure followed by node recovery.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List

from core.quantum_engine import QuantumEngine

from .cluster import SimCluster
from .harness import run_concurrent_scenario, run_sim_scenario
from .node import SimNode


# ---------------------------------------------------------------------------
# Shared simulated agent callables
# ---------------------------------------------------------------------------

async def _agree(task: Any, context: dict) -> str:
    """Fast-path agent that always returns the canonical answer."""
    return f"consensus:{task}"


async def _agree_slow(task: Any, context: dict) -> str:
    """Slower agreeing agent — arrives after fast agents."""
    await asyncio.sleep(0.01)
    return f"consensus:{task}"


async def _dissent(task: Any, context: dict) -> str:
    """Dissenting agent — returns a different answer."""
    await asyncio.sleep(0.005)
    return f"diverge:{task}"


async def _fault(task: Any, context: dict) -> str:
    """Always raises to simulate an agent crash."""
    raise RuntimeError("Simulated agent fault")


# ---------------------------------------------------------------------------
# Scenario: split_brain
# ---------------------------------------------------------------------------

async def scenario_split_brain() -> Dict[str, Any]:
    """Two-node cluster; agents are split but majority agrees on one answer.

    The 2:1 majority of agreeing agents should win the consensus vote.
    Verifies that the engine resolves disagreement via weighted voting.
    """
    engine_a = QuantumEngine(quorum=2, early_exit_conf=0.85, hard_timeout_ms=2000)
    engine_b = QuantumEngine(quorum=2, early_exit_conf=0.85, hard_timeout_ms=2000)
    node_a = SimNode("split-node-a", engine_a, latency_ms=2.0)
    node_b = SimNode("split-node-b", engine_b, latency_ms=2.0)
    cluster = SimCluster([node_a, node_b])

    # 2 agreeing agents + 1 dissenter — majority wins
    agents = {
        "agent-agree-1": _agree,
        "agent-agree-2": _agree_slow,
        "agent-dissent": _dissent,
    }
    tasks = [{"task": f"split-q{i}", "agents": agents} for i in range(4)]
    summary = await run_sim_scenario("split_brain", cluster, tasks)

    passed = summary["passed"] >= 3 and summary["avg_confidence"] > 0.5
    return {
        "name": "split_brain",
        "passed": passed,
        "total_queries": summary["total"],
        "successful_queries": summary["passed"],
        "avg_confidence": summary["avg_confidence"],
    }


# ---------------------------------------------------------------------------
# Scenario: high_load
# ---------------------------------------------------------------------------

async def scenario_high_load() -> Dict[str, Any]:
    """100 tasks dispatched concurrently across a 3-node cluster.

    All tasks must complete successfully with no failures.
    """
    nodes = [
        SimNode(
            f"load-node-{i}",
            QuantumEngine(quorum=1, hard_timeout_ms=3000),
            latency_ms=1.0,
        )
        for i in range(3)
    ]
    cluster = SimCluster(nodes)

    agents = {
        "agent-fast": _agree,
        "agent-confirm": _agree_slow,
    }
    tasks = [{"task": f"load-task-{i}", "agents": agents} for i in range(100)]
    summary = await run_concurrent_scenario("high_load", cluster, tasks)

    passed = summary["passed"] == 100
    return {
        "name": "high_load",
        "passed": passed,
        "total": summary["total"],
        "completed": summary["passed"],
        "failed": summary["failed"],
        "avg_latency_ms": summary["avg_latency_ms"],
        "elapsed_ms": summary["elapsed_ms"],
    }


# ---------------------------------------------------------------------------
# Scenario: cascading_failure
# ---------------------------------------------------------------------------

async def scenario_cascading_failure() -> Dict[str, Any]:
    """
    Three-node cluster loses nodes one at a time.

    Phase 1 (3 nodes online):  queries succeed.
    Phase 2 (node-0 offline):  2 remaining nodes handle queries.
    Phase 3 (nodes-0,1 offline): last node handles queries.
    Phase 4 (all offline):     queries must raise RuntimeError.
    """
    nodes = [
        SimNode(
            f"fail-node-{i}",
            QuantumEngine(quorum=1, hard_timeout_ms=2000),
            latency_ms=1.0,
        )
        for i in range(3)
    ]
    cluster = SimCluster(nodes)
    agents = {"agent-a": _agree, "agent-b": _agree_slow}

    # Phase 1 — all online
    p1 = await run_sim_scenario(
        "cascading_p1", cluster, [{"task": "p1", "agents": agents} for _ in range(2)]
    )

    # Phase 2 — first node offline
    nodes[0].set_online(False)
    p2 = await run_sim_scenario(
        "cascading_p2", cluster, [{"task": "p2", "agents": agents} for _ in range(2)]
    )

    # Phase 3 — second node offline
    nodes[1].set_online(False)
    p3 = await run_sim_scenario(
        "cascading_p3", cluster, [{"task": "p3", "agents": agents}]
    )

    # Phase 4 — last node offline; must fail
    nodes[2].set_online(False)
    p4 = await run_sim_scenario(
        "cascading_p4", cluster, [{"task": "p4", "agents": agents}]
    )

    passed = (
        p1["passed"] == 2
        and p2["passed"] == 2
        and p3["passed"] == 1
        and p4["failed"] == 1        # all-offline raises → counted as failed
    )
    return {
        "name": "cascading_failure",
        "passed": passed,
        "phase1_ok": p1["passed"],
        "phase2_ok": p2["passed"],
        "phase3_ok": p3["passed"],
        "phase4_errors": p4["failed"],
    }


# ---------------------------------------------------------------------------
# Scenario: consensus_recovery
# ---------------------------------------------------------------------------

async def scenario_consensus_recovery() -> Dict[str, Any]:
    """Cluster experiences partial failure then nodes recover.

    Phase 1 (all online):       queries succeed.
    Phase 2 (2 nodes offline):  single surviving node still handles queries.
    Phase 3 (nodes restored):   cluster handles multiple queries after recovery.
    """
    nodes = [
        SimNode(
            f"rec-node-{i}",
            QuantumEngine(quorum=1, hard_timeout_ms=2000),
            latency_ms=1.0,
        )
        for i in range(3)
    ]
    cluster = SimCluster(nodes)
    agents = {"agent-a": _agree, "agent-b": _agree_slow}

    pre = await run_sim_scenario(
        "recovery_pre", cluster, [{"task": "pre-failure", "agents": agents}]
    )

    # Partial failure
    nodes[0].set_online(False)
    nodes[1].set_online(False)
    during = await run_sim_scenario(
        "recovery_during", cluster, [{"task": "during-failure", "agents": agents}]
    )

    # Recovery
    nodes[0].set_online(True)
    nodes[1].set_online(True)
    post = await run_sim_scenario(
        "recovery_post",
        cluster,
        [{"task": f"post-{i}", "agents": agents} for i in range(3)],
    )

    passed = (
        pre["passed"] == 1
        and during["passed"] == 1
        and post["passed"] == 3
    )
    return {
        "name": "consensus_recovery",
        "passed": passed,
        "pre_failure_ok": pre["passed"],
        "during_failure_ok": during["passed"],
        "post_recovery_ok": post["passed"],
        "cluster_stats": cluster.stats(),
    }


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

SCENARIOS = [
    scenario_split_brain,
    scenario_high_load,
    scenario_cascading_failure,
    scenario_consensus_recovery,
]


async def run_all() -> List[Dict[str, Any]]:
    """Run all built-in scenarios and return their result dicts."""
    results: List[Dict[str, Any]] = []
    for scenario_fn in SCENARIOS:
        try:
            result = await scenario_fn()
        except Exception as exc:
            result = {
                "name": scenario_fn.__name__,
                "passed": False,
                "error": str(exc),
            }
        results.append(result)
    return results
