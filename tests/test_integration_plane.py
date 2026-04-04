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
) -> IntegrationPlane:
    return IntegrationPlane(
        integration_audit=audit or _mock_audit(),
        mcp_status_getter=lambda: mcp_status or {"mcp_servers": []},
        aegis_status_getter=lambda: aegis_status or {"available": False},
        ascension_status_getter=lambda: ascension_status or {"available": False},
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
