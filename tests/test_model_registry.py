from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.model_registry import ModelRegistry


class ModelRegistryTests(unittest.TestCase):
    def test_refresh_builds_registry_and_onboarding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            registry_path = Path(temp_dir) / "model_registry.json"
            registry = ModelRegistry()
            registry.registry_path = registry_path
            registry.profile = {
                "hardware": {
                    "cpu_count": 16,
                    "ram_gb": 32,
                    "gpu": {"available": True, "name": "RTX 4070", "vram_gb": 12, "device_count": 1},
                },
                "model_inventory": {
                    "available_models": ["phi-3.5-mini", "qwen2.5-7b"],
                    "model_files": {"phi-3.5-mini": str(Path(temp_dir) / "phi.gguf")},
                    "models_dir": temp_dir,
                },
                "local_runtime": {"model_endpoints": {"phi-3.5-mini": "http://127.0.0.1:8080"}},
            }
            (Path(temp_dir) / "phi.gguf").write_text("stub", encoding="utf-8")

            payload = registry.refresh()

            self.assertTrue(registry_path.exists())
            self.assertEqual(payload["hardware"]["gpu"]["name"], "RTX 4070")
            self.assertEqual(payload["onboarding"]["minimind_optimization_profile"]["approach"], "airllm-inspired")
            self.assertTrue(any(model["id"] == "phi-3.5-mini" for model in payload["recommendations"]["suggested_local_models"]))

            on_disk = json.loads(registry_path.read_text(encoding="utf-8"))
            self.assertIn("providers", on_disk)

    def test_cpu_only_hardware_recommends_cloud_fallback(self) -> None:
        registry = ModelRegistry()
        registry.profile = {
            "hardware": {
                "cpu_count": 8,
                "ram_gb": 8,
                "gpu": {"available": False, "name": "", "vram_gb": 0, "device_count": 0},
            },
            "model_inventory": {"available_models": []},
            "local_runtime": {},
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            registry.registry_path = Path(temp_dir) / "model_registry.json"
            payload = registry.refresh()

        self.assertTrue(payload["recommendations"]["needs_cloud_fallback"])
        self.assertGreaterEqual(len(payload["recommendations"]["suggested_cloud_models"]), 1)


if __name__ == "__main__":
    unittest.main()