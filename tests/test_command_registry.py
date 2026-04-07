"""Tests for core.command_registry — CommandEntry and CommandRegistry."""
from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock

from core.command_registry import CommandEntry, CommandRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bus() -> MagicMock:
    bus = MagicMock()
    bus.publish_nowait = MagicMock()
    return bus


def _make_entry(
    cmd_id: str = "test-cmd",
    name: str = "Test Command",
    description: str = "Does something",
    surfaces: list[str] | None = None,
    tags: list[str] | None = None,
    handler=None,
    requires_admin: bool = False,
) -> CommandEntry:
    return CommandEntry(
        id=cmd_id,
        name=name,
        description=description,
        surfaces=surfaces or [],
        tags=tags or [],
        handler=handler,
        requires_admin=requires_admin,
    )


def _make_registry(cmds: list[CommandEntry] | None = None, bus=None) -> CommandRegistry:
    registry = CommandRegistry(bus=bus)
    for cmd in cmds or []:
        registry.register(cmd)
    return registry


# ---------------------------------------------------------------------------
# CommandEntry.to_dict
# ---------------------------------------------------------------------------

class TestCommandEntryToDict(unittest.TestCase):
    def test_to_dict_has_required_keys(self):
        entry = _make_entry()
        d = entry.to_dict()
        for key in ("id", "name", "description", "entrypoint", "surfaces", "tags", "requires_admin", "executable", "kind"):
            self.assertIn(key, d)

    def test_kind_is_command(self):
        self.assertEqual(_make_entry().to_dict()["kind"], "command")

    def test_executable_false_when_no_handler(self):
        self.assertFalse(_make_entry().to_dict()["executable"])

    def test_executable_true_when_handler_set(self):
        entry = _make_entry(handler=lambda: "ok")
        self.assertTrue(entry.to_dict()["executable"])

    def test_surfaces_is_list(self):
        entry = _make_entry(surfaces=["cli", "api"])
        self.assertEqual(entry.to_dict()["surfaces"], ["cli", "api"])

    def test_tags_is_list(self):
        entry = _make_entry(tags=["alpha", "beta"])
        self.assertEqual(entry.to_dict()["tags"], ["alpha", "beta"])

    def test_requires_admin_default_false(self):
        self.assertFalse(_make_entry().to_dict()["requires_admin"])

    def test_requires_admin_true_when_set(self):
        entry = _make_entry(requires_admin=True)
        self.assertTrue(entry.to_dict()["requires_admin"])


# ---------------------------------------------------------------------------
# CommandRegistry — construction and seeding
# ---------------------------------------------------------------------------

class TestCommandRegistryConstruction(unittest.TestCase):
    def test_empty_registry_has_zero_commands(self):
        reg = CommandRegistry()
        self.assertEqual(len(reg.list_commands()), 0)

    def test_seed_from_capability_registry(self):
        cap_reg = MagicMock()
        cap_reg.list_kind.return_value = [
            {"id": "alpha", "name": "Alpha", "description": "Desc alpha", "surfaces": ["cli"], "tags": []},
            {"id": "beta", "name": "Beta", "description": "Desc beta", "surfaces": ["api"], "tags": []},
        ]
        reg = CommandRegistry(capability_registry=cap_reg)
        ids = {c["id"] for c in reg.list_commands()}
        self.assertIn("alpha", ids)
        self.assertIn("beta", ids)

    def test_seed_skips_entry_with_empty_id(self):
        cap_reg = MagicMock()
        cap_reg.list_kind.return_value = [
            {"id": "", "name": "Bad", "description": "", "surfaces": [], "tags": []},
        ]
        reg = CommandRegistry(capability_registry=cap_reg)
        self.assertEqual(len(reg.list_commands()), 0)


# ---------------------------------------------------------------------------
# CommandRegistry — register / unregister
# ---------------------------------------------------------------------------

