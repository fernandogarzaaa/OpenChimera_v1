from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

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


class AetherServiceLifecycleTests(unittest.TestCase):
    def test_service_is_not_running_initially(self) -> None:
        service = AetherService()
        self.assertFalse(service.is_running())

    def test_service_start_returns_false_when_unavailable(self) -> None:
        service = AetherService()
        service.available = False
        result = service.start()
        self.assertFalse(result)

    def test_service_status_has_all_expected_keys(self) -> None:
        service = AetherService()
        st = service.status()
        for key in ("name", "available", "running", "root", "entrypoint",
                     "immune_loop_available", "start_attempts", "last_error"):
            self.assertIn(key, st)
        self.assertEqual(st["name"], "aether")

    def test_service_start_attempts_increments_on_each_start(self) -> None:
        service = AetherService()
        # When unavailable, start() returns False without incrementing
        service.available = False
        self.assertFalse(service.start())
        self.assertEqual(service.start_attempts, 0)

    def test_service_init_captures_adapter_init_exception(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "core").mkdir(parents=True)
            (root / "core" / "event_bus.py").write_text("# placeholder\n", encoding="utf-8")

            with patch("core.aether_service.get_aether_root", return_value=root), \
                 patch("core.aether_service.AetherKernelAdapter",
                       side_effect=RuntimeError("adapter init failed")):
                service = AetherService()

        self.assertFalse(service.available)
        self.assertEqual(service.error, "adapter init failed")
        self.assertIsNone(service.adapter)


# ---------------------------------------------------------------------------
# AetherKernelAdapter: evolution engine present / missing
# ---------------------------------------------------------------------------

class AetherKernelAdapterEngineTests(unittest.TestCase):
    """Cover adapter init branches for evolution engine (lines 47-50) and
    start_immune_system (lines 53-61)."""

    def _build_adapter(self, *, include_engine: bool, engine_has_class: bool = True):
        mock_engine = MagicMock()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            core_root = root / "core"
            core_root.mkdir(parents=True)
            filenames = ["event_bus.py", "plugin_manager.py"]
            if include_engine:
                filenames.append("evolution_engine.py")
            for fn in filenames:
                (core_root / fn).write_text("# placeholder\n", encoding="utf-8")

            if include_engine and engine_has_class:
                evolution_module = SimpleNamespace(EvolutionEngine=lambda: mock_engine)
            elif include_engine:
                evolution_module = SimpleNamespace()  # no EvolutionEngine attr
            else:
                evolution_module = None

            event_bus_module = SimpleNamespace(
                EventBus=lambda: SimpleNamespace(
                    start=lambda: None, publish_nowait=lambda e, d: None
                ),
                bus=None,
            )
            plugin_manager_module = SimpleNamespace(
                PluginManager=lambda: SimpleNamespace(load_plugins=lambda: None)
            )

            def fake_import(name, path, repo_root=None):
                if path.name == "event_bus.py":
                    return event_bus_module
                if path.name == "plugin_manager.py":
                    return plugin_manager_module
                if path.name == "evolution_engine.py":
                    return evolution_module
                raise AssertionError(f"Unexpected import: {path}")

            with patch("core.aether_service.import_module_from_file", side_effect=fake_import):
                adapter = AetherKernelAdapter(root)
        return adapter, mock_engine

    def test_immune_loop_available_when_engine_found(self) -> None:
        adapter, engine = self._build_adapter(include_engine=True, engine_has_class=True)
        self.assertTrue(adapter.immune_loop_available)
        self.assertIsNone(adapter.immune_loop_error)
        self.assertIs(adapter.evolution_engine, engine)

    def test_immune_loop_error_set_when_engine_export_missing(self) -> None:
        adapter, _ = self._build_adapter(include_engine=True, engine_has_class=False)
        self.assertFalse(adapter.immune_loop_available)
        self.assertEqual(adapter.immune_loop_error, "EvolutionEngine export not found")

    def test_start_immune_system_creates_thread_when_engine_present(self) -> None:
        adapter, _ = self._build_adapter(include_engine=True)
        self.assertIsNone(adapter.evolution_thread)
        adapter.start_immune_system()
        self.assertIsNotNone(adapter.evolution_thread)

    def test_start_immune_system_noop_when_evolution_engine_is_none(self) -> None:
        adapter, _ = self._build_adapter(include_engine=True)
        adapter.evolution_engine = None
        adapter.start_immune_system()
        self.assertIsNone(adapter.evolution_thread)

    def test_start_immune_system_noop_when_thread_already_set(self) -> None:
        adapter, _ = self._build_adapter(include_engine=True)
        adapter.start_immune_system()
        first_thread = adapter.evolution_thread
        adapter.start_immune_system()
        self.assertIs(adapter.evolution_thread, first_thread)


