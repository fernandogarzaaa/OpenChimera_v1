"""Tests for core.session_memory — WorkingMemory, UserPreferences, SessionMemory."""
from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from core.session_memory import SessionMemory, UserPreferences, WorkingMemory


# ---------------------------------------------------------------------------
# WorkingMemory
# ---------------------------------------------------------------------------

class TestWorkingMemory(unittest.TestCase):
    def setUp(self):
        self.wm = WorkingMemory()

    def test_set_and_get(self):
        self.wm.set("key", "value")
        self.assertEqual(self.wm.get("key"), "value")

    def test_get_missing_returns_default(self):
        self.assertIsNone(self.wm.get("nonexistent"))

    def test_get_missing_custom_default(self):
        self.assertEqual(self.wm.get("x", 42), 42)

    def test_set_overwrites_existing(self):
        self.wm.set("k", "v1")
        self.wm.set("k", "v2")
        self.assertEqual(self.wm.get("k"), "v2")

    def test_delete_existing_returns_true(self):
        self.wm.set("del", "me")
        self.assertTrue(self.wm.delete("del"))
        self.assertIsNone(self.wm.get("del"))

    def test_delete_nonexistent_returns_false(self):
        self.assertFalse(self.wm.delete("ghost"))

    def test_clear_removes_all(self):
        self.wm.set("a", 1)
        self.wm.set("b", 2)
        self.wm.clear()
        self.assertEqual(len(self.wm), 0)

    def test_snapshot_returns_copy(self):
        self.wm.set("x", 10)
        snap = self.wm.snapshot()
        snap["injected"] = True
        self.assertNotIn("injected", self.wm.snapshot())

    def test_len_reflects_item_count(self):
        self.assertEqual(len(self.wm), 0)
        self.wm.set("a", 1)
        self.wm.set("b", 2)
        self.assertEqual(len(self.wm), 2)

    def test_contains(self):
        self.wm.set("exists", True)
        self.assertIn("exists", self.wm)
        self.assertNotIn("missing", self.wm)

    def test_stores_complex_values(self):
        data = {"nested": [1, 2, 3], "flag": True}
        self.wm.set("complex", data)
        self.assertEqual(self.wm.get("complex"), data)

    def test_key_is_coerced_to_str(self):
        self.wm.set(42, "numeric-key")
        self.assertEqual(self.wm.get("42"), "numeric-key")


# ---------------------------------------------------------------------------
# UserPreferences
# ---------------------------------------------------------------------------

