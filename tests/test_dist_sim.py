"""Tests for dist_sim — SimNode, SimCluster, harness, and pre-built scenarios.

All tests are fully offline: no network calls, no LLM, no disk I/O.
Uses asyncio.run() in the same pattern as test_quantum_engine.py.
"""
from __future__ import annotations

import asyncio
import unittest
from typing import Any

from core.quantum_engine import ConsensusResult, QuantumEngine
from dist_sim import SimCluster, SimNode, run_sim_scenario
from dist_sim.harness import run_concurrent_scenario
from dist_sim.scenarios import (
    scenario_cascading_failure,
    scenario_consensus_recovery,
    scenario_high_load,
    scenario_split_brain,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def run(coro):
    return asyncio.run(coro)


# Stateless agent callables used across tests

async def _fast_agent(task: Any, context: dict) -> str:
    return f"ok:{task}"


async def _agree_agent(task: Any, context: dict) -> str:
    await asyncio.sleep(0.005)
    return f"ok:{task}"


async def _fault_agent(task: Any, context: dict) -> str:
    raise RuntimeError("Simulated fault")


_BASIC_AGENTS = {"agent-fast": _fast_agent, "agent-slow": _agree_agent}


# ---------------------------------------------------------------------------
# SimNode tests
# ---------------------------------------------------------------------------

class TestSimNodeCreation(unittest.TestCase):
    def test_default_attributes(self):
        node = SimNode("node-1")
        self.assertEqual(node.node_id, "node-1")
        self.assertIsInstance(node.engine, QuantumEngine)
        self.assertEqual(node.latency_ms, 0.0)
        self.assertTrue(node.online)

    def test_custom_engine_and_latency(self):
        engine = QuantumEngine(quorum=1)
        node = SimNode("node-2", engine=engine, latency_ms=10.0)
        self.assertIs(node.engine, engine)
        self.assertEqual(node.latency_ms, 10.0)

    def test_empty_cluster_raises(self):
        with self.assertRaises(ValueError):
            SimCluster([])


class TestSimNodeQuery(unittest.TestCase):
    def test_basic_query_returns_consensus_result(self):
        node = SimNode("n", QuantumEngine(quorum=1, hard_timeout_ms=2000))
        result = run(node.query("task-a", _BASIC_AGENTS))
        self.assertIsInstance(result, ConsensusResult)
        self.assertEqual(result.answer, "ok:task-a")
        self.assertGreater(result.confidence, 0.0)

    def test_offline_node_raises(self):
        node = SimNode("n-offline", QuantumEngine(quorum=1))
        node.set_online(False)
        with self.assertRaises(RuntimeError) as ctx:
            run(node.query("task", _BASIC_AGENTS))
        self.assertIn("offline", str(ctx.exception))

    def test_set_online_toggle(self):
        node = SimNode("n-toggle", QuantumEngine(quorum=1))
        node.set_online(False)
        self.assertFalse(node.online)
        node.set_online(True)
        self.assertTrue(node.online)
        result = run(node.query("tgl", _BASIC_AGENTS))
        self.assertIsInstance(result, ConsensusResult)

    def test_node_stats_after_queries(self):
        node = SimNode("n-stats", QuantumEngine(quorum=1, hard_timeout_ms=2000))
        run(node.query("q1", _BASIC_AGENTS))
        run(node.query("q2", _BASIC_AGENTS))
        s = node.stats()
        self.assertEqual(s["node_id"], "n-stats")
        self.assertEqual(s["query_count"], 2)
        self.assertGreater(s["avg_latency_ms"], 0.0)
        self.assertGreater(s["avg_confidence"], 0.0)
        self.assertTrue(s["online"])

    def test_node_stats_zero_queries(self):
        node = SimNode("n-zero")
        s = node.stats()
        self.assertEqual(s["query_count"], 0)
        self.assertEqual(s["avg_latency_ms"], 0.0)
        self.assertEqual(s["avg_confidence"], 0.0)


# ---------------------------------------------------------------------------
# SimCluster tests
# ---------------------------------------------------------------------------

class TestSimClusterRouting(unittest.TestCase):
    def _make_cluster(self, n: int = 3) -> SimCluster:
        nodes = [
            SimNode(f"c-node-{i}", QuantumEngine(quorum=1, hard_timeout_ms=2000))
            for i in range(n)
        ]
        return SimCluster(nodes)

    def test_basic_cluster_query(self):
        cluster = self._make_cluster(2)
        result = run(cluster.query("hello", _BASIC_AGENTS))
        self.assertIsInstance(result, ConsensusResult)
        self.assertEqual(result.answer, "ok:hello")

    def test_round_robin_distributes_queries(self):
        cluster = self._make_cluster(3)
        for i in range(6):
            run(cluster.query(f"rr-{i}", _BASIC_AGENTS))
        counts = [n.stats()["query_count"] for n in cluster.nodes]
        # Each of 3 nodes should have handled exactly 2 queries
        self.assertEqual(counts, [2, 2, 2])

    def test_cluster_skips_offline_node(self):
        cluster = self._make_cluster(3)
        cluster.nodes[0].set_online(False)
        # 3 queries should still succeed through the 2 online nodes
        for i in range(3):
            result = run(cluster.query(f"skip-{i}", _BASIC_AGENTS))
            self.assertIsInstance(result, ConsensusResult)
        self.assertEqual(cluster.nodes[0].stats()["query_count"], 0)

    def test_all_offline_raises(self):
        cluster = self._make_cluster(2)
        for node in cluster.nodes:
            node.set_online(False)
        with self.assertRaises(RuntimeError) as ctx:
            run(cluster.query("fail", _BASIC_AGENTS))
        self.assertIn("offline", str(ctx.exception).lower())

    def test_cluster_online_count(self):
        cluster = self._make_cluster(3)
        self.assertEqual(cluster.online_count(), 3)
        cluster.nodes[0].set_online(False)
        self.assertEqual(cluster.online_count(), 2)

    def test_cluster_stats_after_queries(self):
        cluster = self._make_cluster(2)
        run(cluster.query("s1", _BASIC_AGENTS))
        run(cluster.query("s2", _BASIC_AGENTS))
        s = cluster.stats()
        self.assertEqual(s["total_queries"], 2)
        self.assertEqual(s["failed_queries"], 0)
        self.assertGreater(s["avg_confidence"], 0.0)
        self.assertEqual(len(s["node_stats"]), 2)

    def test_cluster_stats_empty(self):
        cluster = self._make_cluster(2)
        s = cluster.stats()
        self.assertEqual(s["total_queries"], 0)
        self.assertEqual(s["avg_latency_ms"], 0.0)

    def test_broadcast_all_online_nodes(self):
        cluster = self._make_cluster(3)
        results = run(cluster.broadcast("bcast", _BASIC_AGENTS))
        self.assertEqual(len(results), 3)
        for r in results:
            self.assertIsInstance(r, ConsensusResult)


# ---------------------------------------------------------------------------
# Harness tests
# ---------------------------------------------------------------------------

class TestHarness(unittest.TestCase):
    def _make_cluster(self) -> SimCluster:
        return SimCluster([
            SimNode("h-node", QuantumEngine(quorum=1, hard_timeout_ms=2000))
        ])

    def test_run_sim_scenario_all_pass(self):
        cluster = self._make_cluster()
        tasks = [{"task": f"t{i}", "agents": _BASIC_AGENTS} for i in range(4)]
        summary = run(run_sim_scenario("test_scenario", cluster, tasks))
        self.assertEqual(summary["scenario"], "test_scenario")
        self.assertEqual(summary["total"], 4)
        self.assertEqual(summary["passed"], 4)
        self.assertEqual(summary["failed"], 0)
        self.assertGreater(summary["avg_confidence"], 0.0)

    def test_run_sim_scenario_failed_task_counted(self):
        cluster = SimCluster([
            SimNode("h-fault", QuantumEngine(quorum=1, hard_timeout_ms=2000))
        ])
        # Take node offline so all queries fail
        cluster.nodes[0].set_online(False)
        tasks = [{"task": "t", "agents": _BASIC_AGENTS}]
        summary = run(run_sim_scenario("fail_test", cluster, tasks))
        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["passed"], 0)

    def test_run_concurrent_scenario(self):
        cluster = SimCluster([
            SimNode(f"c-{i}", QuantumEngine(quorum=1, hard_timeout_ms=3000))
            for i in range(2)
        ])
        tasks = [{"task": f"ct{i}", "agents": _BASIC_AGENTS} for i in range(10)]
        summary = run(run_concurrent_scenario("concurrent_test", cluster, tasks))
        self.assertEqual(summary["total"], 10)
        self.assertEqual(summary["passed"], 10)

    def test_harness_basic_quorum_matches_verify_script(self):
        """Replicate the basic_quorum scenario from quantum_sim_verify.py via dist_sim."""
        async def _consensus(task, ctx):
            await asyncio.sleep(0.01)
            return f"answer:{task}"

        async def _fast(task, ctx):
            return f"answer:{task}"

        async def _slow(task, ctx):
            await asyncio.sleep(0.15)
            return f"answer:{task}"

        engine = QuantumEngine(quorum=2, early_exit_conf=0.9, hard_timeout_ms=2000)
        node = SimNode("quorum-node", engine)
        cluster = SimCluster([node])
        agents = {"agent-a": _consensus, "agent-b": _fast, "agent-c": _consensus}
        tasks = [{"task": "query_alpha", "agents": agents}]
        summary = run(run_sim_scenario("basic_quorum", cluster, tasks))
        self.assertEqual(summary["passed"], 1)
        result_entry = summary["results"][0]
        self.assertEqual(result_entry["answer"], "answer:query_alpha")
        self.assertGreater(result_entry["confidence"], 0.6)


