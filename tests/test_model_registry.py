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
                "providers": {"prefer_free_models": True},
                "model_inventory": {
                    "available_models": ["phi-3.5-mini", "qwen2.5-7b"],
                    "model_files": {"phi-3.5-mini": str(Path(temp_dir) / "phi.gguf")},
                    "models_dir": temp_dir,
                },
                "local_runtime": {"model_endpoints": {"phi-3.5-mini": "http://127.0.0.1:8080"}},
            }
            (Path(temp_dir) / "phi.gguf").write_text("stub", encoding="utf-8")

            autonomy_root = Path(temp_dir) / "data" / "autonomy"
            autonomy_root.mkdir(parents=True)
            (autonomy_root / "scouted_models_registry.json").write_text(
                json.dumps(
                    {
                        "models": [
                            {"id": "openrouter/qwen-free", "provider": "openrouter", "recommended_for": ["fallback"], "source": "autonomy-discovery"}
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (autonomy_root / "learned_fallback_rankings.json").write_text(
                json.dumps(
                    {
                        "query_types": {
                            "general": [
                                {
                                    "model": "openrouter/qwen-free",
                                    "rank": 1,
                                    "score": 8.5,
                                    "confidence": 0.9,
                                    "degraded": False,
                                    "reasons": [],
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )

            with patch("core.model_registry.ROOT", Path(temp_dir)):
                payload = registry.refresh()

            self.assertTrue(registry_path.exists())
            self.assertEqual(payload["hardware"]["gpu"]["name"], "RTX 4070")
            self.assertEqual(payload["onboarding"]["minimind_optimization_profile"]["approach"], "airllm-inspired")
            self.assertTrue(any(model["id"] == "phi-3.5-mini" for model in payload["recommendations"]["suggested_local_models"]))
            self.assertTrue(payload["recommendations"]["prefer_free_models"])
            self.assertTrue(any(model["id"] == "openrouter/qwen-free" for model in payload["cloud_models"]))
            self.assertTrue(payload["discovery"]["scouted_models_available"])
            self.assertTrue(payload["discovery"]["learned_rankings_available"])
            learned = next(model for model in payload["cloud_models"] if model["id"] == "openrouter/qwen-free")
            self.assertEqual(learned["learned_rank"], 1)
            self.assertEqual(payload["recommendations"]["learned_free_rankings"][0]["id"], "openrouter/qwen-free")

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

    def test_refresh_discovers_local_models_from_search_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            search_root = Path(temp_dir) / "search-root"
            search_root.mkdir(parents=True)
            (search_root / "qwen2.5-7b-instruct-q4_k_m.gguf").write_text("stub", encoding="utf-8")

            registry = ModelRegistry()
            registry.registry_path = Path(temp_dir) / "model_registry.json"
            registry.profile = {
                "hardware": {
                    "cpu_count": 16,
                    "ram_gb": 32,
                    "gpu": {"available": True, "name": "RTX 4070", "vram_gb": 12, "device_count": 1},
                },
                "providers": {"prefer_free_models": False},
                "model_inventory": {
                    "available_models": [],
                    "model_files": {},
                    "models_dir": str(Path(temp_dir) / "models"),
                    "search_roots": [str(search_root)],
                },
                "local_runtime": {},
            }

            with patch("core.model_registry.ROOT", Path(temp_dir)):
                payload = registry.refresh()

            qwen = next(model for model in payload["local_models"] if model["id"] == "qwen2.5-7b")
            self.assertTrue(qwen["available_locally"])
            self.assertTrue(qwen["model_path_exists"])
            self.assertEqual(qwen["discovered_model_path"], str(search_root / "qwen2.5-7b-instruct-q4_k_m.gguf"))
            self.assertTrue(payload["discovery"]["local_model_assets_available"])
            self.assertIn("qwen2.5-7b", payload["discovery"]["local_discovered_models"])

    def test_refresh_discovers_local_models_from_recovered_appforge_src_models(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            appforge_root = temp_root / "appforge-main"
            recovered_models = appforge_root / "infrastructure" / "clawd-hybrid-rtx" / "src" / "models"
            recovered_models.mkdir(parents=True)
            discovered = recovered_models / "Phi-3.5-mini-instruct-q8_0.gguf"
            discovered.write_text("stub", encoding="utf-8")

            registry = ModelRegistry()
            registry.registry_path = temp_root / "model_registry.json"
            registry.profile = {
                "hardware": {
                    "cpu_count": 16,
                    "ram_gb": 32,
                    "gpu": {"available": True, "name": "RTX 4070", "vram_gb": 12, "device_count": 1},
                },
                "providers": {"prefer_free_models": False},
                "model_inventory": {
                    "available_models": [],
                    "model_files": {},
                    "models_dir": str(temp_root / "models"),
                    "search_roots": [],
                },
                "local_runtime": {},
            }

            with patch("core.model_registry.ROOT", temp_root), patch("core.local_model_inventory.get_appforge_root", return_value=appforge_root), patch(
                "core.local_model_inventory.get_legacy_workspace_root", return_value=temp_root / "legacy"
            ):
                payload = registry.refresh()

            phi = next(model for model in payload["local_models"] if model["id"] == "phi-3.5-mini")
            self.assertTrue(phi["available_locally"])
            self.assertEqual(phi["discovered_model_path"], str(discovered))
            self.assertTrue(payload["discovery"]["local_model_assets_available"])
            self.assertIn("phi-3.5-mini", payload["discovery"]["local_discovered_models"])

    def test_status_refreshes_when_persisted_discovery_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            appforge_root = temp_root / "appforge-main"
            recovered_models = appforge_root / "infrastructure" / "clawd-hybrid-rtx" / "src" / "models"
            recovered_models.mkdir(parents=True)
            discovered = recovered_models / "Qwen2.5-7B-Instruct-Q4_K_M.gguf"
            discovered.write_text("stub", encoding="utf-8")

            registry = ModelRegistry()
            registry.registry_path = temp_root / "model_registry.json"
            registry.profile = {
                "hardware": {
                    "cpu_count": 16,
                    "ram_gb": 32,
                    "gpu": {"available": True, "name": "RTX 4070", "vram_gb": 12, "device_count": 1},
                },
                "providers": {"prefer_free_models": False},
                "model_inventory": {
                    "available_models": [],
                    "model_files": {},
                    "models_dir": str(temp_root / "models"),
                    "search_roots": [],
                },
                "local_runtime": {},
            }
            registry.registry_path.write_text(
                json.dumps(
                    {
                        "generated_at": "stale",
                        "providers": [],
                        "local_models": [],
                        "cloud_models": [],
                        "discovery": {
                            "local_model_assets_available": False,
                            "local_discovered_models": [],
                            "local_search_roots": [str(temp_root / "models")],
                        },
                        "recommendations": {},
                        "onboarding": {},
                    }
                ),
                encoding="utf-8",
            )

            with patch("core.local_model_inventory.get_appforge_root", return_value=appforge_root), patch(
                "core.local_model_inventory.get_legacy_workspace_root", return_value=temp_root / "legacy"
            ):
                payload = registry.status()

            self.assertTrue(payload["discovery"]["local_model_assets_available"])
            self.assertIn(str(recovered_models), payload["discovery"]["local_search_roots"])
            self.assertIn("qwen2.5-7b", payload["discovery"]["local_discovered_models"])


if __name__ == "__main__":
    unittest.main()