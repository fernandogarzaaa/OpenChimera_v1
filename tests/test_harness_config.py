from __future__ import annotations

import importlib
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from core.config import is_supported_harness_repo_root
from core.harness_port import HarnessPortAdapter


class HarnessConfigTests(unittest.TestCase):
    def test_supported_harness_repo_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            src = root / "src"
            src.mkdir(parents=True)
            for relative_path in [
                "main.py",
                "port_manifest.py",
                "query_engine.py",
                "commands.py",
                "tools.py",
            ]:
                (src / relative_path).write_text("# stub\n", encoding="utf-8")

            self.assertTrue(is_supported_harness_repo_root(root))

    def test_sourcemap_style_layout_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            src = root / "src"
            src.mkdir(parents=True)
            for relative_path in [
                "main.py",
                "port_manifest.py",
                "query_engine.py",
                "commands.py",
                "tools.py",
            ]:
                (src / relative_path).write_text("# stub\n", encoding="utf-8")

            (root / "extract-sources.js").write_text("// blocked\n", encoding="utf-8")

            self.assertFalse(is_supported_harness_repo_root(root))


class HarnessPortAdapterTests(unittest.TestCase):
    def test_status_returns_unavailable_when_harness_missing(self) -> None:
        adapter = HarnessPortAdapter()
        status = adapter.status()
        # On a development machine without the live harness, should report unavailable
        if not adapter.available:
            self.assertFalse(status["available"])
            self.assertIn("root", status)
            self.assertIn("error", status)

    def test_sanitize_text_replaces_brand_names(self) -> None:
        adapter = HarnessPortAdapter()
        raw = "Claude Code is built by Anthropic. The claude-code CLI is available."
        result = adapter._sanitize_text(raw)
        self.assertNotIn("Claude Code", result)
        self.assertNotIn("Anthropic", result)
        self.assertNotIn("claude-code", result)

    def test_build_unavailable_reason_root_missing(self) -> None:
        adapter = HarnessPortAdapter()
        with tempfile.TemporaryDirectory() as tmpdir:
            missing = Path(tmpdir) / "nonexistent-root"
            adapter.root = missing
            reason = adapter._build_unavailable_reason()
            self.assertIn("does not exist", reason)

    def test_build_unavailable_reason_suspicious_marker(self) -> None:
        adapter = HarnessPortAdapter()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "extract-sources.js").write_text("// blocked", encoding="utf-8")
            adapter.root = root
            reason = adapter._build_unavailable_reason()
            self.assertIn("safety validation", reason)

    def test_build_unavailable_reason_structural_mismatch(self) -> None:
        adapter = HarnessPortAdapter()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            adapter.root = root
            reason = adapter._build_unavailable_reason()
            self.assertIn("structural validation", reason)

    def test_legacy_snapshot_status_returns_unavailable_when_no_skills_dir(self) -> None:
        adapter = HarnessPortAdapter()
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter.legacy_snapshot_root = Path(tmpdir) / "nowhere"
            legacy = adapter._legacy_snapshot_status()
            self.assertFalse(legacy["available"])
            self.assertEqual(legacy["skill_count"], 0)

    def test_legacy_snapshot_status_finds_skills_when_present(self) -> None:
        adapter = HarnessPortAdapter()
        with tempfile.TemporaryDirectory() as tmpdir:
            skills_root = Path(tmpdir) / ".agents" / "skills"
            (skills_root / "skill-a").mkdir(parents=True)
            (skills_root / "skill-b").mkdir(parents=True)
            adapter.legacy_snapshot_root = Path(tmpdir)
            legacy = adapter._legacy_snapshot_status()
            self.assertTrue(legacy["available"])
            self.assertEqual(legacy["skill_count"], 2)

    # ------------------------------------------------------------------
    # Constructor coverage: unavailable path (line 24) and import-error
    # path (lines 41-43).
    # ------------------------------------------------------------------

    def test_adapter_sets_error_when_harness_not_supported(self) -> None:
        """Constructor should call _build_unavailable_reason when supported=False."""
        with patch("core.harness_port.is_supported_harness_repo_root", return_value=False), \
             patch("core.harness_port.get_harness_repo_root", return_value=Path(tempfile.mkdtemp())):
            adapter = HarnessPortAdapter()
            self.assertFalse(adapter.available)
            self.assertIsNotNone(adapter.error)

    def test_adapter_catches_import_failure_during_module_load(self) -> None:
        """Constructor catches ImportError when module loading fails after structural check passes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            src = root / "src"
            src.mkdir()
            for fname in ["main.py", "port_manifest.py", "query_engine.py", "commands.py", "tools.py"]:
                (src / fname).write_text("# stub\n", encoding="utf-8")

            with patch("core.harness_port.get_harness_repo_root", return_value=root), \
                 patch("core.harness_port.importlib.import_module",
                       side_effect=ModuleNotFoundError("stub-module-missing")):
                adapter = HarnessPortAdapter()
                self.assertFalse(adapter.available)
                self.assertIn("stub-module-missing", adapter.error)

    # ------------------------------------------------------------------
    # status() error field coverage (line 53)
    # ------------------------------------------------------------------

    def test_status_includes_error_field_when_unavailable(self) -> None:
        """status() must expose 'error' when adapter is not available."""
        adapter = HarnessPortAdapter()
        adapter.available = False
        adapter.error = "forced-unavailable-for-test"
        status = adapter.status()
        self.assertFalse(status["available"])
        self.assertEqual(status.get("error"), "forced-unavailable-for-test")

    # ------------------------------------------------------------------
    # build_sft_examples() coverage (lines 104-130)
    # ------------------------------------------------------------------

    def test_build_sft_examples_returns_empty_when_unavailable(self) -> None:
        """build_sft_examples() returns [] immediately when adapter is unavailable."""
        adapter = HarnessPortAdapter()
        adapter.available = False
        examples = adapter.build_sft_examples()
        self.assertEqual(examples, [])

    def test_build_sft_examples_returns_five_conversations_when_available(self) -> None:
        """build_sft_examples() returns 5 conversation dicts when status() is available."""
        adapter = HarnessPortAdapter()
        mock_status = {
            "available": True,
            "root": "/tmp/fake-root",
            "src_root": "/tmp/fake-root/src",
            "summary": "Architecture summary text",
            "commands": [
                {"name": "cmd-a", "responsibility": "handle auth", "status": "active"},
            ],
            "tools": [
                {"name": "tool-a", "responsibility": "search corpus", "status": "active"},
            ],
            "top_level_modules": [
                {"name": "core", "file_count": 42, "notes": "main runtime"},
            ],
            "legacy_snapshot": {
                "root": "/legacy",
                "notable_skills": ["eval-harness", "deep-research"],
            },
        }
        adapter.status = lambda: mock_status  # type: ignore[method-assign]
        examples = adapter.build_sft_examples()
        self.assertEqual(len(examples), 5)
        for ex in examples:
            self.assertIn("conversations", ex)
            convos = ex["conversations"]
            self.assertIsInstance(convos, list)
            roles = [c["role"] for c in convos]
            self.assertIn("user", roles)
            self.assertIn("assistant", roles)

if __name__ == '__main__':
    unittest.main()
