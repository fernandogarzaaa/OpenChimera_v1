"""Tests for core.capability_plane — MCP/plugin facade."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from core.capability_plane import CapabilityPlane


def _make_plane(**overrides) -> CapabilityPlane:
    defaults = dict(
        capabilities=MagicMock(),
        plugins=MagicMock(),
        bus=MagicMock(),
    )
    defaults.update(overrides)
    return CapabilityPlane(**defaults)


class TestCapabilityPlane(unittest.TestCase):
    def test_capability_status_delegates(self) -> None:
        plane = _make_plane()
        plane.capabilities.status.return_value = {"tools": []}
        self.assertEqual(plane.capability_status(), {"tools": []})

    def test_list_capabilities_delegates(self) -> None:
        plane = _make_plane()
        plane.capabilities.list_kind.return_value = [{"name": "search"}]
        result = plane.list_capabilities("tool")
        plane.capabilities.list_kind.assert_called_once_with("tool")
        self.assertEqual(result, [{"name": "search"}])

    def test_plugin_status_delegates(self) -> None:
        plane = _make_plane()
        plane.plugins.status.return_value = {"installed": []}
        self.assertEqual(plane.plugin_status(), {"installed": []})

    def test_install_plugin_publishes(self) -> None:
        plane = _make_plane()
        plane.plugins.install.return_value = {"id": "my-plugin", "status": "installed"}
        plane.install_plugin("my-plugin")
        plane.bus.publish_nowait.assert_called_once()
        topic, payload = plane.bus.publish_nowait.call_args[0]
        self.assertEqual(topic, "system/plugins")
        self.assertEqual(payload["action"], "install")

    def test_uninstall_plugin_publishes(self) -> None:
        plane = _make_plane()
        plane.plugins.uninstall.return_value = {"id": "my-plugin", "removed": True}
        plane.uninstall_plugin("my-plugin")
        plane.bus.publish_nowait.assert_called_once()

    @patch("core.capability_plane.list_mcp_registry_with_health", return_value=[])
    def test_mcp_status_structure(self, _mock_list) -> None:
        plane = _make_plane()
        plane.capabilities.list_kind.return_value = []
        status = plane.mcp_status()
        self.assertIn("counts", status)
        self.assertIn("registry", status)
        self.assertIn("servers", status)

    @patch("core.capability_plane.list_mcp_registry_with_health", return_value=[
        {"id": "s1", "status": "healthy", "enabled": True},
        {"id": "s2", "status": "unavailable", "enabled": False},
    ])
    def test_mcp_status_healthy_count(self, _mock_list) -> None:
        plane = _make_plane()
        plane.capabilities.list_kind.return_value = []
        status = plane.mcp_status()
        self.assertEqual(status["registry"]["counts"]["total"], 2)
        self.assertEqual(status["registry"]["counts"]["healthy"], 1)
        self.assertEqual(status["registry"]["counts"]["enabled"], 1)

    @patch("core.capability_plane.list_mcp_registry_with_health", return_value=[])
    def test_mcp_registry_status_structure(self, _mock_list) -> None:
        plane = _make_plane()
        status = plane.mcp_registry_status()
        self.assertIn("counts", status)
        self.assertIn("servers", status)

    @patch("core.capability_plane.upsert_mcp_registry_entry", return_value={"id": "srv1"})
    def test_register_mcp_connector_publishes(self, _mock_upsert) -> None:
        plane = _make_plane()
        plane.register_mcp_connector("srv1", transport="http", url="http://localhost:9000")
        plane.capabilities.refresh.assert_called_once()
        plane.bus.publish_nowait.assert_called_once()
        topic, payload = plane.bus.publish_nowait.call_args[0]
        self.assertEqual(topic, "system/mcp")
        self.assertEqual(payload["action"], "register")

    @patch("core.capability_plane.delete_mcp_registry_entry", return_value={"deleted": True})
    def test_unregister_mcp_connector_publishes(self, _mock_delete) -> None:
        plane = _make_plane()
        plane.unregister_mcp_connector("srv1")
        plane.capabilities.refresh.assert_called_once()
        plane.bus.publish_nowait.assert_called_once()
        topic, payload = plane.bus.publish_nowait.call_args[0]
        self.assertEqual(topic, "system/mcp")
        self.assertEqual(payload["action"], "unregister")

    @patch("core.capability_plane.probe_mcp_registry_entry", return_value={"id": "srv1", "status": "healthy"})
    def test_probe_single_connector(self, _mock_probe) -> None:
        plane = _make_plane()
        result = plane.probe_mcp_connectors("srv1", timeout_seconds=2.0)
        plane.capabilities.refresh.assert_called_once()
        plane.bus.publish_nowait.assert_called_once()
        self.assertEqual(result["counts"]["total"], 1)
        self.assertEqual(result["counts"]["healthy"], 1)

    @patch("core.capability_plane.probe_all_mcp_registry_entries", return_value={"counts": {"total": 0}, "servers": []})
    def test_probe_all_connectors(self, _mock_probe_all) -> None:
        plane = _make_plane()
        result = plane.probe_mcp_connectors()
        plane.capabilities.refresh.assert_called_once()
        plane.bus.publish_nowait.assert_called_once()
        self.assertIn("counts", result)


if __name__ == "__main__":
    unittest.main()
