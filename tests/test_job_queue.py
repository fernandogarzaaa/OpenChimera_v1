from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path

from core.bus import EventBus
from core.job_queue import PersistentJobQueue


class JobQueueTests(unittest.TestCase):
    def test_queue_executes_autonomy_like_job(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            seen: list[dict[str, object]] = []

            def executor(job: dict[str, object]) -> dict[str, object]:
                seen.append(job)
                return {"status": "ok", "job": job.get("payload", {}).get("job")}

            queue = PersistentJobQueue(EventBus(), executor=executor, store_path=Path(temp_dir) / "job_queue.json")
            queue.start()
            job = queue.enqueue("autonomy", {"job": "sync_scouted_models"}, max_attempts=2)
            deadline = time.time() + 3
            while time.time() < deadline:
                status = queue.status()
                if status["counts"]["completed"] == 1:
                    break
                time.sleep(0.05)
            queue.stop()
            self.assertEqual(len(seen), 1)
            self.assertEqual(queue.status()["counts"]["completed"], 1)
            self.assertEqual(job["job_type"], "autonomy")
            self.assertTrue((Path(temp_dir) / "openchimera.db").exists())

    def test_queue_preserves_job_metadata_and_supports_filters(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            queue = PersistentJobQueue(EventBus(), executor=lambda job: {"status": "ok"}, store_path=Path(temp_dir) / "job_queue.json")
            queued = queue.enqueue(
                "autonomy.preview_repair",
                {"job": "preview_self_repair"},
                max_attempts=2,
                job_class="autonomy.preview_repair",
                label="Preview self repair",
            )

            fetched = queue.get(queued["job_id"])
            filtered = queue.status(job_type="autonomy.preview_repair")

            self.assertEqual(fetched["job_class"], "autonomy.preview_repair")
            self.assertEqual(fetched["label"], "Preview self repair")
            self.assertEqual(filtered["counts"]["total"], 1)
            self.assertEqual(filtered["jobs"][0]["job_id"], queued["job_id"])

    def test_queue_migrates_legacy_json_store(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            legacy_path = Path(temp_dir) / "job_queue.json"
            legacy_path.write_text(
                '{"jobs":[{"job_id":"job-legacy","job_type":"autonomy","job_class":"autonomy","label":"Legacy","payload":{"job":"sync_scouted_models"},"status":"queued","attempt_count":0,"max_attempts":2,"created_at":1.0,"updated_at":1.0,"history":[]}]}',
                encoding="utf-8",
            )
            queue = PersistentJobQueue(EventBus(), executor=lambda job: {"status": "ok"}, store_path=legacy_path)

            migrated = queue.get("job-legacy")

            self.assertEqual(migrated["job_id"], "job-legacy")
            self.assertFalse(legacy_path.exists())
            self.assertTrue((Path(temp_dir) / "migrations" / "legacy" / "job_queue.json.bak").exists())

    def test_stop_shuts_down_running_queue(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            queue = PersistentJobQueue(
                EventBus(),
                executor=lambda job: {"status": "ok"},
                store_path=Path(temp_dir) / "job_queue.json",
            )
            queue.start()
            self.assertTrue(queue.status()["running"])
            queue.stop()
            self.assertFalse(queue.status()["running"])

    def test_cancel_already_completed_job_returns_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            queue = PersistentJobQueue(EventBus(), executor=lambda job: {"status": "ok"}, store_path=Path(temp_dir) / "q.json")
            queue.start()
            job = queue.enqueue("autonomy", {"job": "sync"}, max_attempts=1)
            deadline = time.time() + 3
            while time.time() < deadline:
                if queue.status()["counts"]["completed"] >= 1:
                    break
                time.sleep(0.05)
            queue.stop()
            result = queue.cancel(job["job_id"])
            # Job is already completed — cancel returns current terminal status
            self.assertIn(result["status"], {"completed", "cancelled"})

    def test_cancel_missing_job_returns_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            queue = PersistentJobQueue(EventBus(), executor=lambda job: {"status": "ok"}, store_path=Path(temp_dir) / "q.json")
            result = queue.cancel("job-nonexistent-xyz")
            self.assertEqual(result["status"], "missing")

    def test_cancel_queued_job_marks_cancelled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            started = threading.Event()

            def slow_executor(job: dict) -> dict:
                started.set()
                time.sleep(5)
                return {"status": "ok"}

            queue = PersistentJobQueue(EventBus(), executor=slow_executor, store_path=Path(temp_dir) / "q.json")
            # Enqueue two jobs; the first will be running (blocking), second stays queued
            queue.enqueue("autonomy", {"job": "first"}, max_attempts=1)
            second = queue.enqueue("autonomy", {"job": "second"}, max_attempts=1)
            queue.start()
            started.wait(timeout=3)
            result = queue.cancel(second["job_id"])
            queue.stop()
            self.assertEqual(result["status"], "cancelled")

    def test_replay_creates_new_job(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            queue = PersistentJobQueue(EventBus(), executor=lambda job: {"status": "ok"}, store_path=Path(temp_dir) / "q.json")
            original = queue.enqueue("autonomy", {"job": "sync"}, max_attempts=1)
            replayed = queue.replay(original["job_id"])
            self.assertNotEqual(replayed["job_id"], original["job_id"])
            self.assertEqual(replayed["job_type"], "autonomy")

    def test_replay_missing_job_returns_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            queue = PersistentJobQueue(EventBus(), executor=lambda job: {"status": "ok"}, store_path=Path(temp_dir) / "q.json")
            result = queue.replay("job-nonexistent-xyz")
            self.assertEqual(result["status"], "missing")

    def test_status_with_limit_filter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            queue = PersistentJobQueue(EventBus(), executor=lambda job: {"status": "ok"}, store_path=Path(temp_dir) / "q.json")
            for i in range(5):
                queue.enqueue("autonomy", {"job": f"job_{i}"}, max_attempts=1)
            result = queue.status(limit=2)
            self.assertLessEqual(result["counts"]["total"], 2)

    def test_status_with_status_filter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            queue = PersistentJobQueue(EventBus(), executor=lambda job: {"status": "ok"}, store_path=Path(temp_dir) / "q.json")
            queue.enqueue("autonomy", {"job": "a"}, max_attempts=1)
            result = queue.status(status_filter="queued")
            self.assertEqual(result["counts"]["total"], 1)
            result_none = queue.status(status_filter="completed")
            self.assertEqual(result_none["counts"]["total"], 0)

    def test_job_retries_then_fails_after_max_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            attempts = [0]

            def failing_executor(job: dict) -> dict:
                attempts[0] += 1
                return {"status": "error", "error": "always fails"}

            queue = PersistentJobQueue(
                EventBus(),
                executor=failing_executor,
                store_path=Path(temp_dir) / "q.json",
            )
            queue.start()
            queue.enqueue("autonomy", {"job": "fail_always"}, max_attempts=2)
            deadline = time.time() + 5
            while time.time() < deadline:
                counts = queue.status()["counts"]
                if counts["failed"] >= 1:
                    break
                time.sleep(0.05)
            queue.stop()
            self.assertGreaterEqual(attempts[0], 2)
            self.assertEqual(queue.status()["counts"]["failed"], 1)

    def test_start_already_running_returns_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            queue = PersistentJobQueue(EventBus(), executor=lambda job: {"status": "ok"}, store_path=Path(temp_dir) / "q.json")
            queue.start()
            try:
                result = queue.start()
                self.assertIn("running", result)
            finally:
                queue.stop()


if __name__ == "__main__":
    unittest.main()