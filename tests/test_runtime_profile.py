from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import config


class RuntimeProfileTests(unittest.TestCase):
    def test_local_override_profile_is_merged(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base_path = Path(temp_dir) / "runtime_profile.json"
            override_path = Path(temp_dir) / "runtime_profile.local.json"
            base_path.write_text(
                json.dumps(
                    {
                        "providers": {"enabled": ["openchimera-gateway", "openai"]},
                        "api": {"auth": {"enabled": False, "token": ""}},
                    }
                ),
                encoding="utf-8",
            )
            override_path.write_text(
                json.dumps(
                    {
                        "providers": {"preferred_cloud_provider": "openai"},
                        "api": {"auth": {"enabled": True, "token": "test-user-token"}},
                    }
                ),
                encoding="utf-8",
            )

            config.load_runtime_profile.cache_clear()
            with patch.object(config, "get_runtime_profile_path", return_value=base_path), patch.object(
                config, "get_runtime_profile_override_path", return_value=override_path
            ):
                profile = config.load_runtime_profile()

            self.assertEqual(profile["providers"]["enabled"], ["openchimera-gateway", "openai"])
            self.assertEqual(profile["providers"]["preferred_cloud_provider"], "openai")
            self.assertTrue(profile["api"]["auth"]["enabled"])

    def test_legacy_root_falls_back_to_real_default_when_profile_points_to_missing_bootstrap_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_profile_root = Path(temp_dir) / "external" / "legacy-workspace"
            real_default_root = Path(temp_dir) / "openclaw"
            real_default_root.mkdir(parents=True)
            profile = {
                "external_roots": {
                    "legacy_workspace": str(missing_profile_root),
                    "openclaw": str(missing_profile_root),
                }
            }

            with patch.object(config, "load_runtime_profile", return_value=profile), patch.object(
                config, "DEFAULT_LEGACY_WORKSPACE_ROOT", real_default_root
            ), patch.dict("os.environ", {}, clear=False):
                resolved = config.get_legacy_workspace_root()

            self.assertEqual(resolved, real_default_root)

    def test_legacy_root_honors_env_override_before_profile_or_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_root = Path(temp_dir) / "env-legacy"
            profile_root = Path(temp_dir) / "profile-legacy"
            default_root = Path(temp_dir) / "default-legacy"
            profile = {
                "external_roots": {
                    "legacy_workspace": str(profile_root),
                    "openclaw": str(profile_root),
                }
            }

            with patch.object(config, "load_runtime_profile", return_value=profile), patch.object(
                config, "DEFAULT_LEGACY_WORKSPACE_ROOT", default_root
            ), patch.dict("os.environ", {"OPENCLAW_ROOT": str(env_root)}, clear=False):
                resolved = config.get_legacy_workspace_root()

            self.assertEqual(resolved, env_root)

    def test_legacy_harness_snapshot_falls_back_to_real_default_when_profile_points_to_missing_bootstrap_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_profile_root = Path(temp_dir) / "external" / "legacy-harness-snapshot"
            real_default_root = Path(temp_dir) / "openclaw" / "integrations" / "legacy-harness-snapshot"
            real_default_root.mkdir(parents=True)
            profile = {
                "integration_roots": {
                    "legacy_harness_snapshot": str(missing_profile_root),
                }
            }

            with patch.object(config, "load_runtime_profile", return_value=profile), patch.object(
                config, "DEFAULT_LEGACY_HARNESS_SNAPSHOT_ROOT", real_default_root
            ), patch.dict("os.environ", {}, clear=False):
                resolved = config.get_legacy_harness_snapshot_root()

            self.assertEqual(resolved, real_default_root)

    def test_legacy_harness_snapshot_honors_env_override_before_profile_or_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_root = Path(temp_dir) / "env-snapshot"
            profile_root = Path(temp_dir) / "profile-snapshot"
            default_root = Path(temp_dir) / "default-snapshot"
            profile = {
                "integration_roots": {
                    "legacy_harness_snapshot": str(profile_root),
                }
            }

            with patch.object(config, "load_runtime_profile", return_value=profile), patch.object(
                config, "DEFAULT_LEGACY_HARNESS_SNAPSHOT_ROOT", default_root
            ), patch.dict("os.environ", {"OPENCHIMERA_LEGACY_HARNESS_ROOT": str(env_root)}, clear=False):
                resolved = config.get_legacy_harness_snapshot_root()

            self.assertEqual(resolved, env_root)

    def test_load_runtime_profile_rejects_enabled_auth_without_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base_path = Path(temp_dir) / "runtime_profile.json"
            base_path.write_text(
                json.dumps(
                    {
                        "api": {
                            "auth": {
                                "enabled": True,
                                "token": "",
                                "admin_token": "",
                                "header": "Authorization",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            config.load_runtime_profile.cache_clear()
            with patch.object(config, "get_runtime_profile_path", return_value=base_path), patch.object(
                config, "get_runtime_profile_override_path", return_value=Path(temp_dir) / "runtime_profile.local.json"
            ), patch.dict("os.environ", {}, clear=False):
                with self.assertRaisesRegex(ValueError, "api.auth.enabled requires a user token"):
                    config.load_runtime_profile()

    def test_load_runtime_profile_rejects_enabled_tls_without_key_material(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base_path = Path(temp_dir) / "runtime_profile.json"
            base_path.write_text(
                json.dumps(
                    {
                        "api": {
                            "tls": {
                                "enabled": True,
                                "certfile": "certs/server.crt",
                                "keyfile": "",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            config.load_runtime_profile.cache_clear()
            with patch.object(config, "get_runtime_profile_path", return_value=base_path), patch.object(
                config, "get_runtime_profile_override_path", return_value=Path(temp_dir) / "runtime_profile.local.json"
            ):
                with self.assertRaisesRegex(ValueError, "api.tls.enabled requires a keyfile"):
                    config.load_runtime_profile()

    def test_load_runtime_profile_rejects_preferred_cloud_provider_not_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            base_path = Path(temp_dir) / "runtime_profile.json"
            base_path.write_text(
                json.dumps(
                    {
                        "providers": {
                            "enabled": ["openchimera-gateway", "minimind"],
                            "preferred_cloud_provider": "openai",
                        }
                    }
                ),
                encoding="utf-8",
            )

            config.load_runtime_profile.cache_clear()
            with patch.object(config, "get_runtime_profile_path", return_value=base_path), patch.object(
                config, "get_runtime_profile_override_path", return_value=Path(temp_dir) / "runtime_profile.local.json"
            ):
                with self.assertRaisesRegex(ValueError, "preferred_cloud_provider"):
                    config.load_runtime_profile()

    def test_runtime_profile_local_example_is_valid_json(self) -> None:
        example_path = Path(__file__).resolve().parents[1] / "config" / "runtime_profile.local.example.json"
        payload = json.loads(example_path.read_text(encoding="utf-8"))

        # auth disabled by default — users opt in when exposing beyond loopback
        self.assertFalse(payload["api"]["auth"]["enabled"])
        # prefer_free_models is the safe out-of-the-box default
        self.assertTrue(payload["providers"]["prefer_free_models"])


if __name__ == "__main__":
    unittest.main()