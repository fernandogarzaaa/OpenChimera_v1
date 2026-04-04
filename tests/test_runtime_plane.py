from __future__ import annotations

import unittest
from unittest.mock import MagicMock
from unittest.mock import patch

from core.runtime_plane import RuntimePlane


def _make_plane(**overrides) -> RuntimePlane:
    """Factory that wires sensible MagicMock defaults for all RuntimePlane deps."""
    defaults = dict(
        base_url_getter=lambda: "http://127.0.0.1:7870",
        profile_getter=lambda: {"local_runtime": {"context_length": 4096}},
        llm_manager=MagicMock(
            get_status=MagicMock(return_value={"models": {}, "healthy_count": 0, "total_count": 0}),
            get_runtime_status=MagicMock(return_value={}),
        ),
        rag=MagicMock(get_status=MagicMock(return_value={})),
        router=MagicMock(status=MagicMock(return_value={})),
        harness_port=MagicMock(status=MagicMock(return_value={})),
        minimind=MagicMock(status=MagicMock(return_value={})),
        autonomy=MagicMock(status=MagicMock(return_value={})),
        observability=MagicMock(snapshot=MagicMock(return_value={})),
        health_getter=lambda: {"status": "online"},
        autonomy_diagnostics_getter=lambda: {},
        aegis_status_getter=lambda: {},
        ascension_status_getter=lambda: {},
        model_registry_status_getter=lambda: {},
        browser_status_getter=lambda: {},
        media_status_getter=lambda: {},
        query_status_getter=lambda: {},
        model_role_status_getter=lambda: {},
        plugin_status_getter=lambda: {},
        tool_status_getter=lambda: {},
        subsystem_status_getter=lambda: {},
        onboarding_status_getter=lambda: {},
        integration_status_getter=lambda: {},
    )
    defaults.update(overrides)
    return RuntimePlane(**defaults)


_STUB_DEPLOYMENT = {"mode": "local", "containerized": False, "transport": {"tls_enabled": False}}


class RuntimePlaneTests(unittest.TestCase):
    def test_status_includes_deployment_summary(self) -> None:
        plane = _make_plane()
        with patch("core.runtime_plane.build_deployment_status", return_value=_STUB_DEPLOYMENT):
            payload = plane.status()
        self.assertEqual(payload["deployment"]["mode"], "local")
        self.assertFalse(payload["deployment"]["containerized"])

    def test_instantiation_succeeds(self) -> None:
        """RuntimePlane can be constructed with valid deps without raising."""
        plane = _make_plane()
        self.assertIsInstance(plane, RuntimePlane)

    def test_health_returns_dict(self) -> None:
        """health() delegates to health_getter and returns its dict."""
        plane = _make_plane(health_getter=lambda: {"status": "online", "uptime_seconds": 42})
        result = plane.health()
        self.assertIsInstance(result, dict)
        self.assertEqual(result["status"], "online")

    def test_status_contains_required_top_level_keys(self) -> None:
        """status() includes all expected top-level keys."""
        plane = _make_plane()
        with patch("core.runtime_plane.build_deployment_status", return_value=_STUB_DEPLOYMENT):
            payload = plane.status()
        for key in ("online", "base_url", "deployment", "health", "models", "llm", "router", "rag"):
            self.assertIn(key, payload)

    def test_status_online_flag_true_when_health_online(self) -> None:
        """status()['online'] is True when health status is 'online'."""
        plane = _make_plane(health_getter=lambda: {"status": "online"})
        with patch("core.runtime_plane.build_deployment_status", return_value=_STUB_DEPLOYMENT):
            payload = plane.status()
        self.assertTrue(payload["online"])

    def test_status_online_flag_false_when_health_degraded(self) -> None:
        """status()['online'] is False when health reports a non-online status."""
        plane = _make_plane(health_getter=lambda: {"status": "degraded"})
        with patch("core.runtime_plane.build_deployment_status", return_value=_STUB_DEPLOYMENT):
            payload = plane.status()
        self.assertFalse(payload["online"])

    def test_list_models_always_includes_openchimera_local(self) -> None:
        """list_models() always appends the built-in openchimera-local model."""
        plane = _make_plane()
        result = plane.list_models()
        self.assertIn("data", result)
        ids = [m["id"] for m in result["data"]]
        self.assertIn("openchimera-local", ids)

    def test_subsystem_methods_delegate_to_mocks(self) -> None:
        """Subsystem delegation helpers call through to their injected mocks."""
        plane = _make_plane()
        self.assertIsInstance(plane.minimind_status(), dict)
        self.assertIsInstance(plane.autonomy_status(), dict)
        self.assertIsInstance(plane.observability_status(), dict)
        self.assertIsInstance(plane.harness_port_status(), dict)


if __name__ == "__main__":
    unittest.main()