# ---------------------------------------------------------------------------
# Pre-built scenario tests
# ---------------------------------------------------------------------------

class TestPrebuiltScenarios(unittest.TestCase):
    def test_split_brain_scenario(self):
        result = run(scenario_split_brain())
        self.assertEqual(result["name"], "split_brain")
        self.assertTrue(result["passed"], msg=f"split_brain failed: {result}")

    def test_high_load_scenario(self):
        result = run(scenario_high_load())
        self.assertEqual(result["name"], "high_load")
        self.assertTrue(result["passed"], msg=f"high_load failed: {result}")
        self.assertEqual(result["total"], 100)
        self.assertEqual(result["completed"], 100)

    def test_cascading_failure_scenario(self):
        result = run(scenario_cascading_failure())
        self.assertEqual(result["name"], "cascading_failure")
        self.assertTrue(result["passed"], msg=f"cascading_failure failed: {result}")
        self.assertEqual(result["phase4_errors"], 1)

    def test_consensus_recovery_scenario(self):
        result = run(scenario_consensus_recovery())
        self.assertEqual(result["name"], "consensus_recovery")
        self.assertTrue(result["passed"], msg=f"consensus_recovery failed: {result}")
        self.assertEqual(result["pre_failure_ok"], 1)
        self.assertEqual(result["during_failure_ok"], 1)
        self.assertEqual(result["post_recovery_ok"], 3)

    def test_all_scenarios_via_run_all(self):
        """run_all() executes every scenario; all must pass."""
        from dist_sim.scenarios import run_all
        results = run(run_all())
        self.assertEqual(len(results), 4)
        for r in results:
            self.assertTrue(r["passed"], msg=f"Scenario '{r['name']}' failed: {r}")


if __name__ == "__main__":
    unittest.main()
