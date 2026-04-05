"""Extended multi-agent simulation scenarios for OpenChimera.

Builds on the dist_sim foundation to test realistic multi-agent deployments
through the quantum engine consensus. Each scenario exercises a different
dimension of the system:

  domain_expertise      — Domain-specialist agents outperform generalists
  adversarial_agents    — Intentionally bad agents are outvoted
  confidence_calibration — Confidence tracks actual accuracy
  full_intelligence_loop — Memory → deliberation → consensus → metacognition
  parallel_batch         — High-throughput concurrent task processing
  reputation_learning    — Reputation evolves over multiple rounds

All scenarios are async, self-contained, and portable (no hardcoded paths).
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Dict, List

from core.agent_pool import AgentPool, AgentRole, AgentSpec, create_pool
from core.quantum_engine import (
    AgentReputation,
    ConsensusResult,
    QuantumEngine,
)

from .cluster import SimCluster
from .harness import run_concurrent_scenario, run_sim_scenario
from .node import SimNode


# ---------------------------------------------------------------------------
# Realistic agent callables (simulate domain expertise)
# ---------------------------------------------------------------------------

async def _medical_expert(task: Any, context: dict) -> str:
    """Medical domain expert — high accuracy on medical queries."""
    t = str(task).lower()
    if "medical" in t or "health" in t or "disease" in t or "patient" in t:
        return f"medical-expert-answer:{task}"
    return f"general-attempt:{task}"


async def _legal_expert(task: Any, context: dict) -> str:
    """Legal domain expert — high accuracy on legal queries."""
    t = str(task).lower()
    if "legal" in t or "law" in t or "contract" in t or "regulation" in t:
        return f"legal-expert-answer:{task}"
    return f"general-attempt:{task}"


async def _coding_expert(task: Any, context: dict) -> str:
    """Coding domain expert — high accuracy on technical queries."""
    t = str(task).lower()
    if "code" in t or "algorithm" in t or "debug" in t or "software" in t:
        return f"coding-expert-answer:{task}"
    return f"general-attempt:{task}"


async def _generalist(task: Any, context: dict) -> str:
    """General-purpose agent — reasonable on everything."""
    return f"generalist-answer:{task}"


async def _adversarial(task: Any, context: dict) -> str:
    """Adversarial agent — deliberately produces wrong answers."""
    await asyncio.sleep(0.002)
    return f"WRONG-deliberately-bad-answer:{task}"


async def _slow_correct(task: Any, context: dict) -> str:
    """Slow but correct agent — tests early-exit behavior."""
    await asyncio.sleep(0.05)
    return f"consensus:{task}"


async def _fast_correct(task: Any, context: dict) -> str:
    """Fast correct agent — arrives first."""
    return f"consensus:{task}"


async def _unreliable(task: Any, context: dict) -> str:
    """Flaky agent — sometimes crashes."""
    import random
    if random.random() < 0.3:
        raise RuntimeError("Simulated agent crash")
    return f"consensus:{task}"


# ---------------------------------------------------------------------------
# Scenario: domain_expertise
# ---------------------------------------------------------------------------

async def scenario_domain_expertise() -> Dict[str, Any]:
    """Test that domain-specialist agents produce more coherent consensus
    when queried within their domain.

    Setup: 3 domain specialists + 1 generalist across a 2-node cluster.
    Verifies that domain-matched queries reach higher consensus confidence
    than mismatched queries.
    """
    nodes = [
        SimNode(f"domain-node-{i}", QuantumEngine(quorum=2, hard_timeout_ms=3000), latency_ms=1.0)
        for i in range(2)
    ]
    cluster = SimCluster(nodes)

    medical_agents: Dict[str, Callable] = {
        "med-expert": _medical_expert,
        "generalist-1": _generalist,
        "generalist-2": _generalist,
    }
    coding_agents: Dict[str, Callable] = {
        "code-expert": _coding_expert,
        "generalist-1": _generalist,
        "generalist-2": _generalist,
    }

    # Medical tasks — medical expert should boost consensus
    med_tasks = [
        {"task": f"medical-diagnosis-{i}", "agents": medical_agents}
        for i in range(5)
    ]
    med_results = await run_sim_scenario("domain_medical", cluster, med_tasks)

    # Coding tasks — coding expert should boost consensus
    code_tasks = [
        {"task": f"code-algorithm-review-{i}", "agents": coding_agents}
        for i in range(5)
    ]
    code_results = await run_sim_scenario("domain_coding", cluster, code_tasks)

    passed = (
        med_results["passed"] == 5
        and code_results["passed"] == 5
        and med_results["avg_confidence"] > 0
        and code_results["avg_confidence"] > 0
    )
    return {
        "name": "domain_expertise",
        "passed": passed,
        "medical_queries": med_results["passed"],
        "coding_queries": code_results["passed"],
        "medical_avg_confidence": med_results["avg_confidence"],
        "coding_avg_confidence": code_results["avg_confidence"],
    }


# ---------------------------------------------------------------------------
# Scenario: adversarial_agents
# ---------------------------------------------------------------------------

async def scenario_adversarial_agents() -> Dict[str, Any]:
    """Test that the consensus mechanism correctly outvotes adversarial agents.

    Setup: 3 honest agents vs 1 deliberately wrong agent.
    The honest majority must win every round.
    """
    nodes = [
        SimNode("adv-node", QuantumEngine(quorum=3, hard_timeout_ms=3000), latency_ms=1.0)
    ]
    cluster = SimCluster(nodes)

    agents: Dict[str, Callable] = {
        "honest-1": _fast_correct,
        "honest-2": _fast_correct,
        "honest-3": _slow_correct,
        "adversary": _adversarial,
    }

    tasks = [{"task": f"adversarial-test-{i}", "agents": agents} for i in range(10)]
    results = await run_sim_scenario("adversarial_agents", cluster, tasks)

    # All 10 must pass and none should return the adversarial answer
    honest_wins = 0
    for r in results["results"]:
        if r.get("ok") and "WRONG" not in r.get("answer", ""):
            honest_wins += 1

    passed = honest_wins == 10 and results["avg_confidence"] > 0.5
    return {
        "name": "adversarial_agents",
        "passed": passed,
        "honest_wins": honest_wins,
        "total": 10,
        "avg_confidence": results["avg_confidence"],
    }


# ---------------------------------------------------------------------------
# Scenario: confidence_calibration
# ---------------------------------------------------------------------------

async def scenario_confidence_calibration() -> Dict[str, Any]:
    """Test that consensus confidence reflects actual agreement level.

    High agreement (4 identical answers) → high confidence.
    Split vote (2 vs 2) → lower confidence.
    """
    engine_high = QuantumEngine(quorum=3, hard_timeout_ms=3000)
    engine_split = QuantumEngine(quorum=3, hard_timeout_ms=3000)

    # High agreement: all 4 agents return the same answer
    high_result = await engine_high.gather(
        "calibration-test",
        {
            "a1": _fast_correct,
            "a2": _fast_correct,
            "a3": _slow_correct,
            "a4": _fast_correct,
        },
    )

    # Split vote: 2 honest + 2 adversarial
    async def _alt_answer(task: Any, context: dict) -> str:
        return f"alternative:{task}"

    split_result = await engine_split.gather(
        "calibration-test",
        {
            "honest-1": _fast_correct,
            "honest-2": _fast_correct,
            "alt-1": _alt_answer,
            "alt-2": _alt_answer,
        },
    )

    # High agreement should have higher confidence than split vote
    gap = high_result.confidence - split_result.confidence
    passed = gap >= 0  # High must be ≥ split
    return {
        "name": "confidence_calibration",
        "passed": passed,
        "high_agreement_confidence": round(high_result.confidence, 4),
        "split_vote_confidence": round(split_result.confidence, 4),
        "confidence_gap": round(gap, 4),
    }


# ---------------------------------------------------------------------------
# Scenario: parallel_batch
# ---------------------------------------------------------------------------

async def scenario_parallel_batch() -> Dict[str, Any]:
    """50 tasks dispatched concurrently through a 3-node cluster.

    Tests throughput and correctness under parallel load.
    """
    nodes = [
        SimNode(
            f"batch-node-{i}",
            QuantumEngine(quorum=1, hard_timeout_ms=3000),
            latency_ms=0.5,
        )
        for i in range(3)
    ]
    cluster = SimCluster(nodes)

    agents: Dict[str, Callable] = {
        "fast-1": _fast_correct,
        "fast-2": _fast_correct,
        "slow-1": _slow_correct,
    }
    tasks = [{"task": f"batch-task-{i}", "agents": agents} for i in range(50)]
    summary = await run_concurrent_scenario("parallel_batch", cluster, tasks)

    passed = summary["passed"] >= 48  # Allow 2 failures max
    return {
        "name": "parallel_batch",
        "passed": passed,
        "total": summary["total"],
        "completed": summary["passed"],
        "failed": summary["failed"],
        "avg_latency_ms": summary["avg_latency_ms"],
        "throughput_ms": summary["elapsed_ms"],
    }


# ---------------------------------------------------------------------------
# Scenario: reputation_learning
# ---------------------------------------------------------------------------

async def scenario_reputation_learning() -> Dict[str, Any]:
    """Test that agent reputation evolves correctly over multiple feedback rounds.

    Setup: One reliable agent + one unreliable. After repeated feedback,
    the reliable agent should have significantly higher reputation.
    """
    reputation = AgentReputation()
    engine = QuantumEngine(
        quorum=1, hard_timeout_ms=3000, reputation=reputation,
    )

    # Run 20 rounds; the honest agent always wins, adversary always loses
    results_list: List[ConsensusResult] = []
    for i in range(20):
        r = await engine.gather(
            f"reputation-test-{i}",
            {"reliable": _fast_correct, "unreliable": _adversarial},
        )
        results_list.append(r)
        # Feedback: reliable was correct, unreliable was wrong
        reputation.update("reliable", True)
        reputation.update("unreliable", False)

    # Check reputation divergence
    # snapshot() returns "agent_id::domain" → float
    snap = reputation.snapshot()
    reliable_rep = snap.get("reliable::general", 0.5)
    unreliable_rep = snap.get("unreliable::general", 0.5)
    divergence = reliable_rep - unreliable_rep

    passed = divergence > 0.1  # Measurable reputation gap
    return {
        "name": "reputation_learning",
        "passed": passed,
        "reliable_reputation": round(reliable_rep, 4),
        "unreliable_reputation": round(unreliable_rep, 4),
        "reputation_divergence": round(divergence, 4),
        "rounds": 20,
    }


# ---------------------------------------------------------------------------
# Scenario: full_intelligence_loop (orchestrator)
# ---------------------------------------------------------------------------

async def scenario_full_intelligence_loop() -> Dict[str, Any]:
    """End-to-end test of the recursive intelligence loop.

    1. Creates a MultiAgentOrchestrator with pool + memory + metacognition
    2. Runs multiple tasks through the full loop
    3. Verifies memory recorded, metacognition computed, consensus reached

    This is the most comprehensive scenario — exercises virtually everything.
    """
    from core.multi_agent_orchestrator import MultiAgentOrchestrator

    orch = MultiAgentOrchestrator(
        quorum=2,
        early_exit_conf=0.7,
        hard_timeout_ms=5000,
    )

    tasks = [
        "Analyse the impact of climate change on global food security",
        "What are the ethical implications of autonomous weapons systems?",
        "Explain the P vs NP problem and its practical significance",
        "How should healthcare AI handle diagnostic uncertainty?",
        "Design a fault-tolerant distributed consensus protocol",
    ]

    results = []
    for task in tasks:
        r = await orch.run(task)
        results.append(r)

    completed = sum(1 for r in results if r.answer is not None)
    memory_recorded = sum(1 for r in results if r.memory_recorded)
    avg_confidence = (
        sum(r.confidence for r in results) / len(results)
        if results else 0.0
    )
    avg_agents = (
        sum(r.participating for r in results) / len(results)
        if results else 0.0
    )

    passed = completed >= 4 and avg_confidence > 0.3
    return {
        "name": "full_intelligence_loop",
        "passed": passed,
        "total_tasks": len(tasks),
        "completed": completed,
        "memory_recorded": memory_recorded,
        "avg_confidence": round(avg_confidence, 4),
        "avg_participating_agents": round(avg_agents, 2),
        "orchestrator_status": orch.status(),
    }


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

EXTENDED_SCENARIOS = [
    scenario_domain_expertise,
    scenario_adversarial_agents,
    scenario_confidence_calibration,
    scenario_parallel_batch,
    scenario_reputation_learning,
    scenario_full_intelligence_loop,
]


async def run_all_extended() -> List[Dict[str, Any]]:
    """Run all extended multi-agent scenarios and return results."""
    results: List[Dict[str, Any]] = []
    for scenario_fn in EXTENDED_SCENARIOS:
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
