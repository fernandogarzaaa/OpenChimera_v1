"""Tests for core.tool_registry — UnifiedToolRegistry facade."""
from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock

from core.tool_runtime import (
    RuntimeToolRegistry,
    RuntimeToolSpec,
    ToolMetadata,
    ToolPermissionError,
    ToolRegistry,
)
from core.tool_registry import UnifiedToolRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bus() -> MagicMock:
    bus = MagicMock()
    bus.publish_nowait = MagicMock()
    return bus


def _make_metadata_tool(name: str, handler=None, tags: list[str] | None = None) -> ToolMetadata:
    return ToolMetadata(
        name=name,
        description=f"Description for {name}",
        handler=handler or (lambda args: {"name": name}),
        tags=tags or [],
    )


def _make_runtime_spec(
    tool_id: str,
    executor=None,
    requires_admin: bool = False,
) -> RuntimeToolSpec:
    return RuntimeToolSpec(
        tool_id=tool_id,
        name=f"RT:{tool_id}",
        description=f"Runtime tool {tool_id}",
        schema=None,
        executor=executor or (lambda args: {"id": tool_id}),
        requires_admin=requires_admin,
        category="runtime",
    )


def _make_runtime_registry(
    specs: list[RuntimeToolSpec] | None = None,
    bus: Any = None,
) -> RuntimeToolRegistry:
    cap_reg = MagicMock()
    cap_reg.list_kind.return_value = [
        {"id": s.tool_id, "name": s.name, "description": s.description, "kind": "tool", "category": "runtime"}
        for s in (specs or [])
    ]
    return RuntimeToolRegistry(capability_registry=cap_reg, bus=bus or _make_bus(), specs=specs)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

class TestUnifiedToolRegistryConstruction(unittest.TestCase):
    def test_default_construction_empty(self):
        reg = UnifiedToolRegistry()
        self.assertEqual(reg.list_tools(), [])

    def test_provides_tool_registry_and_runtime_registry(self):
        tr = ToolRegistry()
        rtr = _make_runtime_registry()
        reg = UnifiedToolRegistry(tool_registry=tr, runtime_registry=rtr)
        self.assertIsInstance(reg, UnifiedToolRegistry)

    def test_auto_creates_tool_registry_when_not_provided(self):
        reg = UnifiedToolRegistry()
        self.assertIsNotNone(reg._tool_registry)

    def test_accepts_bus(self):
        bus = _make_bus()
        reg = UnifiedToolRegistry(bus=bus)
        self.assertIsNotNone(reg)


# ---------------------------------------------------------------------------
# register / unregister (ToolMetadata registry)
# ---------------------------------------------------------------------------

class TestUnifiedToolRegistryRegister(unittest.TestCase):
    def test_register_adds_to_list(self):
        reg = UnifiedToolRegistry()
        reg.register(_make_metadata_tool("hello"))
        tools = reg.list_tools()
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["name"], "hello")

    def test_register_returns_tool_metadata(self):
        reg = UnifiedToolRegistry()
        tool = _make_metadata_tool("echo")
        returned = reg.register(tool)
        self.assertIs(returned, tool)

    def test_register_empty_name_raises_value_error(self):
        reg = UnifiedToolRegistry()
        with self.assertRaises(ValueError):
            reg.register(_make_metadata_tool(""))

    def test_unregister_removes_tool(self):
        reg = UnifiedToolRegistry()
        reg.register(_make_metadata_tool("removable"))
        removed = reg.unregister("removable")
        self.assertTrue(removed)
        self.assertEqual(reg.list_tools(), [])

    def test_unregister_unknown_returns_false(self):
        reg = UnifiedToolRegistry()
        self.assertFalse(reg.unregister("ghost"))


# ---------------------------------------------------------------------------
# list_tools — merging and deduplication
# ---------------------------------------------------------------------------

class TestUnifiedToolRegistryListTools(unittest.TestCase):
    def test_list_from_tool_registry_only(self):
        reg = UnifiedToolRegistry()
        reg.register(_make_metadata_tool("alpha"))
        reg.register(_make_metadata_tool("beta"))
        tools = reg.list_tools()
        names = [t["name"] for t in tools]
        self.assertIn("alpha", names)
        self.assertIn("beta", names)

    def test_list_from_runtime_registry_only(self):
        rtr = _make_runtime_registry([_make_runtime_spec("rt-only")])
        reg = UnifiedToolRegistry(runtime_registry=rtr)
        tools = reg.list_tools()
        ids = [t.get("id") or t.get("name") for t in tools]
        self.assertIn("rt-only", ids)

    def test_list_merges_both_registries(self):
        rtr = _make_runtime_registry([_make_runtime_spec("rt-tool")])
        reg = UnifiedToolRegistry(runtime_registry=rtr)
        reg.register(_make_metadata_tool("meta-tool"))
        tools = reg.list_tools()
        self.assertEqual(len(tools), 2)

    def test_deduplication_by_name(self):
        rtr = _make_runtime_registry([_make_runtime_spec("shared-name")])
        tr = ToolRegistry()
        tr.register(_make_metadata_tool("shared-name"))
        reg = UnifiedToolRegistry(tool_registry=tr, runtime_registry=rtr)
        tools = reg.list_tools()
        # Should only appear once
        names = [t.get("name") or t.get("id") for t in tools]
        self.assertEqual(names.count("shared-name"), 1)

    def test_list_sorted_alphabetically(self):
        reg = UnifiedToolRegistry()
        reg.register(_make_metadata_tool("zzz"))
        reg.register(_make_metadata_tool("aaa"))
        reg.register(_make_metadata_tool("mmm"))
        names = [t["name"] for t in reg.list_tools()]
        self.assertEqual(names, sorted(names))

    def test_empty_unified_list(self):
        reg = UnifiedToolRegistry()
        self.assertEqual(reg.list_tools(), [])


