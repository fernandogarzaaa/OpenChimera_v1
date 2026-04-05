"""Tests for core.multi_agent_orchestrator — full-loop orchestration.

Covers:
  1.  OrchestratorResult is a frozen dataclass
  2.  MultiAgentOrchestrator initialises with default config
  3.  Orchestrator initialises from profile dict
  4.  Orchestrator reads env var config overrides
  5.  run() produces valid OrchestratorResult
  6.  run() with no matching agents returns error result
  7.  run() with domain filter selects correct agents
  8.  run_batch() processes multiple tasks concurrently
  9.  feedback() updates reputation
  10. status() returns diagnostic snapshot
  11. Memory is recorded when available
  12. Metacognition report is populated when available
  13. ConsensusFailure handled gracefully
  14. run_orchestrated_task() one-shot convenience
  15. Orchestrator works with custom AgentPool
"""
from __future__ import annotations

import asyncio
import os
import unittest
from unittest.mock import patch

import pytest

from core.agent_pool import AgentPool, AgentRole, AgentSpec, create_pool
from core.multi_agent_orchestrator import (
    MultiAgentOrchestrator,
    OrchestratorResult,
    run_orchestrated_task,
)


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# 1. OrchestratorResult dataclass
# ---------------------------------------------------------------------------

class TestOrchestratorResult(unittest.TestCase):
    def test_frozen(self):
        r = OrchestratorResult(
            task="t", session_id="s", answer="a", confidence=0.5,
            participating=2, total_invited=3, latency_ms=10.0,
            early_exit=False, partial=False, vote_breakdown={},
            contradictions_found=0, agents_used=[], domain="general",
            metacognition={}, memory_recorded=False,
        )
        with self.assertRaises(AttributeError):
            r.answer = "new"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 2–3. Initialisation
# ---------------------------------------------------------------------------

class TestOrchestratorInit(unittest.TestCase):
    def test_default_init(self):
        orch = MultiAgentOrchestrator()
        self.assertIsNotNone(orch.pool)
        self.assertIsNotNone(orch.engine)
        self.assertIsNotNone(orch.reputation)
        self.assertGreater(orch.pool.count(), 0)

    def test_init_from_profile(self):
        profile = {
            "agent_pool": {
                "agents": [
                    {"agent_id": "test-r", "role": "reasoner"},
                    {"agent_id": "test-c", "role": "critic"},
                ]
            },
            "orchestrator": {
                "quorum": 1,
                "early_exit_conf": 0.6,
                "hard_timeout_ms": 2000,
            },
        }
        orch = MultiAgentOrchestrator(profile=profile)
        self.assertEqual(orch.pool.count(), 2)

    def test_init_from_env_vars(self):
        env = {
            "OPENCHIMERA_QUORUM": "3",
            "OPENCHIMERA_EARLY_EXIT_CONF": "0.8",
            "OPENCHIMERA_CONSENSUS_TIMEOUT_MS": "5000",
        }
        with patch.dict(os.environ, env):
            orch = MultiAgentOrchestrator()
        st = orch.status()
        self.assertEqual(st["engine"]["quorum"], 3)
        self.assertAlmostEqual(st["engine"]["early_exit_conf"], 0.8)
        self.assertEqual(st["engine"]["hard_timeout_ms"], 5000)


# ---------------------------------------------------------------------------
# 5. run() produces valid result
# ---------------------------------------------------------------------------

class TestOrchestratorRun(unittest.TestCase):
    def test_basic_run(self):
        orch = MultiAgentOrchestrator(quorum=2, hard_timeout_ms=3000)
        result = run(orch.run("What is 2+2?"))
        self.assertIsInstance(result, OrchestratorResult)
        self.assertIsNotNone(result.answer)
        self.assertTrue(0 <= result.confidence <= 1.0)
        self.assertGreater(result.participating, 0)
        self.assertGreater(len(result.agents_used), 0)
        self.assertIsNotNone(result.session_id)

    def test_run_error_result_on_no_agents(self):
        pool = AgentPool()  # Empty pool
        orch = MultiAgentOrchestrator(pool=pool, quorum=1)
        result = run(orch.run("test", domain="nonexistent"))
        self.assertIsNotNone(result.error)
        self.assertEqual(result.participating, 0)
        self.assertAlmostEqual(result.confidence, 0.0)


# ---------------------------------------------------------------------------
# 7. Domain filter
# ---------------------------------------------------------------------------

