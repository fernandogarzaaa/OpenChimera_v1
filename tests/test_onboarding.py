from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.channels import ChannelManager
from core.credential_store import CredentialStore
from core.model_registry import ModelRegistry
from core.onboarding import OnboardingManager


class OnboardingTests(unittest.TestCase):
    def test_status_treats_cloud_credentials_as_optional_for_local_only_install(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            state_path = temp_root / "onboarding_state.json"
            channel_store = temp_root / "subscriptions.json"
            credential_store_path = temp_root / "credentials.json"
            registry_path = temp_root / "model_registry.json"
            local_asset = temp_root / "phi-3.5-mini-instruct-q8_0.gguf"
            local_asset.write_text("stub", encoding="utf-8")

            credentials = CredentialStore(store_path=credential_store_path)
            channels = ChannelManager(store_path=channel_store)
            registry = ModelRegistry(credential_store=credentials)
            registry.registry_path = registry_path
            profile_state = {
                "hardware": {"cpu_count": 8, "ram_gb": 16, "gpu": {"available": True, "name": "RTX 2060", "vram_gb": 6, "device_count": 1}},
                "model_inventory": {"available_models": ["phi-3.5-mini"], "model_files": {"phi-3.5-mini": str(local_asset)}, "models_dir": temp_dir, "search_roots": [temp_dir]},
                "local_runtime": {"preferred_local_models": ["phi-3.5-mini"]},
                "providers": {"enabled": ["openchimera-gateway", "local-llama-cpp", "minimind"], "preferred_cloud_provider": ""},
                "onboarding": {"preferred_channel_id": "ops-webhook", "completed_at": None, "selected_cloud_provider": ""},
                "external_roots": {},
                "integration_roots": {"harness_repo": temp_dir, "minimind": temp_dir},
            }
            registry.profile = profile_state
            registry.refresh()
            channels.upsert_subscription({"id": "ops-webhook", "channel": "webhook", "endpoint": "http://example.invalid", "topics": ["*"]})

            onboarding = OnboardingManager(
                registry,
                credentials,
                channels,
                state_path=state_path,
                profile_loader=lambda: json.loads(json.dumps(profile_state)),
                profile_saver=lambda profile: profile_state.update(json.loads(json.dumps(profile))),
            )

            status = onboarding.status()
            steps = {step["id"]: step for step in status["steps"]}

            self.assertTrue(steps["local-model"]["completed"])
            self.assertTrue(steps["provider-credentials"]["completed"])
            self.assertFalse(any("Cloud provider credentials" in blocker for blocker in status["blockers"]))

    def test_apply_updates_profile_credentials_and_channels(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            state_path = temp_root / "onboarding_state.json"
            channel_store = temp_root / "subscriptions.json"
            credential_store_path = temp_root / "credentials.json"
            registry_path = temp_root / "model_registry.json"
            local_asset = temp_root / "phi-3.5-mini-instruct-q8_0.gguf"
            local_asset.write_text("stub", encoding="utf-8")

            credentials = CredentialStore(store_path=credential_store_path)
            channels = ChannelManager(store_path=channel_store)
            registry = ModelRegistry(credential_store=credentials)
            registry.registry_path = registry_path
            profile_state = {
                "hardware": {"cpu_count": 8, "ram_gb": 16, "gpu": {"available": True, "name": "RTX 2060", "vram_gb": 6, "device_count": 1}},
                "model_inventory": {
                    "available_models": ["phi-3.5-mini", "qwen2.5-7b"],
                    "model_files": {"phi-3.5-mini": str(local_asset)},
                    "models_dir": temp_dir,
                    "search_roots": [temp_dir],
                },
                "local_runtime": {"preferred_local_models": ["phi-3.5-mini"]},
            }
            registry.profile = profile_state
            registry.refresh()

            def load_profile() -> dict[str, object]:
                return json.loads(json.dumps(profile_state))

            def save_profile(profile: dict[str, object]) -> None:
                profile_state.clear()
                profile_state.update(json.loads(json.dumps(profile)))
                registry.profile = dict(profile_state)

            onboarding = OnboardingManager(
                registry,
                credentials,
                channels,
                state_path=state_path,
                profile_loader=load_profile,
                profile_saver=save_profile,
            )

            result = onboarding.apply(
                {
                    "preferred_local_model": "qwen2.5-7b",
                    "enabled_provider_ids": ["openchimera-gateway", "local-llama-cpp", "minimind", "openai"],
                    "preferred_cloud_provider": "openai",
                    "prefer_free_models": True,
                    "provider_credentials": {"openai": {"OPENAI_API_KEY": "sk-test-123456"}},
                    "channel_subscription": {"id": "ops-webhook", "channel": "webhook", "endpoint": "http://example.invalid", "topics": ["system/briefing/daily"]},
                }
            )

            self.assertTrue(result["completed"])
            self.assertTrue(credentials.has_provider_credentials("openai", ["OPENAI_API_KEY"]))
            self.assertEqual(channels.status()["counts"]["total"], 1)
            self.assertEqual(profile_state["local_runtime"]["preferred_local_models"][0], "qwen2.5-7b")
            self.assertIn("openai", profile_state["providers"]["enabled"])
            self.assertEqual(profile_state["providers"]["preferred_cloud_provider"], "openai")
            self.assertTrue(profile_state["providers"]["prefer_free_models"])
            self.assertEqual(profile_state["onboarding"]["preferred_channel_id"], "ops-webhook")
            self.assertTrue(result["current_profile"]["prefer_free_models"])
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertIn("last_applied_at", state)

    def test_apply_registers_existing_local_model_asset(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            state_path = temp_root / "onboarding_state.json"
            channel_store = temp_root / "subscriptions.json"
            credential_store_path = temp_root / "credentials.json"
            registry_path = temp_root / "model_registry.json"
            asset_path = temp_root / "models-cache" / "qwen2.5-7b-instruct-q4_k_m.gguf"
            asset_path.parent.mkdir(parents=True)
            asset_path.write_text("stub", encoding="utf-8")

            credentials = CredentialStore(store_path=credential_store_path)
            channels = ChannelManager(store_path=channel_store)
            registry = ModelRegistry(credential_store=credentials)
            registry.registry_path = registry_path
            profile_state = {
                "hardware": {"cpu_count": 8, "ram_gb": 16, "gpu": {"available": True, "name": "RTX 2060", "vram_gb": 6, "device_count": 1}},
                "model_inventory": {"available_models": [], "model_files": {}, "models_dir": str(temp_root / "models")},
                "local_runtime": {"preferred_local_models": ["phi-3.5-mini"]},
                "providers": {"enabled": ["openchimera-gateway", "local-llama-cpp", "minimind"], "preferred_cloud_provider": ""},
                "onboarding": {"preferred_channel_id": "", "completed_at": None},
                "external_roots": {},
                "integration_roots": {"harness_repo": temp_dir, "minimind": temp_dir},
            }
            registry.profile = profile_state
            registry.refresh()

            def load_profile() -> dict[str, object]:
                return json.loads(json.dumps(profile_state))

            def save_profile(profile: dict[str, object]) -> None:
                profile_state.clear()
                profile_state.update(json.loads(json.dumps(profile)))
                registry.profile = dict(profile_state)

            onboarding = OnboardingManager(
                registry,
                credentials,
                channels,
                state_path=state_path,
                profile_loader=load_profile,
                profile_saver=save_profile,
            )

            result = onboarding.apply({"local_model_asset_path": str(asset_path)})

            self.assertEqual(profile_state["local_runtime"]["preferred_local_models"][0], "qwen2.5-7b")
            self.assertEqual(profile_state["model_inventory"]["model_files"]["qwen2.5-7b"], str(asset_path))
            self.assertIn(str(asset_path.parent), profile_state["model_inventory"]["search_roots"])
            self.assertTrue(result["current_profile"]["local_model_assets_available"])
            self.assertIn("qwen2.5-7b", result["current_profile"]["preferred_local_models"])

    def test_apply_updates_extended_open_source_runtime_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            state_path = temp_root / "onboarding_state.json"
            channel_store = temp_root / "subscriptions.json"
            credential_store_path = temp_root / "credentials.json"
            registry_path = temp_root / "model_registry.json"

            credentials = CredentialStore(store_path=credential_store_path)
            channels = ChannelManager(store_path=channel_store)
            registry = ModelRegistry(credential_store=credentials)
            registry.registry_path = registry_path
            profile_state = {
                "hardware": {"cpu_count": 8, "ram_gb": 16, "gpu": {"available": True, "name": "RTX 2060", "vram_gb": 6, "device_count": 1}},
                "model_inventory": {"available_models": ["phi-3.5-mini"], "models_dir": temp_dir},
                "local_runtime": {"preferred_local_models": ["phi-3.5-mini"]},
                "external_roots": {},
                "integration_roots": {"harness_repo": temp_dir, "minimind": temp_dir},
            }
            registry.profile = profile_state
            registry.refresh()

            def load_profile() -> dict[str, object]:
                return json.loads(json.dumps(profile_state))

            def save_profile(profile: dict[str, object]) -> None:
                profile_state.clear()
                profile_state.update(json.loads(json.dumps(profile)))
                registry.profile = dict(profile_state)

            onboarding = OnboardingManager(
                registry,
                credentials,
                channels,
                state_path=state_path,
                profile_loader=load_profile,
                profile_saver=save_profile,
            )

            onboarding.apply(
                {
                    "runtime_roots": {
                        "appforge": str(temp_root / "appforge"),
                        "aegis_mobile": str(temp_root / "AegisMobile"),
                    }
                }
            )

            self.assertEqual(profile_state["external_roots"]["appforge"], str(temp_root / "appforge"))
            self.assertEqual(profile_state["external_roots"]["aegis_mobile"], str(temp_root / "AegisMobile"))

    def test_status_surfaces_blockers_and_next_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            state_path = temp_root / "onboarding_state.json"
            channel_store = temp_root / "subscriptions.json"
            credential_store_path = temp_root / "credentials.json"
            registry_path = temp_root / "model_registry.json"

            credentials = CredentialStore(store_path=credential_store_path)
            channels = ChannelManager(store_path=channel_store)
            registry = ModelRegistry(credential_store=credentials)
            registry.registry_path = registry_path
            profile_state = {
                "hardware": {"cpu_count": 4, "ram_gb": 8, "gpu": {"available": False, "name": "cpu-only", "vram_gb": 0, "device_count": 0}},
                "model_inventory": {"available_models": [], "models_dir": temp_dir},
                "local_runtime": {"preferred_local_models": []},
                "providers": {"enabled": [], "preferred_cloud_provider": ""},
                "onboarding": {"preferred_channel_id": "", "completed_at": None},
                "external_roots": {},
                "integration_roots": {"harness_repo": str(temp_root / "missing-harness"), "minimind": str(temp_root / "missing-minimind")},
            }
            registry.profile = profile_state
            with patch("core.local_model_inventory.get_appforge_root", return_value=temp_root / "appforge"), patch(
                "core.local_model_inventory.get_legacy_workspace_root", return_value=temp_root / "legacy"
            ):
                registry.refresh()

            onboarding = OnboardingManager(
                registry,
                credentials,
                channels,
                state_path=state_path,
                profile_loader=lambda: json.loads(json.dumps(profile_state)),
                profile_saver=lambda profile: profile_state.update(json.loads(json.dumps(profile))),
            )

            with patch("core.local_model_inventory.get_appforge_root", return_value=temp_root / "appforge"), patch(
                "core.local_model_inventory.get_legacy_workspace_root", return_value=temp_root / "legacy"
            ):
                status = onboarding.status()
            self.assertFalse(status["completed"])
            self.assertGreaterEqual(len(status["blockers"]), 1)
            self.assertGreaterEqual(len(status["next_actions"]), 1)
            steps = {step["id"]: step for step in status["steps"]}
            self.assertFalse(steps["local-model"]["completed"])
            self.assertIn("No local GGUF model assets are configured or discovered", status["blockers"][0])
            self.assertTrue(any("openchimera channels --channel filesystem" in action for action in status["next_actions"]))
            self.assertTrue(any("--register-local-model-path" in action for action in status["next_actions"]))
            self.assertIn("provider_activation", status)
            self.assertIn("channel_preferences", status)
            self.assertIn("model_discovery", status)

    def test_status_recomputes_stale_saved_steps_from_live_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            state_path = temp_root / "onboarding_state.json"
            channel_store = temp_root / "subscriptions.json"
            credential_store_path = temp_root / "credentials.json"
            registry_path = temp_root / "model_registry.json"

            credentials = CredentialStore(store_path=credential_store_path)
            channels = ChannelManager(store_path=channel_store)
            registry = ModelRegistry(credential_store=credentials)
            registry.registry_path = registry_path
            profile_state = {
                "hardware": {"cpu_count": 4, "ram_gb": 8, "gpu": {"available": False, "name": "cpu-only", "vram_gb": 0, "device_count": 0}},
                "model_inventory": {"available_models": [], "model_files": {}, "models_dir": str(temp_root / "models")},
                "local_runtime": {"preferred_local_models": ["llama-3.2-3b"]},
                "providers": {"enabled": ["openchimera-gateway", "local-llama-cpp", "minimind"], "preferred_cloud_provider": ""},
                "onboarding": {"preferred_channel_id": "", "completed_at": None},
                "external_roots": {},
                "integration_roots": {"harness_repo": temp_dir, "minimind": temp_dir},
            }
            registry.profile = profile_state
            with patch("core.local_model_inventory.get_appforge_root", return_value=temp_root / "appforge"), patch(
                "core.local_model_inventory.get_legacy_workspace_root", return_value=temp_root / "legacy"
            ):
                registry.refresh()
            state_path.write_text(
                json.dumps(
                    {
                        "started_at": 0,
                        "last_applied_at": None,
                        "last_payload": {},
                        "steps": [{"id": "local-model", "completed": True, "detail": "llama-3.2-3b"}],
                        "completed": True,
                    }
                ),
                encoding="utf-8",
            )

            onboarding = OnboardingManager(
                registry,
                credentials,
                channels,
                state_path=state_path,
                profile_loader=lambda: json.loads(json.dumps(profile_state)),
                profile_saver=lambda profile: profile_state.update(json.loads(json.dumps(profile))),
            )

            with patch("core.local_model_inventory.get_appforge_root", return_value=temp_root / "appforge"), patch(
                "core.local_model_inventory.get_legacy_workspace_root", return_value=temp_root / "legacy"
            ):
                status = onboarding.status()
            steps = {step["id"]: step for step in status["steps"]}

            self.assertFalse(steps["local-model"]["completed"])
            self.assertFalse(status["completed"])

    def test_status_prefers_real_default_roots_over_missing_bootstrap_placeholders(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            state_path = temp_root / "onboarding_state.json"
            channel_store = temp_root / "subscriptions.json"
            credential_store_path = temp_root / "credentials.json"
            registry_path = temp_root / "model_registry.json"

            real_legacy = temp_root / "openclaw"
            real_appforge = temp_root / "appforge"
            real_mobile = temp_root / "AegisMobile"
            real_harness = temp_root / "harness"
            real_minimind = temp_root / "minimind"

            real_legacy.mkdir(parents=True)
            real_appforge.mkdir(parents=True)
            real_mobile.mkdir(parents=True)
            real_minimind.mkdir(parents=True)
            (real_harness / "src").mkdir(parents=True)
            for name in ["main.py", "port_manifest.py", "query_engine.py", "commands.py", "tools.py"]:
                (real_harness / "src" / name).write_text("", encoding="utf-8")

            credentials = CredentialStore(store_path=credential_store_path)
            channels = ChannelManager(store_path=channel_store)
            registry = ModelRegistry(credential_store=credentials)
            registry.registry_path = registry_path
            profile_state = {
                "hardware": {"cpu_count": 4, "ram_gb": 8, "gpu": {"available": False, "name": "cpu-only", "vram_gb": 0, "device_count": 0}},
                "model_inventory": {"available_models": ["phi-3.5-mini"], "models_dir": temp_dir},
                "local_runtime": {"preferred_local_models": ["phi-3.5-mini"]},
                "providers": {"enabled": ["openchimera-gateway"], "preferred_cloud_provider": ""},
                "onboarding": {"preferred_channel_id": "", "completed_at": None},
                "external_roots": {
                    "legacy_workspace": str(temp_root / "external" / "legacy-workspace"),
                    "openclaw": str(temp_root / "external" / "legacy-workspace"),
                    "appforge": str(temp_root / "external" / "appforge"),
                    "aegis_mobile": str(temp_root / "external" / "AegisMobile"),
                },
                "integration_roots": {
                    "harness_repo": str(temp_root / "external" / "upstream-harness-repo"),
                    "minimind": str(temp_root / "external" / "minimind"),
                },
            }
            registry.profile = profile_state
            registry.refresh()

            onboarding = OnboardingManager(
                registry,
                credentials,
                channels,
                state_path=state_path,
                profile_loader=lambda: json.loads(json.dumps(profile_state)),
                profile_saver=lambda profile: profile_state.update(json.loads(json.dumps(profile))),
            )

            with patch("core.onboarding.DEFAULT_LEGACY_WORKSPACE_ROOT", real_legacy), patch(
                "core.onboarding.DEFAULT_OPENCLAW_ROOT", real_legacy
            ), patch("core.onboarding.DEFAULT_APPFORGE_ROOT", real_appforge), patch(
                "core.onboarding.DEFAULT_AEGIS_MOBILE_ROOT", real_mobile
            ), patch("core.onboarding.DEFAULT_HARNESS_REPO_ROOT", real_harness), patch(
                "core.onboarding.DEFAULT_MINIMIND_ROOT", real_minimind
            ):
                status = onboarding.status()

            roots = status["validation"]["roots"]
            self.assertEqual(roots["legacy_workspace"]["path"], str(real_legacy))
            self.assertTrue(roots["legacy_workspace"]["exists"])
            self.assertEqual(roots["appforge"]["path"], str(real_appforge))
            self.assertTrue(roots["appforge"]["exists"])
            self.assertEqual(roots["aegis_mobile"]["path"], str(real_mobile))
            self.assertTrue(roots["aegis_mobile"]["exists"])
            self.assertEqual(roots["harness_repo"]["path"], str(real_harness))
            self.assertTrue(roots["harness_repo"]["exists"])
            self.assertEqual(roots["minimind"]["path"], str(real_minimind))
            self.assertTrue(roots["minimind"]["exists"])


if __name__ == "__main__":
    unittest.main()