# ---------------------------------------------------------------------------
# describe
# ---------------------------------------------------------------------------

class TestUnifiedToolRegistryDescribe(unittest.TestCase):
    def test_describe_metadata_tool(self):
        reg = UnifiedToolRegistry()
        reg.register(_make_metadata_tool("describable"))
        desc = reg.describe("describable")
        self.assertEqual(desc["name"], "describable")

    def test_describe_runtime_tool(self):
        rtr = _make_runtime_registry([_make_runtime_spec("rt-describe")])
        reg = UnifiedToolRegistry(runtime_registry=rtr)
        desc = reg.describe("rt-describe")
        self.assertEqual(str(desc.get("id") or desc.get("name")), "rt-describe")

    def test_describe_unknown_raises_value_error(self):
        reg = UnifiedToolRegistry()
        with self.assertRaises(ValueError):
            reg.describe("nonexistent")

    def test_describe_prefers_metadata_registry(self):
        tr = ToolRegistry()
        tr.register(ToolMetadata(name="shared", description="metadata version", handler=lambda a: None))
        rtr = _make_runtime_registry([_make_runtime_spec("shared")])
        reg = UnifiedToolRegistry(tool_registry=tr, runtime_registry=rtr)
        desc = reg.describe("shared")
        # Should come from ToolMetadata (has description "metadata version")
        self.assertEqual(desc["description"], "metadata version")


# ---------------------------------------------------------------------------
# execute
# ---------------------------------------------------------------------------

class TestUnifiedToolRegistryExecute(unittest.TestCase):
    def test_execute_metadata_tool_returns_ok(self):
        reg = UnifiedToolRegistry()
        reg.register(_make_metadata_tool("run-me", handler=lambda args: "result"))
        result = reg.execute("run-me", {})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"], "result")

    def test_execute_runtime_tool_returns_ok(self):
        rtr = _make_runtime_registry([
            _make_runtime_spec("rt-run", executor=lambda args: "rt-result")
        ])
        reg = UnifiedToolRegistry(runtime_registry=rtr)
        result = reg.execute("rt-run", {})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"], "rt-result")

    def test_execute_metadata_tool_failure_returns_error_status(self):
        def bad_handler(args):
            raise RuntimeError("boom")

        reg = UnifiedToolRegistry()
        reg.register(_make_metadata_tool("crash", handler=bad_handler))
        result = reg.execute("crash", {})
        self.assertEqual(result["status"], "error")
        self.assertIn("boom", str(result.get("error", "")))

    def test_execute_unknown_tool_raises_value_error(self):
        reg = UnifiedToolRegistry()
        with self.assertRaises(ValueError):
            reg.execute("ghost", {})

    def test_execute_runtime_admin_tool_without_admin_scope_raises(self):
        rtr = _make_runtime_registry([
            _make_runtime_spec("admin-only", requires_admin=True)
        ])
        reg = UnifiedToolRegistry(runtime_registry=rtr)
        with self.assertRaises(ToolPermissionError):
            reg.execute("admin-only", {}, permission_scope="user")

    def test_execute_runtime_admin_tool_with_admin_scope_succeeds(self):
        rtr = _make_runtime_registry([
            _make_runtime_spec("admin-only", requires_admin=True, executor=lambda a: "ok")
        ])
        reg = UnifiedToolRegistry(runtime_registry=rtr)
        result = reg.execute("admin-only", {}, permission_scope="admin")
        self.assertEqual(result["status"], "ok")

    def test_execute_result_has_tool_id(self):
        reg = UnifiedToolRegistry()
        reg.register(_make_metadata_tool("tid-check", handler=lambda a: None))
        result = reg.execute("tid-check", {})
        self.assertEqual(result["tool_id"], "tid-check")

    def test_execute_result_has_permission_scope(self):
        reg = UnifiedToolRegistry()
        reg.register(_make_metadata_tool("scope-check", handler=lambda a: None))
        result = reg.execute("scope-check", {}, permission_scope="admin")
        self.assertEqual(result["permission_scope"], "admin")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

class TestUnifiedToolRegistryStatus(unittest.TestCase):
    def test_status_counts_metadata_tools(self):
        reg = UnifiedToolRegistry()
        reg.register(_make_metadata_tool("a"))
        reg.register(_make_metadata_tool("b"))
        self.assertEqual(reg.status()["counts"]["metadata_tools"], 2)

    def test_status_counts_runtime_tools(self):
        rtr = _make_runtime_registry([_make_runtime_spec("x"), _make_runtime_spec("y")])
        reg = UnifiedToolRegistry(runtime_registry=rtr)
        self.assertEqual(reg.status()["counts"]["runtime_tools"], 2)

    def test_status_total_is_deduplicated(self):
        tr = ToolRegistry()
        tr.register(_make_metadata_tool("shared"))
        rtr = _make_runtime_registry([_make_runtime_spec("shared"), _make_runtime_spec("unique-rt")])
        reg = UnifiedToolRegistry(tool_registry=tr, runtime_registry=rtr)
        self.assertEqual(reg.status()["counts"]["total"], 2)

    def test_status_empty_registry(self):
        reg = UnifiedToolRegistry()
        status = reg.status()
        self.assertEqual(status["counts"]["total"], 0)
        self.assertEqual(status["counts"]["metadata_tools"], 0)
        self.assertEqual(status["counts"]["runtime_tools"], 0)


if __name__ == "__main__":
    unittest.main()
