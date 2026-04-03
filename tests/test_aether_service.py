from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core.aether_service import AetherKernelAdapter, AetherService


class AetherServiceTests(unittest.TestCase):
    def test_adapter_reports_immune_loop_degradation_when_evolution_import_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            core_root = root / "core"
            core_root.mkdir(parents=True)
            for filename in ["event_bus.py", "plugin_manager.py", "evolution_engine.py"]:
                (core_root / filename).write_text("# placeholder\n", encoding="utf-8")

            event_bus_module = SimpleNamespace(EventBus=lambda: SimpleNamespace(start=lambda: None), bus=None)
            plugin_manager_module = SimpleNamespace(PluginManager=lambda: SimpleNamespace(load_plugins=lambda: None))

            def fake_import(module_name: str, file_path: Path, repo_root: Path | None = None):
                if file_path.name == "event_bus.py":
                    return event_bus_module
                if file_path.name == "plugin_manager.py":
                    return plugin_manager_module
                if file_path.name == "evolution_engine.py":
                    raise ModuleNotFoundError("No module named 'psutil'")
                raise AssertionError(f"Unexpected import: {file_path}")

            with patch("core.aether_service.import_module_from_file", side_effect=fake_import):
                adapter = AetherKernelAdapter(root)

        self.assertFalse(adapter.immune_loop_available)
        self.assertEqual(adapter.immune_loop_error, "No module named 'psutil'")
        self.assertIsNone(adapter.evolution_engine)

    def test_service_status_exposes_immune_loop_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            core_root = root / "core"
            core_root.mkdir(parents=True)
            (core_root / "event_bus.py").write_text("# placeholder\n", encoding="utf-8")

            fake_adapter = SimpleNamespace(immune_loop_available=False, immune_loop_error="No module named 'psutil'")

            with patch("core.aether_service.get_aether_root", return_value=root), patch(
                "core.aether_service.AetherKernelAdapter", return_value=fake_adapter
            ):
                service = AetherService()

        status = service.status()
        self.assertTrue(status["available"])
        self.assertFalse(status["immune_loop_available"])
        self.assertEqual(status["immune_loop_error"], "No module named 'psutil'")


if __name__ == "__main__":
    unittest.main()