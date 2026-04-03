from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import config
from core.model_registry import ModelRegistry
from core.model_roles import ModelRoleManager


class ModelRoleManagerTests(unittest.TestCase):
    def test_role_resolution_and_override_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            profile_path = Path(temp_dir) / "runtime_profile.json"
            profile_path.write_text(
                json.dumps(
                    {
                        "providers": {"enabled": ["local-llama-cpp"], "preferred_cloud_provider": ""},
                        "local_runtime": {"preferred_local_models": ["qwen2.5-7b"], "model_roles": {}},
                    }
                ),
                encoding="utf-8",
            )
            config.load_runtime_profile.cache_clear()
            registry = ModelRegistry()
            registry.registry_path = Path(temp_dir) / "model_registry.json"
            registry.profile = {
                "hardware": {"cpu_count": 8, "ram_gb": 16, "gpu": {"available": True, "name": "RTX 2060", "vram_gb": 6, "device_count": 1}},
                "model_inventory": {"available_models": ["phi-3.5-mini", "qwen2.5-7b", "llama-3.2-3b"], "models_dir": temp_dir},
                "local_runtime": {"preferred_local_models": ["qwen2.5-7b"]},
                "providers": {"enabled": ["local-llama-cpp"], "preferred_cloud_provider": ""},
            }
            registry.refresh()

            with patch.object(config, "get_runtime_profile_path", return_value=profile_path):
                manager = ModelRoleManager(registry)
                status = manager.status()
                self.assertEqual(status["roles"]["code_model"]["model"], "qwen2.5-7b")

                updated = manager.configure({"fast_model": "llama-3.2-3b"})
                self.assertEqual(updated["roles"]["fast_model"]["model"], "llama-3.2-3b")


if __name__ == "__main__":
    unittest.main()
