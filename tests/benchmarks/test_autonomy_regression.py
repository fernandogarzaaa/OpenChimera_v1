from __future__ import annotations

import os
import pathlib
import tempfile
import unittest

from core._bus_fallback import EventBus
from core._database_fallback import DatabaseManager
from core.goal_planner import GoalPlanner, GoalStatus

MIGRATIONS = pathlib.Path("core/migrations")


def _make_env():
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db = DatabaseManager(tmp.name, migrations_path=MIGRATIONS)
    db.initialize()
    return db, EventBus(), tmp.name


class TestAutonomyRegression(unittest.TestCase):
    def setUp(self) -> None:
        self.db, self.bus, self._db_path = _make_env()
        self.planner = GoalPlanner(self.db, self.bus)

    def tearDown(self) -> None:
        self.db.close()
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(self._db_path + suffix)
            except OSError:
                pass

    def test_long_horizon_decompose_expands_multi_level_tree(self) -> None:
        root = self.planner.create_goal(
            "collect requirements and implement backend and write tests",
            domain="reasoning",
            max_depth=4,
        )
        result = self.planner.plan_long_horizon(root.id, horizon=2, max_subgoals_per_level=4)
        self.assertGreaterEqual(result["created_count"], 3)
        self.assertGreaterEqual(result["levels_expanded"], 1)

    def test_replan_failed_goal_prefers_learned_strategy(self) -> None:
        for _ in range(2):
            self.planner._strategy_learner.record_decomposition(  # noqa: SLF001
                "reasoning",
                ["triage failure", "retry execution", "validate output"],
                succeeded=True,
            )
        goal = self.planner.create_goal("Recover pipeline", domain="reasoning")
        self.planner.update_goal(goal.id, status=GoalStatus.FAILED)
        result = self.planner.replan_goal(goal.id, failure_reason="transient timeout")
        self.assertEqual(result["status"], "replanned")
        self.assertEqual(len(result["subgoal_ids"]), 3)

    def test_intervention_minimization_metrics_track_avoided_rate(self) -> None:
        g1 = self.planner.create_goal("A")
        g2 = self.planner.create_goal("B")
        g3 = self.planner.create_goal("C")
        self.planner.record_intervention(g1.id, required=False, reason="auto-replan")
        self.planner.record_intervention(g2.id, required=True, reason="manual unblock")
        self.planner.record_intervention(g3.id, required=False, reason="auto-decompose")
        metrics = self.planner.intervention_minimization_metrics()
        self.assertEqual(metrics["total_events"], 3)
        self.assertEqual(metrics["required_interventions"], 1)
        self.assertEqual(metrics["avoided_interventions"], 2)
        self.assertAlmostEqual(metrics["intervention_avoidance_rate"], 2 / 3, places=5)


if __name__ == "__main__":
    unittest.main()
