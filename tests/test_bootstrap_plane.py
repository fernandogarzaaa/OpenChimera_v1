from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.bootstrap_plane import BootstrapPlane


class BootstrapPlaneTests(unittest.TestCase):
    def _build_plane(self, profile: dict[str, object] | None = None) -> tuple[BootstrapPlane, dict[str, object]]:
        state: dict[str, object] = {
            "profile": profile or {"local_runtime": {"reasoning_engine_config": {}}},
            "started": False,
        }
        plane = BootstrapPlane(
            profile_loader=lambda: state["profile"],
            profile_setter=lambda profile: state.__setitem__("profile", profile),
            started_getter=lambda: bool(state["started"]),
            started_setter=lambda started: state.__setitem__("started", started),
            llm_manager=MagicMock(),
            job_queue=MagicMock(),
            minimind=MagicMock(),
            autonomy=MagicMock(),
            aegis=MagicMock(),
            ascension=MagicMock(),
            bus=MagicMock(),
            status_getter=MagicMock(return_value={"online": True}),
            rag=MagicMock(),
            harness_port=MagicMock(),
            onboarding=MagicMock(),
            model_registry=MagicMock(),
        )
        plane.harness_port.available = False
        plane.minimind.available = False
        plane.autonomy.should_auto_start.return_value = False
        return plane, state

    def test_start_starts_runtime_and_publishes_status(self) -> None:
        plane, state = self._build_plane(
            profile={"local_runtime": {"reasoning_engine_config": {"auto_start_server": True}}}
        )

        plane.start()

        self.assertTrue(state["started"])
        plane.llm_manager.start_health_monitoring.assert_called_once_with()
        plane.job_queue.start.assert_called_once_with()
        plane.minimind.refresh_runtime_state.assert_called_once_with()
        plane.minimind.start_server.assert_called_once_with()
        plane.aegis.start.assert_called_once_with()
        plane.ascension.start.assert_called_once_with()
        plane.bus.publish_nowait.assert_called_once_with("system/provider", {"online": True})

    def test_apply_onboarding_reloads_profile_and_publishes_event(self) -> None:
        plane, state = self._build_plane()
        plane.onboarding.apply.return_value = {"completed": True}
        refreshed_profile = {"providers": {"enabled": ["local-llama-cpp"]}}
        plane.profile_loader = MagicMock(side_effect=[refreshed_profile, refreshed_profile])

        result = plane.apply_onboarding({"preferred_local_model": "qwen2.5-7b"})

        self.assertTrue(result["completed"])
        self.assertEqual(state["profile"], refreshed_profile)
        self.assertEqual(plane.model_registry.profile, refreshed_profile)
        plane.onboarding.apply.assert_called_once_with({"preferred_local_model": "qwen2.5-7b"})
        plane.bus.publish_nowait.assert_called_once_with("system/onboarding", {"action": "apply", "result": {"completed": True}})

    def test_seed_knowledge_adds_bootstrap_sources(self) -> None:
        plane, _ = self._build_plane()
        plane.harness_port.available = True
        plane.harness_port.status.return_value = {"summary": "Harness summary"}
        plane.harness_port.root = Path("fake/harness")
        plane.minimind.available = True
        plane.minimind.root = Path("fake/minimind")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            kb_path = root / "chimera_kb.json"
            kb_path.write_text('[{"id": "kb-1", "text": "OpenChimera fact", "metadata": {"topic": "runtime"}}]', encoding="utf-8")
            legacy_root = root / "legacy-snapshot"
            legacy_root.mkdir(parents=True, exist_ok=True)
            with patch("core.bootstrap_plane.ROOT", root), patch("core.bootstrap_plane.get_chimera_kb_path", return_value=kb_path), patch(
                "core.bootstrap_plane.get_legacy_harness_snapshot_root", return_value=legacy_root
            ):
                plane.seed_knowledge()

        added_docs = plane.rag.add_documents.call_args_list
        self.assertEqual(len(added_docs), 2)
        self.assertEqual(added_docs[0].kwargs["persist"], False)
        self.assertEqual(added_docs[0].args[0][0].text, "OpenChimera fact")
        self.assertEqual(added_docs[1].args[0][0].text, "Harness summary")
        added_files = [call.args[0] for call in plane.rag.add_file.call_args_list]
        self.assertIn(root / "README.md", added_files)
        self.assertIn(root / "config" / "runtime_profile.json", added_files)
        self.assertIn(legacy_root / "README.md", added_files)
        self.assertIn(Path("fake/harness") / "README.md", added_files)
        self.assertIn(Path("fake/minimind") / "README.md", added_files)
        self.assertIn(Path("fake/minimind") / "CHIMERA_MINI_PROPOSAL.md", added_files)