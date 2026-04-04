"""Tests for core.integration_plane — IntegrationPlane status methods and
legacy-stack detection helpers.

All tests use mocked dependencies; no network or disk I/O.
"""
from __future__ import annotations
import unittest
from unittest.mock import MagicMock, patch

from core.integration_plane import IntegrationPlane


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_audit(engines: dict | None = None, subsystems: dict | None = None) -> MagicMock:
    audit = MagicMock()
    audit.build_report.return_value = {
        "engines": engines or {},
        "overall_status": "nominal",
        "subsystems": subsystems or {},
    }
    return audit


def _make_plane(
    audit=None,
    mcp_status: dict | None = None,
    aegis_status: dict | None = None,
    ascension_status: dict | None = None,
    bus=None,
) -> IntegrationPlane:
    return IntegrationPlane(
        integration_audit=audit or _mock_audit(),
        mcp_status_getter=lambda: mcp_status or {"mcp_servers": []},
        aegis_status_getter=lambda: aegis_status or {"available": False},
        ascension_status_getter=lambda: ascension_status or {"available": False},
        bus=bus,
    )


# ---------------------------------------------------------------------------
# build_integration_status
# ---------------------------------------------------------------------------

class TestBuildIntegrationStatus(unittest.TestCase):
    def test_returns_dict(self):
        plane = _make_plane()
        result = plane.build_integration_status()
        self.assertIsInstance(result, dict)

    def test_includes_engines_from_audit(self):
        audit = _mock_audit(engines={"aether": {"status": "ok"}})
        plane = _make_plane(audit=audit)
        result = plane.build_integration_status()
        self.assertIn("engines", result)
        self.assertIn("aether", result["engines"])

    def test_aegis_swarm_gets_bridge_status_injected(self):
        audit = _mock_audit(engines={"aegis_swarm": {}})
        plane = _make_plane(audit=audit, aegis_status={"available": True, "mode": "live"})
        result = plane.build_integration_status()
        aegis = result["engines"]["aegis_swarm"]
        self.assertIn("integrated_runtime", aegis)
        self.assertTrue(aegis["integrated_runtime"])

    def test_ascension_engine_gets_bridge_status_injected(self):
        audit = _mock_audit(engines={"ascension_engine": {}})
        plane = _make_plane(audit=audit, ascension_status={"available": True})
        result = plane.build_integration_status()
        ascension = result["engines"]["ascension_engine"]
        self.assertIn("bridge_status", ascension)


# ---------------------------------------------------------------------------
# qwen_agent_status
# ---------------------------------------------------------------------------

class TestQwenAgentStatus(unittest.TestCase):
    def test_qwen_status_returns_dict(self):
        plane = _make_plane()
        with patch("core.config.get_legacy_workspace_root", return_value=None):
            result = plane.qwen_agent_status()
        self.assertIsInstance(result, dict)


# ---------------------------------------------------------------------------
# context_hub_status
# ---------------------------------------------------------------------------

class TestContextHubStatus(unittest.TestCase):
    def test_context_hub_status_returns_dict(self):
        plane = _make_plane()
        result = plane.context_hub_status()
        self.assertIsInstance(result, dict)


# ---------------------------------------------------------------------------
# deepagents_stack_status
# ---------------------------------------------------------------------------

class TestDeepagentsStackStatus(unittest.TestCase):
    def test_deepagents_status_returns_dict(self):
        plane = _make_plane()
        result = plane.deepagents_stack_status()
        self.assertIsInstance(result, dict)


# ---------------------------------------------------------------------------
# aether_operator_stack_status
# ---------------------------------------------------------------------------

class TestAetherOperatorStackStatus(unittest.TestCase):
    def test_aether_status_returns_dict(self):
        plane = _make_plane()
        with patch("core.config.get_aether_root", return_value=None):
            result = plane.aether_operator_stack_status()
        self.assertIsInstance(result, dict)


# ---------------------------------------------------------------------------
# clawd_hybrid_rtx_status
# ---------------------------------------------------------------------------

class TestClawdHybridRtxStatus(unittest.TestCase):
    def test_clawd_status_returns_dict(self):
        plane = _make_plane()
        with patch("core.config.get_appforge_root", return_value=None):
            result = plane.clawd_hybrid_rtx_status()
        self.assertIsInstance(result, dict)


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# activate_bridge / invoke_bridge — new execution layer tests
# ---------------------------------------------------------------------------