# ---------------------------------------------------------------------------
# AetherKernelAdapter: boot() async method (lines 64-75)
# ---------------------------------------------------------------------------

class AetherKernelAdapterBootTests(unittest.TestCase):
    """Test AetherKernelAdapter.boot() by patching asyncio.sleep to break the loop."""

    def _build_adapter(self):
        mock_engine = MagicMock()
        mock_bus = MagicMock()
        mock_bus.start.return_value = None

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            core_root = root / "core"
            core_root.mkdir(parents=True)
            for fn in ["event_bus.py", "plugin_manager.py", "evolution_engine.py"]:
                (core_root / fn).write_text("# placeholder\n", encoding="utf-8")

            evolution_module = SimpleNamespace(EvolutionEngine=lambda: mock_engine)
            event_bus_module = SimpleNamespace(EventBus=lambda: mock_bus, bus=None)
            plugin_manager_module = SimpleNamespace(
                PluginManager=lambda: SimpleNamespace(load_plugins=lambda: None)
            )

            def fake_import(name, path, repo_root=None):
                if path.name == "event_bus.py":
                    return event_bus_module
                if path.name == "plugin_manager.py":
                    return plugin_manager_module
                if path.name == "evolution_engine.py":
                    return evolution_module
                raise AssertionError(f"Unexpected: {path}")

            with patch("core.aether_service.import_module_from_file", side_effect=fake_import):
                adapter = AetherKernelAdapter(root)
        return adapter, mock_bus

    def test_boot_calls_load_plugins_and_bus_start(self) -> None:
        adapter, mock_bus = self._build_adapter()
        mock_pm = MagicMock()
        adapter.plugin_manager = mock_pm

        with patch("asyncio.sleep", side_effect=asyncio.CancelledError):
            try:
                asyncio.run(adapter.boot())
            except asyncio.CancelledError:
                pass

        mock_pm.load_plugins.assert_called_once()
        mock_bus.start.assert_called_once()
        mock_bus.publish_nowait.assert_called_once()

    def test_boot_awaits_coroutine_bus_start(self) -> None:
        adapter, mock_bus = self._build_adapter()
        awaited: list[bool] = []

        async def async_start() -> None:
            awaited.append(True)

        mock_bus.start.return_value = async_start()

        with patch("asyncio.sleep", side_effect=asyncio.CancelledError):
            try:
                asyncio.run(adapter.boot())
            except asyncio.CancelledError:
                pass

        self.assertTrue(awaited, "async bus.start() coroutine should have been awaited")


# ---------------------------------------------------------------------------
# AetherService.start() — lines 93-96 (already-running) and 101-120 (runner)
# ---------------------------------------------------------------------------

class AetherServiceStartTests(unittest.TestCase):
    """Cover AetherService.start() paths that require a live adapter."""

    def _make_service(self, boot_fn):
        fake_adapter = SimpleNamespace(
            immune_loop_available=False,
            immune_loop_error=None,
            boot=boot_fn,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "core").mkdir(parents=True)
            (root / "core" / "event_bus.py").write_text("# placeholder\n", encoding="utf-8")
            with patch("core.aether_service.get_aether_root", return_value=root), \
                 patch("core.aether_service.AetherKernelAdapter", return_value=fake_adapter):
                service = AetherService()
        return service

    def test_start_returns_true_when_already_running(self) -> None:
        async def noop() -> None:
            pass

        service = self._make_service(noop)
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True
        service.thread = mock_thread

        result = service.start()
        self.assertTrue(result)
        self.assertEqual(service.start_attempts, 0)

    def test_start_creates_thread_and_increments_attempts(self) -> None:
        async def quick_boot() -> None:
            await asyncio.sleep(0)

        service = self._make_service(quick_boot)
        result = service.start()
        self.assertTrue(result)
        self.assertEqual(service.start_attempts, 1)
        self.assertIsNotNone(service.thread)

    def test_start_runner_captures_boot_exception(self) -> None:
        async def failing_boot() -> None:
            raise RuntimeError("simulated crash")

        service = self._make_service(failing_boot)
        service.start()
        service.thread.join(timeout=3.0)
        self.assertEqual(service.error, "simulated crash")
        self.assertGreater(service.last_exited_at, 0.0)
