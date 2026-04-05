"""Tests for core.mcp_adapter — MCPAdapter runtime connection manager."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.mcp_adapter import MCPAdapter, MCPConnectionError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bus() -> MagicMock:
    bus = MagicMock()
    bus.publish_nowait = MagicMock()
    return bus


def _make_adapter(bus=None, timeout_seconds: float = 5.0) -> MCPAdapter:
    return MCPAdapter(bus=bus, timeout_seconds=timeout_seconds)


def _fake_probe_result(server_id: str, status: str = "healthy") -> dict:
    return {
        "id": server_id,
        "status": status,
        "checked_at": 1234567890.0,
        "transport": "http",
        "probe_target": "http://localhost:9000",
    }


def _fake_registry_entries(*server_ids: str) -> list[dict]:
    return [
        {
            "id": sid,
            "name": sid.title(),
            "transport": "http",
            "url": f"http://localhost:{9000 + i}",
            "enabled": True,
            "status": "registered",
        }
        for i, sid in enumerate(server_ids)
    ]


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

class TestMCPAdapterConstruction(unittest.TestCase):
    def test_default_construction(self):
        adapter = MCPAdapter()
        self.assertIsInstance(adapter, MCPAdapter)

    def test_default_connected_is_empty(self):
        adapter = MCPAdapter()
        self.assertEqual(adapter.connected_servers(), [])

    def test_accepts_bus(self):
        bus = _make_bus()
        adapter = MCPAdapter(bus=bus)
        self.assertIsNotNone(adapter)

    def test_accepts_custom_timeout(self):
        adapter = MCPAdapter(timeout_seconds=10.0)
        self.assertEqual(adapter._timeout, 10.0)


# ---------------------------------------------------------------------------
# list_servers
# ---------------------------------------------------------------------------

class TestMCPAdapterListServers(unittest.TestCase):
    def test_list_servers_returns_list(self):
        with patch("core.mcp_adapter.list_mcp_registry_with_health", return_value=[]):
            adapter = _make_adapter()
            result = adapter.list_servers()
            self.assertIsInstance(result, list)

    def test_list_servers_with_entries(self):
        entries = _fake_registry_entries("server-a", "server-b")
        with patch("core.mcp_adapter.list_mcp_registry_with_health", return_value=entries):
            adapter = _make_adapter()
            servers = adapter.list_servers()
            self.assertEqual(len(servers), 2)

    def test_list_servers_enabled_only_filters_disabled(self):
        entries = [
            {**_fake_registry_entries("on")[0], "enabled": True},
            {**_fake_registry_entries("off")[0], "id": "off", "enabled": False},
        ]
        with patch("core.mcp_adapter.list_mcp_registry_with_health", return_value=entries):
            adapter = _make_adapter()
            servers = adapter.list_servers(enabled_only=True)
            ids = [s["id"] for s in servers]
            self.assertIn("on", ids)
            self.assertNotIn("off", ids)


# ---------------------------------------------------------------------------
# connect / disconnect
# ---------------------------------------------------------------------------

class TestMCPAdapterConnect(unittest.TestCase):
    def test_connect_healthy_server_adds_to_connected(self):
        probe_result = _fake_probe_result("srv-1", status="healthy")
        with patch("core.mcp_adapter.probe_mcp_registry_entry", return_value=probe_result):
            adapter = _make_adapter()
            adapter.connect("srv-1")
            self.assertIn("srv-1", adapter.connected_servers())

    def test_connect_unhealthy_server_not_in_connected(self):
        probe_result = _fake_probe_result("srv-2", status="degraded")
        with patch("core.mcp_adapter.probe_mcp_registry_entry", return_value=probe_result):
            adapter = _make_adapter()
            adapter.connect("srv-2")
            self.assertNotIn("srv-2", adapter.connected_servers())

    def test_connect_returns_probe_result(self):
        probe_result = _fake_probe_result("srv-3")
        with patch("core.mcp_adapter.probe_mcp_registry_entry", return_value=probe_result):
            adapter = _make_adapter()
            result = adapter.connect("srv-3")
            self.assertEqual(result["id"], "srv-3")
            self.assertEqual(result["status"], "healthy")

    def test_connect_healthy_publishes_connected_event(self):
        bus = _make_bus()
        probe_result = _fake_probe_result("srv-pub", status="healthy")
        with patch("core.mcp_adapter.probe_mcp_registry_entry", return_value=probe_result):
            adapter = _make_adapter(bus=bus)
            adapter.connect("srv-pub")
        bus.publish_nowait.assert_called()
        topics = [call[0][0] for call in bus.publish_nowait.call_args_list]
        self.assertIn("mcp/connected", topics)

    def test_connect_unhealthy_publishes_connect_failed_event(self):
        bus = _make_bus()
        probe_result = _fake_probe_result("srv-fail", status="degraded")
        probe_result["last_error"] = "connection refused"
        with patch("core.mcp_adapter.probe_mcp_registry_entry", return_value=probe_result):
            adapter = _make_adapter(bus=bus)
            adapter.connect("srv-fail")
        topics = [call[0][0] for call in bus.publish_nowait.call_args_list]
        self.assertIn("mcp/connect_failed", topics)

    def test_connect_previously_connected_then_degraded_removes_from_connected(self):
        with patch("core.mcp_adapter.probe_mcp_registry_entry", return_value=_fake_probe_result("srv-x")):
            adapter = _make_adapter()
            adapter.connect("srv-x")
        self.assertIn("srv-x", adapter.connected_servers())
        with patch("core.mcp_adapter.probe_mcp_registry_entry", return_value=_fake_probe_result("srv-x", status="degraded")):
            adapter.connect("srv-x")
        self.assertNotIn("srv-x", adapter.connected_servers())


class TestMCPAdapterDisconnect(unittest.TestCase):
    def test_disconnect_connected_server(self):
        with patch("core.mcp_adapter.probe_mcp_registry_entry", return_value=_fake_probe_result("dc-srv")):
            adapter = _make_adapter()
            adapter.connect("dc-srv")
        result = adapter.disconnect("dc-srv")
        self.assertTrue(result["disconnected"])
        self.assertTrue(result["was_connected"])
        self.assertNotIn("dc-srv", adapter.connected_servers())

    def test_disconnect_not_connected_server(self):
        adapter = _make_adapter()
        result = adapter.disconnect("never-connected")
        self.assertTrue(result["disconnected"])
        self.assertFalse(result["was_connected"])

    def test_disconnect_publishes_event(self):
        bus = _make_bus()
        adapter = _make_adapter(bus=bus)
        adapter.disconnect("any")
        bus.publish_nowait.assert_called()
        topics = [call[0][0] for call in bus.publish_nowait.call_args_list]
        self.assertIn("mcp/disconnected", topics)


# ---------------------------------------------------------------------------
# connected_servers
# ---------------------------------------------------------------------------

class TestMCPAdapterConnectedServers(unittest.TestCase):
    def test_connected_servers_sorted(self):
        probes = {"zzz": _fake_probe_result("zzz"), "aaa": _fake_probe_result("aaa")}
        adapter = _make_adapter()
        for sid, probe in probes.items():
            with patch("core.mcp_adapter.probe_mcp_registry_entry", return_value=probe):
                adapter.connect(sid)
        servers = adapter.connected_servers()
        self.assertEqual(servers, sorted(servers))

    def test_connected_servers_empty_initially(self):
        adapter = _make_adapter()
        self.assertEqual(adapter.connected_servers(), [])


# ---------------------------------------------------------------------------
# list_server_tools
# ---------------------------------------------------------------------------

class TestMCPAdapterListServerTools(unittest.TestCase):
    def _mock_entry(self, server_id: str, transport: str = "http", url: str = "http://localhost:9000") -> dict:
        return {"id": server_id, "transport": transport, "url": url, "enabled": True, "status": "registered"}

    def test_list_tools_http_server(self):
        entry = self._mock_entry("tools-srv")
        tools_response = {"jsonrpc": "2.0", "id": "x", "result": {"tools": [
            {"name": "tool-a", "description": "A"},
            {"name": "tool-b", "description": "B"},
        ]}}
        with patch("core.mcp_adapter.list_mcp_registry_with_health", return_value=[entry]):
            adapter = _make_adapter()
            with patch.object(adapter, "_http_call", return_value=tools_response):
                tools = adapter.list_server_tools("tools-srv")
        self.assertEqual(len(tools), 2)
        names = [t["name"] for t in tools]
        self.assertIn("tool-a", names)
        self.assertIn("tool-b", names)

    def test_list_tools_stdio_server_returns_empty(self):
        entry = {"id": "stdio-srv", "transport": "stdio", "command": "my-cmd", "enabled": True, "status": "registered"}
        with patch("core.mcp_adapter.list_mcp_registry_with_health", return_value=[entry]):
            adapter = _make_adapter()
            tools = adapter.list_server_tools("stdio-srv")
        self.assertEqual(tools, [])

    def test_list_tools_unknown_server_raises_value_error(self):
        with patch("core.mcp_adapter.list_mcp_registry_with_health", return_value=[]):
            adapter = _make_adapter()
            with self.assertRaises(ValueError):
                adapter.list_server_tools("no-such-server")

    def test_list_tools_returns_empty_on_empty_result(self):
        entry = self._mock_entry("empty-srv")
        with patch("core.mcp_adapter.list_mcp_registry_with_health", return_value=[entry]):
            adapter = _make_adapter()
            with patch.object(adapter, "_http_call", return_value={"jsonrpc": "2.0", "id": "x", "result": {}}):
                tools = adapter.list_server_tools("empty-srv")
        self.assertEqual(tools, [])


# ---------------------------------------------------------------------------
# call_tool
# ---------------------------------------------------------------------------

class TestMCPAdapterCallTool(unittest.TestCase):
    def _mock_http_entry(self, server_id: str = "call-srv") -> dict:
        return {"id": server_id, "transport": "http", "url": "http://localhost:9000", "enabled": True, "status": "registered"}

    def test_call_tool_ok_result(self):
        entry = self._mock_http_entry()
        call_response = {"jsonrpc": "2.0", "id": "x", "result": {"value": 42}}
        with patch("core.mcp_adapter.list_mcp_registry_with_health", return_value=[entry]):
            adapter = _make_adapter()
            with patch.object(adapter, "_http_call", return_value=call_response):
                result = adapter.call_tool("call-srv", "my-tool", {"arg": 1})
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"], {"value": 42})
        self.assertEqual(result["server_id"], "call-srv")
        self.assertEqual(result["tool_name"], "my-tool")
        self.assertIn("latency_ms", result)

    def test_call_tool_error_response(self):
        entry = self._mock_http_entry()
        error_response = {"jsonrpc": "2.0", "id": "x", "error": {"code": -32601, "message": "Method not found"}}
        with patch("core.mcp_adapter.list_mcp_registry_with_health", return_value=[entry]):
            adapter = _make_adapter()
            with patch.object(adapter, "_http_call", return_value=error_response):
                result = adapter.call_tool("call-srv", "bad-tool")
        self.assertEqual(result["status"], "error")
        self.assertIn("error", result)

    def test_call_tool_stdio_raises_mcp_connection_error(self):
        entry = {"id": "stdio-srv", "transport": "stdio", "command": "cmd", "enabled": True, "status": "registered"}
        with patch("core.mcp_adapter.list_mcp_registry_with_health", return_value=[entry]):
            adapter = _make_adapter()
            with self.assertRaises(MCPConnectionError):
                adapter.call_tool("stdio-srv", "any-tool")

    def test_call_tool_unknown_server_raises_value_error(self):
        with patch("core.mcp_adapter.list_mcp_registry_with_health", return_value=[]):
            adapter = _make_adapter()
            with self.assertRaises(ValueError):
                adapter.call_tool("unknown-srv", "tool")

    def test_call_tool_publishes_event(self):
        bus = _make_bus()
        entry = self._mock_http_entry()
        with patch("core.mcp_adapter.list_mcp_registry_with_health", return_value=[entry]):
            adapter = _make_adapter(bus=bus)
            with patch.object(adapter, "_http_call", return_value={"result": "ok"}):
                adapter.call_tool("call-srv", "t", {})
        topics = [call[0][0] for call in bus.publish_nowait.call_args_list]
        self.assertIn("mcp/tool_called", topics)


# ---------------------------------------------------------------------------
# health_status
# ---------------------------------------------------------------------------

class TestMCPAdapterHealthStatus(unittest.TestCase):
    def test_health_status_structure(self):
        with patch("core.mcp_adapter.list_mcp_registry_with_health", return_value=[]):
            adapter = _make_adapter()
            status = adapter.health_status()
        for key in ("counts", "connected", "servers"):
            self.assertIn(key, status)

    def test_health_status_counts_healthy(self):
        entries = [
            {"id": "a", "status": "healthy", "enabled": True},
            {"id": "b", "status": "degraded", "enabled": True},
        ]
        with patch("core.mcp_adapter.list_mcp_registry_with_health", return_value=entries):
            adapter = _make_adapter()
            status = adapter.health_status()
        self.assertEqual(status["counts"]["total"], 2)
        self.assertEqual(status["counts"]["healthy"], 1)

    def test_health_status_counts_connected(self):
        with patch("core.mcp_adapter.probe_mcp_registry_entry", return_value=_fake_probe_result("h")):
            adapter = _make_adapter()
            adapter.connect("h")
        with patch("core.mcp_adapter.list_mcp_registry_with_health", return_value=[]):
            status = adapter.health_status()
        self.assertEqual(status["counts"]["connected"], 1)

    def test_health_status_connected_sorted(self):
        with patch("core.mcp_adapter.list_mcp_registry_with_health", return_value=[]):
            adapter = _make_adapter()
        adapter._connected = {"zzz": {}, "aaa": {}, "mmm": {}}
        with patch("core.mcp_adapter.list_mcp_registry_with_health", return_value=[]):
            status = adapter.health_status()
        self.assertEqual(status["connected"], sorted(status["connected"]))


# ---------------------------------------------------------------------------
# register_server / unregister_server
# ---------------------------------------------------------------------------

class TestMCPAdapterRegistration(unittest.TestCase):
    def test_register_server_http(self):
        with patch("core.mcp_adapter.upsert_mcp_registry_entry", return_value={"id": "new-srv"}) as mock_upsert:
            adapter = _make_adapter()
            result = adapter.register_server(
                "new-srv", transport="http", url="http://localhost:8888"
            )
        mock_upsert.assert_called_once()
        self.assertEqual(result["id"], "new-srv")

    def test_register_server_publishes_event(self):
        bus = _make_bus()
        with patch("core.mcp_adapter.upsert_mcp_registry_entry", return_value={"id": "evt-srv"}):
            adapter = _make_adapter(bus=bus)
            adapter.register_server("evt-srv", transport="http", url="http://x")
        topics = [call[0][0] for call in bus.publish_nowait.call_args_list]
        self.assertIn("mcp/registered", topics)

    def test_unregister_server_calls_delete(self):
        with patch("core.mcp_adapter.delete_mcp_registry_entry", return_value={"id": "del-srv", "deleted": True}) as mock_del:
            adapter = _make_adapter()
            result = adapter.unregister_server("del-srv")
        mock_del.assert_called_once_with("del-srv")

    def test_unregister_server_removes_from_connected(self):
        adapter = _make_adapter()
        adapter._connected["del-conn"] = {"id": "del-conn"}
        with patch("core.mcp_adapter.delete_mcp_registry_entry", return_value={"id": "del-conn", "deleted": True}):
            adapter.unregister_server("del-conn")
        self.assertNotIn("del-conn", adapter.connected_servers())

    def test_unregister_server_publishes_event(self):
        bus = _make_bus()
        with patch("core.mcp_adapter.delete_mcp_registry_entry", return_value={"id": "x"}):
            adapter = _make_adapter(bus=bus)
            adapter.unregister_server("x")
        topics = [call[0][0] for call in bus.publish_nowait.call_args_list]
        self.assertIn("mcp/unregistered", topics)


# ---------------------------------------------------------------------------
# Bus tolerance
# ---------------------------------------------------------------------------

class TestMCPAdapterBusTolerance(unittest.TestCase):
    def test_publish_failure_does_not_crash(self):
        bus = MagicMock()
        bus.publish_nowait.side_effect = RuntimeError("bus down")
        adapter = _make_adapter(bus=bus)
        # Should not raise even though bus fails
        adapter._publish("any/topic", {"key": "val"})


if __name__ == "__main__":
    unittest.main()
