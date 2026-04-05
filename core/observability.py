from __future__ import annotations

import sqlite3
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any


class ObservabilityStore:
    def __init__(self, recent_limit: int = 64, persist_path: str | Path | None = None):
        self._lock = threading.RLock()
        self._recent_limit = max(1, int(recent_limit))
        self._persist_path = Path(persist_path).expanduser() if persist_path else None
        self._connection: sqlite3.Connection | None = None
        self._http_total_requests = 0
        self._http_status_counts: dict[str, int] = {}
        self._http_route_counts: dict[str, int] = {}
        self._http_total_duration_ms = 0.0
        self._llm_total_completions = 0
        self._llm_fallback_completions = 0
        self._llm_model_counts: dict[str, int] = {}
        self._llm_query_type_counts: dict[str, int] = {}
        self._recent_requests: deque[dict[str, Any]] = deque(maxlen=self._recent_limit)
        self._recent_completions: deque[dict[str, Any]] = deque(maxlen=self._recent_limit)
        self._job_total_runs = 0
        self._job_success_count = 0
        self._job_name_counts: dict[str, int] = {}
        self._recent_jobs: deque[dict[str, Any]] = deque(maxlen=self._recent_limit)
        if self._persist_path is not None:
            self._initialize_persistence()

    def _initialize_persistence(self) -> None:
        assert self._persist_path is not None
        self._persist_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(self._persist_path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA synchronous=NORMAL")
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS http_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL,
                method TEXT NOT NULL,
                path TEXT NOT NULL,
                status_code INTEGER NOT NULL,
                duration_ms REAL NOT NULL,
                recorded_at INTEGER NOT NULL
            )
            """
        )
        self._connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_http_requests_recorded_at ON http_requests(recorded_at DESC, id DESC)"
        )
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS llm_completions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL,
                model TEXT NOT NULL,
                query_type TEXT NOT NULL,
                fallback INTEGER NOT NULL,
                recorded_at INTEGER NOT NULL
            )
            """
        )
        self._connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_llm_completions_recorded_at ON llm_completions(recorded_at DESC, id DESC)"
        )
        self._connection.commit()
        self._load_persisted_state()

    def _load_persisted_state(self) -> None:
        if self._connection is None:
            return
        http_row = self._connection.execute(
            "SELECT COUNT(*) AS total, COALESCE(SUM(duration_ms), 0.0) AS total_duration_ms FROM http_requests"
        ).fetchone()
        if http_row is not None:
            self._http_total_requests = int(http_row["total"] or 0)
            self._http_total_duration_ms = float(http_row["total_duration_ms"] or 0.0)
        self._http_status_counts = {
            str(row["status_code"]): int(row["count"])
            for row in self._connection.execute(
                "SELECT status_code, COUNT(*) AS count FROM http_requests GROUP BY status_code"
            )
        }
        self._http_route_counts = {
            str(row["route_key"]): int(row["count"])
            for row in self._connection.execute(
                "SELECT method || ' ' || path AS route_key, COUNT(*) AS count FROM http_requests GROUP BY method, path"
            )
        }
        recent_http_rows = self._connection.execute(
            "SELECT request_id, method, path, status_code, duration_ms, recorded_at FROM http_requests ORDER BY id DESC LIMIT ?",
            (self._recent_limit,),
        ).fetchall()
        for row in reversed(recent_http_rows):
            self._recent_requests.append(
                {
                    "request_id": str(row["request_id"]),
                    "method": str(row["method"]),
                    "path": str(row["path"]),
                    "status_code": int(row["status_code"]),
                    "duration_ms": round(float(row["duration_ms"]), 2),
                    "recorded_at": int(row["recorded_at"]),
                }
            )

        llm_row = self._connection.execute(
            "SELECT COUNT(*) AS total, COALESCE(SUM(fallback), 0) AS fallback_total FROM llm_completions"
        ).fetchone()
        if llm_row is not None:
            self._llm_total_completions = int(llm_row["total"] or 0)
            self._llm_fallback_completions = int(llm_row["fallback_total"] or 0)
        self._llm_model_counts = {
            str(row["model"]): int(row["count"])
            for row in self._connection.execute(
                "SELECT model, COUNT(*) AS count FROM llm_completions GROUP BY model"
            )
        }
        self._llm_query_type_counts = {
            str(row["query_type"]): int(row["count"])
            for row in self._connection.execute(
                "SELECT query_type, COUNT(*) AS count FROM llm_completions GROUP BY query_type"
            )
        }
        recent_llm_rows = self._connection.execute(
            "SELECT request_id, model, query_type, fallback, recorded_at FROM llm_completions ORDER BY id DESC LIMIT ?",
            (self._recent_limit,),
        ).fetchall()
        for row in reversed(recent_llm_rows):
            self._recent_completions.append(
                {
                    "request_id": str(row["request_id"]),
                    "model": str(row["model"]),
                    "query_type": str(row["query_type"]),
                    "fallback": bool(row["fallback"]),
                    "recorded_at": int(row["recorded_at"]),
                }
            )

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    def __del__(self) -> None:
        self.close()

    def record_http_request(self, method: str, path: str, status_code: int, duration_ms: float, request_id: str) -> None:
        with self._lock:
            recorded_at = int(time.time())
            self._http_total_requests += 1
            status_key = str(status_code)
            route_key = f"{method.upper()} {path}"
            self._http_status_counts[status_key] = self._http_status_counts.get(status_key, 0) + 1
            self._http_route_counts[route_key] = self._http_route_counts.get(route_key, 0) + 1
            self._http_total_duration_ms += float(duration_ms)
            entry = {
                "request_id": request_id,
                "method": method.upper(),
                "path": path,
                "status_code": int(status_code),
                "duration_ms": round(float(duration_ms), 2),
                "recorded_at": recorded_at,
            }
            self._recent_requests.append(entry)
            if self._connection is not None:
                self._connection.execute(
                    "INSERT INTO http_requests(request_id, method, path, status_code, duration_ms, recorded_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (request_id, method.upper(), path, int(status_code), float(duration_ms), recorded_at),
                )
                self._connection.commit()

    def record_completion(self, request_id: str, model: str, query_type: str, fallback: bool) -> None:
        with self._lock:
            recorded_at = int(time.time())
            self._llm_total_completions += 1
            if fallback:
                self._llm_fallback_completions += 1
            self._llm_model_counts[model] = self._llm_model_counts.get(model, 0) + 1
            self._llm_query_type_counts[query_type] = self._llm_query_type_counts.get(query_type, 0) + 1
            entry = {
                "request_id": request_id,
                "model": model,
                "query_type": query_type,
                "fallback": bool(fallback),
                "recorded_at": recorded_at,
            }
            self._recent_completions.append(entry)
            if self._connection is not None:
                self._connection.execute(
                    "INSERT INTO llm_completions(request_id, model, query_type, fallback, recorded_at) VALUES (?, ?, ?, ?, ?)",
                    (request_id, model, query_type, 1 if fallback else 0, recorded_at),
                )
                self._connection.commit()

    def record_autonomy_job(self, job_name: str, status: str) -> None:
        """Record an autonomy job execution."""
        with self._lock:
            self._job_total_runs += 1
            if status == "ok":
                self._job_success_count += 1
            self._job_name_counts[job_name] = self._job_name_counts.get(job_name, 0) + 1
            self._recent_jobs.append({
                "job": job_name,
                "status": status,
                "recorded_at": int(time.time()),
            })

    def subscribe_to_bus(self, bus: Any) -> None:
        """Subscribe to event bus topics to auto-record observability data."""
        try:
            bus.subscribe("system/autonomy/job", self._on_autonomy_job_event)
        except Exception:
            pass

    def _on_autonomy_job_event(self, event: dict[str, Any]) -> None:
        job_name = str(event.get("job", "unknown"))
        result = event.get("result", {})
        status = str(result.get("status", "ok")) if isinstance(result, dict) else "ok"
        self.record_autonomy_job(job_name, status)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            average_duration_ms = 0.0
            if self._http_total_requests:
                average_duration_ms = self._http_total_duration_ms / self._http_total_requests
            return {
                "http": {
                    "total_requests": self._http_total_requests,
                    "status_codes": dict(sorted(self._http_status_counts.items())),
                    "routes": dict(sorted(self._http_route_counts.items())),
                    "average_duration_ms": round(average_duration_ms, 2),
                    "recent_requests": list(self._recent_requests),
                },
                "llm": {
                    "total_completions": self._llm_total_completions,
                    "fallback_completions": self._llm_fallback_completions,
                    "models": dict(sorted(self._llm_model_counts.items())),
                    "query_types": dict(sorted(self._llm_query_type_counts.items())),
                    "recent_completions": list(self._recent_completions),
                },
                "autonomy_jobs": {
                    "total_runs": self._job_total_runs,
                    "success_count": self._job_success_count,
                    "jobs": dict(sorted(self._job_name_counts.items())),
                    "recent_jobs": list(self._recent_jobs),
                },
            }