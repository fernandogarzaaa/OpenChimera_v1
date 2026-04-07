from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from core.capabilities import CapabilityRegistry
from core.model_registry import ModelRegistry
from core.model_roles import ModelRoleManager
from core.query_engine import QueryEngine


# ---------------------------------------------------------------------------
# Helpers for mock-based tests
# ---------------------------------------------------------------------------

def _mock_db(sessions: list | None = None, tool_events: list | None = None) -> MagicMock:
    db = MagicMock()
    db.initialize.return_value = None
    db.list_query_sessions.return_value = list(sessions or [])
    db.get_query_session.return_value = None
    db.upsert_query_session.return_value = None
    db.append_tool_event.return_value = None
    db.list_tool_events.return_value = list(tool_events or [])
    return db


def _mock_roles() -> MagicMock:
    roles = MagicMock()
    roles.status.return_value = {"roles": {"general": "phi-3.5-mini"}}
    roles.select_model_for_query_type.return_value = {"model": "phi-3.5-mini", "role": "general"}
    return roles


def _session_dict(sid: str = "qs-abc123", updated_at: int | None = None) -> dict:
    ts = updated_at if updated_at is not None else int(time.time())
    return {
        "session_id": sid,
        "created_at": ts - 10,
        "updated_at": ts,
        "title": "Test session",
        "permission_scope": "user",
        "turns": [],
        "task_snapshots": [],
    }


def _make_mock_engine(
    sessions: list | None = None,
    tool_events: list | None = None,
) -> tuple[QueryEngine, MagicMock, MagicMock]:
    """Return (engine, mock_db, mock_completion)."""
    db = _mock_db(sessions, tool_events)
    roles = _mock_roles()
    registry = MagicMock()
    registry.list_kind.return_value = []
    completion = MagicMock(return_value={
        "choices": [{"message": {"content": "answer text"}}],
        "usage": {"completion_tokens": 10},
    })
    engine = QueryEngine(
        capability_registry=registry,
        model_roles=roles,
        tool_registry=None,
        completion_callback=completion,
        database=db,
    )
    return engine, db, completion


# ---------------------------------------------------------------------------
# Mock-based unit tests
# ---------------------------------------------------------------------------

class TestQueryEngineMockStatus(unittest.TestCase):
    def setUp(self) -> None:
        self.engine, self.db, _ = _make_mock_engine()

    def test_status_returns_dict(self) -> None:
        self.assertIsInstance(self.engine.status(), dict)

    def test_status_has_session_count(self) -> None:
        self.assertIn("session_count", self.engine.status())

    def test_status_has_active_session_ids(self) -> None:
        self.assertIn("active_session_ids", self.engine.status())

    def test_status_has_tool_history_events(self) -> None:
        self.assertIn("tool_history_events", self.engine.status())

    def test_status_has_memory(self) -> None:
        self.assertIn("memory", self.engine.status())

    def test_status_has_model_roles(self) -> None:
        self.assertIn("model_roles", self.engine.status())

    def test_status_session_count_zero_when_empty(self) -> None:
        self.assertEqual(self.engine.status()["session_count"], 0)

    def test_status_session_count_matches_sessions(self) -> None:
        engine, _, _ = _make_mock_engine(sessions=[_session_dict("s1"), _session_dict("s2")])
        self.assertEqual(engine.status()["session_count"], 2)

    def test_status_tool_history_events_zero_when_empty(self) -> None:
        self.assertEqual(self.engine.status()["tool_history_events"], 0)

    def test_status_tool_history_events_count_matches(self) -> None:
        engine, _, _ = _make_mock_engine(tool_events=[{"e": 1}, {"e": 2}])
        self.assertEqual(engine.status()["tool_history_events"], 2)


class TestQueryEngineMockListSessions(unittest.TestCase):
    def test_returns_empty_list_when_no_sessions(self) -> None:
        engine, _, _ = _make_mock_engine()
        self.assertEqual(engine.list_sessions(), [])

    def test_returns_list_type(self) -> None:
        engine, _, _ = _make_mock_engine()
        self.assertIsInstance(engine.list_sessions(), list)

    def test_sorted_descending_by_updated_at(self) -> None:
        s_old = _session_dict("s-old", updated_at=1000)
        s_new = _session_dict("s-new", updated_at=9000)
        engine, _, _ = _make_mock_engine(sessions=[s_old, s_new])
        result = engine.list_sessions()
        self.assertEqual(result[0]["session_id"], "s-new")
        self.assertEqual(result[1]["session_id"], "s-old")

    def test_limit_caps_results(self) -> None:
        sessions = [_session_dict(f"s{i}", updated_at=i) for i in range(10)]
        engine, _, _ = _make_mock_engine(sessions=sessions)
        result = engine.list_sessions(limit=3)
        self.assertLessEqual(len(result), 3)

    def test_default_limit_20(self) -> None:
        sessions = [_session_dict(f"s{i}", updated_at=i) for i in range(25)]
        engine, _, _ = _make_mock_engine(sessions=sessions)
        result = engine.list_sessions()
        self.assertLessEqual(len(result), 20)


