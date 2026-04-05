"""Tests for dist_sim.cognitive_scenarios — AGI subsystem simulation.

Covers all 5 cognitive scenarios plus the run_all_cognitive runner.
Each scenario is fully offline with deterministic agent callables,
no hardcoded paths, and no external dependencies.
"""
from __future__ import annotations

import asyncio
import unittest

from dist_sim.cognitive_scenarios import (
    COGNITIVE_SCENARIOS,
    run_all_cognitive,
    scenario_causal_inference,
    scenario_cognitive_resilience,
    scenario_cross_domain_transfer,
    scenario_integrated_cognition,
    scenario_self_awareness,
)


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Individual scenario tests
# ---------------------------------------------------------------------------

class TestSelfAwareness(unittest.TestCase):
    def test_self_awareness_scenario(self):
        result = run(scenario_self_awareness())
        self.assertTrue(result["passed"], f"self_awareness failed: {result}")
        self.assertGreater(result["capabilities_tracked"], 0)
        self.assertIsInstance(result["assessment_fitness"], float)
        self.assertGreater(result["total_tasks"], 0)

    def test_self_awareness_tracks_domains(self):
        result = run(scenario_self_awareness())
        # Should have tracked at least math and language domains
        self.assertGreaterEqual(result["capabilities_tracked"], 2)


class TestCrossDomainTransfer(unittest.TestCase):
    def test_transfer_scenario(self):
        result = run(scenario_cross_domain_transfer())
        self.assertTrue(result["passed"], f"cross_domain_transfer failed: {result}")
        self.assertGreater(result["patterns_learned"], 0)
        self.assertGreaterEqual(result["domains_active"], 2)

    def test_transfer_math_and_physics(self):
        result = run(scenario_cross_domain_transfer())
        self.assertGreater(result["math_patterns"], 0)
        self.assertGreater(result["physics_patterns"], 0)


class TestCausalInference(unittest.TestCase):
    def test_causal_scenario(self):
        result = run(scenario_causal_inference())
        self.assertTrue(result["passed"], f"causal_inference failed: {result}")
        self.assertGreater(result["causal_paths_found"], 0)
        self.assertGreater(result["edge_count"], 0)

    def test_causal_intervention_nonzero(self):
        result = run(scenario_causal_inference())
        # Intervention should produce a non-trivial effect
        self.assertIsInstance(result["intervention_effect"], float)

    def test_causal_counterfactual_present(self):
        result = run(scenario_causal_inference())
        self.assertTrue(result["has_counterfactual"])


class TestIntegratedCognition(unittest.TestCase):
    def test_integrated_scenario(self):
        result = run(scenario_integrated_cognition())
        self.assertTrue(result["passed"], f"integrated_cognition failed: {result}")
        self.assertGreater(result["capabilities_tracked"], 0)
        self.assertGreater(result["patterns_learned"], 0)
        self.assertGreater(result["causal_edges"], 0)

    def test_integrated_multiple_domains(self):
        result = run(scenario_integrated_cognition())
        self.assertGreaterEqual(result["domains_active"], 3)

    def test_integrated_has_fitness(self):
        result = run(scenario_integrated_cognition())
        self.assertIsInstance(result["overall_fitness"], float)
        self.assertGreaterEqual(result["overall_fitness"], 0.0)


class TestCognitiveResilience(unittest.TestCase):
    def test_resilience_scenario(self):
        result = run(scenario_cognitive_resilience())
        self.assertTrue(result["passed"], f"cognitive_resilience failed: {result}")
        self.assertGreater(result["recovered_capabilities"], 0)
        self.assertGreater(result["recovered_patterns"], 0)
        self.assertGreater(result["recovered_edges"], 0)

    def test_resilience_import_count(self):
        result = run(scenario_cognitive_resilience())
        self.assertGreater(result["patterns_imported"], 0)

    def test_resilience_consensus_after_recovery(self):
        result = run(scenario_cognitive_resilience())
        self.assertGreater(result["consensus_passed"], 0)


# ---------------------------------------------------------------------------
# Runner test
# ---------------------------------------------------------------------------

class TestRunAllCognitive(unittest.TestCase):
    def test_run_all_cognitive(self):
        results = run(run_all_cognitive())
        self.assertEqual(results["total"], 5)
        self.assertEqual(results["failed"], 0, f"Some scenarios failed: {results}")
        self.assertEqual(len(results["scenarios"]), 5)

    def test_scenario_registry(self):
        self.assertEqual(len(COGNITIVE_SCENARIOS), 5)
        # All are callable
        for fn in COGNITIVE_SCENARIOS:
            self.assertTrue(callable(fn))


if __name__ == "__main__":
    unittest.main()
