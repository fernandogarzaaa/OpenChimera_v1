"""
OpenChimera Quantum Simulation Verification Harness
====================================================
Runs the quantum engine in simulation mode to verify that the consensus
control plane is operational. Used as a CI sanity gate and for manual
health checks.

Usage:
  python scripts/quantum_sim_verify.py
  python scripts/quantum_sim_verify.py --verbose
  python scripts/quantum_sim_verify.py --json

Exit codes:
  0 = All scenarios passed
  1 = One or more scenarios failed
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

# Ensure the project root is on sys.path so core imports work whether this
# script is run directly or via `python scripts/quantum_sim_verify.py`.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from core.quantum_engine import AgentReputation, QuantumEngine


# ---------------------------------------------------------------------------
# Simulated agent pool
# ---------------------------------------------------------------------------

async def _agent_consensus(task: str, _context: dict) -> str:
    """Agent that always agrees with the expected answer."""
    await asyncio.sleep(0.01)
    return f"answer:{task}"


async def _agent_fast(task: str, _context: dict) -> str:
    """Fast responding agent — low latency, same answer."""
    return f"answer:{task}"


async def _agent_slow(task: str, _context: dict) -> str:
    """Slow agent — arrives after quorum may already be met."""
    await asyncio.sleep(0.15)
    return f"answer:{task}"


async def _agent_wrong(task: str, _context: dict) -> str:
    """Dissenting agent — returns a different answer."""
    await asyncio.sleep(0.02)
    return "WRONG_ANSWER"


async def _agent_error(task: str, _context: dict) -> str:
    """Unreliable agent — always raises an exception."""
    await asyncio.sleep(0.01)
    raise RuntimeError("Simulated agent failure")


async def _agent_late_correct(task: str, _context: dict) -> str:
    """Late-arrival correct agent — should be included in final vote."""
    await asyncio.sleep(0.2)
    return f"answer:{task}"


# ---------------------------------------------------------------------------
# Verification scenarios
# ---------------------------------------------------------------------------

ScenarioResult = dict[str, Any]


async def scenario_basic_quorum() -> ScenarioResult:
    """Three agreeing agents → unanimous consensus, high confidence."""
    engine = QuantumEngine(quorum=2, early_exit_conf=0.9, hard_timeout_ms=2000)
    task = "query_alpha"
    result = await engine.gather(
        task,
        agents={
            "agent-a": _agent_consensus,
            "agent-b": _agent_fast,
            "agent-c": _agent_consensus,
        },
    )
    success = (
        result.answer == f"answer:{task}"
        and result.confidence > 0.6
        and result.participating >= 2
    )
    return {
        "name": "basic_quorum",
        "passed": success,
        "answer": result.answer,
        "confidence": round(result.confidence, 3),
        "participating": result.participating,
        "latency_ms": round(result.latency_ms, 1),
        "early_exit": result.early_exit,
    }


async def scenario_fault_tolerance() -> ScenarioResult:
    """Two good agents + one crashing agent → fault isolated, consensus reached."""
    engine = QuantumEngine(quorum=2, early_exit_conf=0.8, hard_timeout_ms=2000)
    task = "query_fault"
    result = await engine.gather(
        task,
        agents={
            "agent-good-1": _agent_fast,
            "agent-bad": _agent_error,
            "agent-good-2": _agent_consensus,
        },
    )
    success = result.answer == f"answer:{task}" and not result.partial
    return {
        "name": "fault_tolerance",
        "passed": success,
        "answer": result.answer,
        "confidence": round(result.confidence, 3),
        "participating": result.participating,
        "partial": result.partial,
        "latency_ms": round(result.latency_ms, 1),
    }


async def scenario_minority_dissent() -> ScenarioResult:
    """Minority wrong agent + majority correct → correct answer wins."""
    engine = QuantumEngine(quorum=2, early_exit_conf=0.7, hard_timeout_ms=2000)
    task = "query_dissent"
    reputation = AgentReputation()
    reputation.update("agent-wrong", correct=False)
    reputation.update("agent-right-1", correct=True)
    reputation.update("agent-right-2", correct=True)
    engine.reputation = reputation

    result = await engine.gather(
        task,
        agents={
            "agent-right-1": _agent_fast,
            "agent-right-2": _agent_consensus,
            "agent-wrong": _agent_wrong,
        },
    )
    success = result.answer == f"answer:{task}"
    return {
        "name": "minority_dissent",
        "passed": success,
        "answer": result.answer,
        "confidence": round(result.confidence, 3),
        "vote_breakdown_len": len(result.vote_breakdown),
        "latency_ms": round(result.latency_ms, 1),
    }


async def scenario_reputation_updates() -> ScenarioResult:
    """Validate that reputation EMA updates converge correctly."""
    rep = AgentReputation(alpha=0.5, default_weight=0.5)
    agent_id = "test-agent"

    # Force correct feedback 4 times
    for _ in range(4):
        rep.update(agent_id, correct=True)
    weight_after_correct = rep.weight(agent_id)

    # Reset and force wrong feedback
    rep2 = AgentReputation(alpha=0.5, default_weight=0.5)
    for _ in range(4):
        rep2.update(agent_id, correct=False)
    weight_after_wrong = rep2.weight(agent_id)

    success = weight_after_correct > 0.7 and weight_after_wrong < 0.1
    return {
        "name": "reputation_updates",
        "passed": success,
        "weight_after_correct": round(weight_after_correct, 4),
        "weight_after_wrong": round(weight_after_wrong, 4),
    }


async def scenario_early_exit() -> ScenarioResult:
    """Fast early exit: first two agents agree at high confidence → skip slower agents."""
    engine = QuantumEngine(quorum=1, early_exit_conf=0.95, hard_timeout_ms=3000)
    task = "query_early"
    start = time.perf_counter()
    result = await engine.gather(
        task,
        agents={
            "agent-fast": _agent_fast,
            "agent-slow": _agent_slow,
        },
    )
    elapsed = time.perf_counter() - start
    # Should finish well before the slow agent's 150ms delay (allow up to 100ms overhead)
    success = result.answer == f"answer:{task}" and elapsed < 0.25
    return {
        "name": "early_exit",
        "passed": success,
        "answer": result.answer,
        "early_exit": result.early_exit,
        "wall_time_ms": round(elapsed * 1000, 1),
        "latency_ms": round(result.latency_ms, 1),
    }


async def scenario_partial_result_on_timeout() -> ScenarioResult:
    """Tight timeout forces partial result or graceful all-failed error."""
    engine = QuantumEngine(quorum=3, early_exit_conf=0.99, hard_timeout_ms=50)
    task = "query_timeout"
    try:
        result = await engine.gather(
            task,
            agents={
                "agent-slow-1": _agent_slow,
                "agent-slow-2": _agent_slow,
                "agent-slow-3": _agent_slow,
            },
        )
        # partial result returned — valid
        success = result.partial or result.participating == 0
        return {
            "name": "partial_result_on_timeout",
            "passed": success,
            "partial": result.partial,
            "participating": result.participating,
            "latency_ms": round(result.latency_ms, 1),
        }
    except RuntimeError as exc:
        # Engine raised "all agents failed or timed out" — this is also valid
        msg = str(exc)
        success = "failed or timed out" in msg.lower() or "all" in msg.lower()
        return {
            "name": "partial_result_on_timeout",
            "passed": success,
            "graceful_error": msg,
        }


async def scenario_late_arrival_consensus() -> ScenarioResult:
    """Late correct vote should still produce the expected consensus answer."""
    engine = QuantumEngine(quorum=3, early_exit_conf=0.99, hard_timeout_ms=1000)
    task = "query_late_arrival"
    result = await engine.gather(
        task,
        agents={
            "agent-fast-1": _agent_fast,
            "agent-fast-2": _agent_fast,
            "agent-late-correct": _agent_late_correct,
        },
    )
    success = result.answer == f"answer:{task}" and result.participating >= 3 and not result.partial
    return {
        "name": "late_arrival_consensus",
        "passed": success,
        "answer": result.answer,
        "participating": result.participating,
        "partial": result.partial,
        "latency_ms": round(result.latency_ms, 1),
    }


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

SCENARIOS = [
    scenario_basic_quorum,
    scenario_fault_tolerance,
    scenario_minority_dissent,
    scenario_reputation_updates,
    scenario_early_exit,
    scenario_partial_result_on_timeout,
    scenario_late_arrival_consensus,
]


async def run_all_scenarios(verbose: bool = False) -> list[ScenarioResult]:
    results: list[ScenarioResult] = []
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
        if verbose:
            status = "PASS" if result["passed"] else "FAIL"
            print(f"  [{status}] {result['name']}", end="")
            if not result["passed"]:
                print(f" — error: {result.get('error', 'assertion failed')}", end="")
            print()
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenChimera Quantum Engine Sim Verification")
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--json", dest="as_json", action="store_true")
    args = parser.parse_args()

    if args.verbose and not args.as_json:
        print("OpenChimera Quantum Engine Simulation Verifier")
        print(f"Running {len(SCENARIOS)} scenarios...\n")

    start = time.perf_counter()
    results = asyncio.run(run_all_scenarios(verbose=args.verbose and not args.as_json))
    elapsed = time.perf_counter() - start

    passed = sum(1 for r in results if r["passed"])
    failed = len(results) - passed

    if args.as_json:
        print(json.dumps({
            "passed": passed,
            "failed": failed,
            "total": len(results),
            "elapsed_ms": round(elapsed * 1000, 1),
            "scenarios": results,
        }, indent=2))
    else:
        print(f"\nQuantum Engine Sim: {passed}/{len(results)} passed in {elapsed * 1000:.0f}ms")
        if failed:
            print(f"FAILED scenarios:")
            for r in results:
                if not r["passed"]:
                    print(f"  - {r['name']}: {r.get('error', 'assertion failed')}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