class TestCommandRegistryRegisterUnregister(unittest.TestCase):
    def test_register_adds_command(self):
        reg = _make_registry()
        reg.register(_make_entry("cmd-a"))
        self.assertEqual(len(reg.list_commands()), 1)

    def test_register_replaces_existing_by_id(self):
        reg = _make_registry()
        reg.register(_make_entry("cmd-a", description="v1"))
        reg.register(_make_entry("cmd-a", description="v2"))
        cmds = reg.list_commands()
        self.assertEqual(len(cmds), 1)
        self.assertEqual(cmds[0]["description"], "v2")

    def test_register_empty_id_raises_value_error(self):
        reg = _make_registry()
        with self.assertRaises(ValueError):
            reg.register(_make_entry(cmd_id=""))

    def test_register_returns_the_entry(self):
        reg = _make_registry()
        entry = _make_entry("ret-test")
        returned = reg.register(entry)
        self.assertIs(returned, entry)

    def test_register_publishes_to_bus(self):
        bus = _make_bus()
        reg = CommandRegistry(bus=bus)
        reg.register(_make_entry("pub-test"))
        bus.publish_nowait.assert_called_once()
        topic, payload = bus.publish_nowait.call_args[0]
        self.assertEqual(topic, "system/commands")
        self.assertEqual(payload["action"], "register")

    def test_unregister_removes_command(self):
        reg = _make_registry([_make_entry("del-me")])
        removed = reg.unregister("del-me")
        self.assertTrue(removed)
        self.assertEqual(len(reg.list_commands()), 0)

    def test_unregister_unknown_returns_false(self):
        reg = _make_registry()
        self.assertFalse(reg.unregister("no-such"))

    def test_unregister_publishes_to_bus(self):
        bus = _make_bus()
        reg = CommandRegistry(bus=bus)
        reg.register(_make_entry("del-pub"))
        bus.reset_mock()
        reg.unregister("del-pub")
        bus.publish_nowait.assert_called_once()
        _, payload = bus.publish_nowait.call_args[0]
        self.assertEqual(payload["action"], "unregister")

    def test_unregister_unknown_does_not_publish(self):
        bus = _make_bus()
        reg = CommandRegistry(bus=bus)
        reg.unregister("nonexistent")
        bus.publish_nowait.assert_not_called()


# ---------------------------------------------------------------------------
# CommandRegistry — list_commands
# ---------------------------------------------------------------------------

class TestCommandRegistryListCommands(unittest.TestCase):
    def setUp(self):
        self.reg = CommandRegistry()
        self.reg.register(_make_entry("alpha", surfaces=["cli"], tags=["core"]))
        self.reg.register(_make_entry("beta", surfaces=["api"], tags=["extended"]))
        self.reg.register(_make_entry("gamma", surfaces=["cli", "api"], tags=["core"]))

    def test_list_all_commands(self):
        self.assertEqual(len(self.reg.list_commands()), 3)

    def test_list_commands_sorted_by_id(self):
        ids = [c["id"] for c in self.reg.list_commands()]
        self.assertEqual(ids, sorted(ids))

    def test_filter_by_surface_cli(self):
        cmds = self.reg.list_commands(surface="cli")
        ids = {c["id"] for c in cmds}
        self.assertIn("alpha", ids)
        self.assertIn("gamma", ids)
        self.assertNotIn("beta", ids)

    def test_filter_by_surface_api(self):
        cmds = self.reg.list_commands(surface="api")
        ids = {c["id"] for c in cmds}
        self.assertIn("beta", ids)
        self.assertIn("gamma", ids)
        self.assertNotIn("alpha", ids)

    def test_filter_by_tag(self):
        cmds = self.reg.list_commands(tag="core")
        ids = {c["id"] for c in cmds}
        self.assertIn("alpha", ids)
        self.assertIn("gamma", ids)
        self.assertNotIn("beta", ids)

    def test_filter_tag_is_case_insensitive(self):
        cmds = self.reg.list_commands(tag="CORE")
        self.assertEqual(len(cmds), 2)

    def test_filter_surface_and_tag_combined(self):
        cmds = self.reg.list_commands(surface="api", tag="core")
        ids = {c["id"] for c in cmds}
        self.assertEqual(ids, {"gamma"})

    def test_no_match_returns_empty_list(self):
        cmds = self.reg.list_commands(surface="nonexistent-surface")
        self.assertEqual(cmds, [])


