"""Tests for core.tool_runtime — RuntimeToolRegistry, ToolPermissionError,
ToolExecutionError, RuntimeToolSpec.

All tests are offline. No network, DB, or disk access.
"""
from __future__ import annotations
import unittest
from typing import Any
from unittest.mock import MagicMock

from pydantic import BaseModel

from core.tool_runtime import (
    RuntimeToolRegistry,
    RuntimeToolSpec,
    ToolExecutionError,
    ToolPermissionError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_capability_registry(tool_ids: list[str] | None = None):
    """Return a mock capability registry that lists the given tool IDs."""
    cap_reg = MagicMock()
    cap_reg.list_kind.return_value = [
        {"id": tid, "kind": "tool", "name": tid, "description": f"desc for {tid}", "category": "test"}
        for tid in (tool_ids or [])
    ]
    return cap_reg


def _make_bus():
    bus = MagicMock()
    bus.publish_nowait = MagicMock()
    return bus


def _make_spec(
    tool_id: str = "echo",
    executor=None,
    schema=None,
    requires_admin: bool = False,
    category: str = "test",
) -> RuntimeToolSpec:
    if executor is None:
        executor = lambda args: {"echoed": args}
    return RuntimeToolSpec(
        tool_id=tool_id,
        name=f"Tool:{tool_id}",
        description=f"Description for {tool_id}",
        schema=schema,
        executor=executor,
        requires_admin=requires_admin,
        category=category,
    )


def _make_registry(specs=None):
    cap_reg = _make_capability_registry([s.tool_id for s in (specs or [])])
    bus = _make_bus()
    return RuntimeToolRegistry(
        capability_registry=cap_reg,
        bus=bus,
        specs=specs,
    ), bus


# ---------------------------------------------------------------------------
# Tests: list_tools
# ---------------------------------------------------------------------------

class TestListTools(unittest.TestCase):
    def test_empty_registry_returns_empty_list(self):
        reg, _ = _make_registry()
        self.assertEqual(reg.list_tools(), [])

    def test_single_spec_appears_in_list(self):
        reg, _ = _make_registry([_make_spec("ping")])
        tools = reg.list_tools()
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["id"], "ping")

    def test_tool_has_expected_fields(self):
        reg, _ = _make_registry([_make_spec("alpha")])
        tool = reg.list_tools()[0]
        for key in ("id", "name", "description", "category", "requires_admin", "executable", "input_schema"):
            self.assertIn(key, tool)

    def test_executable_is_true(self):
        reg, _ = _make_registry([_make_spec("x")])
        tool = reg.list_tools()[0]
        self.assertTrue(tool["executable"])

    def test_requires_admin_reflected(self):
        reg, _ = _make_registry([_make_spec("admin-tool", requires_admin=True)])
        tool = reg.list_tools()[0]
        self.assertTrue(tool["requires_admin"])

    def test_multiple_tools_sorted_by_id(self):
        specs = [_make_spec("zzz"), _make_spec("aaa"), _make_spec("mmm")]
        reg, _ = _make_registry(specs)
        ids = [t["id"] for t in reg.list_tools()]
        self.assertEqual(ids, sorted(ids))


# ---------------------------------------------------------------------------
# Tests: get_tool
# ---------------------------------------------------------------------------

class TestGetTool(unittest.TestCase):
    def test_get_existing_tool(self):
        reg, _ = _make_registry([_make_spec("fetch")])
        tool = reg.get_tool("fetch")
        self.assertEqual(tool["id"], "fetch")

    def test_get_unknown_tool_raises_value_error(self):
        reg, _ = _make_registry()
        with self.assertRaises(ValueError):
            reg.get_tool("nonexistent")

    def test_get_tool_empty_id_raises_value_error(self):
        reg, _ = _make_registry([_make_spec("x")])
        with self.assertRaises(ValueError):
            reg.get_tool("")


# ---------------------------------------------------------------------------
# Tests: execute
# ---------------------------------------------------------------------------

class TestExecute(unittest.TestCase):
    def test_execute_returns_ok_envelope(self):
        reg, _ = _make_registry([_make_spec("echo", executor=lambda a: "pong")])
        result = reg.execute("echo", {})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["tool_id"], "echo")
        self.assertEqual(result["result"], "pong")

    def test_execute_unknown_tool_raises_value_error(self):
        reg, _ = _make_registry()
        with self.assertRaises(ValueError):
            reg.execute("phantom")

    def test_execute_admin_tool_without_admin_scope_raises_permission_error(self):
        reg, _ = _make_registry([_make_spec("secure", requires_admin=True)])
        with self.assertRaises(ToolPermissionError):
            reg.execute("secure", {}, permission_scope="user")

    def test_execute_admin_tool_with_admin_scope_succeeds(self):
        reg, _ = _make_registry([_make_spec("secure", requires_admin=True, executor=lambda a: "done")])
        result = reg.execute("secure", {}, permission_scope="admin")
        self.assertEqual(result["status"], "ok")

    def test_execute_publishes_to_bus(self):
        reg, bus = _make_registry([_make_spec("notify", executor=lambda a: "ok")])
        reg.execute("notify", {})
        bus.publish_nowait.assert_called_once()
        event = bus.publish_nowait.call_args[0]
        self.assertEqual(event[0], "system/tools")

    def test_execute_passes_arguments_to_executor(self):
        received: list = []

        def executor(args):
            received.append(args)
            return "done"

        reg, _ = _make_registry([_make_spec("capture", executor=executor)])
        reg.execute("capture", {"key": "value"})
        self.assertEqual(received[0].get("key"), "value")

    def test_execute_with_pydantic_schema_validates_input(self):
        class MyInput(BaseModel):
            name: str
            count: int

        def executor(args: dict) -> str:
            return f"{args['name']}x{args['count']}"

        reg, _ = _make_registry([
            RuntimeToolSpec(
                tool_id="typed",
                name="Typed",
                description="uses schema",
                schema=MyInput,
                executor=executor,
            )
        ])
        result = reg.execute("typed", {"name": "foo", "count": 3})
        self.assertEqual(result["result"], "foox3")

    def test_execute_with_bad_schema_raises_tool_execution_error(self):
        class MyInput(BaseModel):
            name: str

        reg, _ = _make_registry([
            RuntimeToolSpec(
                tool_id="typed2",
                name="Typed2",
                description="",
                schema=MyInput,
                executor=lambda a: a,
            )
        ])
        with self.assertRaises(ToolExecutionError):
            reg.execute("typed2", {"name": 12345})  # int where str expected

    def test_execute_result_has_executed_at_timestamp(self):
        reg, _ = _make_registry([_make_spec("ts", executor=lambda a: None)])
        result = reg.execute("ts", {})
        self.assertIn("executed_at", result)
        self.assertIsInstance(result["executed_at"], int)


# ---------------------------------------------------------------------------
# Tests: RuntimeToolSpec immutability
# ---------------------------------------------------------------------------

class TestRuntimeToolSpec(unittest.TestCase):
    def test_spec_is_frozen(self):
        spec = _make_spec("frozen")
        with self.assertRaises((AttributeError, TypeError)):
            spec.tool_id = "modified"  # type: ignore[misc]

    def test_default_requires_admin_is_false(self):
        spec = _make_spec("x")
        self.assertFalse(spec.requires_admin)

    def test_default_category_is_runtime(self):
        spec = RuntimeToolSpec(
            tool_id="bare",
            name="Bare",
            description="",
            schema=None,
            executor=lambda a: None,
        )
        self.assertEqual(spec.category, "runtime")


if __name__ == "__main__":
    unittest.main()
