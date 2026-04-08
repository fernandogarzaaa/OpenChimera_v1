from __future__ import annotations

import os
import tempfile
import unittest

from core._bus_fallback import EventBus
from core._database_fallback import DatabaseManager
from core.metacognition import MetacognitionEngine
from core.safety_layer import SafetyLayer


class _ReliabilityBase(unittest.TestCase):
    def setUp(self) -> None:
        self.bus = EventBus()
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.db = DatabaseManager(self._tmp.name)
        self.db.initialize()

    def tearDown(self) -> None:
        self.db.close()
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(self._tmp.name + suffix)
            except OSError:
                pass


class TestMetacognitionReliability(_ReliabilityBase):
    def test_compute_ece_ignores_fault_injected_confidence_values(self) -> None:
        engine = MetacognitionEngine(self.db, self.bus, n_bins=5)
        episodes = [
            {"confidence_final": 0.9, "outcome": "success"},
            {"confidence_final": 0.1, "outcome": "failure"},
            {"confidence_final": "nan", "outcome": "success"},
            {"confidence_final": "not-a-number", "outcome": "failure"},
            {"confidence_final": None, "outcome": "success"},
        ]

        result = engine._compute_ece_for_episodes(episodes)  # noqa: SLF001
        self.assertEqual(result["total_episodes"], 2)
        self.assertGreaterEqual(result["ece"], 0.0)

    def test_adapt_thresholds_tolerates_invalid_ece_payload(self) -> None:
        engine = MetacognitionEngine(self.db, self.bus)
        baseline = engine._thresholds["confidence_threshold"]  # noqa: SLF001

        out = engine.adapt_thresholds({"ece": "fault-injected"})
        self.assertAlmostEqual(out["confidence_threshold"], baseline, places=4)


class TestSafetyLayerReliability(unittest.TestCase):
    def test_validate_content_rejects_non_string_payload(self) -> None:
        safety = SafetyLayer()
        is_safe, reason = safety.validate_content(None)  # type: ignore[arg-type]
        self.assertFalse(is_safe)
        self.assertIsNotNone(reason)

    def test_validate_action_rejects_non_mapping_parameters(self) -> None:
        safety = SafetyLayer()
        is_safe, reason = safety.validate_action("read_file", None)  # type: ignore[arg-type]
        self.assertFalse(is_safe)
        self.assertIn("parameters", (reason or "").lower())

    def test_contradictory_admin_context_is_blocked(self) -> None:
        safety = SafetyLayer()
        is_safe, reason = safety.validate_action(
            "file_delete",
            {"path": "safe/relative.txt"},
            context={"user_role": "admin", "auth_verified": False},
        )
        self.assertFalse(is_safe)
        self.assertIn("contradict", (reason or "").lower())


if __name__ == "__main__":
    unittest.main()
