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

            with patch("core.model_registry.ROOT", temp_root), patch("core.local_model_inventory.ROOT", temp_root), patch("core.local_model_inventory.get_appforge_root", return_value=appforge_root), patch(
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

    def test_ollama_discovery_in_provider_catalog(self) -> None:
        """Provider catalog for 'ollama' includes discovered models from live Ollama probe."""
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = ModelRegistry()
            registry.registry_path = Path(temp_dir) / "model_registry.json"
            registry.profile = {
                "hardware": {"cpu_count": 4, "ram_gb": 8, "gpu": {"available": False, "name": "cpu-only", "vram_gb": 0, "device_count": 0}},
                "providers": {"enabled": ["openchimera-gateway", "local-llama-cpp", "ollama"], "prefer_free_models": True},
                "model_inventory": {"available_models": [], "model_files": {}, "models_dir": temp_dir},
            }
            fake_ollama_models = ["llama3.2:latest", "gemma3:4b"]
            with patch("core.model_registry.discover_ollama_models", return_value=fake_ollama_models):
                payload = registry.refresh()

            ollama_provider = next((p for p in payload["providers"] if p["id"] == "ollama"), None)
            self.assertIsNotNone(ollama_provider)
            self.assertEqual(ollama_provider["discovered_models"], fake_ollama_models)
            self.assertTrue(ollama_provider["ollama_reachable"])
            self.assertIn("ollama_discovered_models", payload["discovery"])
            self.assertEqual(payload["discovery"]["ollama_discovered_models"], fake_ollama_models)
            self.assertTrue(payload["discovery"]["ollama_reachable"])

    def test_ollama_not_reachable_produces_empty_discovery(self) -> None:
        """When Ollama is unreachable, discovered_models is empty and ollama_reachable is False."""
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = ModelRegistry()
            registry.registry_path = Path(temp_dir) / "model_registry.json"
            registry.profile = {
                "hardware": {"cpu_count": 4, "ram_gb": 8, "gpu": {"available": False, "name": "cpu-only", "vram_gb": 0, "device_count": 0}},
                "providers": {"prefer_free_models": False},
                "model_inventory": {"available_models": [], "model_files": {}, "models_dir": temp_dir},
            }
            with patch("core.model_registry.discover_ollama_models", return_value=None):
                payload = registry.refresh()

            ollama_provider = next((p for p in payload["providers"] if p["id"] == "ollama"), None)
            self.assertIsNotNone(ollama_provider)
            self.assertEqual(ollama_provider["discovered_models"], [])
            self.assertFalse(ollama_provider["ollama_reachable"])
            self.assertFalse(payload["discovery"]["ollama_reachable"])

    def test_huggingface_provider_accepts_hf_token_alias(self) -> None:
        """HuggingFace provider checks both HUGGINGFACEHUB_API_TOKEN and HF_TOKEN."""
        from core.model_registry import PROVIDER_MODULE_SEEDS

        hf_seed = next((p for p in PROVIDER_MODULE_SEEDS if p["id"] == "huggingface-inference"), None)
        self.assertIsNotNone(hf_seed, "huggingface-inference provider must be in PROVIDER_MODULE_SEEDS")
        auth_vars = hf_seed.get("auth_env_vars", [])
        self.assertIn("HUGGINGFACEHUB_API_TOKEN", auth_vars)
        self.assertIn("HF_TOKEN", auth_vars)

    def test_failover_chain_in_profile_is_preserved(self) -> None:
        """failover_chain from provider config is preserved in profile after normalize."""
        from core.config import normalize_runtime_profile, validate_runtime_profile

        profile_input = {
            "providers": {
                "enabled": ["openchimera-gateway", "local-llama-cpp"],
                "prefer_free_models": True,
                "failover_chain": ["openai", "anthropic", "groq"],
            },
        }
        normalized, _ = normalize_runtime_profile(profile_input)
        errors = validate_runtime_profile(normalized)
        self.assertFalse(any("failover_chain" in e for e in errors))
        self.assertEqual(normalized.get("providers", {}).get("failover_chain"), ["openai", "anthropic", "groq"])

    def test_failover_chain_validation_rejects_non_list(self) -> None:
        """validate_runtime_profile emits an error when failover_chain is not a list."""
        from core.config import normalize_runtime_profile, validate_runtime_profile

        profile_input = {
            "providers": {
                "enabled": ["openchimera-gateway"],
                "failover_chain": "openai,anthropic",
            },
        }
        normalized, _ = normalize_runtime_profile(profile_input)
        normalized.setdefault("providers", {})["failover_chain"] = "openai,anthropic"
        errors = validate_runtime_profile(normalized)
        self.assertTrue(any("failover_chain" in e for e in errors))


if __name__ == "__main__":
    unittest.main()