class TestUserPreferences(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.prefs_path = self.root / "prefs.json"
        self.prefs = UserPreferences(self.prefs_path)

    def tearDown(self):
        self._td.cleanup()

    def test_set_and_get(self):
        self.prefs.set("theme", "dark")
        self.assertEqual(self.prefs.get("theme"), "dark")

    def test_get_missing_returns_none(self):
        self.assertIsNone(self.prefs.get("nonexistent"))

    def test_get_missing_custom_default(self):
        self.assertEqual(self.prefs.get("x", "fallback"), "fallback")

    def test_set_persists_to_disk(self):
        self.prefs.set("lang", "en")
        self.assertTrue(self.prefs_path.exists())
        raw = json.loads(self.prefs_path.read_text())
        self.assertEqual(raw["lang"], "en")

    def test_reload_reads_from_disk(self):
        self.prefs.set("key1", "val1")
        # Create a fresh instance pointing at the same file
        prefs2 = UserPreferences(self.prefs_path)
        self.assertEqual(prefs2.get("key1"), "val1")

    def test_delete_existing_returns_true(self):
        self.prefs.set("to-del", "yes")
        self.assertTrue(self.prefs.delete("to-del"))
        self.assertIsNone(self.prefs.get("to-del"))

    def test_delete_nonexistent_returns_false(self):
        self.assertFalse(self.prefs.delete("ghost"))

    def test_clear_empties_prefs(self):
        self.prefs.set("a", 1)
        self.prefs.set("b", 2)
        self.prefs.clear()
        self.assertEqual(self.prefs.snapshot(), {})

    def test_clear_persists_empty_file(self):
        self.prefs.set("a", 1)
        self.prefs.clear()
        raw = json.loads(self.prefs_path.read_text())
        self.assertEqual(raw, {})

    def test_snapshot_returns_copy(self):
        self.prefs.set("x", 10)
        snap = self.prefs.snapshot()
        snap["injected"] = True
        self.assertNotIn("injected", self.prefs.snapshot())

    def test_missing_file_returns_empty_on_load(self):
        prefs = UserPreferences(self.root / "nonexistent.json")
        self.assertEqual(prefs.snapshot(), {})

    def test_corrupt_file_returns_empty(self):
        self.prefs_path.write_text("not-json{{{{", encoding="utf-8")
        prefs = UserPreferences(self.prefs_path)
        self.assertEqual(prefs.snapshot(), {})

    def test_creates_parent_directory(self):
        nested_path = self.root / "deep" / "nested" / "prefs.json"
        prefs = UserPreferences(nested_path)
        prefs.set("k", "v")
        self.assertTrue(nested_path.exists())


# ---------------------------------------------------------------------------
# SessionMemory — construction
# ---------------------------------------------------------------------------

class TestSessionMemoryConstruction(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_creates_with_valid_session_id(self):
        mem = SessionMemory("qs-abc", store_root=self.root)
        self.assertEqual(mem.session_id, "qs-abc")

    def test_strips_whitespace_from_session_id(self):
        mem = SessionMemory("  qs-abc  ", store_root=self.root)
        self.assertEqual(mem.session_id, "qs-abc")

    def test_empty_session_id_raises_value_error(self):
        with self.assertRaises(ValueError):
            SessionMemory("", store_root=self.root)

    def test_whitespace_only_session_id_raises_value_error(self):
        with self.assertRaises(ValueError):
            SessionMemory("   ", store_root=self.root)

    def test_has_working_memory(self):
        mem = SessionMemory("s1", store_root=self.root)
        self.assertIsInstance(mem.working, WorkingMemory)

    def test_has_user_prefs(self):
        mem = SessionMemory("s1", store_root=self.root)
        self.assertIsInstance(mem.user_prefs, UserPreferences)

    def test_turns_initially_empty(self):
        mem = SessionMemory("s1", store_root=self.root)
        self.assertEqual(mem.get_turns(), [])

    def test_snapshots_initially_empty(self):
        mem = SessionMemory("s1", store_root=self.root)
        self.assertEqual(mem.list_snapshots(), [])

    def test_tool_events_initially_empty(self):
        mem = SessionMemory("s1", store_root=self.root)
        self.assertEqual(mem.list_tool_events(), [])


# ---------------------------------------------------------------------------
# SessionMemory — turns (episodic)
# ---------------------------------------------------------------------------

class TestSessionMemoryTurns(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.mem = SessionMemory("t-session", store_root=self.root)

    def tearDown(self):
        self._td.cleanup()

    def test_append_turn_returns_dict(self):
        turn = self.mem.append_turn("user", "hello")
        self.assertIsInstance(turn, dict)

    def test_append_turn_has_role_content_ts(self):
        turn = self.mem.append_turn("user", "hello")
        self.assertEqual(turn["role"], "user")
        self.assertEqual(turn["content"], "hello")
        self.assertIn("ts", turn)

    def test_get_turns_returns_all(self):
        self.mem.append_turn("user", "a")
        self.mem.append_turn("assistant", "b")
        turns = self.mem.get_turns()
        self.assertEqual(len(turns), 2)

    def test_get_turns_with_limit(self):
        for i in range(10):
            self.mem.append_turn("user", str(i))
        turns = self.mem.get_turns(limit=3)
        self.assertEqual(len(turns), 3)
        self.assertEqual(turns[-1]["content"], "9")

    def test_get_turns_limit_zero_returns_all(self):
        for i in range(5):
            self.mem.append_turn("user", str(i))
        turns = self.mem.get_turns(limit=0)
        self.assertEqual(len(turns), 5)

    def test_get_turns_returns_copy(self):
        self.mem.append_turn("user", "x")
        turns = self.mem.get_turns()
        turns.append({"role": "injected"})
        self.assertEqual(len(self.mem.get_turns()), 1)

    def test_clear_turns_empties_history(self):
        self.mem.append_turn("user", "x")
        self.mem.clear_turns()
        self.assertEqual(self.mem.get_turns(), [])


# ---------------------------------------------------------------------------
# SessionMemory — task snapshots
# ---------------------------------------------------------------------------

class TestSessionMemorySnapshots(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.mem = SessionMemory("snap-session", store_root=self.root)

    def tearDown(self):
        self._td.cleanup()

    def test_save_snapshot_returns_dict(self):
        snap = self.mem.save_snapshot({"query_type": "code"})
        self.assertIsInstance(snap, dict)

    def test_save_snapshot_has_recorded_at(self):
        snap = self.mem.save_snapshot({"x": 1})
        self.assertIn("recorded_at", snap)

    def test_save_snapshot_preserves_data(self):
        snap = self.mem.save_snapshot({"key": "value"})
        self.assertEqual(snap["key"], "value")

    def test_latest_snapshot_returns_most_recent(self):
        self.mem.save_snapshot({"n": 1})
        self.mem.save_snapshot({"n": 2})
        latest = self.mem.latest_snapshot()
        self.assertEqual(latest["n"], 2)

    def test_latest_snapshot_returns_none_when_empty(self):
        self.assertIsNone(self.mem.latest_snapshot())

    def test_list_snapshots_returns_recent(self):
        for i in range(5):
            self.mem.save_snapshot({"i": i})
        snaps = self.mem.list_snapshots(limit=3)
        self.assertEqual(len(snaps), 3)
        self.assertEqual(snaps[-1]["i"], 4)

    def test_list_snapshots_returns_copy(self):
        self.mem.save_snapshot({"x": 1})
        snaps = self.mem.list_snapshots()
        snaps.append({"injected": True})
        self.assertEqual(len(self.mem.list_snapshots()), 1)


# ---------------------------------------------------------------------------
# SessionMemory — tool events
# ---------------------------------------------------------------------------

class TestSessionMemoryToolEvents(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.mem = SessionMemory("tool-session", store_root=self.root)

    def tearDown(self):
        self._td.cleanup()

    def test_record_tool_event_returns_dict(self):
        event = self.mem.record_tool_event({"tool_id": "echo", "status": "ok"})
        self.assertIsInstance(event, dict)

    def test_record_tool_event_has_recorded_at(self):
        event = self.mem.record_tool_event({"tool_id": "x"})
        self.assertIn("recorded_at", event)

    def test_record_tool_event_preserves_data(self):
        event = self.mem.record_tool_event({"tool_id": "echo", "result": 42})
        self.assertEqual(event["tool_id"], "echo")
        self.assertEqual(event["result"], 42)

    def test_list_tool_events_returns_recent(self):
        for i in range(10):
            self.mem.record_tool_event({"seq": i})
        events = self.mem.list_tool_events(limit=3)
        self.assertEqual(len(events), 3)
        self.assertEqual(events[-1]["seq"], 9)

    def test_list_tool_events_returns_copy(self):
        self.mem.record_tool_event({"x": 1})
        events = self.mem.list_tool_events()
        events.append({"injected": True})
        self.assertEqual(len(self.mem.list_tool_events()), 1)


# ---------------------------------------------------------------------------
# SessionMemory — persistence (save / load)
# ---------------------------------------------------------------------------

class TestSessionMemoryPersistence(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def _make_mem(self, session_id="persist-session"):
        return SessionMemory(session_id, store_root=self.root)

    def test_save_creates_file(self):
        mem = self._make_mem()
        mem.append_turn("user", "hello")
        path = mem.save()
        self.assertTrue(path.exists())

    def test_save_returns_path(self):
        mem = self._make_mem()
        path = mem.save()
        self.assertIsInstance(path, Path)

    def test_save_file_contains_valid_json(self):
        mem = self._make_mem()
        mem.append_turn("user", "test")
        path = mem.save()
        data = json.loads(path.read_text())
        self.assertIsInstance(data, dict)

    def test_save_contains_session_id(self):
        mem = self._make_mem("my-session")
        mem.save()
        path = self.root / "my-session.json"
        data = json.loads(path.read_text())
        self.assertEqual(data["session_id"], "my-session")

    def test_load_round_trip_turns(self):
        mem = self._make_mem()
        mem.append_turn("user", "hello")
        mem.append_turn("assistant", "hi there")
        mem.save()

        mem2 = SessionMemory.load("persist-session", store_root=self.root)
        turns = mem2.get_turns()
        self.assertEqual(len(turns), 2)
        self.assertEqual(turns[0]["content"], "hello")
        self.assertEqual(turns[1]["content"], "hi there")

    def test_load_round_trip_snapshots(self):
        mem = self._make_mem()
        mem.save_snapshot({"query_type": "code"})
        mem.save()

        mem2 = SessionMemory.load("persist-session", store_root=self.root)
        self.assertEqual(len(mem2.list_snapshots()), 1)
        self.assertEqual(mem2.list_snapshots()[0]["query_type"], "code")

    def test_load_round_trip_tool_events(self):
        mem = self._make_mem()
        mem.record_tool_event({"tool_id": "echo", "status": "ok"})
        mem.save()

        mem2 = SessionMemory.load("persist-session", store_root=self.root)
        events = mem2.list_tool_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["tool_id"], "echo")

    def test_load_nonexistent_raises_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            SessionMemory.load("nonexistent", store_root=self.root)

    def test_load_corrupt_json_raises_value_error(self):
        corrupt_path = self.root / "bad.json"
        corrupt_path.write_text("{{not-json", encoding="utf-8")
        with self.assertRaises(ValueError):
            SessionMemory.load("bad", store_root=self.root)

    def test_load_non_object_json_raises_value_error(self):
        path = self.root / "arr.json"
        path.write_text("[1, 2, 3]", encoding="utf-8")
        with self.assertRaises(ValueError):
            SessionMemory.load("arr", store_root=self.root)

    def test_load_wrong_version_raises_value_error(self):
        mem = self._make_mem()
        mem.save()
        path = self.root / "persist-session.json"
        data = json.loads(path.read_text())
        data["version"] = 999
        path.write_text(json.dumps(data))
        with self.assertRaises(ValueError):
            SessionMemory.load("persist-session", store_root=self.root)

    def test_exists_true_after_save(self):
        mem = self._make_mem("exists-check")
        self.assertFalse(SessionMemory.exists("exists-check", store_root=self.root))
        mem.save()
        self.assertTrue(SessionMemory.exists("exists-check", store_root=self.root))

    def test_exists_false_for_unknown(self):
        self.assertFalse(SessionMemory.exists("unknown", store_root=self.root))

    def test_save_creates_store_root_if_missing(self):
        deep_root = self.root / "deep" / "nested"
        mem = SessionMemory("s", store_root=deep_root)
        mem.save()
        self.assertTrue(deep_root.exists())


# ---------------------------------------------------------------------------
# SessionMemory — show
# ---------------------------------------------------------------------------

class TestSessionMemoryShow(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.mem = SessionMemory("show-session", store_root=self.root)

    def tearDown(self):
        self._td.cleanup()

    def test_show_returns_dict(self):
        self.assertIsInstance(self.mem.show(), dict)

    def test_show_has_session_id(self):
        self.assertEqual(self.mem.show()["session_id"], "show-session")

    def test_show_has_working(self):
        self.assertIn("working", self.mem.show())

    def test_show_has_user_prefs(self):
        self.assertIn("user_prefs", self.mem.show())

    def test_show_has_turns(self):
        self.assertIn("turns", self.mem.show())

    def test_show_has_task_snapshots(self):
        self.assertIn("task_snapshots", self.mem.show())

    def test_show_has_tool_events(self):
        self.assertIn("tool_events", self.mem.show())

    def test_show_turns_count_correct(self):
        self.mem.append_turn("user", "a")
        self.mem.append_turn("assistant", "b")
        self.assertEqual(self.mem.show()["turns"]["count"], 2)

    def test_show_snapshots_count_correct(self):
        self.mem.save_snapshot({"x": 1})
        self.assertEqual(self.mem.show()["task_snapshots"]["count"], 1)

    def test_show_tool_events_count_correct(self):
        self.mem.record_tool_event({"id": "x"})
        self.assertEqual(self.mem.show()["tool_events"]["count"], 1)

    def test_show_created_at_present(self):
        self.assertIn("created_at", self.mem.show())


# ---------------------------------------------------------------------------
# SessionMemory — clear
# ---------------------------------------------------------------------------

class TestSessionMemoryClear(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        self.mem = SessionMemory("clear-session", store_root=self.root)

    def tearDown(self):
        self._td.cleanup()

    def test_clear_empties_turns(self):
        self.mem.append_turn("user", "x")
        self.mem.clear()
        self.assertEqual(self.mem.get_turns(), [])

    def test_clear_empties_snapshots(self):
        self.mem.save_snapshot({"x": 1})
        self.mem.clear()
        self.assertEqual(self.mem.list_snapshots(), [])

    def test_clear_empties_tool_events(self):
        self.mem.record_tool_event({"id": "x"})
        self.mem.clear()
        self.assertEqual(self.mem.list_tool_events(), [])

    def test_clear_empties_working_memory(self):
        self.mem.working.set("ctx", "value")
        self.mem.clear()
        self.assertIsNone(self.mem.working.get("ctx"))

    def test_clear_removes_snapshot_file(self):
        self.mem.append_turn("user", "x")
        self.mem.save()
        self.assertTrue(SessionMemory.exists("clear-session", store_root=self.root))
        self.mem.clear()
        self.assertFalse(SessionMemory.exists("clear-session", store_root=self.root))

    def test_clear_does_not_raise_if_no_file(self):
        # No file saved yet — clear should not raise
        self.mem.clear()

    def test_clear_does_not_touch_user_prefs(self):
        self.mem.user_prefs.set("pref", "keep-me")
        self.mem.clear()
        self.assertEqual(self.mem.user_prefs.get("pref"), "keep-me")


# ---------------------------------------------------------------------------
# QueryEngine — resume_session and clear_memory
# ---------------------------------------------------------------------------

class TestQueryEngineResumeAndClearMemory(unittest.TestCase):
    """Test the resume_session and clear_memory additions to QueryEngine."""

    def _make_engine(self, sessions=None):
        from unittest.mock import MagicMock
        from core.capabilities import CapabilityRegistry
        from core.model_roles import ModelRoleManager
        from core.model_registry import ModelRegistry
        from core.query_engine import QueryEngine

        db = MagicMock()
        db.initialize.return_value = None
        db.list_query_sessions.return_value = list(sessions or [])
        db.get_query_session.return_value = None
        db.upsert_query_session.return_value = None
        db.append_tool_event.return_value = None
        db.list_tool_events.return_value = []

        registry = MagicMock()
        registry.list_kind.return_value = []
        roles = MagicMock()
        roles.status.return_value = {"roles": {}}
        roles.select_model_for_query_type.return_value = {"model": "phi", "role": "general"}

        completion = MagicMock(return_value={
            "choices": [{"message": {"content": "resumed-answer"}}],
        })

        engine = QueryEngine(
            capability_registry=registry,
            model_roles=roles,
            tool_registry=None,
            completion_callback=completion,
            database=db,
        )
        return engine, db, completion

    def test_resume_session_raises_on_empty_id(self):
        engine, _, _ = self._make_engine()
        with self.assertRaises(ValueError):
            engine.resume_session("", "hello")

    def test_resume_session_raises_on_unknown_session(self):
        engine, db, _ = self._make_engine()
        db.get_query_session.return_value = None
        with self.assertRaises(ValueError):
            engine.resume_session("no-such-session", "hello")

    def test_resume_session_runs_query_for_known_session(self):
        engine, db, completion = self._make_engine()
        db.get_query_session.return_value = {
            "session_id": "qs-known",
            "created_at": 1,
            "updated_at": 2,
            "title": "Known session",
            "permission_scope": "user",
            "turns": [],
            "task_snapshots": [],
        }
        result = engine.resume_session("qs-known", "follow-up question")
        self.assertEqual(result["session_id"], "qs-known")
        completion.assert_called_once()

    def test_resume_session_inherits_session_context(self):
        engine, db, completion = self._make_engine()
        prior_turns = [
            {"role": "user", "content": "first question", "recorded_at": 1},
            {"role": "assistant", "content": "first answer", "recorded_at": 2},
        ]
        db.get_query_session.return_value = {
            "session_id": "qs-ctx",
            "created_at": 1,
            "updated_at": 2,
            "title": "Context session",
            "permission_scope": "user",
            "turns": prior_turns,
            "task_snapshots": [],
        }
        engine.resume_session("qs-ctx", "follow-up")
        call_kwargs = completion.call_args.kwargs
        messages = call_kwargs["messages"]
        contents = [m["content"] for m in messages]
        # Prior turns should appear in hydrated messages
        self.assertTrue(any("first question" in c for c in contents))

    def test_clear_memory_returns_dict(self):
        engine, _, _ = self._make_engine()
        result = engine.clear_memory()
        self.assertIsInstance(result, dict)

    def test_clear_memory_has_scope_key(self):
        engine, _, _ = self._make_engine()
        result = engine.clear_memory()
        self.assertIn("scope", result)

    def test_clear_memory_all_scope(self):
        engine, _, _ = self._make_engine()
        result = engine.clear_memory(scope=None)
        self.assertEqual(result["scope"], "all")

    def test_clear_memory_sessions_scope(self):
        engine, _, _ = self._make_engine()
        result = engine.clear_memory(scope="sessions")
        self.assertEqual(result["scope"], "sessions")

    def test_clear_memory_has_memory_key(self):
        engine, _, _ = self._make_engine()
        result = engine.clear_memory()
        self.assertIn("memory", result)


# ---------------------------------------------------------------------------
# Phase 4 upgrades — turn/event trimming and zlib compression
# ---------------------------------------------------------------------------

class TestSessionMemoryTurnTrimming(unittest.TestCase):
    """Verify turns are trimmed when exceeding _MAX_TURNS."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sm = SessionMemory(session_id="trim-test", store_root=Path(self.tmp))

    def test_append_turn_trims_when_over_limit(self):
        import core.session_memory as sm_mod
        original_max = sm_mod._MAX_TURNS
        try:
            sm_mod._MAX_TURNS = 20
            for i in range(25):
                self.sm.append_turn("user", f"msg-{i}")
            turns = self.sm.get_turns()
            self.assertLessEqual(len(turns), 25)
            self.assertGreater(len(turns), 0)
        finally:
            sm_mod._MAX_TURNS = original_max

    def test_record_tool_event_trims_when_over_limit(self):
        import core.session_memory as sm_mod
        original_max = sm_mod._MAX_TOOL_EVENTS
        try:
            sm_mod._MAX_TOOL_EVENTS = 15
            for i in range(20):
                self.sm.record_tool_event({"tool": f"tool-{i}", "i": i})
            events = self.sm.list_tool_events()
            self.assertLessEqual(len(events), 20)
            self.assertGreater(len(events), 0)
        finally:
            sm_mod._MAX_TOOL_EVENTS = original_max


class TestSessionMemoryCompression(unittest.TestCase):
    """Verify save/load with zlib compression round-trips correctly."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.sm = SessionMemory(session_id="compress-test", store_root=Path(self.tmp))

    def test_save_load_small_payload_uses_json(self):
        self.sm.append_turn("user", "hello")
        self.sm.save()
        json_path = Path(self.tmp) / "compress-test.json"
        self.assertTrue(json_path.exists())
        loaded = SessionMemory.load("compress-test", store_root=Path(self.tmp))
        self.assertEqual(len(loaded.get_turns()), 1)

    def test_save_load_large_payload_uses_compressed(self):
        import core.session_memory as sm_mod
        original_threshold = sm_mod._COMPRESS_THRESHOLD_BYTES
        try:
            sm_mod._COMPRESS_THRESHOLD_BYTES = 50  # force compression
            self.sm.append_turn("user", "x" * 200)
            self.sm.save()
            compressed_path = Path(self.tmp) / "compress-test.json.z"
            self.assertTrue(compressed_path.exists())
            loaded = SessionMemory.load("compress-test", store_root=Path(self.tmp))
            turns = loaded.get_turns()
            self.assertEqual(len(turns), 1)
            self.assertIn("x" * 200, turns[0]["content"])
        finally:
            sm_mod._COMPRESS_THRESHOLD_BYTES = original_threshold

    def test_exists_finds_compressed_file(self):
        import core.session_memory as sm_mod
        original_threshold = sm_mod._COMPRESS_THRESHOLD_BYTES
        try:
            sm_mod._COMPRESS_THRESHOLD_BYTES = 50
            self.sm.append_turn("user", "y" * 200)
            self.sm.save()
            self.assertTrue(SessionMemory.exists("compress-test", store_root=Path(self.tmp)))
        finally:
            sm_mod._COMPRESS_THRESHOLD_BYTES = original_threshold


if __name__ == "__main__":
    unittest.main()
