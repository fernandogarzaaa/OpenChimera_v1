"""Tests for scripts/self_evolution_cycle.py — evolution cycle helpers."""
from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Import the module under test (not on sys.path by default)
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import self_evolution_cycle as evo_cycle  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_memory(last_ts: float = 0.0, cycles: list | None = None) -> dict:
    return {
        "schema_version": 1,
        "last_cycle_timestamp": last_ts,
        "cycles": cycles or [],
    }


# ---------------------------------------------------------------------------
# Memory log helpers
# ---------------------------------------------------------------------------

class TestLoadMemory(unittest.TestCase):
    def test_returns_default_when_file_missing(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "nonexistent.json"
            with patch.object(evo_cycle, "MEMORY_PATH", path):
                mem = evo_cycle.load_memory()
        self.assertEqual(mem["schema_version"], 1)
        self.assertEqual(mem["last_cycle_timestamp"], 0)
        self.assertEqual(mem["cycles"], [])

    def test_loads_valid_json(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "mem.json"
            data = _make_memory(last_ts=12345.0, cycles=[{"cycle_id": 1}])
            path.write_text(json.dumps(data), encoding="utf-8")
            with patch.object(evo_cycle, "MEMORY_PATH", path):
                mem = evo_cycle.load_memory()
        self.assertEqual(mem["last_cycle_timestamp"], 12345.0)
        self.assertEqual(len(mem["cycles"]), 1)

    def test_returns_default_on_invalid_json(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "bad.json"
            path.write_text("{not valid json", encoding="utf-8")
            with patch.object(evo_cycle, "MEMORY_PATH", path):
                mem = evo_cycle.load_memory()
        self.assertEqual(mem["cycles"], [])


class TestSaveMemory(unittest.TestCase):
    def test_writes_and_reads_back(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "mem.json"
            data = _make_memory(last_ts=99.9, cycles=[{"cycle_id": 1}])
            with patch.object(evo_cycle, "MEMORY_PATH", path):
                evo_cycle.save_memory(data)
                loaded = json.loads(path.read_text(encoding="utf-8"))
        self.assertAlmostEqual(loaded["last_cycle_timestamp"], 99.9)

    def test_prunes_cycles_beyond_max(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "mem.json"
            cycles = [{"cycle_id": i} for i in range(200)]
            data = _make_memory(cycles=cycles)
            with patch.object(evo_cycle, "MEMORY_PATH", path):
                with patch.object(evo_cycle, "MEMORY_MAX_CYCLES", 10):
                    evo_cycle.save_memory(data)
                    loaded = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(len(loaded["cycles"]), 10)
        # Should retain the last 10 entries
        self.assertEqual(loaded["cycles"][0]["cycle_id"], 190)


# ---------------------------------------------------------------------------
# Loop guard
# ---------------------------------------------------------------------------

class TestCheckLoopGuard(unittest.TestCase):
    def test_allows_run_when_no_previous_cycle(self):
        mem = _make_memory(last_ts=0.0)
        self.assertTrue(evo_cycle.check_loop_guard(mem))

    def test_allows_run_when_enough_time_elapsed(self):
        old_ts = time.time() - (24 * 3600)  # 24 h ago
        mem = _make_memory(last_ts=old_ts)
        self.assertTrue(evo_cycle.check_loop_guard(mem))

    def test_blocks_run_when_too_recent(self):
        recent_ts = time.time() - 3600  # only 1 h ago
        mem = _make_memory(last_ts=recent_ts)
        self.assertFalse(evo_cycle.check_loop_guard(mem))


# ---------------------------------------------------------------------------
# GitHub Actions output writer
# ---------------------------------------------------------------------------

class TestWriteGithubOutputs(unittest.TestCase):
    def test_writes_cycle_id_and_branch_name(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as fh:
            output_path = fh.name
        try:
            with patch.dict(os.environ, {"GITHUB_OUTPUT": output_path}):
                evo_cycle.write_github_outputs(cycle_id=7, branch_name="evo/cycle-0007")
            content = Path(output_path).read_text(encoding="utf-8")
        finally:
            os.unlink(output_path)

        self.assertIn("cycle_id=7", content)
        self.assertIn("branch_name=evo/cycle-0007", content)

    def test_noop_when_github_output_not_set(self):
        """Should not raise when GITHUB_OUTPUT is absent (local run)."""
        env = {k: v for k, v in os.environ.items() if k != "GITHUB_OUTPUT"}
        with patch.dict(os.environ, env, clear=True):
            # Must not raise
            evo_cycle.write_github_outputs(cycle_id=1, branch_name="evo/cycle-0001")

    def test_branch_name_matches_expected_pattern(self):
        """Branch name written to output should match evo/cycle-NNNN."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".env", delete=False) as fh:
            output_path = fh.name
        try:
            with patch.dict(os.environ, {"GITHUB_OUTPUT": output_path}):
                evo_cycle.write_github_outputs(cycle_id=42, branch_name="evo/cycle-0042")
            content = Path(output_path).read_text(encoding="utf-8")
        finally:
            os.unlink(output_path)

        self.assertIn("branch_name=evo/cycle-0042", content)


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

class TestWriteInsightsReport(unittest.TestCase):
    def _make_health(self):
        return {
            "python_version": "3.12.0",
            "source_file_count": 50,
            "test_file_count": 20,
            "core_module_count": 15,
            "core_modules": ["api_server", "evolution", "kernel"],
            "evolution_cycles_recorded": 3,
        }

    def _make_engine_result(self, status="ok"):
        if status == "ok":
            return {
                "status": "ok",
                "cycle": {
                    "pairs": [],
                    "dataset_size": 0,
                    "model_fitness": {},
                    "recommendations": [],
                    "adapter_id": None,
                },
                "summary": {},
            }
        return {"status": "skipped", "reason": "ImportError: missing dep"}

    def test_report_file_created(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.object(evo_cycle, "REPO_ROOT", Path(td)):
                report_path = evo_cycle.write_insights_report(
                    cycle_id=1,
                    health=self._make_health(),
                    engine_result=self._make_engine_result(),
                    copilot_insights="1. Improve test coverage.",
                )
                self.assertTrue(report_path.exists())
        self.assertEqual(report_path.name, "cycle_0001.md")

    def test_report_contains_scope_and_limitations(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.object(evo_cycle, "REPO_ROOT", Path(td)):
                report_path = evo_cycle.write_insights_report(
                    cycle_id=2,
                    health=self._make_health(),
                    engine_result=self._make_engine_result(),
                    copilot_insights="No suggestions.",
                )
            content = report_path.read_text(encoding="utf-8")
        self.assertIn("Scope", content)
        self.assertIn("Limitations", content)
        self.assertIn("Sources", content)

    def test_report_contains_copilot_insights(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.object(evo_cycle, "REPO_ROOT", Path(td)):
                report_path = evo_cycle.write_insights_report(
                    cycle_id=3,
                    health=self._make_health(),
                    engine_result=self._make_engine_result(),
                    copilot_insights="Top suggestion: write more tests.",
                )
            content = report_path.read_text(encoding="utf-8")
        self.assertIn("Top suggestion: write more tests.", content)

    def test_report_contains_system_health(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.object(evo_cycle, "REPO_ROOT", Path(td)):
                report_path = evo_cycle.write_insights_report(
                    cycle_id=4,
                    health=self._make_health(),
                    engine_result=self._make_engine_result(),
                    copilot_insights="OK.",
                )
            content = report_path.read_text(encoding="utf-8")
        self.assertIn("3.12.0", content)
        self.assertIn("50", content)  # source_file_count

    def test_report_skipped_engine_section(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.object(evo_cycle, "REPO_ROOT", Path(td)):
                report_path = evo_cycle.write_insights_report(
                    cycle_id=5,
                    health=self._make_health(),
                    engine_result=self._make_engine_result(status="skipped"),
                    copilot_insights="N/A.",
                )
            content = report_path.read_text(encoding="utf-8")
        self.assertIn("skipped", content.lower())

    def test_old_reports_pruned(self):
        with tempfile.TemporaryDirectory() as td:
            reports_dir = Path(td) / "data" / "evolution_reports"
            reports_dir.mkdir(parents=True)
            # Pre-populate with 5 old reports
            for i in range(1, 6):
                (reports_dir / f"cycle_{i:04d}.md").write_text("old", encoding="utf-8")

            with patch.object(evo_cycle, "REPO_ROOT", Path(td)):
                with patch.object(evo_cycle, "MEMORY_MAX_CYCLES", 3):
                    evo_cycle.write_insights_report(
                        cycle_id=6,
                        health=self._make_health(),
                        engine_result=self._make_engine_result(),
                        copilot_insights=".",
                    )

            remaining = sorted(reports_dir.glob("cycle_*.md"))
        # After pruning, only 3 should remain (keep=3)
        self.assertEqual(len(remaining), 3)


# ---------------------------------------------------------------------------
# Build health summary (smoke test — avoids heavy imports)
# ---------------------------------------------------------------------------

class TestBuildHealthSummary(unittest.TestCase):
    def test_returns_expected_keys(self):
        health = evo_cycle.build_health_summary()
        self.assertIn("repo_root", health)
        self.assertIn("python_version", health)
        self.assertIn("source_file_count", health)
        self.assertIn("test_file_count", health)
        self.assertIn("core_module_count", health)
        self.assertIn("evolution_cycles_recorded", health)

    def test_source_file_count_positive(self):
        health = evo_cycle.build_health_summary()
        self.assertGreater(health["source_file_count"], 0)

    def test_core_modules_is_list(self):
        health = evo_cycle.build_health_summary()
        self.assertIsInstance(health.get("core_modules", []), list)


if __name__ == "__main__":
    unittest.main()
