"""Tests for core.activation_plane — ActivationPlane status methods.

All tests use mocked dependencies; no network or disk I/O.
"""
from __future__ import annotations
import unittest
from unittest.mock import MagicMock, patch

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


class TestActivationPlaneAuthStatus(unittest.TestCase):
    def test_auth_status_has_expected_keys(self):
        plane = _make_plane()
        result = plane.auth_status()
        for key in ("enabled", "header", "user_token_configured", "admin_token_configured", "protected_mutations"):
            self.assertIn(key, result)

    def test_auth_status_protected_mutations_always_true(self):
        plane = _make_plane()
        result = plane.auth_status()
        self.assertTrue(result["protected_mutations"])


class TestActivationPlaneConfigureModelRoles(unittest.TestCase):
    def test_configure_model_roles_delegates_and_publishes(self):
        mock_roles = MagicMock()
        mock_roles.status.return_value = {}
        mock_roles.configure.return_value = {"status": "ok", "roles": {}}
        mock_bus = MagicMock()
        plane = ActivationPlane(
            profile_getter=lambda: {},
            refresh_profile=lambda: {},
            credential_store=MagicMock(),
            model_registry=MagicMock(),
            model_roles=mock_roles,
            bus=mock_bus,
        )
        result = plane.configure_model_roles({"reasoning": "mistral-7b"})
        self.assertEqual(result["status"], "ok")
        mock_bus.publish_nowait.assert_called_once()


class TestActivationPlaneFallbackLearningRankings(unittest.TestCase):
    def test_fallback_learning_with_ranked_models(self):
        """learned_rankings with degraded models should be reflected in output."""
        plane = _make_plane()
        registry = {
            "discovery": {
                "learned_rankings_available": True,
                "scouted_models_available": True,
            },
            "recommendations": {
                "learned_free_rankings": [
                    {"id": "model-a", "query_type": "reasoning", "rank": 1, "score": 0.9, "confidence": 0.8, "degraded": False},
                    {"id": "model-b", "query_type": "general", "rank": 2, "score": 0.7, "confidence": 0.6, "degraded": True},
                ]
            },
        }
        result = plane.fallback_learning_summary(registry=registry)
        self.assertTrue(result["learned_rankings_available"])
        self.assertEqual(len(result["top_ranked_models"]), 2)
        self.assertIn("model-b", result["degraded_models"])


# ---------------------------------------------------------------------------
# Line 52: continue branch when learned_rankings contains non-dict items
# ---------------------------------------------------------------------------

class TestActivationPlaneFallbackLearningEdgeCases(unittest.TestCase):
    def test_non_dict_items_in_rankings_are_skipped(self) -> None:
        plane = _make_plane()
        registry = {
            "recommendations": {
                "learned_free_rankings": [
                    "not-a-dict",
                    None,
                    42,
                    {"id": "model-kept", "query_type": "general", "rank": 1,
                     "score": 0.9, "confidence": 0.8, "degraded": False},
                ]
            },
        }
        result = plane.fallback_learning_summary(registry=registry)
        self.assertEqual(len(result["top_ranked_models"]), 1)
        self.assertEqual(result["top_ranked_models"][0]["id"], "model-kept")


# ---------------------------------------------------------------------------
# set_provider_credential / delete_provider_credential / refresh_model_registry
# Lines 111-131
# ---------------------------------------------------------------------------

