from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import bootstrap


class BootstrapTests(unittest.TestCase):
    def test_bootstrap_creates_missing_workspace_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            report = bootstrap.bootstrap_workspace(root=root)

            self.assertEqual(report["status"], "ok")
            self.assertTrue((root / "logs").exists())
            self.assertTrue((root / "data" / "minimind").exists())
            self.assertTrue((root / "chimera_kb.json").exists())
            self.assertTrue((root / "rag_storage.json").exists())
            self.assertTrue((root / "config" / "runtime_profile.json").exists())

    def test_build_default_directories_returns_list_of_paths(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            dirs = bootstrap.build_default_directories(root)
            self.assertIsInstance(dirs, list)
            self.assertTrue(all(isinstance(d, Path) for d in dirs))
            self.assertTrue(any("logs" in str(d) for d in dirs))
            self.assertTrue(any("data" in str(d) for d in dirs))

    def test_build_default_json_files_returns_dict_of_paths(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            json_files = bootstrap.build_default_json_files(root)
            self.assertIsInstance(json_files, dict)
            self.assertTrue(all(isinstance(k, Path) for k in json_files.keys()))
            # chimera_kb.json and rag_storage.json must be present
            paths_str = [str(k) for k in json_files.keys()]
            self.assertTrue(any("chimera_kb.json" in p for p in paths_str))
            self.assertTrue(any("rag_storage.json" in p for p in paths_str))

    def test_bootstrap_skips_directories_that_already_exist(self) -> None:
        """Directories pre-created before bootstrap should not appear in created_directories."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for directory in bootstrap.build_default_directories(root):
                directory.mkdir(parents=True, exist_ok=True)

            report = bootstrap.bootstrap_workspace(root=root)

            self.assertEqual(report["status"], "ok")
            self.assertEqual(report["created_directories"], [])

    def test_bootstrap_skips_json_files_that_already_exist(self) -> None:
        """JSON files that already exist should not be re-created on a second bootstrap pass."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bootstrap.bootstrap_workspace(root=root)
            # Second pass — everything already exists.
            report = bootstrap.bootstrap_workspace(root=root)
            self.assertEqual(report["status"], "ok")
            self.assertEqual(report["created_files"], [])

    def test_bootstrap_repairs_invalid_json_profile(self) -> None:
        """An existing but corrupt runtime_profile.json triggers the JSONDecodeError path."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_dir = root / "config"
            config_dir.mkdir(parents=True)
            (config_dir / "runtime_profile.json").write_text(
                "{{not valid json}}", encoding="utf-8"
            )

            report = bootstrap.bootstrap_workspace(root=root)

            self.assertEqual(report["status"], "ok")
            self.assertTrue(
                any("runtime_profile.json" in p for p in report["normalized_files"]),
                msg="Corrupt profile should appear in normalized_files after repair",
            )

    def test_bootstrap_normalizes_partial_profile(self) -> None:
        """A valid but incomplete profile causes normalize_runtime_profile to mark changed=True."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_dir = root / "config"
            config_dir.mkdir(parents=True)
            # An empty dict is missing all default keys → normalize_runtime_profile changed=True.
            (config_dir / "runtime_profile.json").write_text("{}", encoding="utf-8")

            report = bootstrap.bootstrap_workspace(root=root)

            self.assertEqual(report["status"], "ok")
            self.assertTrue(
                any("runtime_profile.json" in p for p in report["normalized_files"]),
                msg="Partial profile should appear in normalized_files after normalization",
            )