# ---------------------------------------------------------------------------
# CommandRegistry — describe
# ---------------------------------------------------------------------------

class TestCommandRegistryDescribe(unittest.TestCase):
    def test_describe_returns_entry(self):
        reg = _make_registry([_make_entry("doc-test")])
        entry = reg.describe("doc-test")
        self.assertEqual(entry.id, "doc-test")

    def test_describe_unknown_raises_value_error(self):
        reg = _make_registry()
        with self.assertRaises(ValueError):
            reg.describe("ghost")


# ---------------------------------------------------------------------------
# CommandRegistry — find_by_keyword
# ---------------------------------------------------------------------------

class TestCommandRegistryFindByKeyword(unittest.TestCase):
    def setUp(self):
        self.reg = _make_registry([
            _make_entry("bootstrap-workspace", name="Bootstrap Workspace", description="Initialize state"),
            _make_entry("doctor-check", name="Doctor", description="Run diagnostics"),
            _make_entry("status-report", name="Status Report", description="Current runtime status"),
        ])

    def test_find_by_id_substring(self):
        results = self.reg.find_by_keyword("bootstrap")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], "bootstrap-workspace")

    def test_find_by_name_substring(self):
        results = self.reg.find_by_keyword("doctor")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], "doctor-check")

    def test_find_by_description_substring(self):
        results = self.reg.find_by_keyword("diagnostics")
        self.assertEqual(len(results), 1)

    def test_find_keyword_case_insensitive(self):
        results = self.reg.find_by_keyword("STATUS")
        self.assertGreater(len(results), 0)

    def test_find_no_match_returns_empty(self):
        results = self.reg.find_by_keyword("zzz-no-match-zzz")
        self.assertEqual(results, [])

    def test_find_results_sorted_by_id(self):
        results = self.reg.find_by_keyword("s")  # matches "status-report"
        ids = [r["id"] for r in results]
        self.assertEqual(ids, sorted(ids))


# ---------------------------------------------------------------------------
# CommandRegistry — execute
# ---------------------------------------------------------------------------

class TestCommandRegistryExecute(unittest.TestCase):
    def test_execute_calls_handler(self):
        called: list = []
        reg = _make_registry([_make_entry("run", handler=lambda: called.append(1) or "done")])
        result = reg.execute("run")
        self.assertEqual(result, "done")
        self.assertEqual(len(called), 1)

    def test_execute_passes_kwargs_to_handler(self):
        received: dict = {}

        def handler(x, y):
            received["x"] = x
            received["y"] = y
            return x + y

        reg = _make_registry([_make_entry("add", handler=handler)])
        result = reg.execute("add", x=3, y=4)
        self.assertEqual(result, 7)
        self.assertEqual(received, {"x": 3, "y": 4})

    def test_execute_unknown_command_raises_value_error(self):
        reg = _make_registry()
        with self.assertRaises(ValueError):
            reg.execute("nonexistent")

    def test_execute_without_handler_raises_not_implemented(self):
        reg = _make_registry([_make_entry("no-handler")])
        with self.assertRaises(NotImplementedError):
            reg.execute("no-handler")

    def test_execute_publishes_success_event(self):
        bus = _make_bus()
        reg = CommandRegistry(bus=bus)
        reg.register(_make_entry("go", handler=lambda: "ok"))
        bus.reset_mock()
        reg.execute("go")
        bus.publish_nowait.assert_called_once()
        _, payload = bus.publish_nowait.call_args[0]
        self.assertEqual(payload["action"], "execute")
        self.assertTrue(payload["success"])

    def test_execute_publishes_failure_event_and_reraises(self):
        bus = _make_bus()
        reg = CommandRegistry(bus=bus)

        def bad_handler():
            raise RuntimeError("boom")

        reg.register(_make_entry("fail", handler=bad_handler))
        bus.reset_mock()
        with self.assertRaises(RuntimeError):
            reg.execute("fail")
        bus.publish_nowait.assert_called_once()
        _, payload = bus.publish_nowait.call_args[0]
        self.assertFalse(payload["success"])

    def test_execute_result_includes_latency_ms(self):
        bus = _make_bus()
        reg = CommandRegistry(bus=bus)
        reg.register(_make_entry("timed", handler=lambda: None))
        bus.reset_mock()
        reg.execute("timed")
        _, payload = bus.publish_nowait.call_args[0]
        self.assertIn("latency_ms", payload)
        self.assertIsInstance(payload["latency_ms"], float)


