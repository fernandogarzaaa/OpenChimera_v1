from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.aegis_service import AegisService
from core.ascension_service import AscensionService
from core.local_llm import LocalLLMManager
from core.minimind_service import MiniMindService


class AdvancedCapabilityTests(unittest.TestCase):
    def test_aegis_preview_scans_targets_without_mutating(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "test_demo.py").write_text("print('ok')\n", encoding="utf-8")
            service = AegisService()
            service.available = True

            result = service.run_workflow(target_project=str(root), preview=True)

            self.assertEqual(result["status"], "preview")
            self.assertEqual(result["debt_count"], 1)
            self.assertTrue((root / "test_demo.py").exists())

    def test_aegis_preview_includes_context_recommendations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            service = AegisService()
            service.available = True

            result = service.run_workflow(
                target_project=str(root),
                preview=True,
                preview_context={
                    "focus_areas": ["generation-path-offline"],
                    "recommendations": ["Restore at least one healthy local or cloud generation path."],
                },
            )

            self.assertIn("generation-path-offline", result["focus_areas"])
            self.assertTrue(any("Restore at least one healthy local or cloud generation path." in item for item in result["recommended_actions"]))

    def test_ascension_deliberation_falls_back_to_local_llm(self) -> None:
        minimind = MiniMindService()
        minimind.reasoning_completion = MagicMock(return_value={"content": "", "model": "minimind", "error": "low quality"})
        llm_manager = LocalLLMManager()
        llm_manager.get_ranked_models = MagicMock(return_value=["llama-3.2-3b"])
        llm_manager.chat_completion = MagicMock(
            return_value={"content": "Use a stronger runtime bridge and better discovery.", "model": "llama-3.2-3b"}
        )
        service = AscensionService(llm_manager, minimind)

        result = service.deliberate("How should OpenChimera surpass OpenClaw?", perspectives=["architect"])

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["perspectives"][0]["model"], "llama-3.2-3b")
        self.assertIn("Consensus:", result["consensus"])


if __name__ == "__main__":
    unittest.main()


class AscensionLifecycleTests(unittest.TestCase):
    """Additional tests for AscensionService lifecycle and status contract."""

    def _make_service(self):
        minimind = MagicMock()
        llm_manager = MagicMock()
        return AscensionService(llm_manager, minimind)

    def test_ascension_status_has_all_expected_keys(self):
        service = self._make_service()
        st = service.status()
        for key in ("name", "available", "running", "last_result", "capabilities"):
            self.assertIn(key, st)
        self.assertEqual(st["name"], "ascension")

    def test_ascension_start_sets_running_true(self):
        service = self._make_service()
        result = service.start()
        self.assertTrue(result["running"])

    def test_ascension_stop_sets_running_false(self):
        service = self._make_service()
        service.start()
        result = service.stop()
        self.assertFalse(result["running"])

    def test_ascension_capabilities_list_not_empty(self):
        service = self._make_service()
        self.assertGreater(len(service.status()["capabilities"]), 0)

    def test_ascension_deliberate_all_minimind_fail_uses_local_llm_for_each(self):
        """When minimind returns empty content for every perspective the fallback chain is used."""
        minimind = MiniMindService()
        minimind.reasoning_completion = MagicMock(
            return_value={"content": "", "model": "minimind", "error": "timeout"}
        )
        llm_manager = LocalLLMManager()
        llm_manager.get_ranked_models = MagicMock(return_value=["mistral-7b"])
        llm_manager.chat_completion = MagicMock(
            return_value={"content": "Local LLM answered.", "model": "mistral-7b"}
        )
        service = AscensionService(llm_manager, minimind)

        result = service.deliberate(
            "What is the best path forward?",
            perspectives=["architect", "skeptic"],
        )

        self.assertEqual(result["status"], "ok")
        for perspective_result in result["perspectives"]:
            self.assertEqual(perspective_result["source"], "local-llm")
        self.assertIn("Consensus:", result["consensus"])

    def test_ascension_deliberate_minimind_succeeds_no_fallback(self):
        """When minimind returns valid content, local LLM is never called."""
        minimind = MiniMindService()
        minimind.reasoning_completion = MagicMock(
            return_value={"content": "MiniMind gave a solid answer.", "model": "minimind-v1"}
        )
        llm_manager = LocalLLMManager()
        llm_manager.chat_completion = MagicMock()
        service = AscensionService(llm_manager, minimind)

        result = service.deliberate("Plan the next release.", perspectives=["operator"])

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["perspectives"][0]["source"], "minimind")
        llm_manager.chat_completion.assert_not_called()