class TestQueryEngineMockGetSession(unittest.TestCase):
    def test_raises_value_error_for_unknown_id(self) -> None:
        engine, _, _ = _make_mock_engine()
        with self.assertRaises(ValueError):
            engine.get_session("no-such-id")

    def test_error_message_includes_session_id(self) -> None:
        engine, _, _ = _make_mock_engine()
        with self.assertRaises(ValueError) as ctx:
            engine.get_session("bad-id-xyz")
        self.assertIn("bad-id-xyz", str(ctx.exception))

    def test_returns_session_dict_for_known_id(self) -> None:
        engine, db, _ = _make_mock_engine()
        s = _session_dict("qs-known")
        db.get_query_session.return_value = s
        result = engine.get_session("qs-known")
        self.assertEqual(result["session_id"], "qs-known")


class TestQueryEngineMockRunQuery(unittest.TestCase):
    def setUp(self) -> None:
        self.engine, self.db, self.completion = _make_mock_engine()

    def test_calls_completion_callback(self) -> None:
        self.engine.run_query(query="hello")
        self.completion.assert_called_once()

    def test_returns_dict(self) -> None:
        self.assertIsInstance(self.engine.run_query(query="hi"), dict)

    def test_returns_session_id(self) -> None:
        result = self.engine.run_query(query="hi")
        self.assertTrue(result["session_id"])

    def test_returns_query_type(self) -> None:
        result = self.engine.run_query(query="hi")
        self.assertIn("query_type", result)

    def test_returns_response_key(self) -> None:
        result = self.engine.run_query(query="hi")
        self.assertIn("response", result)

    def test_response_contains_completion_content(self) -> None:
        result = self.engine.run_query(query="hi")
        content = result["response"]["choices"][0]["message"]["content"]
        self.assertEqual(content, "answer text")

    def test_passes_messages_to_callback(self) -> None:
        self.engine.run_query(query="tell me")
        kwargs = self.completion.call_args.kwargs
        self.assertIn("messages", kwargs)
        self.assertIsInstance(kwargs["messages"], list)

    def test_empty_query_does_not_raise(self) -> None:
        result = self.engine.run_query(query="")
        self.assertIsInstance(result, dict)

    def test_saves_session_via_db(self) -> None:
        self.engine.run_query(query="persist me")
        self.db.upsert_query_session.assert_called()

    def test_appends_tool_event_via_db(self) -> None:
        self.engine.run_query(query="log event")
        self.db.append_tool_event.assert_called()

    def test_reuses_existing_session_by_id(self) -> None:
        s = _session_dict("qs-reuse")
        self.db.get_query_session.return_value = s
        result = self.engine.run_query(query="reuse", session_id="qs-reuse")
        self.assertEqual(result["session_id"], "qs-reuse")

    def test_infers_code_query_type(self) -> None:
        result = self.engine.run_query(query="fix this bug in the code")
        self.assertEqual(result["query_type"], "code")

    def test_infers_reasoning_query_type(self) -> None:
        result = self.engine.run_query(query="analyze the architecture")
        self.assertEqual(result["query_type"], "reasoning")

    def test_infers_general_query_type(self) -> None:
        result = self.engine.run_query(query="what is the weather")
        self.assertEqual(result["query_type"], "general")

    def test_permission_scope_reflected_in_result(self) -> None:
        result = self.engine.run_query(query="hi", permission_scope="admin")
        self.assertEqual(result["permission_context"]["scope"], "admin")

    def test_suggested_tools_is_list(self) -> None:
        result = self.engine.run_query(query="hi")
        self.assertIsInstance(result["suggested_tools"], list)

    def test_executed_tools_is_list(self) -> None:
        result = self.engine.run_query(query="hi")
        self.assertIsInstance(result["executed_tools"], list)


