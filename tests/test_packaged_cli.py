"""Tests for the packaged v2 CLI surface exercised by CI smoke checks.

The ``smoke-install`` CI job installs only the built wheel and runs::

    openchimera bootstrap
    openchimera doctor --production --json
    openchimera status --json
    openchimera backup create --json

These tests load the packaged CLI (``python/openchimera/cli.py``) directly
from its file path and verify every smoke command exits 0 on a fresh
workspace. The module is loaded under a private name because the repo-root
``openchimera`` namespace package shadows the installed one inside a
checkout. Seeded ``sys.modules`` entries are removed after the suite so
other tests keep seeing the repo-root namespace.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path

from click.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
V2 = ROOT / "python" / "openchimera"

_SEEDED_MODULE_NAMES = (
    "openchimera.config",
    "openchimera.server",
    "openchimera_v2_cli_under_test",
)


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_v2_cli():
    """Load the packaged v2 CLI with a stubbed server module."""
    config_mod = _load_module("openchimera.config", V2 / "config.py")
    config_mod._SETTINGS_CACHE = None
    server_stub = types.ModuleType("openchimera.server")
    server_stub.start_server = lambda *args, **kwargs: None
    sys.modules["openchimera.server"] = server_stub
    cli_mod = _load_module("openchimera_v2_cli_under_test", V2 / "cli.py")
    return cli_mod, config_mod


class PackagedCliSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._previous_modules = {
            name: sys.modules[name] for name in _SEEDED_MODULE_NAMES if name in sys.modules
        }
        cli_mod, config_mod = _load_v2_cli()
        cls._cli = cli_mod.cli
        cls._config_mod = config_mod
        cls.addClassCleanup(cls._restore_modules)

    @classmethod
    def _restore_modules(cls) -> None:
        for name in _SEEDED_MODULE_NAMES:
            sys.modules.pop(name, None)
        sys.modules.update(cls._previous_modules)

    def setUp(self) -> None:
        self._config_mod._SETTINGS_CACHE = None
        self.runner = CliRunner()

    def test_bootstrap_creates_state_dirs(self) -> None:
        with self.runner.isolated_filesystem():
            result = self.runner.invoke(self._cli, ["bootstrap"])
            self.assertEqual(result.exit_code, 0, msg=result.output)
            self.assertTrue(Path("config").is_dir())
            self.assertTrue(Path("data").is_dir())

    def test_bootstrap_json_reports_workspace(self) -> None:
        with self.runner.isolated_filesystem():
            result = self.runner.invoke(self._cli, ["bootstrap", "--json"])
            self.assertEqual(result.exit_code, 0, msg=result.output)
            payload = json.loads(result.output)
            self.assertEqual(payload["status"], "ok")
            self.assertIn("created_directories", payload)

    def test_status_json_reports_version(self) -> None:
        with self.runner.isolated_filesystem():
            result = self.runner.invoke(self._cli, ["status", "--json"])
            self.assertEqual(result.exit_code, 0, msg=result.output)
            payload = json.loads(result.output)
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["version"], "2.0.0")

    def test_doctor_production_json_always_reports(self) -> None:
        with self.runner.isolated_filesystem():
            result = self.runner.invoke(self._cli, ["doctor", "--production", "--json"])
            self.assertEqual(result.exit_code, 0, msg=result.output)
            payload = json.loads(result.output)
            self.assertTrue(payload["production"]["requested"])
            self.assertIn("checks", payload["production"])
            self.assertIn("warnings", payload["production"])

    def test_backup_create_then_list(self) -> None:
        with self.runner.isolated_filesystem():
            created = self.runner.invoke(self._cli, ["backup", "create", "--json"])
            self.assertEqual(created.exit_code, 0, msg=created.output)
            payload = json.loads(created.output)
            self.assertEqual(payload["status"], "ok")
            self.assertTrue(Path(payload["backup"]["path"]).exists())
            listed = self.runner.invoke(self._cli, ["backup", "list", "--json"])
            self.assertEqual(listed.exit_code, 0, msg=listed.output)
            self.assertGreaterEqual(json.loads(listed.output)["count"], 1)

    def test_ci_smoke_sequence_passes_fresh(self) -> None:
        """Mirror the exact CI smoke-install command sequence."""
        with self.runner.isolated_filesystem():
            commands = [
                ["bootstrap"],
                ["doctor", "--production", "--json"],
                ["status", "--json"],
                ["backup", "create", "--json"],
            ]
            for argv in commands:
                result = self.runner.invoke(self._cli, argv)
                self.assertEqual(result.exit_code, 0, msg=f"{argv}: {result.output}")


if __name__ == "__main__":
    unittest.main()
