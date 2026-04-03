from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

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
