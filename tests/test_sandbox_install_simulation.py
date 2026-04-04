from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.capabilities import CapabilityRegistry
from core.plugins import PluginManager
from sandbox.install_simulation import prepare_sandbox_workspace, simulate_installation, simulate_installation_smoke_run


class SandboxInstallSimulationTests(unittest.TestCase):
    def test_prepare_sandbox_workspace_creates_stub_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = prepare_sandbox_workspace(destination=temp_dir)
            workspace_root = Path(result["workspace_root"])
            self.assertTrue((workspace_root / "core" / "migrations" / "001_initial_runtime_tables.sql").exists())
            self.assertTrue((workspace_root / "sandbox" / "stubs" / "repos" / "upstream-harness-repo" / "src" / "main.py").exists())
            self.assertTrue((workspace_root / "sandbox" / "stubs" / "openclaw" / "research" / "minimind" / "model" / "model_minimind.py").exists())
            self.assertIn("OPENCHIMERA_PORT", result["environment"])

    def test_simulate_installation_runs_bootstrap_in_sandbox(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = simulate_installation(destination=temp_dir)
            bootstrap_report = result["bootstrap"]
            self.assertEqual(bootstrap_report["status"], "ok")
            workspace_root = Path(result["workspace_root"])
            self.assertTrue((workspace_root / "data" / "model_registry.json").exists())

    def test_simulate_installation_smoke_run_starts_api(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = simulate_installation_smoke_run(destination=temp_dir)
            smoke_run = result["smoke_run"]
            self.assertEqual(smoke_run["status"], "ok")
            self.assertEqual(smoke_run["health"]["status"], "online")
            self.assertIn(smoke_run["readiness"]["status"], {"ready", "degraded"})
            self.assertIsNotNone(smoke_run["system_status"])


class PluginManagerTests(unittest.TestCase):
    """Unit tests for core.plugins.PluginManager."""

    def _make_plugin_manager(self, tmpdir: str, plugin_ids: list[str] | None = None) -> PluginManager:
        root = Path(tmpdir)
        plugins_dir = root / "plugins"
        plugins_dir.mkdir(parents=True, exist_ok=True)
        for pid in (plugin_ids or ["test-plugin"]):
            (plugins_dir / f"{pid}.json").write_text(
                f'{{"id": "{pid}", "name": "{pid.title()}", "version": "1.0.0", "description": "Auto-generated test plugin."}}',
                encoding="utf-8",
            )
        registry = CapabilityRegistry(root=root)
        return PluginManager(
            capability_registry=registry,
            state_path=root / "plugins_state.json",
        )

    def test_list_plugins_returns_a_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pm = self._make_plugin_manager(tmpdir)
            result = pm.list_plugins()
            self.assertIsInstance(result, list)

    def test_list_plugins_discovered_plugin_appears_not_installed_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pm = self._make_plugin_manager(tmpdir, plugin_ids=["my-plugin"])
            plugins = pm.list_plugins()
            self.assertEqual(len(plugins), 1)
            self.assertFalse(plugins[0]["installed"])

    def test_plugin_manager_status_has_expected_structure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pm = self._make_plugin_manager(tmpdir)
            st = pm.status()
            self.assertIn("counts", st)
            self.assertIn("plugins", st)
            self.assertIn("total", st["counts"])
            self.assertIn("installed", st["counts"])

    def test_install_plugin_sets_installed_flag(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pm = self._make_plugin_manager(tmpdir, plugin_ids=["test-plugin"])
            result = pm.install("test-plugin")
            self.assertEqual(result["status"], "installed")
            plugins = {p["id"]: p for p in pm.list_plugins()}
            self.assertTrue(plugins["test-plugin"]["installed"])

    def test_install_then_uninstall_clears_installed_flag(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pm = self._make_plugin_manager(tmpdir, plugin_ids=["removable"])
            pm.install("removable")
            uninstall_result = pm.uninstall("removable")
            self.assertEqual(uninstall_result["status"], "uninstalled")
            plugins = {p["id"]: p for p in pm.list_plugins()}
            self.assertFalse(plugins["removable"]["installed"])

    def test_install_unknown_plugin_raises_value_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pm = self._make_plugin_manager(tmpdir, plugin_ids=["known-plugin"])
            with self.assertRaises(ValueError):
                pm.install("ghost-plugin-that-does-not-exist")

    def test_uninstall_unknown_plugin_raises_value_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pm = self._make_plugin_manager(tmpdir, plugin_ids=["known-plugin"])
            with self.assertRaises(ValueError):
                pm.uninstall("ghost-plugin-that-does-not-exist")

    def test_status_installed_count_increases_after_install(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pm = self._make_plugin_manager(tmpdir, plugin_ids=["alpha", "beta"])
            self.assertEqual(pm.status()["counts"]["installed"], 0)
            pm.install("alpha")
            self.assertEqual(pm.status()["counts"]["installed"], 1)
            pm.install("beta")
            self.assertEqual(pm.status()["counts"]["installed"], 2)

