"""
SessionMemory
=============
Explicit, standalone session memory module for OpenChimera.

Provides four memory layers:

  WorkingMemory     — per-turn in-memory key-value store; cleared between
                      sessions.  Fast access to the current context.

  UserPreferences   — cross-session persistent user preferences backed by
                      a JSON file.  Survives process restarts.

  SessionMemory     — unified facade.  Holds turn history (episodic),
                      task snapshots (for resume), tool execution events,
                      and references to the two sub-stores above.
                      Can be saved to / loaded from a JSON snapshot file
                      so a session can be fully resumed from disk.

Usage::

    mem = SessionMemory(session_id="qs-abc", store_root=Path("data/sessions"))
    mem.set_working("ctx", {"model": "phi-3"})
    mem.append_turn("user", "What is 2+2?")
    mem.save_snapshot({"query_type": "math"})
    mem.save()                           # persist to disk

    # Resume later:
    mem2 = SessionMemory.load(session_id="qs-abc", store_root=Path("data/sessions"))
    print(mem2.show())
"""
from __future__ import annotations

import json
import logging
import time
import zlib
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# WorkingMemory — in-memory per-turn context store
# ---------------------------------------------------------------------------

class WorkingMemory:
    """Per-turn in-memory key-value store.

    Stores arbitrary key-value pairs for the duration of the current turn.
    The store is intentionally kept simple — no expiry, no max-size, and
    not persisted.
    """

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}

    def set(self, key: str, value: Any) -> None:
        """Set a working-memory key."""
        self._store[str(key)] = value

    def get(self, key: str, default: Any = None) -> Any:
        """Return a working-memory value, or *default* if not set."""
        return self._store.get(str(key), default)

    def delete(self, key: str) -> bool:
        """Remove a key.  Returns True if it existed."""
        return self._store.pop(str(key), None) is not None

    def clear(self) -> None:
        """Clear the entire working memory store."""
        self._store.clear()

    def snapshot(self) -> dict[str, Any]:
        """Return a shallow copy of the current working memory."""
        return dict(self._store)

    def __len__(self) -> int:
        return len(self._store)

    def __contains__(self, key: str) -> bool:
        return str(key) in self._store


# ---------------------------------------------------------------------------
# UserPreferences — persistent cross-session user preferences
# ---------------------------------------------------------------------------

