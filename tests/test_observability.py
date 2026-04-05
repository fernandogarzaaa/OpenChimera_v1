from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.observability import ObservabilityStore


class ObservabilityStoreTests(unittest.TestCase):
    def test_snapshot_persists_across_restarts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "observability.db"

            first = ObservabilityStore(recent_limit=4, persist_path=db_path)
            try:
                first.record_http_request("GET", "/health", 200, 12.5, "req-1")
                first.record_completion("req-1", "openchimera-local", "general", False)
            finally:
                first.close()

            second = ObservabilityStore(recent_limit=4, persist_path=db_path)
            try:
                snapshot = second.snapshot()
            finally:
                second.close()

            self.assertEqual(snapshot["http"]["total_requests"], 1)
            self.assertEqual(snapshot["http"]["status_codes"], {"200": 1})
            self.assertEqual(snapshot["http"]["routes"], {"GET /health": 1})
            self.assertEqual(len(snapshot["http"]["recent_requests"]), 1)
            self.assertEqual(snapshot["llm"]["total_completions"], 1)
            self.assertEqual(snapshot["llm"]["fallback_completions"], 0)
            self.assertEqual(snapshot["llm"]["models"], {"openchimera-local": 1})
            self.assertEqual(snapshot["llm"]["query_types"], {"general": 1})
            self.assertEqual(len(snapshot["llm"]["recent_completions"]), 1)

    def test_recent_entries_honor_limit_after_reload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "observability.db"

            store = ObservabilityStore(recent_limit=2, persist_path=db_path)
            try:
                store.record_http_request("GET", "/health", 200, 10.0, "req-1")
                store.record_http_request("GET", "/v1/system/readiness", 200, 11.0, "req-2")
                store.record_http_request("GET", "/v1/system/metrics", 200, 12.0, "req-3")
            finally:
                store.close()

            reloaded = ObservabilityStore(recent_limit=2, persist_path=db_path)
            try:
                recent_requests = reloaded.snapshot()["http"]["recent_requests"]
            finally:
                reloaded.close()

            self.assertEqual([entry["request_id"] for entry in recent_requests], ["req-2", "req-3"])


class ObservabilityAutonomyJobTests(unittest.TestCase):
    """Tests for Phase 8 autonomy job tracking in ObservabilityStore."""

    def test_record_autonomy_job_increments_counters(self) -> None:
        store = ObservabilityStore(recent_limit=4)
        store.record_autonomy_job("sync_scouted_models", "ok")
        store.record_autonomy_job("discover_free_models", "error")
        store.record_autonomy_job("sync_scouted_models", "ok")
        snap = store.snapshot()
        jobs = snap["autonomy_jobs"]
        self.assertEqual(jobs["total_runs"], 3)
        self.assertEqual(jobs["success_count"], 2)
        self.assertEqual(jobs["jobs"]["sync_scouted_models"], 2)
        self.assertEqual(jobs["jobs"]["discover_free_models"], 1)
        self.assertEqual(len(jobs["recent_jobs"]), 3)

    def test_snapshot_includes_autonomy_jobs_key(self) -> None:
        store = ObservabilityStore()
        snap = store.snapshot()
        self.assertIn("autonomy_jobs", snap)
        self.assertEqual(snap["autonomy_jobs"]["total_runs"], 0)

    def test_subscribe_to_bus_captures_events(self) -> None:
        from unittest.mock import MagicMock
        store = ObservabilityStore()
        mock_bus = MagicMock()
        store.subscribe_to_bus(mock_bus)
        mock_bus.subscribe.assert_called_once_with(
            "system/autonomy/job", store._on_autonomy_job_event
        )

    def test_on_autonomy_job_event_records_job(self) -> None:
        store = ObservabilityStore()
        store._on_autonomy_job_event({
            "job": "run_self_audit",
            "result": {"status": "ok"},
        })
        snap = store.snapshot()
        self.assertEqual(snap["autonomy_jobs"]["total_runs"], 1)
        self.assertEqual(snap["autonomy_jobs"]["success_count"], 1)