class TestActivationPlaneCredentialMutations(unittest.TestCase):
    def _make_plane_with_mocks(self):
        mock_cred = MagicMock()
        mock_registry = MagicMock()
        mock_bus = MagicMock()
        plane = ActivationPlane(
            profile_getter=lambda: {},
            refresh_profile=lambda: {},
            credential_store=mock_cred,
            model_registry=mock_registry,
            model_roles=MagicMock(),
            bus=mock_bus,
        )
        return plane, mock_cred, mock_registry, mock_bus

    def test_set_provider_credential_delegates_and_publishes(self) -> None:
        plane, mock_cred, mock_registry, mock_bus = self._make_plane_with_mocks()
        mock_cred.set_provider_credential.return_value = {"status": "ok"}

        result = plane.set_provider_credential("openai", "api_key", "sk-test")
        self.assertEqual(result, {"status": "ok"})
        mock_cred.set_provider_credential.assert_called_once_with("openai", "api_key", "sk-test")
        mock_registry.refresh.assert_called_once()
        mock_bus.publish_nowait.assert_called_once()

    def test_delete_provider_credential_delegates_and_publishes(self) -> None:
        plane, mock_cred, mock_registry, mock_bus = self._make_plane_with_mocks()
        mock_cred.delete_provider_credential.return_value = {"status": "deleted"}

        result = plane.delete_provider_credential("openai", "api_key")
        self.assertEqual(result, {"status": "deleted"})
        mock_cred.delete_provider_credential.assert_called_once_with("openai", "api_key")
        mock_registry.refresh.assert_called_once()
        mock_bus.publish_nowait.assert_called_once()

    def test_refresh_model_registry_delegates_and_publishes(self) -> None:
        plane, _, mock_registry, mock_bus = self._make_plane_with_mocks()
        mock_registry.refresh.return_value = {"providers": [], "discovery": {}}

        result = plane.refresh_model_registry()
        self.assertEqual(result, {"providers": [], "discovery": {}})
        mock_registry.refresh.assert_called_once()
        mock_bus.publish_nowait.assert_called_once()


# ---------------------------------------------------------------------------
# configure_provider_activation (lines 139-160)
# ---------------------------------------------------------------------------

class TestActivationPlaneConfigureProvider(unittest.TestCase):
    def _make_plane_with_mocks(self):
        mock_registry = MagicMock()
        mock_registry.refresh.return_value = {"providers": ["openai"], "discovery": {}}
        mock_bus = MagicMock()
        refreshed: list[dict] = []
        plane = ActivationPlane(
            profile_getter=lambda: {},
            refresh_profile=lambda: refreshed.append({}) or {},
            credential_store=MagicMock(),
            model_registry=mock_registry,
            model_roles=MagicMock(),
            bus=mock_bus,
        )
        return plane, mock_registry, mock_bus

    def test_configure_provider_activation_with_all_params(self) -> None:
        plane, mock_registry, mock_bus = self._make_plane_with_mocks()
        fake_profile: dict = {}

        with patch("core.activation_plane.load_runtime_profile", return_value=fake_profile), \
             patch("core.activation_plane.save_runtime_profile") as mock_save:
            result = plane.configure_provider_activation(
                enabled_provider_ids=["openai", "ollama"],
                preferred_cloud_provider="openai",
                prefer_free_models=True,
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["preferred_cloud_provider"], "openai")
        self.assertTrue(result["prefer_free_models"])
        mock_save.assert_called_once()
        mock_registry.refresh.assert_called_once()
        mock_bus.publish_nowait.assert_called_once()

    def test_configure_provider_activation_with_no_params(self) -> None:
        plane, mock_registry, mock_bus = self._make_plane_with_mocks()
        fake_profile: dict = {}

        with patch("core.activation_plane.load_runtime_profile", return_value=fake_profile), \
             patch("core.activation_plane.save_runtime_profile"):
            result = plane.configure_provider_activation()

        self.assertEqual(result["status"], "ok")
        mock_registry.refresh.assert_called_once()

    def test_configure_provider_activation_prefer_free_models_flag(self) -> None:
        plane, _, _ = self._make_plane_with_mocks()
        fake_profile: dict = {}

        with patch("core.activation_plane.load_runtime_profile", return_value=fake_profile), \
             patch("core.activation_plane.save_runtime_profile"):
            result = plane.configure_provider_activation(prefer_free_models=False)

        self.assertFalse(result["prefer_free_models"])