class UserPreferences:
    """Cross-session persistent user preferences backed by a JSON file.

    Reads lazily on first access and writes back on every mutation.

    Parameters
    ----------
    path:
        Path to the JSON file that stores preferences.  Created
        automatically if it does not exist.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._prefs: dict[str, Any] | None = None  # lazy load

    # ------------------------------------------------------------------
    # Lazy load
    # ------------------------------------------------------------------

    def _load(self) -> dict[str, Any]:
        if self._prefs is not None:
            return self._prefs
        if self._path.exists():
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                self._prefs = raw if isinstance(raw, dict) else {}
            except (json.JSONDecodeError, OSError):
                self._prefs = {}
        else:
            self._prefs = {}
        return self._prefs

    def _persist(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._prefs or {}, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set(self, key: str, value: Any) -> None:
        """Set a user preference and persist it."""
        prefs = self._load()
        prefs[str(key)] = value
        self._persist()

    def get(self, key: str, default: Any = None) -> Any:
        """Return a user preference, or *default* if not set."""
        return self._load().get(str(key), default)

    def delete(self, key: str) -> bool:
        """Remove a preference.  Returns True if it existed."""
        prefs = self._load()
        existed = str(key) in prefs
        if existed:
            del prefs[str(key)]
            self._persist()
        return existed

    def clear(self) -> None:
        """Remove all user preferences and persist the empty store."""
        self._prefs = {}
        self._persist()

    def snapshot(self) -> dict[str, Any]:
        """Return a shallow copy of all user preferences."""
        return dict(self._load())


# ---------------------------------------------------------------------------
# SessionMemory — unified session memory facade
# ---------------------------------------------------------------------------

_SESSION_FILE_VERSION = 1

# Guard-rails for runaway sessions
_MAX_TURNS = 10_000
_MAX_TOOL_EVENTS = 5_000
_MAX_SNAPSHOTS = 500
_COMPRESS_THRESHOLD_BYTES = 512 * 1024  # 512 KB — use zlib above this


class SessionMemory:
    """Unified session memory facade.

    Stores four kinds of memory for a single session:

    * **Working memory** — per-turn key-value context (in-memory only).
    * **Turn history** — episodic list of ``{"role", "content", "ts"}`` dicts.
    * **Task snapshots** — arbitrary dicts that capture execution state for
      resume.
    * **Tool execution events** — structured records of tool calls made
      during this session.

    User preferences are shared across sessions and are accessed through the
    ``user_prefs`` attribute.

    Parameters
    ----------
    session_id:
        Unique session identifier.
    store_root:
        Directory where this session's JSON snapshot file is stored.
        The file is named ``{session_id}.json``.
    user_prefs_path:
        Path to the shared user preferences file.  Defaults to
        ``{store_root}/user_preferences.json``.
    """

    def __init__(
        self,
        session_id: str,
        store_root: Path | None = None,
        user_prefs_path: Path | None = None,
    ) -> None:
        if not session_id or not str(session_id).strip():
            raise ValueError("session_id must be non-empty")
        self.session_id = str(session_id).strip()
        self._store_root = store_root or Path("data") / "sessions"
        self._snapshot_path = self._store_root / f"{self.session_id}.json"
        _prefs_path = user_prefs_path or (self._store_root / "user_preferences.json")

        self.working = WorkingMemory()
        self.user_prefs = UserPreferences(_prefs_path)

        self._turns: list[dict[str, Any]] = []
        self._task_snapshots: list[dict[str, Any]] = []
        self._tool_events: list[dict[str, Any]] = []
        self._created_at: float = time.time()

    # ------------------------------------------------------------------
    # Turn history (episodic)
    # ------------------------------------------------------------------

    def append_turn(self, role: str, content: str) -> dict[str, Any]:
        """Append a turn to the episodic history.

        If the history exceeds *_MAX_TURNS*, the oldest 10 % is trimmed.
        Returns the appended turn dict.
        """
        turn = {"role": str(role), "content": str(content), "ts": time.time()}
        self._turns.append(turn)
        if len(self._turns) > _MAX_TURNS:
            trim = max(1, _MAX_TURNS // 10)
            self._turns = self._turns[trim:]
            _log.debug("[SessionMemory] Trimmed %d oldest turns", trim)
        return dict(turn)

    def get_turns(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Return turn history, newest-last.

        Parameters
        ----------
        limit:
            If given, return only the last *limit* turns.
        """
        if limit is None or limit <= 0:
            return list(self._turns)
        return list(self._turns[-limit:])

    def clear_turns(self) -> None:
        """Clear all recorded turns."""
        self._turns.clear()

    # ------------------------------------------------------------------
    # Task snapshots (for resume)
    # ------------------------------------------------------------------

    def save_snapshot(self, data: dict[str, Any]) -> dict[str, Any]:
        """Append a task snapshot.  Automatically stamps ``recorded_at``."""
        snapshot = {"recorded_at": time.time(), **dict(data)}
        self._task_snapshots.append(snapshot)
        return dict(snapshot)

    def latest_snapshot(self) -> dict[str, Any] | None:
        """Return the most recent task snapshot, or None."""
        return dict(self._task_snapshots[-1]) if self._task_snapshots else None

    def list_snapshots(self, limit: int = 10) -> list[dict[str, Any]]:
        """Return recent task snapshots, newest-last."""
        n = max(1, int(limit))
        return [dict(s) for s in self._task_snapshots[-n:]]

    # ------------------------------------------------------------------
    # Tool execution history
    # ------------------------------------------------------------------

    def record_tool_event(self, event: dict[str, Any]) -> dict[str, Any]:
        """Record a tool execution event."""
        stamped = {"recorded_at": time.time(), **dict(event)}
        self._tool_events.append(stamped)
        if len(self._tool_events) > _MAX_TOOL_EVENTS:
            trim = max(1, _MAX_TOOL_EVENTS // 10)
            self._tool_events = self._tool_events[trim:]
        return dict(stamped)

    def list_tool_events(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return recent tool events, newest-last."""
        n = max(1, int(limit))
        return [dict(e) for e in self._tool_events[-n:]]

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> Path:
        """Persist this session to ``{store_root}/{session_id}.json``.

        If the serialised payload exceeds *_COMPRESS_THRESHOLD_BYTES* the
        file is written as zlib-compressed JSON with a ``.json.z`` suffix.
        Returns the path the snapshot was written to.
        """
        self._store_root.mkdir(parents=True, exist_ok=True)
        payload = self._to_payload()
        raw = json.dumps(payload, indent=2, default=str).encode("utf-8")

        if len(raw) > _COMPRESS_THRESHOLD_BYTES:
            compressed_path = self._snapshot_path.with_suffix(".json.z")
            compressed_path.write_bytes(zlib.compress(raw, level=6))
            # Remove uncompressed copy if it exists
            if self._snapshot_path.exists():
                self._snapshot_path.unlink()
            _log.info(
                "[SessionMemory] Saved compressed snapshot (%d → %d bytes): %s",
                len(raw), compressed_path.stat().st_size, compressed_path,
            )
            return compressed_path

        self._snapshot_path.write_text(raw.decode("utf-8"), encoding="utf-8")
        # Remove compressed copy if it exists
        compressed_path = self._snapshot_path.with_suffix(".json.z")
        if compressed_path.exists():
            compressed_path.unlink()
        return self._snapshot_path

    def _to_payload(self) -> dict[str, Any]:
        return {
            "version": _SESSION_FILE_VERSION,
            "session_id": self.session_id,
            "created_at": self._created_at,
            "saved_at": time.time(),
            "turns": list(self._turns),
            "task_snapshots": list(self._task_snapshots),
            "tool_events": list(self._tool_events),
        }

    @classmethod
    def load(
        cls,
        session_id: str,
        store_root: Path | None = None,
        user_prefs_path: Path | None = None,
    ) -> "SessionMemory":
        """Load a previously saved session from disk.

        Supports both plain JSON (``.json``) and zlib-compressed
        (``.json.z``) snapshots.  Raises ``FileNotFoundError`` if neither
        exists for *session_id*.
        Raises ``ValueError`` if the file is corrupt or has an unknown version.
        """
        root = store_root or Path("data") / "sessions"
        path = root / f"{session_id}.json"
        compressed_path = root / f"{session_id}.json.z"

        if compressed_path.exists():
            try:
                raw = zlib.decompress(compressed_path.read_bytes())
                payload = json.loads(raw)
            except (zlib.error, json.JSONDecodeError) as exc:
                raise ValueError(f"Corrupt compressed session snapshot at {compressed_path}: {exc}") from exc
        elif path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Corrupt session snapshot at {path}: {exc}") from exc
        else:
            raise FileNotFoundError(
                f"No session snapshot found for {session_id!r} at {path}"
            )
        if not isinstance(payload, dict):
            raise ValueError(f"Session snapshot is not a JSON object: {path}")
        version = payload.get("version", 0)
        if version != _SESSION_FILE_VERSION:
            raise ValueError(
                f"Unsupported session snapshot version {version!r} at {path}"
            )
        obj = cls(
            session_id=str(payload.get("session_id", session_id)),
            store_root=root,
            user_prefs_path=user_prefs_path,
        )
        obj._created_at = float(payload.get("created_at", time.time()))
        obj._turns = list(payload.get("turns", []))
        obj._task_snapshots = list(payload.get("task_snapshots", []))
        obj._tool_events = list(payload.get("tool_events", []))
        return obj

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    def show(self) -> dict[str, Any]:
        """Return a complete snapshot of this session's memory state."""
        return {
            "session_id": self.session_id,
            "created_at": self._created_at,
            "working": self.working.snapshot(),
            "user_prefs": self.user_prefs.snapshot(),
            "turns": {
                "count": len(self._turns),
                "recent": self.get_turns(limit=5),
            },
            "task_snapshots": {
                "count": len(self._task_snapshots),
                "latest": self.latest_snapshot(),
            },
            "tool_events": {
                "count": len(self._tool_events),
                "recent": self.list_tool_events(limit=5),
            },
        }

    def clear(self) -> None:
        """Clear all in-memory state (working, turns, snapshots, events).

        Does NOT clear user preferences — those are cross-session.
        Removes the on-disk snapshot file if it exists.
        """
        self.working.clear()
        self._turns.clear()
        self._task_snapshots.clear()
        self._tool_events.clear()
        if self._snapshot_path.exists():
            self._snapshot_path.unlink()

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    @staticmethod
    def exists(session_id: str, store_root: Path | None = None) -> bool:
        """Return True if a snapshot exists for *session_id*."""
        root = store_root or Path("data") / "sessions"
        return (root / f"{session_id}.json").exists() or (root / f"{session_id}.json.z").exists()