class TestCommandRegistryAdminEnforcement(unittest.TestCase):
    """Phase 3 — requires_admin enforcement via is_admin keyword."""

    def test_admin_command_blocked_without_is_admin(self):
        reg = _make_registry([
            _make_entry("admin-only", handler=lambda: "secret", requires_admin=True),
        ])
        with self.assertRaises(PermissionError):
            reg.execute("admin-only")

    def test_admin_command_allowed_with_is_admin_true(self):
        reg = _make_registry([
            _make_entry("admin-only", handler=lambda: "secret", requires_admin=True),
        ])
        result = reg.execute("admin-only", is_admin=True)
        self.assertEqual(result, "secret")

    def test_non_admin_command_passes_without_is_admin(self):
        reg = _make_registry([
            _make_entry("public", handler=lambda: "open"),
        ])
        result = reg.execute("public")
        self.assertEqual(result, "open")

    def test_admin_blocked_publishes_bus_event(self):
        bus = _make_bus()
        reg = CommandRegistry(bus=bus)
        reg.register(_make_entry("locked", handler=lambda: "x", requires_admin=True))
        bus.reset_mock()
        with self.assertRaises(PermissionError):
            reg.execute("locked")
        self.assertEqual(bus.publish_nowait.call_count, 2)
        # First call should be security event
        security_call = bus.publish_nowait.call_args_list[0]
        self.assertEqual(security_call[0][0], "security.unauthorized_access")
        # Second call should be system/commands event
        cmd_call = bus.publish_nowait.call_args_list[1]
        self.assertEqual(cmd_call[0][1]["reason"], "admin_required")


# ---------------------------------------------------------------------------
# CommandRegistry — status
# ---------------------------------------------------------------------------

class TestCommandRegistryStatus(unittest.TestCase):
    def test_status_total_count(self):
        reg = _make_registry([_make_entry("a"), _make_entry("b")])
        self.assertEqual(reg.status()["counts"]["total"], 2)

    def test_status_executable_count(self):
        reg = _make_registry([
            _make_entry("x", handler=lambda: None),
            _make_entry("y"),
        ])
        self.assertEqual(reg.status()["counts"]["executable"], 1)

    def test_status_surfaces_aggregated(self):
        reg = _make_registry([
            _make_entry("a", surfaces=["cli"]),
            _make_entry("b", surfaces=["api"]),
        ])
        surfaces = reg.status()["surfaces"]
        self.assertIn("cli", surfaces)
        self.assertIn("api", surfaces)

    def test_status_surfaces_sorted(self):
        reg = _make_registry([
            _make_entry("z", surfaces=["web", "api", "cli"]),
        ])
        surfaces = reg.status()["surfaces"]
        self.assertEqual(surfaces, sorted(surfaces))

    def test_status_empty_registry(self):
        reg = CommandRegistry()
        status = reg.status()
        self.assertEqual(status["counts"]["total"], 0)
        self.assertEqual(status["counts"]["executable"], 0)
        self.assertEqual(status["surfaces"], [])


if __name__ == "__main__":
    unittest.main()
