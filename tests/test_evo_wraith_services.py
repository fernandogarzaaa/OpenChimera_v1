"""Tests for core.evo_service and core.wraith_service — autonomous swarm services."""
from __future__ import annotations

import threading
import unittest
from unittest.mock import MagicMock, patch


class TestEvoService(unittest.TestCase):
    @patch("core.evo_service.get_evo_root")
    def _make_svc(self, get_evo_root_mock, entrypoint_exists=False):
        from pathlib import Path
        import tempfile, types

        td = Path(tempfile.mkdtemp())
        get_evo_root_mock.return_value = td
        if entrypoint_exists:
            ep = td / "swarm_bot.py"
            ep.write_text(
                "class SwarmBot:\n"
                "    def start_autonomous_loop(self): pass\n",
                encoding="utf-8",
            )

        from core.evo_service import EvoService
        return EvoService()

    def test_unavailable_when_no_entrypoint(self) -> None:
        svc = self._make_svc(entrypoint_exists=False)
        self.assertFalse(svc.available)

    def test_status_structure_when_unavailable(self) -> None:
        svc = self._make_svc(entrypoint_exists=False)
        status = svc.status()
        self.assertIn("name", status)
        self.assertEqual(status["name"], "evo")
        self.assertFalse(status["available"])
        self.assertFalse(status["running"])
        self.assertIn("start_attempts", status)

    def test_start_returns_false_when_unavailable(self) -> None:
        svc = self._make_svc(entrypoint_exists=False)
        svc.available = False
        self.assertFalse(svc.start())

    def test_is_running_false_initially(self) -> None:
        svc = self._make_svc(entrypoint_exists=False)
        self.assertFalse(svc.is_running())

    def test_is_running_true_when_thread_alive(self) -> None:
        svc = self._make_svc(entrypoint_exists=False)
        barrier = threading.Barrier(2)
        t = threading.Thread(target=barrier.wait, daemon=True)
        t.start()
        svc.thread = t
        self.assertTrue(svc.is_running())
        barrier.wait()
        t.join(timeout=2)

    def test_available_when_entrypoint_exists(self) -> None:
        svc = self._make_svc(entrypoint_exists=True)
        self.assertTrue(svc.available)

    def test_start_increments_attempts_and_returns_true(self) -> None:
        svc = self._make_svc(entrypoint_exists=True)
        if not svc.available:
            self.skipTest("entrypoint not set up correctly")
        svc.start()
        self.assertEqual(svc.start_attempts, 1)

    def test_start_when_already_running_returns_true_without_incrementing(self) -> None:
        svc = self._make_svc(entrypoint_exists=True)
        if not svc.available:
            self.skipTest("entrypoint not set up correctly")
        # Manually mark as running
        barrier = threading.Barrier(2)
        t = threading.Thread(target=barrier.wait, daemon=True)
        t.start()
        svc.thread = t
        result = svc.start()
        self.assertTrue(result)
        self.assertEqual(svc.start_attempts, 0)  # not incremented
        barrier.wait()
        t.join(timeout=2)


class TestWraithService(unittest.TestCase):
    @patch("core.wraith_service.get_wraith_root")
    def _make_svc(self, get_wraith_root_mock, entrypoint_exists=False):
        from pathlib import Path
        import tempfile

        td = Path(tempfile.mkdtemp())
        get_wraith_root_mock.return_value = td
        if entrypoint_exists:
            (td / "orchestrator").mkdir(parents=True, exist_ok=True)
            ep = td / "orchestrator" / "god_node.py"
            ep.write_text(
                "class WraithOrchestrator:\n"
                "    def run(self): pass\n",
                encoding="utf-8",
            )

        from core.wraith_service import WraithService
        return WraithService()

    def test_unavailable_when_no_entrypoint(self) -> None:
        svc = self._make_svc(entrypoint_exists=False)
        self.assertFalse(svc.available)

    def test_status_structure_when_unavailable(self) -> None:
        svc = self._make_svc(entrypoint_exists=False)
        status = svc.status()
        self.assertIn("name", status)
        self.assertEqual(status["name"], "wraith")
        self.assertFalse(status["available"])
        self.assertIn("start_attempts", status)

    def test_start_returns_false_when_unavailable(self) -> None:
        svc = self._make_svc(entrypoint_exists=False)
        self.assertFalse(svc.start())

    def test_is_running_false_initially(self) -> None:
        svc = self._make_svc(entrypoint_exists=False)
        self.assertFalse(svc.is_running())

    def test_available_when_entrypoint_exists(self) -> None:
        svc = self._make_svc(entrypoint_exists=True)
        self.assertTrue(svc.available)

    def test_start_when_available_increments_attempts(self) -> None:
        svc = self._make_svc(entrypoint_exists=True)
        if not svc.available:
            self.skipTest("entrypoint not set up correctly")
        svc.start()
        self.assertEqual(svc.start_attempts, 1)


if __name__ == "__main__":
    unittest.main()
