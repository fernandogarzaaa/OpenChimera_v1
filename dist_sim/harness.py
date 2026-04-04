"""run_sim_scenario — general simulation harness for stress-testing SimClusters."""
from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Dict, List

from core.quantum_engine import ConsensusFailure, ConsensusResult

from .cluster import SimCluster


async def run_sim_scenario(
    scenario_name: str,
    cluster: SimCluster,
    tasks: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Run a list of tasks sequentially against a SimCluster and collect metrics.

    Parameters
    ----------
    scenario_name : str
        Human-readable label for this scenario run.
    cluster : SimCluster
        Pre-configured cluster to run tasks on.
    tasks : list of dict
        Each dict must contain:
          - ``"task"``: Any — the task value passed to node.query()
          - ``"agents"``: Dict[str, Callable] — agent pool for this task

    Returns
    -------
    dict
        Summary with keys: scenario, total, passed, failed,
        avg_latency_ms, avg_confidence, elapsed_ms, results.
    """
    results: List[Dict[str, Any]] = []
    start = time.perf_counter()

    for i, task_spec in enumerate(tasks):
        task = task_spec["task"]
        agents = task_spec["agents"]
        try:
            result = await cluster.query(task, agents)
            results.append({
                "index": i,
                "task": str(task),
                "ok": True,
                "answer": str(result.answer),
                "confidence": round(result.confidence, 4),
                "latency_ms": round(result.latency_ms, 2),
                "early_exit": result.early_exit,
                "partial": result.partial,
            })
        except (RuntimeError, ConsensusFailure) as exc:
            results.append({
                "index": i,
                "task": str(task),
                "ok": False,
                "error": str(exc),
                "confidence": 0.0,
                "latency_ms": 0.0,
            })

    elapsed_ms = (time.perf_counter() - start) * 1000.0
    passed = sum(1 for r in results if r["ok"])
    failed = len(results) - passed
    ok_results = [r for r in results if r["ok"]]
    avg_lat = (
        sum(r["latency_ms"] for r in ok_results) / len(ok_results)
        if ok_results else 0.0
    )
    avg_conf = (
        sum(r["confidence"] for r in ok_results) / len(ok_results)
        if ok_results else 0.0
    )
    return {
        "scenario": scenario_name,
        "total": len(tasks),
        "passed": passed,
        "failed": failed,
        "avg_latency_ms": round(avg_lat, 2),
        "avg_confidence": round(avg_conf, 4),
        "elapsed_ms": round(elapsed_ms, 2),
        "results": results,
    }


async def run_concurrent_scenario(
    scenario_name: str,
    cluster: SimCluster,
    tasks: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Run all tasks concurrently (high-load mode) against a SimCluster.

    Same return shape as :func:`run_sim_scenario`.
    """
    start = time.perf_counter()

    async def _run_one(i: int, task_spec: Dict[str, Any]) -> Dict[str, Any]:
        task = task_spec["task"]
        agents = task_spec["agents"]
        try:
            result = await cluster.query(task, agents)
            return {
                "index": i,
                "task": str(task),
                "ok": True,
                "answer": str(result.answer),
                "confidence": round(result.confidence, 4),
                "latency_ms": round(result.latency_ms, 2),
                "early_exit": result.early_exit,
                "partial": result.partial,
            }
        except (RuntimeError, ConsensusFailure) as exc:
            return {
                "index": i,
                "task": str(task),
                "ok": False,
                "error": str(exc),
                "confidence": 0.0,
                "latency_ms": 0.0,
            }

    raw = await asyncio.gather(*[_run_one(i, ts) for i, ts in enumerate(tasks)])
    results = list(raw)
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    passed = sum(1 for r in results if r["ok"])
    failed = len(results) - passed
    ok_results = [r for r in results if r["ok"]]
    avg_lat = (
        sum(r["latency_ms"] for r in ok_results) / len(ok_results)
        if ok_results else 0.0
    )
    avg_conf = (
        sum(r["confidence"] for r in ok_results) / len(ok_results)
        if ok_results else 0.0
    )
    return {
        "scenario": scenario_name,
        "total": len(tasks),
        "passed": passed,
        "failed": failed,
        "avg_latency_ms": round(avg_lat, 2),
        "avg_confidence": round(avg_conf, 4),
        "elapsed_ms": round(elapsed_ms, 2),
        "results": results,
    }
