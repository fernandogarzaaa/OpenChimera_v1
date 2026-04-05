from __future__ import annotations

import json
import shutil
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from core.config import ROOT


PACKAGE_ROOT = Path(__file__).resolve().parent
PACKAGED_MIGRATIONS_PATH = PACKAGE_ROOT / "migrations"
LEGACY_MIGRATIONS_PATH = ROOT / "data" / "migrations"


def _deep_copy(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _default_migrations_path() -> Path:
    if PACKAGED_MIGRATIONS_PATH.exists():
        return PACKAGED_MIGRATIONS_PATH
    return LEGACY_MIGRATIONS_PATH


class _InMemoryConnectionProxy:
    """Thin proxy around a persistent :memory: sqlite3 connection.

    Delegates all attribute access to the real connection but makes
    ``close()`` a no-op so that the ``finally: connection.close()``
    pattern in ``transaction()`` and ``initialize()`` doesn't destroy
    the in-memory database between calls.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # Proxy everything except close()
    def __getattr__(self, name: str):  # type: ignore[override]
        return getattr(self._conn, name)

    def close(self) -> None:  # intentional no-op
        pass


class DatabaseManager:
    def __init__(
        self,
        db_path: Path | None = None,
        *,
        migrations_path: Path | None = None,
        legacy_data_root: Path | None = None,
    ) -> None:
        raw = str(db_path) if db_path is not None else None
        self._in_memory = raw == ":memory:"
        self.db_path = Path(raw) if raw is not None else (ROOT / "data" / "openchimera.db")
        self.migrations_path = Path(migrations_path) if migrations_path is not None else _default_migrations_path()
        self.legacy_data_root = Path(legacy_data_root) if legacy_data_root is not None else self.db_path.parent
        self._initialized = False
        # For :memory: databases we must reuse a single connection because each
        # call to sqlite3.connect(":memory:") opens a fresh, empty database.
        self._memory_conn: sqlite3.Connection | None = None

    def initialize(self) -> None:
        if self._initialized:
            return
        if not self._in_memory:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.migrations_path.exists():
            raise FileNotFoundError(f"Database migrations path does not exist: {self.migrations_path}")
        connection = self._get_connection()
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    applied_at INTEGER NOT NULL
                )
                """
            )
            connection.commit()
            self._apply_migrations(connection)
            self._migrate_legacy_json(connection)
            self._initialized = True
        finally:
            # For file-backed DBs we close the setup connection; for :memory:
            # we must NOT close it — the persistent _memory_conn holds the data.
            if not self._in_memory:
                connection.close()

    def close(self) -> None:
        self._initialized = False
        if self._in_memory and self._memory_conn is not None:
            try:
                self._memory_conn.close()
            except Exception:
                pass
            self._memory_conn = None

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        self.initialize()
        connection = self._get_connection()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def backup(self, destination: Path) -> Path:
        self.initialize()
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        source = self._get_connection()
        backup_connection = sqlite3.connect(destination)
        try:
            source.backup(backup_connection)
        finally:
            source.close()
            backup_connection.close()
        return destination

    def restore(self, source: Path) -> Path:
        source = Path(source)
        if not source.exists():
            raise FileNotFoundError(f"Backup does not exist: {source}")
        self.close()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        source_connection = sqlite3.connect(source)
        restored_connection = sqlite3.connect(self.db_path)
        try:
            source_connection.backup(restored_connection)
        finally:
            source_connection.close()
            restored_connection.close()
        self.initialize()
        return self.db_path

    def status(self) -> dict[str, Any]:
        self.initialize()
        with self.transaction() as connection:
            migration_rows = connection.execute(
                "SELECT version, applied_at FROM schema_migrations ORDER BY version"
            ).fetchall()
        return {
            "database_path": str(self.db_path),
            "migrations_path": str(self.migrations_path),
            "wal_enabled": True,
            "applied_migrations": [dict(row) for row in migration_rows],
        }

    def list_jobs(self) -> list[dict[str, Any]]:
        with self.transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY created_at ASC, job_id ASC"
            ).fetchall()
        return [self._job_from_row(row) for row in rows]

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self.transaction() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return self._job_from_row(row) if row is not None else None

    def upsert_job(self, job: dict[str, Any]) -> dict[str, Any]:
        payload = _deep_copy(job)
        with self.transaction() as connection:
            self._upsert_job(connection, payload)
        return payload

    def list_subscriptions(self) -> list[dict[str, Any]]:
        with self.transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM subscriptions ORDER BY subscription_id ASC"
            ).fetchall()
        return [self._subscription_from_row(row) for row in rows]

    def upsert_subscription(self, subscription: dict[str, Any]) -> dict[str, Any]:
        payload = _deep_copy(subscription)
        with self.transaction() as connection:
            self._upsert_subscription(connection, payload)
        return payload

    def delete_subscription(self, subscription_id: str) -> bool:
        with self.transaction() as connection:
            cursor = connection.execute("DELETE FROM subscriptions WHERE subscription_id = ?", (subscription_id,))
        return bool(cursor.rowcount)

    def record_channel_delivery(self, record: dict[str, Any]) -> dict[str, Any]:
        payload = _deep_copy(record)
        with self.transaction() as connection:
            self._insert_channel_delivery(connection, payload)
        return payload

    def list_channel_deliveries(self) -> list[dict[str, Any]]:
        with self.transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM channels ORDER BY id ASC"
            ).fetchall()
        return [self._channel_delivery_from_row(row) for row in rows]

    def upsert_query_session(self, session: dict[str, Any]) -> dict[str, Any]:
        payload = _deep_copy(session)
        with self.transaction() as connection:
            self._upsert_query_session(connection, payload)
        return payload

    def list_query_sessions(self) -> list[dict[str, Any]]:
        with self.transaction() as connection:
            rows = connection.execute(
                "SELECT * FROM query_sessions ORDER BY updated_at DESC, session_id DESC"
            ).fetchall()
        return [self._query_session_from_row(row) for row in rows]

    def get_query_session(self, session_id: str) -> dict[str, Any] | None:
        with self.transaction() as connection:
            row = connection.execute(
                "SELECT * FROM query_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return self._query_session_from_row(row) if row is not None else None

    def append_tool_event(self, event: dict[str, Any]) -> dict[str, Any]:
        payload = _deep_copy(event)
        with self.transaction() as connection:
            self._insert_tool_event(connection, payload)
            connection.execute(
                "DELETE FROM query_tool_history WHERE id NOT IN (SELECT id FROM query_tool_history ORDER BY id DESC LIMIT 200)"
            )
        return payload

    def list_tool_events(self) -> list[dict[str, Any]]:
        with self.transaction() as connection:
            rows = connection.execute(
                "SELECT event_json FROM query_tool_history ORDER BY id ASC"
            ).fetchall()
        return [self._loads(row["event_json"], []) for row in rows]

    def load_credentials(self) -> dict[str, Any]:
        with self.transaction() as connection:
            rows = connection.execute(
                "SELECT provider_id, credential_key, credential_value FROM credentials ORDER BY provider_id ASC, credential_key ASC"
            ).fetchall()
        providers: dict[str, dict[str, str]] = {}
        for row in rows:
            provider_id = str(row["provider_id"])
            providers.setdefault(provider_id, {})[str(row["credential_key"])] = str(row["credential_value"])
        return {"providers": providers}

    def set_credential(self, provider_id: str, key: str, value: str) -> None:
        with self.transaction() as connection:
            self._set_credential(connection, provider_id, key, value)

    def delete_credential(self, provider_id: str, key: str) -> None:
        with self.transaction() as connection:
            connection.execute(
                "DELETE FROM credentials WHERE provider_id = ? AND credential_key = ?",
                (provider_id, key),
            )

    def _get_connection(self) -> sqlite3.Connection:
        if self._in_memory:
            if self._memory_conn is None:
                self._memory_conn = sqlite3.connect(
                    ":memory:", check_same_thread=False, timeout=30.0
                )
                self._memory_conn.row_factory = sqlite3.Row
            return _InMemoryConnectionProxy(self._memory_conn)
        connection = sqlite3.connect(self.db_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        return connection

    def _apply_migrations(self, connection: sqlite3.Connection) -> None:
        applied = {
            str(row["version"])
            for row in connection.execute("SELECT version FROM schema_migrations").fetchall()
        }
        migration_paths = sorted(self.migrations_path.glob("*.sql"))
        if not migration_paths:
            raise RuntimeError(f"No database migrations found in {self.migrations_path}")
        for path in migration_paths:
            version = path.stem
            if version in applied:
                continue
            connection.executescript(path.read_text(encoding="utf-8"))
            connection.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (version, int(time.time())),
            )
            applied.add(version)
        connection.commit()

    def _migrate_legacy_json(self, connection: sqlite3.Connection) -> None:
        self._migrate_jobs(connection)
        self._migrate_subscriptions(connection)
        self._migrate_query_sessions(connection)
        self._migrate_tool_history(connection)
        self._migrate_credentials(connection)
        connection.commit()

    def _migrate_jobs(self, connection: sqlite3.Connection) -> None:
        legacy_path = self.legacy_data_root / "job_queue.json"
        if not legacy_path.exists() or self._table_has_rows(connection, "jobs"):
            return
        payload = self._read_json(legacy_path, {"jobs": []})
        jobs = payload.get("jobs", []) if isinstance(payload, dict) else []
        for job in jobs:
            if isinstance(job, dict):
                self._upsert_job(connection, job)
        self._archive_legacy_file(legacy_path)

    def _migrate_subscriptions(self, connection: sqlite3.Connection) -> None:
        legacy_path = self.legacy_data_root / "subscriptions.json"
        if not legacy_path.exists() or self._table_has_rows(connection, "subscriptions"):
            return
        payload = self._read_json(legacy_path, {"subscriptions": [], "delivery_history": []})
        subscriptions = payload.get("subscriptions", []) if isinstance(payload, dict) else []
        for subscription in subscriptions:
            if isinstance(subscription, dict):
                self._upsert_subscription(connection, subscription)
        history = payload.get("delivery_history", []) if isinstance(payload, dict) else []
        for entry in history:
            if isinstance(entry, dict):
                self._insert_channel_delivery(connection, entry)
        last_delivery = payload.get("last_delivery") if isinstance(payload, dict) else None
        if isinstance(last_delivery, dict) and last_delivery:
            self._insert_channel_delivery(connection, last_delivery)
        self._archive_legacy_file(legacy_path)

    def _migrate_query_sessions(self, connection: sqlite3.Connection) -> None:
        legacy_path = self.legacy_data_root / "query_sessions.json"
        if not legacy_path.exists() or self._table_has_rows(connection, "query_sessions"):
            return
        payload = self._read_json(legacy_path, {"sessions": []})
        sessions = payload.get("sessions", []) if isinstance(payload, dict) else []
        for session in sessions:
            if isinstance(session, dict):
                self._upsert_query_session(connection, session)
        self._archive_legacy_file(legacy_path)

    def _migrate_tool_history(self, connection: sqlite3.Connection) -> None:
        legacy_path = self.legacy_data_root / "tool_execution_history.json"
        if not legacy_path.exists() or self._table_has_rows(connection, "query_tool_history"):
            return
        payload = self._read_json(legacy_path, {"events": []})
        events = payload.get("events", []) if isinstance(payload, dict) else []
        for event in events:
            if isinstance(event, dict):
                self._insert_tool_event(connection, event)
        self._archive_legacy_file(legacy_path)

    def _migrate_credentials(self, connection: sqlite3.Connection) -> None:
        legacy_path = self.legacy_data_root / "credentials.json"
        if not legacy_path.exists() or self._table_has_rows(connection, "credentials"):
            return
        payload = self._read_json(legacy_path, {"providers": {}})
        providers = payload.get("providers", {}) if isinstance(payload, dict) else {}
        for provider_id, values in providers.items():
            if not isinstance(values, dict):
                continue
            for key, value in values.items():
                if value not in {None, ""}:
                    self._set_credential(connection, str(provider_id), str(key), str(value))
        self._archive_legacy_file(legacy_path)

    def _upsert_job(self, connection: sqlite3.Connection, payload: dict[str, Any]) -> None:
        connection.execute(
            """
            INSERT INTO jobs (
                job_id,
                job_type,
                job_class,
                label,
                payload_json,
                status,
                attempt_count,
                max_attempts,
                created_at,
                updated_at,
                history_json,
                result_json,
                last_error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                job_type = excluded.job_type,
                job_class = excluded.job_class,
                label = excluded.label,
                payload_json = excluded.payload_json,
                status = excluded.status,
                attempt_count = excluded.attempt_count,
                max_attempts = excluded.max_attempts,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at,
                history_json = excluded.history_json,
                result_json = excluded.result_json,
                last_error = excluded.last_error
            """,
            (
                str(payload.get("job_id", "")),
                str(payload.get("job_type", "autonomy")),
                str(payload.get("job_class", payload.get("job_type", "autonomy"))),
                str(payload.get("label", payload.get("job_type", "autonomy"))),
                json.dumps(payload.get("payload", {})),
                str(payload.get("status", "queued")),
                int(payload.get("attempt_count", 0) or 0),
                int(payload.get("max_attempts", 3) or 3),
                float(payload.get("created_at", time.time()) or time.time()),
                float(payload.get("updated_at", time.time()) or time.time()),
                json.dumps(payload.get("history", [])),
                json.dumps(payload.get("result")) if payload.get("result") is not None else None,
                str(payload.get("result", {}).get("error", "")) if isinstance(payload.get("result"), dict) else None,
            ),
        )

    def _upsert_subscription(self, connection: sqlite3.Connection, payload: dict[str, Any]) -> None:
        config_payload = {
            key: value
            for key, value in payload.items()
            if key not in {"id", "channel", "enabled", "topics", "last_validation"}
        }
        connection.execute(
            """
            INSERT INTO subscriptions (
                subscription_id,
                channel,
                enabled,
                topics_json,
                config_json,
                last_validation_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(subscription_id) DO UPDATE SET
                channel = excluded.channel,
                enabled = excluded.enabled,
                topics_json = excluded.topics_json,
                config_json = excluded.config_json,
                last_validation_json = excluded.last_validation_json
            """,
            (
                str(payload.get("id", "")),
                str(payload.get("channel", "webhook")),
                1 if payload.get("enabled", True) else 0,
                json.dumps(payload.get("topics", [])),
                json.dumps(config_payload),
                json.dumps(payload.get("last_validation")) if payload.get("last_validation") is not None else None,
            ),
        )

    def _insert_channel_delivery(self, connection: sqlite3.Connection, payload: dict[str, Any]) -> None:
        connection.execute(
            """
            INSERT INTO channels (
                subscription_id,
                topic,
                dispatched_at,
                delivery_count,
                delivered_count,
                error_count,
                skipped_count,
                payload_preview_json,
                results_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(payload.get("subscription_id", "")) or None,
                str(payload.get("topic", "")),
                int(payload.get("dispatched_at", int(time.time())) or int(time.time())),
                int(payload.get("delivery_count", 0) or 0),
                int(payload.get("delivered_count", 0) or 0),
                int(payload.get("error_count", 0) or 0),
                int(payload.get("skipped_count", 0) or 0),
                json.dumps(payload.get("payload_preview", {})),
                json.dumps(payload.get("results", [])),
            ),
        )

    def _upsert_query_session(self, connection: sqlite3.Connection, payload: dict[str, Any]) -> None:
        connection.execute(
            """
            INSERT INTO query_sessions (
                session_id,
                created_at,
                updated_at,
                title,
                permission_scope,
                turns_json,
                task_snapshots_json,
                last_result_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                created_at = excluded.created_at,
                updated_at = excluded.updated_at,
                title = excluded.title,
                permission_scope = excluded.permission_scope,
                turns_json = excluded.turns_json,
                task_snapshots_json = excluded.task_snapshots_json,
                last_result_json = excluded.last_result_json
            """,
            (
                str(payload.get("session_id", "")),
                int(payload.get("created_at", int(time.time())) or int(time.time())),
                int(payload.get("updated_at", int(time.time())) or int(time.time())),
                str(payload.get("title", "OpenChimera session")),
                str(payload.get("permission_scope", "user")),
                json.dumps(payload.get("turns", [])),
                json.dumps(payload.get("task_snapshots", [])),
                json.dumps(payload.get("last_result")) if payload.get("last_result") is not None else None,
            ),
        )

    def _insert_tool_event(self, connection: sqlite3.Connection, payload: dict[str, Any]) -> None:
        connection.execute(
            """
            INSERT INTO query_tool_history (
                session_id,
                query_type,
                suggested_tools_json,
                recorded_at,
                event_json
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                str(payload.get("session_id", "")),
                str(payload.get("query_type", "general")),
                json.dumps(payload.get("suggested_tools", [])),
                int(payload.get("recorded_at", int(time.time())) or int(time.time())),
                json.dumps(payload),
            ),
        )

    def _set_credential(self, connection: sqlite3.Connection, provider_id: str, key: str, value: str) -> None:
        connection.execute(
            """
            INSERT INTO credentials (provider_id, credential_key, credential_value)
            VALUES (?, ?, ?)
            ON CONFLICT(provider_id, credential_key) DO UPDATE SET
                credential_value = excluded.credential_value
            """,
            (provider_id, key, value),
        )

    def _table_has_rows(self, connection: sqlite3.Connection, table_name: str) -> bool:
        row = connection.execute(f"SELECT 1 FROM {table_name} LIMIT 1").fetchone()
        return row is not None

    def _archive_legacy_file(self, path: Path) -> None:
        legacy_root = self.legacy_data_root / "migrations" / "legacy"
        legacy_root.mkdir(parents=True, exist_ok=True)
        archived_path = legacy_root / f"{path.name}.bak"
        if archived_path.exists():
            archived_path.unlink()
        shutil.move(str(path), str(archived_path))

    def _read_json(self, path: Path, default: dict[str, Any]) -> dict[str, Any]:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default
        return raw if isinstance(raw, dict) else default

    def _job_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        payload = self._loads(row["payload_json"], {})
        result = self._loads(row["result_json"], None) if row["result_json"] else None
        return {
            "job_id": row["job_id"],
            "job_type": row["job_type"],
            "job_class": row["job_class"],
            "label": row["label"],
            "payload": payload,
            "status": row["status"],
            "attempt_count": int(row["attempt_count"]),
            "max_attempts": int(row["max_attempts"]),
            "created_at": float(row["created_at"]),
            "updated_at": float(row["updated_at"]),
            "history": self._loads(row["history_json"], []),
            **({"result": result} if result is not None else {}),
        }

    def _subscription_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        payload = {
            "id": row["subscription_id"],
            "channel": row["channel"],
            "enabled": bool(row["enabled"]),
            "topics": self._loads(row["topics_json"], []),
        }
        payload.update(self._loads(row["config_json"], {}))
        if row["last_validation_json"]:
            payload["last_validation"] = self._loads(row["last_validation_json"], {})
        return payload

    def _channel_delivery_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        payload = {
            "topic": row["topic"],
            "dispatched_at": int(row["dispatched_at"]),
            "delivery_count": int(row["delivery_count"]),
            "delivered_count": int(row["delivered_count"]),
            "error_count": int(row["error_count"]),
            "skipped_count": int(row["skipped_count"]),
            "payload_preview": self._loads(row["payload_preview_json"], {}),
            "results": self._loads(row["results_json"], []),
        }
        if row["subscription_id"]:
            payload["subscription_id"] = row["subscription_id"]
        return payload

    def _query_session_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        payload = {
            "session_id": row["session_id"],
            "created_at": int(row["created_at"]),
            "updated_at": int(row["updated_at"]),
            "title": row["title"],
            "permission_scope": row["permission_scope"],
            "turns": self._loads(row["turns_json"], []),
            "task_snapshots": self._loads(row["task_snapshots_json"], []),
        }
        if row["last_result_json"]:
            payload["last_result"] = self._loads(row["last_result_json"], {})
        return payload

    def _loads(self, raw: str | None, default: Any) -> Any:
        if raw in {None, ""}:
            return default
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return default