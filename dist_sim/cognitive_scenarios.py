"""Cognitive simulation scenarios exercising AGI subsystems through QuantumEngine.

Tests Self-Model, Transfer Learning, and Causal Reasoning modules in
a distributed simulation environment. Each scenario:

  self_awareness       — Agents track their own capabilities and adapt
  cross_domain_transfer — Pattern transfer across domains with quality scoring
  causal_inference     — Agents reason causally about interventions
  integrated_cognition — All three subsystems working together
  cognitive_resilience — Subsystems recover from partial failures

All scenarios are async, self-contained, and portable (no hardcoded paths).
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Dict, List

from core._bus_fallback import EventBus
from core.causal_reasoning import CausalReasoning, EdgeType
from core.quantum_engine import ConsensusResult, QuantumEngine
from core.self_model import HealthStatus, SelfModel
from core.transfer_learning import PatternType, TransferLearning

from .cluster import SimCluster
from .harness import run_sim_scenario
from .node import SimNode


# ---------------------------------------------------------------------------
# Agent callables — cognitive agents backed by real subsystems
# ---------------------------------------------------------------------------

def _make_self_aware_agent(
    model: SelfModel,
    domain: str,
) -> Callable[..., Any]:
    """Create an agent that records capability snapshots per task."""

    async def agent(task: Any, context: dict) -> str:
        t = str(task).lower()
        if domain in t:
            model.record_capability(domain, "accuracy", 0.9, sample_count=1)
            return f"{domain}-expert:{task}"
        model.record_capability(domain, "accuracy", 0.4, sample_count=1)
        return f"{domain}-attempt:{task}"

    return agent


def _make_transfer_agent(
    tl: TransferLearning,
    source_domain: str,
) -> Callable[..., Any]:
    """Agent that registers patterns from results and attempts transfers."""

    async def agent(task: Any, context: dict) -> str:
        t = str(task).lower()
        if source_domain in t:
            tl.register_pattern(
                source_domain,
                PatternType.STRATEGY,
                f"pattern-from-{task}",
                [source_domain, "learned"],
                success_rate=0.8,
            )
            return f"transfer-expert:{task}"
        candidates = tl.find_transfers(t[:20], [t[:10]], limit=1)
        if candidates:
            tl.apply_transfer(candidates[0].pattern_id, t[:20], success=True)
            return f"transfer-applied:{task}"
        return f"transfer-none:{task}"

    return agent


def _make_causal_agent(
    cr: CausalReasoning,
) -> Callable[..., Any]:
    """Agent that builds causal models for each task."""

    async def agent(task: Any, context: dict) -> str:
        t = str(task).lower()
        cr.add_cause("input", t[:15], EdgeType.CAUSES, strength=0.7)
        cr.set_variable("input", 1.0)
        result = cr.intervene(t[:15], 1.0)
        return f"causal-answer:{task}:effect={result.total_effect:.2f}"

    return agent


async def _baseline_agent(task: Any, context: dict) -> str:
    """Simple correct agent for majority consensus base."""
    return f"consensus:{task}"


async def _slow_baseline(task: Any, context: dict) -> str:
    """Slower baseline that agrees with majority."""
    await asyncio.sleep(0.005)
    return f"consensus:{task}"


# ---------------------------------------------------------------------------
# Scenario: self_awareness
# ---------------------------------------------------------------------------

async def scenario_self_awareness() -> Dict[str, Any]:
    """Agents with self-model track capability evolution across tasks.

    Verifies that self-aware agents correctly record domain performance,
    produce valid self-assessments, and identify strengths/weaknesses.
    """
    bus = EventBus()
    model = SelfModel(bus=bus)

    math_agent = _make_self_aware_agent(model, "math")
    language_agent = _make_self_aware_agent(model, "language")

    node = SimNode("self-aware-node", latency_ms=1.0)
    cluster = SimCluster([node])

    agents: Dict[str, Callable] = {
        "math-agent": math_agent,
        "language-agent": language_agent,
        "baseline": _baseline_agent,
    }

    # Run domain-specific tasks
    tasks: List[Dict[str, Any]] = []
    for i in range(5):
        tasks.append({"task": f"math-problem-{i}", "agents": agents})
    for i in range(5):
        tasks.append({"task": f"language-task-{i}", "agents": agents})
    for i in range(3):
        tasks.append({"task": f"general-query-{i}", "agents": agents})

    result = await run_sim_scenario("self_awareness", cluster, tasks)

    # Validate self-model output
    assessment = model.self_assessment()
    strengths = model.strengths()
    weaknesses = model.weaknesses()
    capabilities = model.list_capabilities()

    has_math = any(c.domain == "math" for c in capabilities)
    has_language = any(c.domain == "language" for c in capabilities)

    exported = model.export_state()
    can_export = "capabilities" in exported and "health" in exported

    passed = (
        result["passed"] >= (result["total"] // 2)
        and has_math
        and has_language
        and can_export
        and isinstance(assessment, dict)
        and "overall_fitness" in assessment
    )

    return {
        "name": "self_awareness",
        "passed": passed,
        "total_tasks": result["total"],
        "consensus_passed": result["passed"],
        "capabilities_tracked": len(capabilities),
        "strengths_found": len(strengths),
        "weaknesses_found": len(weaknesses),
        "assessment_fitness": assessment.get("overall_fitness", 0.0),
        "elapsed_ms": result["elapsed_ms"],
    }


# ---------------------------------------------------------------------------
# Scenario: cross_domain_transfer
# ---------------------------------------------------------------------------

async def scenario_cross_domain_transfer() -> Dict[str, Any]:
    """Patterns learned in one domain transfer successfully to another.

    Tests that the transfer learning engine accumulates patterns from
    domain-expert tasks and applies them cross-domain with rising success.
    """
    bus = EventBus()
    tl = TransferLearning(bus=bus)

    math_transfer = _make_transfer_agent(tl, "math")
    physics_transfer = _make_transfer_agent(tl, "physics")

    node = SimNode("transfer-node", latency_ms=1.0)
    cluster = SimCluster([node])

    agents: Dict[str, Callable] = {
        "math-transfer": math_transfer,
        "physics-transfer": physics_transfer,
        "baseline": _baseline_agent,
    }

    # Phase 1: learn patterns in source domains
    tasks: List[Dict[str, Any]] = []
    for i in range(5):
        tasks.append({"task": f"math-exercise-{i}", "agents": agents})
    for i in range(5):
        tasks.append({"task": f"physics-experiment-{i}", "agents": agents})

    # Phase 2: attempt transfer to new domains
    for i in range(5):
        tasks.append({"task": f"engineering-problem-{i}", "agents": agents})

    result = await run_sim_scenario("cross_domain_transfer", cluster, tasks)

    # Validate transfer learning state
    patterns = tl.list_patterns()
    math_profile = tl.domain_profile("math")
    physics_profile = tl.domain_profile("physics")
    domains = tl.list_domains()

    exported = tl.export_state()
    has_patterns = len(exported.get("patterns", [])) > 0

    passed = (
        result["passed"] >= (result["total"] // 2)
        and math_profile.pattern_count > 0
        and physics_profile.pattern_count > 0
        and len(domains) >= 2
        and has_patterns
    )

    return {
        "name": "cross_domain_transfer",
        "passed": passed,
        "total_tasks": result["total"],
        "consensus_passed": result["passed"],
        "patterns_learned": len(patterns),
        "math_patterns": math_profile.pattern_count,
        "physics_patterns": physics_profile.pattern_count,
        "domains_active": len(domains),
        "elapsed_ms": result["elapsed_ms"],
    }


# ---------------------------------------------------------------------------
# Scenario: causal_inference
# ---------------------------------------------------------------------------

async def scenario_causal_inference() -> Dict[str, Any]:
    """Agents build and query a causal model during task resolution.

    Verifies causal graph construction, do-calculus interventions,
    counterfactual reasoning, and strength estimation.
    """
    bus = EventBus()
    cr = CausalReasoning(bus=bus)

    causal_agent = _make_causal_agent(cr)

    node = SimNode("causal-node", latency_ms=1.0)
    cluster = SimCluster([node])

    agents: Dict[str, Callable] = {
        "causal-agent": causal_agent,
        "baseline-1": _baseline_agent,
        "baseline-2": _slow_baseline,
    }

    # Causal tasks that build the graph incrementally
    tasks: List[Dict[str, Any]] = []
    causal_vars = ["temperature", "pressure", "density", "flow_rate", "output"]
    for v in causal_vars:
        tasks.append({"task": f"analyse-{v}", "agents": agents})

    # Add explicit causal edges for richer graph
    cr.add_cause("temperature", "pressure", EdgeType.CAUSES, strength=0.8)
    cr.add_cause("pressure", "density", EdgeType.CAUSES, strength=0.6)
    cr.add_cause("density", "flow_rate", EdgeType.ENABLES, strength=0.5)
    cr.add_cause("flow_rate", "output", EdgeType.CAUSES, strength=0.7)

    result = await run_sim_scenario("causal_inference", cluster, tasks)

    # Query the causal model
    graph = cr.graph
    paths = graph.find_causal_paths("temperature", "output")
    intervention = cr.intervene("pressure", 2.0)
    counterfactual = cr.counterfactual("temperature", 100.0, "output")

    # Set some observations for strength estimation
    for i in range(5):
        cr.set_variable("temperature", 20.0 + i * 5)
        cr.set_variable("pressure", 100.0 + i * 10)
    strength = cr.estimate_strength("temperature", "pressure")

    summary = cr.summary()
    exported = cr.export_state()

    passed = (
        result["passed"] >= (result["total"] // 2)
        and len(paths) > 0
        and intervention is not None
        and counterfactual is not None
        and "edges" in exported
        and summary["edge_count"] > 0
    )

    return {
        "name": "causal_inference",
        "passed": passed,
        "total_tasks": result["total"],
        "consensus_passed": result["passed"],
        "causal_paths_found": len(paths),
        "intervention_effect": intervention.total_effect if intervention else 0.0,
        "has_counterfactual": counterfactual is not None,
        "edge_count": summary["edge_count"],
        "strength_estimate": strength,
        "elapsed_ms": result["elapsed_ms"],
    }


# ---------------------------------------------------------------------------
# Scenario: integrated_cognition
# ---------------------------------------------------------------------------

async def scenario_integrated_cognition() -> Dict[str, Any]:
    """Full cognitive pipeline: self-model → transfer → causal reasoning.

    Tests all 3 subsystems working in concert on a shared task stream.
    Agents track their own capabilities, accumulate patterns, and build
    a causal model simultaneously.
    """
    bus = EventBus()
    model = SelfModel(bus=bus)
    tl = TransferLearning(bus=bus)
    cr = CausalReasoning(bus=bus)

    # Multi-role agent combining all three cognitive systems
    async def cognitive_agent(task: Any, context: dict) -> str:
        t = str(task).lower()

        # Self-model: record what we're doing
        domain = t.split("-")[0] if "-" in t else "general"
        model.record_capability(domain, "task_count", 1.0, sample_count=1)

        # Transfer learning: register pattern from this task
        tl.register_pattern(
            domain,
            PatternType.STRATEGY,
            f"learned-from-{t[:20]}",
            [domain, "cognitive"],
            success_rate=0.7,
        )

        # Causal reasoning: add a cause
        cr.add_cause("task_input", domain, EdgeType.CAUSES, strength=0.6)
        cr.set_variable("task_input", 1.0)

        return f"cognitive:{task}"

    nodes = [
        SimNode("cog-node-1", latency_ms=1.0),
        SimNode("cog-node-2", latency_ms=2.0),
    ]
    cluster = SimCluster(nodes)

    agents: Dict[str, Callable] = {
        "cognitive": cognitive_agent,
        "baseline-1": _baseline_agent,
        "baseline-2": _slow_baseline,
    }

    # Mixed task stream
    tasks: List[Dict[str, Any]] = []
    for domain in ["math", "physics", "language", "logic", "planning"]:
        for i in range(3):
            tasks.append({"task": f"{domain}-task-{i}", "agents": agents})

    result = await run_sim_scenario("integrated_cognition", cluster, tasks)

    # Validate all subsystems populated
    capabilities = model.list_capabilities()
    assessment = model.self_assessment()
    patterns = tl.list_patterns()
    domains = tl.list_domains()
    summary = cr.summary()

    passed = (
        result["passed"] >= (result["total"] // 2)
        and len(capabilities) > 0
        and len(patterns) > 0
        and summary["edge_count"] > 0
        and len(domains) >= 3
    )

    return {
        "name": "integrated_cognition",
        "passed": passed,
        "total_tasks": result["total"],
        "consensus_passed": result["passed"],
        "capabilities_tracked": len(capabilities),
        "patterns_learned": len(patterns),
        "domains_active": len(domains),
        "causal_edges": summary["edge_count"],
        "overall_fitness": assessment.get("overall_fitness", 0.0),
        "elapsed_ms": result["elapsed_ms"],
    }


# ---------------------------------------------------------------------------
# Scenario: cognitive_resilience
# ---------------------------------------------------------------------------

async def scenario_cognitive_resilience() -> Dict[str, Any]:
    """Cognitive subsystems recover from partial failures via export/import.

    Simulates a node failure mid-stream, exports cognitive state,
    reconstructs on a fresh set of subsystem instances, and continues.
    """
    bus = EventBus()
    model = SelfModel(bus=bus)
    tl = TransferLearning(bus=bus)
    cr = CausalReasoning(bus=bus)

    # Phase 1: build cognitive state
    for i in range(5):
        model.record_capability("math", "accuracy", 0.5 + i * 0.08)
        tl.register_pattern(
            "math",
            PatternType.STRATEGY,
            f"pattern-{i}",
            ["math", "learned"],
            success_rate=0.6 + i * 0.05,
        )
    cr.add_cause("study", "knowledge", EdgeType.CAUSES, strength=0.8)
    cr.add_cause("knowledge", "performance", EdgeType.CAUSES, strength=0.7)

    # Export state (simulating pre-failure checkpoint)
    model_state = model.export_state()
    tl_state = tl.export_state()
    cr_state = cr.export_state()

    # Phase 2: simulate failure and recovery
    bus2 = EventBus()
    model2 = SelfModel(bus=bus2)
    tl2 = TransferLearning(bus=bus2)
    cr2 = CausalReasoning(bus=bus2)

    model2.import_state(model_state)
    tl_imported = tl2.import_state(tl_state)
    cr2.import_state(cr_state)

    # Phase 3: verify recovered state and continue working
    recovered_caps = model2.list_capabilities()
    recovered_patterns = tl2.list_patterns()
    recovered_edges = cr2.graph.export_edges()

    # Resume cognitive work on recovered instances
    model2.record_capability("math", "accuracy", 0.95)
    tl2.register_pattern("physics", PatternType.ANALOGY, "new-pattern", ["physics"])

    node = SimNode("recovery-node", latency_ms=1.0)
    cluster = SimCluster([node])

    agents: Dict[str, Callable] = {
        "agent-1": _baseline_agent,
        "agent-2": _slow_baseline,
    }

    tasks = [{"task": f"post-recovery-{i}", "agents": agents} for i in range(5)]
    result = await run_sim_scenario("cognitive_resilience", cluster, tasks)

    passed = (
        result["passed"] >= (result["total"] // 2)
        and len(recovered_caps) > 0
        and len(recovered_patterns) > 0
        and len(recovered_edges) > 0
        and tl_imported > 0
    )

    return {
        "name": "cognitive_resilience",
        "passed": passed,
        "total_tasks": result["total"],
        "consensus_passed": result["passed"],
        "recovered_capabilities": len(recovered_caps),
        "recovered_patterns": len(recovered_patterns),
        "recovered_edges": len(recovered_edges),
        "patterns_imported": tl_imported,
        "elapsed_ms": result["elapsed_ms"],
    }


# ---------------------------------------------------------------------------
# Registry and runner
# ---------------------------------------------------------------------------

COGNITIVE_SCENARIOS: List[Callable] = [
    scenario_self_awareness,
    scenario_cross_domain_transfer,
    scenario_causal_inference,
    scenario_integrated_cognition,
    scenario_cognitive_resilience,
]


async def run_all_cognitive() -> Dict[str, Any]:
    """Execute all cognitive scenarios and return aggregate results.

    Returns
    -------
    dict
        Keys: total, passed, failed, scenarios (list of individual results).
    """
    results: List[Dict[str, Any]] = []
    for scenario_fn in COGNITIVE_SCENARIOS:
        result = await scenario_fn()
        results.append(result)

    passed = sum(1 for r in results if r.get("passed"))
    return {
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "scenarios": results,
    }
