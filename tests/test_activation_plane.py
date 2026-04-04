"""Tests for core.activation_plane — ActivationPlane status methods.

All tests use mocked dependencies; no network or disk I/O.
"""
from __future__ import annotations
import unittest
from unittest.mock import MagicMock

from core.activation_plane import ActivationPlane


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_plane(
    profile: dict | None = None,
    model_registry_status: dict | None = None,
    credential_status: dict | None = None,
    model_roles_status: dict | None = None,
) -> ActivationPlane:
    profile = profile or {"providers": {"prefer_free_models": True}}
    model_registry_status = model_registry_status or {"providers": [], "cloud_models": []}
    credential_status = credential_status or {}
    model_roles_status = model_roles_status or {}

    mock_registry = MagicMock()
    mock_registry.status.return_value = model_registry_status

    mock_cred = MagicMock()
    mock_cred.status.return_value = credential_status

    mock_roles = MagicMock()
    mock_roles.status.return_value = model_roles_status

    mock_bus = MagicMock()
    mock_bus.publish_nowait = MagicMock()

    return ActivationPlane(
        profile_getter=lambda: dict(profile),
        refresh_profile=lambda: dict(profile),
        credential_store=mock_cred,
        model_registry=mock_registry,
        model_roles=mock_roles,
        bus=mock_bus,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestActivationPlaneProfile(unittest.TestCase):
    def test_profile_returns_dict(self):
        plane = _make_plane()
        result = plane.profile()
        self.assertIsInstance(result, dict)

    def test_profile_is_a_copy(self):
        source = {"providers": {"prefer_free_models": False}}
        plane = _make_plane(profile=source)
        profile = plane.profile()
        profile["injected"] = True
        # Mutating the returned dict must not affect the source
        result2 = plane.profile()
        self.assertNotIn("injected", result2)

    def test_profile_none_returns_empty_dict(self):
        plane = ActivationPlane(
            profile_getter=lambda: None,  # type: ignore[return-value]
            refresh_profile=lambda: {},
            credential_store=MagicMock(),
            model_registry=MagicMock(),
            model_roles=MagicMock(),
            bus=MagicMock(),
        )
        # Should not raise; returns {}
        self.assertEqual(plane.profile(), {})


class TestActivationPlaneModelRegistry(unittest.TestCase):
    def test_model_registry_status_returns_expected(self):
        expected = {"providers": [{"id": "ollama"}], "cloud_models": []}
        plane = _make_plane(model_registry_status=expected)
        result = plane.model_registry_status()
        self.assertEqual(result, expected)


class TestActivationPlaneCredential(unittest.TestCase):
    def test_credential_status_returns_expected(self):
        expected = {"openai": False, "anthropic": False}
        plane = _make_plane(credential_status=expected)
        result = plane.credential_status()
        self.assertEqual(result, expected)


class TestActivationPlaneFallbackLearning(unittest.TestCase):
    def test_fallback_learning_summary_returns_dict(self):
        plane = _make_plane()
        result = plane.fallback_learning_summary()
        self.assertIsInstance(result, dict)

    def test_fallback_learning_summary_accepts_registry_override(self):
        plane = _make_plane()
        registry_override = {"cloud_models": [], "discovery": {"scouted_count": 5}}
        result = plane.fallback_learning_summary(registry=registry_override)
        self.assertIsInstance(result, dict)


class TestActivationPlaneProviderActivationStatus(unittest.TestCase):
    def test_provider_activation_status_returns_dict(self):
        plane = _make_plane()
        result = plane.provider_activation_status()
        self.assertIsInstance(result, dict)

    def test_provider_activation_status_has_list(self):
        plane = _make_plane(model_registry_status={"providers": [{"id": "ollama", "enabled": True}], "cloud_models": []})
        result = plane.provider_activation_status()
        self.assertIsInstance(result, dict)


class TestActivationPlaneModelRoleStatus(unittest.TestCase):
    def test_model_role_status_returns_dict(self):
        plane = _make_plane(model_roles_status={"roles": []})
        result = plane.model_role_status()
        self.assertIsInstance(result, dict)


if __name__ == "__main__":
    unittest.main()