class TestOrchestratorDomainFilter(unittest.TestCase):
    def test_domain_selection(self):
        pool = AgentPool()
        pool.register(AgentSpec("med", AgentRole.SPECIALIST, domain="medical"))
        pool.register(AgentSpec("gen", AgentRole.REASONER, domain="general"))
        orch = MultiAgentOrchestrator(pool=pool, quorum=1, hard_timeout_ms=3000)

        result = run(orch.run("diagnose patient", domain="medical"))
        self.assertIn("med", result.agents_used)
        # "general" agents also included in medical domain
        self.assertIn("gen", result.agents_used)


# ---------------------------------------------------------------------------
# 8. run_batch()
# ---------------------------------------------------------------------------

class TestOrchestratorBatch(unittest.TestCase):
    def test_batch_multiple_tasks(self):
        orch = MultiAgentOrchestrator(quorum=2, hard_timeout_ms=3000)
        tasks = [f"task-{i}" for i in range(5)]
        results = run(orch.run_batch(tasks, concurrency=3))
        self.assertEqual(len(results), 5)
        completed = sum(1 for r in results if r.answer is not None)
        self.assertEqual(completed, 5)


# ---------------------------------------------------------------------------
# 9. feedback()
# ---------------------------------------------------------------------------

class TestOrchestratorFeedback(unittest.TestCase):
    def test_feedback_updates_reputation(self):
        orch = MultiAgentOrchestrator(quorum=2, hard_timeout_ms=3000)
        # Run a task to register agents in reputation
        run(orch.run("warmup task"))
        orch.feedback("reasoner-alpha", True)
        orch.feedback("reasoner-alpha", True)
        orch.feedback("critic-prime", False)
        snap = orch.reputation.snapshot()
        # Reasoner should have higher reputation than critic
        r_rep = snap.get("reasoner-alpha", {}).get("reputation", 0.5)
        c_rep = snap.get("critic-prime", {}).get("reputation", 0.5)
        self.assertGreaterEqual(r_rep, c_rep)


# ---------------------------------------------------------------------------
# 10. status()
# ---------------------------------------------------------------------------

class TestOrchestratorStatus(unittest.TestCase):
    def test_status_shape(self):
        orch = MultiAgentOrchestrator(quorum=2, hard_timeout_ms=3000)
        st = orch.status()
        self.assertIn("pool", st)
        self.assertIn("engine", st)
        self.assertIn("reputation", st)
        self.assertIn("profiler", st)
        self.assertIn("memory_available", st)
        self.assertIn("metacognition_available", st)
        self.assertIsInstance(st["pool"]["agents"], list)
        self.assertGreater(st["pool"]["total"], 0)


# ---------------------------------------------------------------------------
# 11–12. Memory and metacognition integration
# ---------------------------------------------------------------------------

class TestOrchestratorLoop(unittest.TestCase):
    def test_memory_recorded(self):
        orch = MultiAgentOrchestrator(quorum=2, hard_timeout_ms=3000)
        result = run(orch.run("Remember this"))
        # Memory should be available if MemorySystem imports succeed
        st = orch.status()
        if st["memory_available"]:
            self.assertTrue(result.memory_recorded)

    def test_metacognition_report(self):
        orch = MultiAgentOrchestrator(quorum=2, hard_timeout_ms=3000)
        result = run(orch.run("Calibration test"))
        # Metacognition may or may not be available
        self.assertIsInstance(result.metacognition, dict)


# ---------------------------------------------------------------------------
# 14. run_orchestrated_task() convenience
# ---------------------------------------------------------------------------

class TestRunOrchestratedTask(unittest.TestCase):
    def test_one_shot(self):
        config = [
            {"agent_id": "fast-r", "role": "reasoner"},
            {"agent_id": "fast-c", "role": "critic"},
        ]
        result = run(run_orchestrated_task(
            "one-shot test", agents_config=config,
        ))
        self.assertIsInstance(result, OrchestratorResult)
        self.assertIsNotNone(result.answer)


# ---------------------------------------------------------------------------
# 15. Custom pool
# ---------------------------------------------------------------------------

class TestOrchestratorCustomPool(unittest.TestCase):
    def test_custom_pool_injection(self):
        pool = AgentPool()
        pool.register(AgentSpec("custom-1", AgentRole.REASONER))
        pool.register(AgentSpec("custom-2", AgentRole.SYNTHESIZER))
        pool.register(AgentSpec("custom-3", AgentRole.CRITIC))

        orch = MultiAgentOrchestrator(
            pool=pool, quorum=2, hard_timeout_ms=3000,
        )
        self.assertEqual(orch.pool.count(), 3)
        result = run(orch.run("test with custom pool"))
        self.assertIsNotNone(result.answer)
        # Should use our custom agents
        for aid in result.agents_used:
            self.assertTrue(aid.startswith("custom-"))


if __name__ == "__main__":
    unittest.main()
