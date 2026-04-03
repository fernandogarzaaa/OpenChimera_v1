from __future__ import annotations

import tempfile
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


if __name__ == "__main__":
    unittest.main()