class AegisServiceTests(unittest.TestCase):
    """Tests for AegisService status contract and lifecycle."""

    def test_aegis_status_has_all_expected_keys(self):
        service = AegisService()
        st = service.status()
        for key in ("name", "available", "running", "root", "entrypoint", "orchestrator", "last_run", "last_error", "capabilities"):
            self.assertIn(key, st)
        self.assertEqual(st["name"], "aegis")

    def test_aegis_start_sets_running_equal_to_available(self):
        service = AegisService()
        result = service.start()
        self.assertEqual(result["running"], service.available)

    def test_aegis_stop_always_sets_running_false(self):
        service = AegisService()
        service.start()
        result = service.stop()
        self.assertFalse(result["running"])

    def test_aegis_run_workflow_unavailable_returns_error_status(self):
        service = AegisService()
        service.available = False
        result = service.run_workflow(preview=True)
        self.assertEqual(result["status"], "error")
        self.assertIn("error", result)


# ---------------------------------------------------------------------------
# AegisService: __init__ (lines 25-36), run_workflow live mode (80-94),
# _preview_recommendations empty path (line 136)
# ---------------------------------------------------------------------------

class AegisServiceAdvancedTests(unittest.TestCase):
    """Cover aegis init branches and live-mode workflow paths."""

    def _make_root_with_entrypoints(self):
        tmp = tempfile.mkdtemp()
        root = Path(tmp)
        main_py = root / "main.py"
        orch_dir = root / "core"
        orch_dir.mkdir()
        main_py.touch()
        (orch_dir / "orchestrator.py").touch()
        return root

    def test_init_loads_swarm_when_entrypoints_exist(self) -> None:
        root = self._make_root_with_entrypoints()
        mock_swarm_cls = MagicMock()
        mock_orch_cls = MagicMock()
        main_mod = SimpleNamespace(AegisSwarm=mock_swarm_cls)
        orch_mod = SimpleNamespace(SwarmOrchestrator=mock_orch_cls)

        def fake_import(name, path, repo_root=None):
            if path.name == "main.py":
                return main_mod
            return orch_mod

        with patch("core.aegis_service.get_aegis_root", return_value=root), \
             patch("core.aegis_service.import_module_from_file", side_effect=fake_import):
            service = AegisService()

        self.assertTrue(service.available)
        self.assertIs(service.aegis_swarm, mock_swarm_cls)
        self.assertIs(service.orchestrator_cls, mock_orch_cls)

    def test_init_sets_unavailable_on_import_error(self) -> None:
        root = self._make_root_with_entrypoints()

        with patch("core.aegis_service.get_aegis_root", return_value=root), \
             patch("core.aegis_service.import_module_from_file",
                   side_effect=ImportError("missing dep")):
            service = AegisService()

        self.assertFalse(service.available)
        self.assertEqual(service.last_error, "missing dep")

    def test_run_workflow_live_mode_no_swarm_returns_error(self) -> None:
        service = AegisService()
        service.available = True
        service.aegis_swarm = None

        result = service.run_workflow(preview=False)

        self.assertEqual(result["status"], "error")
        self.assertIn("unavailable", result["error"])
        self.assertIs(service.last_run, result)

    def test_run_workflow_live_mode_calls_swarm_and_returns_ok(self) -> None:
        mock_swarm_instance = MagicMock()
        mock_swarm_cls = MagicMock(return_value=mock_swarm_instance)

        service = AegisService()
        service.available = True
        service.aegis_swarm = mock_swarm_cls

        with tempfile.TemporaryDirectory() as tmp:
            result = service.run_workflow(target_project=tmp, preview=False)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["mode"], "workflow")
        mock_swarm_cls.assert_called_once()
        mock_swarm_instance.run_workflow.assert_called_once()
        self.assertIs(service.last_run, result)

    def test_preview_empty_dir_no_context_gives_default_recommendation(self) -> None:
        service = AegisService()
        service.available = True

        with tempfile.TemporaryDirectory() as tmp:
            result = service.run_workflow(
                target_project=tmp,
                preview=True,
                preview_context={},
            )

        self.assertEqual(result["status"], "preview")
        self.assertEqual(result["debt_count"], 0)
        self.assertTrue(
            any("No concrete repair actions" in r for r in result["recommended_actions"]),
            f"Expected default recommendation, got: {result['recommended_actions']}",
        )