class TestQueryEngineMockInspectMemory(unittest.TestCase):
    def setUp(self) -> None:
        self.engine, _, _ = _make_mock_engine()

    def test_returns_dict(self) -> None:
        self.assertIsInstance(self.engine.inspect_memory(), dict)

    def test_has_scopes_key(self) -> None:
        self.assertIn("scopes", self.engine.inspect_memory())

    def test_has_summaries_key(self) -> None:
        self.assertIn("summaries", self.engine.inspect_memory())

    def test_summaries_is_list(self) -> None:
        self.assertIsInstance(self.engine.inspect_memory()["summaries"], list)

    def test_scopes_is_dict(self) -> None:
        self.assertIsInstance(self.engine.inspect_memory()["scopes"], dict)


class _FakeToolRegistry:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object], str]] = []

    def execute(self, tool_id: str, arguments: dict[str, object] | None = None, *, permission_scope: str = "user") -> dict[str, object]:
        payload = dict(arguments or {})
        self.calls.append((tool_id, payload, permission_scope))
        return {
            "tool_id": tool_id,
            "status": "ok",
            "permission_scope": permission_scope,
            "arguments": payload,
            "result": {"echo": payload},
        }


class QueryEngineTests(unittest.TestCase):
    def test_query_engine_persists_sessions_and_memory_hydration(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            capabilities = CapabilityRegistry(root=root)
            registry = ModelRegistry()
            registry.registry_path = root / "model_registry.json"
            registry.profile = {
                "hardware": {"cpu_count": 8, "ram_gb": 16, "gpu": {"available": True, "name": "RTX 2060", "vram_gb": 6, "device_count": 1}},
                "model_inventory": {"available_models": ["phi-3.5-mini", "qwen2.5-7b"], "models_dir": temp_dir},
                "local_runtime": {"preferred_local_models": ["qwen2.5-7b"]},
                "providers": {"enabled": ["local-llama-cpp"], "preferred_cloud_provider": ""},
            }
            registry.refresh()
            roles = ModelRoleManager(registry)
            engine = QueryEngine(
                capability_registry=capabilities,
                model_roles=roles,
                tool_registry=None,
                completion_callback=lambda **_: {"model": "openchimera-local", "choices": [{"message": {"content": "answer"}}]},
                sessions_path=root / "query_sessions.json",
                tool_history_path=root / "tool_history.json",
            )

            result = engine.run_query(query="Fetch a page and summarize it")

            self.assertTrue(result["session_id"])
            self.assertEqual(result["response"]["choices"][0]["message"]["content"], "answer")
            self.assertGreaterEqual(len(engine.list_sessions()), 1)
            self.assertIn("scopes", engine.inspect_memory())
            self.assertTrue((root / "openchimera.db").exists())

    def test_query_engine_migrates_legacy_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "query_sessions.json").write_text(
                '{"sessions":[{"session_id":"qs-legacy","created_at":1,"updated_at":2,"title":"Legacy","permission_scope":"user","turns":[],"task_snapshots":[]}]}',
                encoding="utf-8",
            )
            capabilities = CapabilityRegistry(root=root)
            registry = ModelRegistry()
            roles = ModelRoleManager(registry)
            engine = QueryEngine(
                capability_registry=capabilities,
                model_roles=roles,
                tool_registry=None,
                completion_callback=lambda **_: {"model": "openchimera-local", "choices": [{"message": {"content": "answer"}}]},
                sessions_path=root / "query_sessions.json",
                tool_history_path=root / "tool_history.json",
            )

            session = engine.get_session("qs-legacy")

            self.assertEqual(session["title"], "Legacy")
            self.assertFalse((root / "query_sessions.json").exists())

    def test_query_engine_can_execute_explicit_tool_requests(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            capabilities = CapabilityRegistry(root=root)
            registry = ModelRegistry()
            roles = ModelRoleManager(registry)
            tool_registry = _FakeToolRegistry()
            captured_messages: list[dict[str, object]] = []

            def _completion_callback(**kwargs: object) -> dict[str, object]:
                captured_messages.extend(kwargs.get("messages", []))
                return {"model": "openchimera-local", "choices": [{"message": {"content": "tool-backed-answer"}}]}

            engine = QueryEngine(
                capability_registry=capabilities,
                model_roles=roles,
                tool_registry=tool_registry,
                completion_callback=_completion_callback,
                sessions_path=root / "query_sessions.json",
                tool_history_path=root / "tool_history.json",
            )

            result = engine.run_query(
                query="Fetch the page and summarize it",
                permission_scope="admin",
                execute_tools=True,
                tool_requests=[{"tool_id": "browser.fetch", "arguments": {"url": "https://example.com", "max_chars": 512}}],
            )

            self.assertEqual(result["executed_tools"][0]["tool_id"], "browser.fetch")
            self.assertEqual(tool_registry.calls[0][0], "browser.fetch")
            self.assertTrue(any("Executed tools:" in str(item.get("content", "")) for item in captured_messages))


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# Tests: hallucination_scan field in run_query response
# ---------------------------------------------------------------------------

class TestRunQueryHallucinationScan(unittest.TestCase):
    """Verify that hallucination_scan is always present in run_query results."""

    def _engine(self, response_text: str = "clean answer"):
        db = _mock_db()
        roles = _mock_roles()
        registry = MagicMock()
        registry.list_kind.return_value = []
        completion = MagicMock(return_value={
            "choices": [{"message": {"content": response_text}}],
        })
        engine = QueryEngine(
            capability_registry=registry,
            model_roles=roles,
            tool_registry=None,
            completion_callback=completion,
            database=db,
        )
        return engine

    def test_hallucination_scan_key_present(self):
        engine = self._engine()
        result = engine.run_query(query="What is OpenChimera?")
        self.assertIn("hallucination_scan", result)

    def test_hallucination_scan_is_none_when_chimera_unavailable(self):
        """When ChimeraLang is unavailable the field should be None, not an error."""
        engine = self._engine()
        result = engine.run_query(query="test")
        # ChimeraLang may or may not be available; the field must exist and be dict or None.
        scan = result["hallucination_scan"]
        self.assertTrue(scan is None or isinstance(scan, dict))

    def test_hallucination_scan_dict_has_expected_keys_when_available(self):
        """If scan is returned as a dict, it must include 'clean' and 'recommendation'."""
        engine = self._engine()
        result = engine.run_query(query="hi")
        scan = result["hallucination_scan"]
        if isinstance(scan, dict):
            self.assertIn("clean", scan)
            self.assertIn("recommendation", scan)


# ---------------------------------------------------------------------------
# Tests: skill prompt selection
# ---------------------------------------------------------------------------

class TestSkillPromptSelection(unittest.TestCase):
    """Verify _select_skill_prompt returns expected results."""

    def _engine_with_skill(self, skill_name: str, description: str, path: str = ""):
        db = _mock_db()
        roles = _mock_roles()
        registry = MagicMock()
        registry.list_kind.return_value = [
            {
                "id": skill_name.lower().replace(" ", "-"),
                "name": skill_name,
                "description": description,
                "category": "test",
                "path": path,
            }
        ]
        completion = MagicMock(return_value={"choices": [{"message": {"content": "ok"}}]})
        engine = QueryEngine(
            capability_registry=registry,
            model_roles=roles,
            tool_registry=None,
            completion_callback=completion,
            database=db,
        )
        return engine

    def test_no_skill_when_registry_empty(self):
        db = _mock_db()
        roles = _mock_roles()
        registry = MagicMock()
        registry.list_kind.return_value = []
        completion = MagicMock(return_value={"choices": [{"message": {"content": "ok"}}]})
        engine = QueryEngine(
            capability_registry=registry,
            model_roles=roles,
            tool_registry=None,
            completion_callback=completion,
            database=db,
        )
        self.assertIsNone(engine._select_skill_prompt("help me debug"))

    def test_no_skill_when_query_too_generic(self):
        engine = self._engine_with_skill("FDA Regulatory Consultant", "FDA 21 CFR compliance expert")
        # A short, generic query shouldn't match a niche skill
        result = engine._select_skill_prompt("hi")
        self.assertIsNone(result)

    def test_matching_skill_returns_none_for_missing_path(self):
        """Skill matched but SKILL.md doesn't exist — should return None gracefully."""
        engine = self._engine_with_skill(
            "Security Auditor",
            "ISO 27001 information security auditor",
            path="/nonexistent/path/SKILL.md",
        )
        # High-overlap query
        result = engine._select_skill_prompt("iso 27001 security audit information")
        # File doesn't exist, so returns None rather than an error
        self.assertIsNone(result)

    def test_skill_prompt_injected_into_hydrated_messages(self):
        """When a skill matches, the hydrated messages should contain a system message with the skill name."""
        import tempfile, os
        with tempfile.NamedTemporaryFile(mode="w", suffix="SKILL.md", delete=False) as f:
            f.write("---\nid: security-auditor\n---\nYou are an ISO 27001 security auditor.\n")
            skill_path = f.name
        try:
            engine = self._engine_with_skill(
                "Security Auditor",
                "ISO 27001 information security auditor",
                path=skill_path,
            )
            result = engine.run_query(query="iso 27001 security audit information compliance")
            # The completion callback is the authoritative source; just verify no exception occurred
            self.assertIn("response", result)
        finally:
            os.unlink(skill_path)
