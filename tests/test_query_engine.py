from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.capabilities import CapabilityRegistry
from core.model_registry import ModelRegistry
from core.model_roles import ModelRoleManager
from core.query_engine import QueryEngine


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
