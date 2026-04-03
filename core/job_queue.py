from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from core.bus import EventBus
from core.config import ROOT
from core.database import DatabaseManager


class PersistentJobQueue:
    def __init__(
        self,
        bus: EventBus,
        executor: Callable[[dict[str, Any]], dict[str, Any]],
        store_path: Path | None = None,
        database: DatabaseManager | None = None,
        database_path: Path | None = None,
    ):
        self.bus = bus
        self.executor = executor
        self.store_path = store_path or (ROOT / "data" / "job_queue.json")
        self.database = database or DatabaseManager(db_path=database_path or (self.store_path.parent / "openchimera.db"))
        self.database.initialize()
        self._lock = threading.RLock()
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._running:
                return self.status()
            self._running = True
            self._thread = threading.Thread(target=self._run_loop, daemon=True, name="OpenChimera-JobQueue")
            self._thread.start()
        self.bus.publish_nowait("system/job-queue", {"status": "online"})
        return self.status()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            self._running = False
            thread = self._thread
        if thread is not None:
            thread.join(timeout=5)
        with self._lock:
            self._thread = None
        self.bus.publish_nowait("system/job-queue", {"status": "offline"})
        return self.status()

    def enqueue(
        self,
        job_type: str,
        payload: dict[str, Any],
        max_attempts: int = 3,
        *,
        job_class: str | None = None,
        label: str | None = None,
    ) -> dict[str, Any]:
        record = {
            "job_id": f"job-{uuid.uuid4().hex[:12]}",
            "job_type": job_type,
            "job_class": str(job_class or job_type),
            "label": str(label or job_type),
            "payload": payload,
            "status": "queued",
            "attempt_count": 0,
            "max_attempts": max(1, int(max_attempts)),
            "created_at": time.time(),
            "updated_at": time.time(),
            "history": [],
        }
        with self._lock:
            self.database.upsert_job(record)
        self.bus.publish_nowait("system/job-queue/job", {"action": "enqueue", "job": record})
        return json.loads(json.dumps(record))

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self.database.get_job(job_id)
            if job is None:
                return {"status": "missing", "job_id": job_id}
            if job["status"] in {"completed", "failed", "cancelled"}:
                return {"status": job["status"], "job_id": job_id}
            job["status"] = "cancelled"
            job["updated_at"] = time.time()
            job.setdefault("history", []).append({"status": "cancelled", "at": time.time()})
            self.database.upsert_job(job)
            return {"status": "cancelled", "job_id": job_id}

    def replay(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self.database.get_job(job_id)
            if job is None:
                return {"status": "missing", "job_id": job_id}
            return self.enqueue(
                job_type=str(job.get("job_type", "autonomy")),
                payload=dict(job.get("payload", {})),
                max_attempts=int(job.get("max_attempts", 3)),
                job_class=str(job.get("job_class", job.get("job_type", "autonomy"))),
                label=str(job.get("label", job.get("job_type", "autonomy"))),
            )

    def get(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self.database.get_job(job_id)
            if job is None:
                return {"status": "missing", "job_id": job_id}
            return json.loads(json.dumps(job))

    def status(self, *, status_filter: str | None = None, job_type: str | None = None, limit: int | None = None) -> dict[str, Any]:
        with self._lock:
            jobs = [json.loads(json.dumps(job)) for job in self.database.list_jobs()]
            filtered = jobs
            if status_filter:
                filtered = [job for job in filtered if str(job.get("status", "")).strip() == status_filter]
            if job_type:
                filtered = [job for job in filtered if str(job.get("job_type", "")).strip() == job_type or str(job.get("job_class", "")).strip() == job_type]
            if limit is not None:
                filtered = filtered[: max(1, int(limit))]
            return {
                "running": self._running,
                "store_path": str(self.store_path),
                "database_path": str(self.database.db_path),
                "jobs": filtered,
                "counts": {
                    "total": len(filtered),
                    "queued": sum(1 for job in filtered if job.get("status") == "queued"),
                    "running": sum(1 for job in filtered if job.get("status") == "running"),
                    "completed": sum(1 for job in filtered if job.get("status") == "completed"),
                    "failed": sum(1 for job in filtered if job.get("status") == "failed"),
                    "cancelled": sum(1 for job in filtered if job.get("status") == "cancelled"),
                },
                "filters": {"status": status_filter or "", "job_type": job_type or "", "limit": limit or 0},
                "total_counts": {
                    "total": len(jobs),
                    "queued": sum(1 for job in jobs if job.get("status") == "queued"),
                    "running": sum(1 for job in jobs if job.get("status") == "running"),
                    "completed": sum(1 for job in jobs if job.get("status") == "completed"),
                    "failed": sum(1 for job in jobs if job.get("status") == "failed"),
                    "cancelled": sum(1 for job in jobs if job.get("status") == "cancelled"),
                },
            }

    def _run_loop(self) -> None:
        while True:
            with self._lock:
                if not self._running:
                    return
                job = next((item for item in self.database.list_jobs() if item.get("status") == "queued"), None)
                if job is not None:
                    job["status"] = "running"
                    job["attempt_count"] = int(job.get("attempt_count", 0)) + 1
                    job["updated_at"] = time.time()
                    job.setdefault("history", []).append({"status": "running", "at": time.time(), "attempt": job["attempt_count"]})
                    self.database.upsert_job(job)
                    job_copy = json.loads(json.dumps(job))
                else:
                    job_copy = None

            if job_copy is None:
                time.sleep(0.5)
                continue

            result = self._execute_job(job_copy)
            self.bus.publish_nowait("system/job-queue/job", {"action": "result", "job_id": job_copy["job_id"], "result": result})

    def _execute_job(self, job: dict[str, Any]) -> dict[str, Any]:
        try:
            result = self.executor(job)
            success = str(result.get("status", "ok")) not in {"error", "failed"}
        except Exception as exc:
            result = {"status": "error", "error": str(exc)}
            success = False

        with self._lock:
            current = self.database.get_job(str(job.get("job_id")))
            if current is None:
                return result
            current["result"] = result
            current["updated_at"] = time.time()
            if success:
                current["status"] = "completed"
                current.setdefault("history", []).append({"status": "completed", "at": time.time()})
            elif int(current.get("attempt_count", 0)) < int(current.get("max_attempts", 3)):
                current["status"] = "queued"
                current.setdefault("history", []).append({"status": "retrying", "at": time.time()})
            else:
                current["status"] = "failed"
                current.setdefault("history", []).append({"status": "failed", "at": time.time()})
            self.database.upsert_job(current)
            return result
