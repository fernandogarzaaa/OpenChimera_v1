from __future__ import annotations

import asyncio
import unittest

from scripts import quantum_sim_verify


class QuantumSimVerifyTests(unittest.TestCase):
    def test_scenarios_include_late_arrival_consensus(self) -> None:
        names = [scenario.__name__ for scenario in quantum_sim_verify.SCENARIOS]
        self.assertIn("scenario_late_arrival_consensus", names)

    def test_late_arrival_consensus_succeeds(self) -> None:
        result = asyncio.run(quantum_sim_verify.scenario_late_arrival_consensus())
        self.assertTrue(result["passed"])
        self.assertEqual(result["name"], "late_arrival_consensus")
        self.assertGreaterEqual(result["participating"], 3)

    def test_run_all_scenarios_includes_late_arrival_result(self) -> None:
        results = asyncio.run(quantum_sim_verify.run_all_scenarios(verbose=False))
        by_name = {item["name"]: item for item in results}
        self.assertIn("late_arrival_consensus", by_name)
        self.assertTrue(by_name["late_arrival_consensus"]["passed"])

