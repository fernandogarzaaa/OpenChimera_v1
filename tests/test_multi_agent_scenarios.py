"""Tests for dist_sim.multi_agent_scenarios — extended simulation scenarios.

Covers all 6 extended scenarios plus the run_all_extended runner.
Each scenario is fully offline with deterministic agent callables.
"""
from __future__ import annotations

import asyncio
import unittest

from dist_sim.multi_agent_scenarios import (
    EXTENDED_SCENARIOS,
    run_all_extended,
    scenario_adversarial_agents,
    scenario_confidence_calibration,
    scenario_domain_expertise,
    scenario_full_intelligence_loop,
    scenario_parallel_batch,
    scenario_reputation_learning,
)


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Individual scenario tests
# ---------------------------------------------------------------------------

class TestDomainExpertise(unittest.TestCase):
    def test_domain_expertise_scenario(self):
        result = run(scenario_domain_expertise())
        self.assertTrue(result["passed"], f"domain_expertise failed: {result}")
        self.assertEqual(result["medical_queries"], 5)
        self.assertEqual(result["coding_queries"], 5)
        self.assertGreater(result["medical_avg_confidence"], 0)
        self.assertGreater(result["coding_avg_confidence"], 0)


class TestAdversarialAgents(unittest.TestCase):
    def test_honest_majority_wins(self):
        result = run(scenario_adversarial_agents())
        self.assertTrue(result["passed"], f"adversarial_agents failed: {result}")
        self.assertEqual(result["honest_wins"], 10)
        self.assertGreater(result["avg_confidence"], 0.5)


class TestConfidenceCalibration(unittest.TestCase):
    def test_confidence_gap(self):
        result = run(scenario_confidence_calibration())
        self.assertTrue(result["passed"], f"confidence_calibration failed: {result}")
        self.assertGreaterEqual(result["confidence_gap"], 0)
        self.assertGreater(result["high_agreement_confidence"], 0)


class TestParallelBatch(unittest.TestCase):
    def test_throughput(self):
        result = run(scenario_parallel_batch())
        self.assertTrue(result["passed"], f"parallel_batch failed: {result}")
        self.assertGreaterEqual(result["completed"], 48)
        self.assertEqual(result["total"], 50)


class TestReputationLearning(unittest.TestCase):
    def test_reputation_divergence(self):
        result = run(scenario_reputation_learning())
        self.assertTrue(result["passed"], f"reputation_learning failed: {result}")
        self.assertGreater(result["reputation_divergence"], 0.1)
        self.assertGreater(result["reliable_reputation"],
                           result["unreliable_reputation"])


class TestFullIntelligenceLoop(unittest.TestCase):
    def test_end_to_end(self):
        result = run(scenario_full_intelligence_loop())
        self.assertTrue(result["passed"], f"full_intelligence_loop failed: {result}")
        self.assertGreaterEqual(result["completed"], 4)
        self.assertGreater(result["avg_confidence"], 0.3)
        self.assertGreater(result["avg_participating_agents"], 0)


# ---------------------------------------------------------------------------
# Registry & runner
# ---------------------------------------------------------------------------

class TestExtendedScenarioRegistry(unittest.TestCase):
    def test_registry_has_all_scenarios(self):
        self.assertEqual(len(EXTENDED_SCENARIOS), 6)
        names = [fn.__name__ for fn in EXTENDED_SCENARIOS]
        self.assertIn("scenario_domain_expertise", names)
        self.assertIn("scenario_adversarial_agents", names)
        self.assertIn("scenario_confidence_calibration", names)
        self.assertIn("scenario_parallel_batch", names)
        self.assertIn("scenario_reputation_learning", names)
        self.assertIn("scenario_full_intelligence_loop", names)

    def test_run_all_extended(self):
        results = run(run_all_extended())
        self.assertEqual(len(results), 6)
        passed = sum(1 for r in results if r.get("passed"))
        # All 6 should pass
        self.assertEqual(passed, 6, f"Some scenarios failed: {results}")
        # Each result has a name
        for r in results:
            self.assertIn("name", r)


if __name__ == "__main__":
    unittest.main()