class TestActivateBridge(unittest.TestCase):
    def test_activate_bridge_returns_dict(self):
        plane = _make_plane()
        result = plane.activate_bridge("nonexistent")
        self.assertIsInstance(result, dict)

    def test_activate_bridge_not_found_activated_false(self):
        plane = _make_plane()
        result = plane.activate_bridge("no_such_bridge")
        self.assertFalse(result["activated"])

    def test_activate_bridge_not_found_status_is_not_found(self):
        plane = _make_plane()
        result = plane.activate_bridge("no_such_bridge")
        self.assertEqual(result["status"], "not_found")

    def test_activate_bridge_not_found_has_error_key(self):
        plane = _make_plane()
        result = plane.activate_bridge("no_such_bridge")
        self.assertIn("error", result)

    def test_activate_bridge_not_found_bridge_id_in_result(self):
        plane = _make_plane()
        result = plane.activate_bridge("my_bridge")
        self.assertEqual(result["bridge_id"], "my_bridge")

    def test_activate_bridge_found_activated_true(self):
        plane = _make_plane()
        plane._bridges["b1"] = {"name": "b1"}
        result = plane.activate_bridge("b1")
        self.assertTrue(result["activated"])

    def test_activate_bridge_found_status_is_active(self):
        plane = _make_plane()
        plane._bridges["b1"] = {"name": "b1"}
        result = plane.activate_bridge("b1")
        self.assertEqual(result["status"], "active")

    def test_activate_bridge_found_has_activated_at(self):
        plane = _make_plane()
        plane._bridges["b1"] = {"name": "b1"}
        result = plane.activate_bridge("b1")
        self.assertIn("activated_at", result)
        self.assertIsInstance(result["activated_at"], int)

    def test_active_bridges_updated_after_activate(self):
        plane = _make_plane()
        plane._bridges["b2"] = {}
        plane.activate_bridge("b2")
        self.assertIn("b2", plane._active_bridges)

    def test_active_bridges_not_updated_if_not_found(self):
        plane = _make_plane()
        plane.activate_bridge("ghost")
        self.assertNotIn("ghost", plane._active_bridges)

    def test_instantiation_with_bus_mock(self):
        bus = MagicMock()
        plane = _make_plane(bus=bus)
        self.assertIsNotNone(plane)
        self.assertIsInstance(plane._bridges, dict)
        self.assertIsInstance(plane._active_bridges, dict)

    def test_bus_publish_nowait_called_on_activate_found(self):
        bus = MagicMock()
        plane = _make_plane(bus=bus)
        plane._bridges["b3"] = {}
        plane.activate_bridge("b3")
        bus.publish_nowait.assert_called_once()
        args = bus.publish_nowait.call_args[0]
        self.assertEqual(args[0], "integration/bridge/activated")

    def test_bus_publish_nowait_called_on_activate_not_found(self):
        bus = MagicMock()
        plane = _make_plane(bus=bus)
        plane.activate_bridge("missing")
        bus.publish_nowait.assert_called_once()
        args = bus.publish_nowait.call_args[0]
        self.assertEqual(args[0], "integration/bridge/activated")

    def test_bus_failure_on_activate_does_not_propagate(self):
        bus = MagicMock()
        bus.publish_nowait.side_effect = RuntimeError("bus down")
        plane = _make_plane(bus=bus)
        result = plane.activate_bridge("any")
        self.assertIsInstance(result, dict)  # no exception raised


class TestInvokeBridge(unittest.TestCase):
    def test_invoke_bridge_returns_dict(self):
        plane = _make_plane()
        result = plane.invoke_bridge("b")
        self.assertIsInstance(result, dict)

    def test_invoke_bridge_auto_activates_unactivated(self):
        plane = _make_plane()
        plane._bridges["auto"] = {}
        plane.invoke_bridge("auto")
        self.assertIn("auto", plane._active_bridges)

    def test_invoke_bridge_no_executor_returns_metadata_note(self):
        plane = _make_plane()
        plane._bridges["meta"] = {"name": "meta"}  # no executor key
        result = plane.invoke_bridge("meta")
        self.assertIn("note", result)
        self.assertIn("metadata-only", result["note"])

    def test_invoke_bridge_no_executor_invoked_true(self):
        plane = _make_plane()
        plane._bridges["meta2"] = {}
        result = plane.invoke_bridge("meta2")
        self.assertTrue(result["invoked"])

    def test_invoke_bridge_with_callable_executor_calls_it(self):
        plane = _make_plane()
        executor = MagicMock(return_value={"ok": True})
        plane._bridges["ex"] = {"executor": executor}
        plane.invoke_bridge("ex", payload={"x": 1})
        executor.assert_called_once_with({"x": 1})

    def test_invoke_bridge_with_callable_executor_returns_result(self):
        plane = _make_plane()
        plane._bridges["ex2"] = {"executor": lambda p: "done"}
        result = plane.invoke_bridge("ex2", payload=None)
        self.assertEqual(result["result"], "done")
        self.assertTrue(result["invoked"])

    def test_invoke_bridge_executor_raises_returns_error_dict(self):
        plane = _make_plane()

        def bad_executor(p):
            raise ValueError("boom")

        plane._bridges["bad"] = {"executor": bad_executor}
        result = plane.invoke_bridge("bad")
        self.assertFalse(result["invoked"])
        self.assertIn("error", result)
        self.assertIn("boom", result["error"])

    def test_invoke_bridge_executor_raises_no_propagation(self):
        plane = _make_plane()
        plane._bridges["bad2"] = {"executor": lambda p: 1 / 0}
        try:
            plane.invoke_bridge("bad2")
        except Exception:
            self.fail("invoke_bridge propagated an exception from executor")

    def test_bus_publish_nowait_called_on_invoke(self):
        bus = MagicMock()
        plane = _make_plane(bus=bus)
        plane._bridges["ev"] = {}
        plane.invoke_bridge("ev")
        topics = [call[0][0] for call in bus.publish_nowait.call_args_list]
        self.assertIn("integration/bridge/invoked", topics)

    def test_bus_failure_on_invoke_does_not_propagate(self):
        bus = MagicMock()
        bus.publish_nowait.side_effect = RuntimeError("bus down")
        plane = _make_plane(bus=bus)
        plane._bridges["ev2"] = {}
        result = plane.invoke_bridge("ev2")
        self.assertIsInstance(result, dict)

    def test_invoke_bridge_payload_echoed_in_metadata_only(self):
        plane = _make_plane()
        plane._bridges["pecho"] = {}
        payload = {"key": "val"}
        result = plane.invoke_bridge("pecho", payload=payload)
        self.assertEqual(result["payload_echo"], payload)

    def test_invoke_bridge_has_executed_at(self):
        plane = _make_plane()
        plane._bridges["ts"] = {}
        result = plane.invoke_bridge("ts")
        self.assertIn("executed_at", result)
        self.assertIsInstance(result["executed_at"], int)
