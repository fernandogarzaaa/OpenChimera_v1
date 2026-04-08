from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, request

from core.config import ROOT, load_runtime_profile
from core.credential_store import CredentialStore
from core.local_model_inventory import discover_local_model_inventory, discover_ollama_models
from core.transactions import atomic_write_json


LOCAL_MODEL_SEEDS: dict[str, dict[str, Any]] = {
    "phi-3.5-mini": {
        "family": "phi",
        "provider_module": "local-llama-cpp",
        "min_vram_gb": 4.0,
        "min_ram_gb": 8.0,
        "recommended_for": ["fast", "general"],
    },
    "llama-3.2-3b": {
        "family": "llama",
        "provider_module": "local-llama-cpp",
        "min_vram_gb": 4.0,
        "min_ram_gb": 8.0,
        "recommended_for": ["fast", "general", "reasoning"],
    },
    "qwen2.5-7b": {
        "family": "qwen",
        "provider_module": "local-llama-cpp",
        "min_vram_gb": 6.0,
        "min_ram_gb": 16.0,
        "recommended_for": ["general", "code"],
    },
    "gemma-2-9b": {
        "family": "gemma",
        "provider_module": "local-llama-cpp",
        "min_vram_gb": 8.0,
        "min_ram_gb": 20.0,
        "recommended_for": ["general", "reasoning"],
    },
    "mistral-7b": {
        "family": "mistral",
        "provider_module": "local-llama-cpp",
        "min_vram_gb": 6.0,
        "min_ram_gb": 16.0,
        "recommended_for": ["general", "code"],
    },
    "llama-3.1-8b": {
        "family": "llama",
        "provider_module": "local-llama-cpp",
        "min_vram_gb": 8.0,
        "min_ram_gb": 18.0,
        "recommended_for": ["general", "reasoning", "code"],
    },
}

PROVIDER_MODULE_SEEDS: list[dict[str, Any]] = [
    {"id": "openchimera-gateway", "kind": "gateway", "module": "core.provider.OpenChimeraProvider", "configurable": True},
    {"id": "local-llama-cpp", "kind": "local", "module": "core.local_llm.LocalLLMManager", "configurable": True},
    {"id": "minimind", "kind": "reasoning", "module": "core.minimind_service.MiniMindService", "configurable": True},
    {"id": "ollama", "kind": "local", "module": "external.ollama", "configurable": True, "auth_env_vars": [], "docs_path": "/providers/ollama"},
    {"id": "openai", "kind": "cloud", "module": "external.openai", "configurable": True, "auth_env_vars": ["OPENAI_API_KEY"], "docs_path": "/providers/openai"},
    {"id": "anthropic", "kind": "cloud", "module": "external.anthropic", "configurable": True, "auth_env_vars": ["ANTHROPIC_API_KEY"], "docs_path": "/providers/anthropic"},
    {"id": "google", "kind": "cloud", "module": "external.google", "configurable": True, "auth_env_vars": ["GOOGLE_API_KEY", "GEMINI_API_KEY"], "docs_path": "/providers/google"},
    {"id": "groq", "kind": "cloud", "module": "external.groq", "configurable": True, "auth_env_vars": ["GROQ_API_KEY"], "docs_path": "/providers/groq"},
    {"id": "openrouter", "kind": "cloud", "module": "external.openrouter", "configurable": True, "auth_env_vars": ["OPENROUTER_API_KEY"], "docs_path": "/providers/openrouter"},
    {"id": "vercel-ai-gateway", "kind": "cloud", "module": "external.vercel", "configurable": True, "auth_env_vars": ["AI_GATEWAY_API_KEY"], "docs_path": "/providers/vercel-ai-gateway"},
    {"id": "cloudflare-ai-gateway", "kind": "cloud", "module": "external.cloudflare", "configurable": True, "auth_env_vars": ["CLOUDFLARE_API_TOKEN"], "docs_path": "/providers/cloudflare-ai-gateway"},
    {"id": "moonshot", "kind": "cloud", "module": "external.moonshot", "configurable": True, "auth_env_vars": ["MOONSHOT_API_KEY"], "docs_path": "/providers/moonshot"},
    {"id": "minimax", "kind": "cloud", "module": "external.minimax", "configurable": True, "auth_env_vars": ["MINIMAX_API_KEY"], "docs_path": "/providers/minimax"},
    {"id": "xai", "kind": "cloud", "module": "external.xai", "configurable": True, "auth_env_vars": ["XAI_API_KEY"], "docs_path": "/providers/xai"},
    {"id": "huggingface-inference", "kind": "cloud", "module": "external.huggingface", "configurable": True, "auth_env_vars": ["HUGGINGFACEHUB_API_TOKEN", "HF_TOKEN"], "docs_path": "/providers/huggingface"},
]

CLOUD_MODEL_SEEDS: list[dict[str, Any]] = [
    {"id": "gpt-4.1-mini", "provider": "openai", "recommended_for": ["fallback", "code"], "strength": "balanced cloud fallback"},
    {"id": "gpt-4.1", "provider": "openai", "recommended_for": ["reasoning", "code"], "strength": "high-quality reasoning"},
    {"id": "claude-3.7-sonnet", "provider": "anthropic", "recommended_for": ["reasoning", "writing"], "strength": "high-quality analysis"},
    {"id": "gemini-2.5-pro", "provider": "google", "recommended_for": ["reasoning", "multimodal"], "strength": "long-context reasoning"},
    {"id": "llama-3.3-70b-versatile", "provider": "groq", "recommended_for": ["speed", "general"], "strength": "fast remote inference"},
    {"id": "openrouter/claude-sonnet", "provider": "openrouter", "recommended_for": ["reasoning", "fallback"], "strength": "broad brokered catalog"},
    {"id": "moonshot/kimi-k2.5", "provider": "moonshot", "recommended_for": ["code", "reasoning"], "strength": "high-context Kimi coding"},
    {"id": "minimax/MiniMax-M2.7", "provider": "minimax", "recommended_for": ["reasoning", "general"], "strength": "strong general-purpose reasoning"},
    {"id": "xai/grok-code-fast-1", "provider": "xai", "recommended_for": ["code", "speed"], "strength": "fast coding assistant"},
]


class ModelRegistry:
    def __init__(self, credential_store: CredentialStore | None = None):
        self.profile = load_runtime_profile()
        self.registry_path = ROOT / "data" / "model_registry.json"
        self.credential_store = credential_store or CredentialStore()

    def status(self) -> dict[str, Any]:
        if self.registry_path.exists():
            try:
                raw = json.loads(self.registry_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                raw = None
            if isinstance(raw, dict):
                persisted_discovery = raw.get("discovery", {}) if isinstance(raw.get("discovery", {}), dict) else {}
                live_inventory = discover_local_model_inventory(self.profile, known_model_names=list(LOCAL_MODEL_SEEDS.keys()))
                live_search_roots = list(live_inventory.get("search_roots") or [])
                live_available_models = list(live_inventory.get("available_models") or [])
                persisted_search_roots = list(persisted_discovery.get("local_search_roots") or [])
                persisted_available_models = list(persisted_discovery.get("local_discovered_models") or [])
                if (
                    persisted_search_roots == live_search_roots
                    and bool(persisted_discovery.get("local_model_assets_available", False)) == bool(live_available_models)
                    and persisted_available_models == live_available_models
                ):
                    return raw
        return self.refresh()

    def refresh(self) -> dict[str, Any]:
        hardware = self._detect_hardware()
        local_models = self._build_local_model_catalog(hardware)
        cloud_models = self._build_cloud_model_catalog()
        discovery = self._build_discovery_status()
        recommendations = self._build_recommendations(hardware, local_models, cloud_models)
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "hardware": hardware,
            "providers": self._build_provider_catalog(local_models),
            "local_models": local_models,
            "cloud_models": cloud_models,
            "discovery": discovery,
            "recommendations": recommendations,
            "onboarding": self._build_onboarding(hardware, recommendations),
        }
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.registry_path, payload)
        return payload

    def onboarding_status(self) -> dict[str, Any]:
        return self.status().get("onboarding", {})

    def _detect_hardware(self) -> dict[str, Any]:
        # If profile already has explicit hardware data, use it directly
        # (this allows tests and manual config to override real detection)
        profile_hw = self.profile.get("hardware", {})
        if isinstance(profile_hw, dict) and profile_hw.get("cpu_count") is not None:
            gpu = profile_hw.get("gpu", {}) if isinstance(profile_hw.get("gpu", {}), dict) else {}
            cpu_count = int(profile_hw.get("cpu_count") or (os.cpu_count() or 4))
            ram_gb = float(profile_hw.get("ram_gb") or 0.0)
            vram_gb = float(gpu.get("vram_gb") or 0.0)
            gpu_name = str(gpu.get("name") or "unknown")
            if vram_gb <= 0.0 and not gpu.get("available", False):
                gpu_name = gpu_name if gpu_name != "unknown" else "cpu-only"
            return {
                "cpu_count": cpu_count,
                "ram_gb": ram_gb,
                "gpu": {
                    "available": bool(gpu.get("available", vram_gb > 0.0)),
                    "name": gpu_name,
                    "vram_gb": vram_gb,
                    "device_count": int(gpu.get("device_count", 0 if vram_gb <= 0.0 else 1)),
                },
            }
        # Try real detection; fall back to defaults
        try:
            from core.hardware_detector import detect_hardware
            hw = detect_hardware()
            # Persist detected values back to profile if they look valid
            if hw.get("cpu_count", 0) > 0:
                hardware_section = self.profile.setdefault("hardware", {})
                hardware_section["cpu_count"] = hw["cpu_count"]
                hardware_section["ram_gb"] = hw.get("ram_gb", 0.0)
                gpu_detected = hw.get("gpu", {})
                hardware_section["gpu"] = {
                    "available": gpu_detected.get("available", False),
                    "name": gpu_detected.get("name", ""),
                    "vram_gb": gpu_detected.get("vram_gb", 0.0),
                    "device_count": gpu_detected.get("device_count", 0),
                }
            return {
                "cpu_count": hw.get("cpu_count", os.cpu_count() or 4),
                "ram_gb": hw.get("ram_gb", 0.0),
                "gpu": {
                    "available": hw.get("gpu", {}).get("available", False),
                    "name": hw.get("gpu", {}).get("name", "cpu-only"),
                    "vram_gb": hw.get("gpu", {}).get("vram_gb", 0.0),
                    "device_count": hw.get("gpu", {}).get("device_count", 0),
                },
            }
        except Exception:
            pass
        # Final fallback: minimal defaults
        return {
            "cpu_count": os.cpu_count() or 4,
            "ram_gb": 0.0,
            "gpu": {
                "available": False,
                "name": "cpu-only",
                "vram_gb": 0.0,
                "device_count": 0,
            },
        }

    def _build_local_model_catalog(self, hardware: dict[str, Any]) -> list[dict[str, Any]]:
        model_inventory = self.profile.get("model_inventory", {})
        local_runtime = self.profile.get("local_runtime", {})
        discovered_inventory = discover_local_model_inventory(self.profile, known_model_names=list(LOCAL_MODEL_SEEDS.keys()))
        configured_available_models = list(model_inventory.get("available_models") or [])
        discovered_available_models = list(discovered_inventory.get("available_models") or [])
        available_models = configured_available_models + [
            model_name for model_name in discovered_available_models if model_name not in configured_available_models
        ]
        model_files = model_inventory.get("model_files", {}) or {}
        endpoint_overrides = local_runtime.get("model_endpoints", {}) or {}
        models_dir = Path(model_inventory.get("models_dir") or ROOT / "models")

        known_model_names = sorted(set(LOCAL_MODEL_SEEDS.keys()) | set(available_models))
        catalog: list[dict[str, Any]] = []
        for model_name in known_model_names:
            seed = LOCAL_MODEL_SEEDS.get(model_name, {})
            configured_file = model_files.get(model_name)
            discovered_file = discovered_inventory.get("model_files", {}).get(model_name) if isinstance(discovered_inventory, dict) else None
            model_path = Path(configured_file) if configured_file else None
            if model_path is not None and not model_path.is_absolute():
                model_path = models_dir / model_path
            if (model_path is None or not model_path.exists()) and discovered_file:
                model_path = Path(discovered_file)
            model_path_exists = bool(model_path and model_path.exists())
            catalog.append(
                {
                    "id": model_name,
                    "family": seed.get("family", "unknown"),
                    "provider_module": seed.get("provider_module", "local-llama-cpp"),
                    "available_locally": model_name in available_models or model_path_exists,
                    "configured_endpoint": endpoint_overrides.get(model_name),
                    "configured_model_path": str(model_path) if model_path else None,
                    "discovered_model_path": discovered_file,
                    "model_path_exists": model_path_exists,
                    "min_vram_gb": float(seed.get("min_vram_gb", 0.0)),
                    "min_ram_gb": float(seed.get("min_ram_gb", 0.0)),
                    "recommended_for": list(seed.get("recommended_for", ["general"])),
                    "runnable_on_detected_hardware": self._is_runnable(seed, hardware),
                    "compatibility": {
                        "openchimera": True,
                        "legacy_runtime_compatible": True,
                    },
                }
            )
        return catalog

    def _build_cloud_model_catalog(self) -> list[dict[str, Any]]:
        catalog = [dict(item) for item in CLOUD_MODEL_SEEDS]
        catalog.extend(self._load_scouted_models())
        catalog.extend(self._load_discovery_source_models())
        deduped: dict[str, dict[str, Any]] = {}
        for item in catalog:
            deduped[str(item.get("id"))] = item
        return self._apply_learned_fallback_rankings(list(deduped.values()))

    def _build_provider_catalog(self, local_models: list[dict[str, Any]]) -> list[dict[str, Any]]:
        providers: list[dict[str, Any]] = []
        providers_config = self.profile.get("providers", {}) if isinstance(self.profile.get("providers", {}), dict) else {}
        enabled_provider_ids = set(str(item) for item in providers_config.get("enabled", []))
        preferred_cloud_provider = str(providers_config.get("preferred_cloud_provider", "")).strip()
        ollama_config = self.profile.get("ollama", {}) if isinstance(self.profile.get("ollama", {}), dict) else {}
        ollama_host = str(ollama_config.get("host", "127.0.0.1"))
        ollama_port = int(ollama_config.get("port", 11434))
        _ollama_probe_done = False
        _ollama_discovered: list[str] | None = None
        for provider in PROVIDER_MODULE_SEEDS:
            item = dict(provider)
            if item["id"] == "local-llama-cpp":
                item["discovered_models"] = sorted(model["id"] for model in local_models if model["provider_module"] == "local-llama-cpp")
            if item["id"] == "ollama":
                if not _ollama_probe_done:
                    _ollama_discovered = discover_ollama_models(ollama_host=ollama_host, ollama_port=ollama_port)
                    _ollama_probe_done = True
                item["discovered_models"] = _ollama_discovered if _ollama_discovered is not None else []
                item["ollama_reachable"] = _ollama_discovered is not None
            default_enabled = item["id"] in {"openchimera-gateway", "local-llama-cpp", "minimind"}
            item["enabled"] = item["id"] in enabled_provider_ids if enabled_provider_ids else default_enabled
            configured_from_env = any(os.getenv(env_var) for env_var in item.get("auth_env_vars", []))
            configured_from_store = self.credential_store.has_provider_credentials(item["id"], list(item.get("auth_env_vars", [])))
            item["auth_configured"] = configured_from_env or configured_from_store
            item["credential_sources"] = {
                "environment": configured_from_env,
                "credential_store": configured_from_store,
            }
            item["activation_state"] = {
                "enabled": item["enabled"],
                "preferred_cloud_provider": bool(preferred_cloud_provider and preferred_cloud_provider == item["id"]),
                "prefer_free_models": bool(providers_config.get("prefer_free_models", False)),
            }
            providers.append(item)
        return providers

    def _build_recommendations(
        self,
        hardware: dict[str, Any],
        local_models: list[dict[str, Any]],
        cloud_models: list[dict[str, Any]],
    ) -> dict[str, Any]:
        prefer_free_models = bool(self.profile.get("providers", {}).get("prefer_free_models", False))
        local_candidates = [model for model in local_models if model["runnable_on_detected_hardware"]]
        local_candidates.sort(key=lambda item: (not item["available_locally"], item["min_vram_gb"], item["id"]))
        free_candidates = [
            model
            for model in cloud_models
            if str(model.get("provider") or "") in {"scouted", "openrouter", "ollama"}
            or str(model.get("source") or "") in {"autonomy-sync", "autonomy-discovery"}
        ]
        cloud_candidates = []
        if not local_candidates or float(hardware.get("gpu", {}).get("vram_gb", 0.0)) < 6.0:
            prioritized = free_candidates + [item for item in cloud_models if item not in free_candidates]
            cloud_candidates = prioritized[:3] if prefer_free_models else cloud_models[:3]
        return {
            "suggested_local_models": local_candidates[:4],
            "suggested_cloud_models": cloud_candidates,
            "suggested_free_models": free_candidates[:5],
            "learned_free_rankings": [
                {
                    "id": model.get("id"),
                    "query_type": model.get("learned_query_type"),
                    "rank": model.get("learned_rank"),
                    "score": model.get("learned_score"),
                    "confidence": model.get("learned_confidence"),
                    "degraded": model.get("learned_degraded", False),
                }
                for model in free_candidates
                if model.get("learned_rank") is not None
            ][:5],
            "needs_cloud_fallback": not bool(local_candidates) or float(hardware.get("gpu", {}).get("vram_gb", 0.0)) < 4.0,
            "prefer_free_models": prefer_free_models,
            "refresh_strategy": "runtime-profile plus curated catalog, scouted model sync, and optional remote discovery refresh",
        }

    def _build_onboarding(self, hardware: dict[str, Any], recommendations: dict[str, Any]) -> dict[str, Any]:
        local_suggestions = recommendations.get("suggested_local_models", [])
        setup_notes: list[str] = []
        if local_suggestions:
            setup_notes.append(
                "Detected hardware can run local models: " + ", ".join(item["id"] for item in local_suggestions)
            )
        else:
            setup_notes.append("Detected hardware is below the current local-model comfort range; configure a cloud provider first.")
        setup_notes.append("OpenChimera keeps a modular provider catalog so users can replace or extend local/cloud providers after open-sourcing.")
        return {
            "hardware_detected": hardware,
            "suggested_local_models": local_suggestions,
            "suggested_cloud_models": recommendations.get("suggested_cloud_models", []),
            "suggested_free_models": recommendations.get("suggested_free_models", []),
            "prefer_free_models": recommendations.get("prefer_free_models", False),
            "setup_notes": setup_notes,
            "minimind_optimization_profile": self._build_minimind_optimization_profile(hardware),
        }

    def _build_discovery_status(self) -> dict[str, Any]:
        scouted_path = ROOT / "data" / "autonomy" / "scouted_models_registry.json"
        discovered_path = ROOT / "data" / "autonomy" / "discovered_models.json"
        sources = self.profile.get("model_inventory", {}).get("discovery_sources", [])
        local_inventory = discover_local_model_inventory(self.profile, known_model_names=list(LOCAL_MODEL_SEEDS.keys()))
        ollama_config = self.profile.get("ollama", {}) if isinstance(self.profile.get("ollama", {}), dict) else {}
        ollama_host = str(ollama_config.get("host", "127.0.0.1"))
        ollama_port = int(ollama_config.get("port", 11434))
        ollama_models = discover_ollama_models(ollama_host=ollama_host, ollama_port=ollama_port)
        return {
            "scouted_models_path": str(scouted_path),
            "scouted_models_available": scouted_path.exists(),
            "discovered_models_path": str(discovered_path),
            "discovered_models_available": discovered_path.exists(),
            "learned_rankings_path": str(ROOT / "data" / "autonomy" / "learned_fallback_rankings.json"),
            "learned_rankings_available": (ROOT / "data" / "autonomy" / "learned_fallback_rankings.json").exists(),
            "local_model_assets_available": bool(local_inventory.get("available_models")),
            "local_discovered_models": list(local_inventory.get("available_models") or []),
            "local_search_roots": list(local_inventory.get("search_roots") or []),
            "remote_sources": [str(source.get("name") or source.get("url") or "unnamed") for source in sources if isinstance(source, dict)],
            "ollama_discovered_models": ollama_models if ollama_models is not None else [],
            "ollama_reachable": ollama_models is not None,
        }

    def _build_minimind_optimization_profile(self, hardware: dict[str, Any]) -> dict[str, Any]:
        vram_gb = float(hardware.get("gpu", {}).get("vram_gb", 0.0))
        ram_gb = float(hardware.get("ram_gb", 0.0))
        if vram_gb >= 12.0:
            compression = "8bit"
            bits = 8
        else:
            compression = "4bit"
            bits = 4
        return {
            "approach": "airllm-inspired",
            "goal": "bias MiniMind toward low-memory fine-tuning and streamed inference on constrained hardware",
            "training": {
                "bits": bits,
                "compression": compression,
                "double_quant": True,
                "quant_type": "nf4",
                "lora_r": 64,
                "lora_alpha": 16,
                "gradient_checkpointing": True,
                "max_memory_mb": max(int(vram_gb * 1024 * 0.8), 4096),
            },
            "inference": {
                "layer_streaming_candidate": vram_gb <= 8.0 and ram_gb >= 16.0,
                "prefetch_layers": ram_gb >= 16.0,
                "compression": compression,
            },
        }

    def _is_runnable(self, seed: dict[str, Any], hardware: dict[str, Any]) -> bool:
        min_vram = float(seed.get("min_vram_gb", 0.0))
        min_ram = float(seed.get("min_ram_gb", 0.0))
        ram_gb = float(hardware.get("ram_gb", 0.0))
        vram_gb = float(hardware.get("gpu", {}).get("vram_gb", 0.0))
        if ram_gb and ram_gb < min_ram:
            return False
        if min_vram == 0.0:
            return True
        return vram_gb >= min_vram

    def _load_scouted_models(self) -> list[dict[str, Any]]:
        scouted_path = ROOT / "data" / "autonomy" / "scouted_models_registry.json"
        if not scouted_path.exists():
            return []
        try:
            raw = json.loads(scouted_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        models = raw.get("models", raw)
        if isinstance(models, dict):
            items = [{"id": key, **(value if isinstance(value, dict) else {})} for key, value in models.items()]
        elif isinstance(models, list):
            items = [item for item in models if isinstance(item, dict)]
        else:
            items = []
        normalized = []
        for item in items:
            model_id = str(item.get("id") or item.get("model") or "").strip()
            if not model_id:
                continue
            normalized.append(
                {
                    "id": model_id,
                    "provider": str(item.get("provider") or "scouted"),
                    "recommended_for": list(item.get("recommended_for") or ["fallback"]),
                    "strength": str(item.get("strength") or "synced from scouted models registry"),
                    "source": "autonomy-sync",
                }
            )
        return normalized

    def _load_discovery_source_models(self) -> list[dict[str, Any]]:
        sources = self.profile.get("model_inventory", {}).get("discovery_sources", [])
        discovered: list[dict[str, Any]] = []
        for source in sources:
            if not isinstance(source, dict):
                continue
            url = str(source.get("url") or "").strip()
            if not url:
                continue
            provider = str(source.get("provider") or source.get("name") or "remote")
            try:
                with request.urlopen(url, timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except (OSError, error.URLError, json.JSONDecodeError):
                continue
            entries = payload.get("models") if isinstance(payload, dict) else payload
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                model_id = str(entry.get("id") or entry.get("model") or "").strip()
                if not model_id:
                    continue
                discovered.append(
                    {
                        "id": model_id,
                        "provider": provider,
                        "recommended_for": list(entry.get("recommended_for") or ["general"]),
                        "strength": str(entry.get("strength") or f"discovered from {provider}"),
                        "source": url,
                    }
                )
        return discovered

    def _apply_learned_fallback_rankings(self, catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rankings = self._load_learned_fallback_rankings()
        if not rankings:
            return catalog
        annotated: list[dict[str, Any]] = []
        for item in catalog:
            annotated_item = dict(item)
            model_id = str(annotated_item.get("id") or "").strip()
            entry = rankings.get(model_id)
            if entry:
                annotated_item.update(
                    {
                        "learned_query_type": entry.get("query_type"),
                        "learned_rank": entry.get("rank"),
                        "learned_score": entry.get("score"),
                        "learned_confidence": entry.get("confidence"),
                        "learned_degraded": entry.get("degraded", False),
                        "learned_reasons": list(entry.get("reasons") or []),
                    }
                )
            annotated.append(annotated_item)
        return annotated

    def _load_learned_fallback_rankings(self) -> dict[str, dict[str, Any]]:
        learned_path = ROOT / "data" / "autonomy" / "learned_fallback_rankings.json"
        if not learned_path.exists():
            return {}
        try:
            raw = json.loads(learned_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        query_types = raw.get("query_types", {}) if isinstance(raw, dict) else {}
        if not isinstance(query_types, dict):
            return {}
        learned: dict[str, dict[str, Any]] = {}
        for query_type, entries in query_types.items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                model_id = str(entry.get("model") or "").strip()
                if not model_id:
                    continue
                existing = learned.get(model_id)
                if existing is None or int(entry.get("rank") or 999999) < int(existing.get("rank") or 999999):
                    learned[model_id] = {
                        "query_type": str(query_type),
                        "rank": int(entry.get("rank") or 0),
                        "score": float(entry.get("score") or 0.0),
                        "confidence": float(entry.get("confidence") or 0.0),
                        "degraded": bool(entry.get("degraded", False)),
                        "reasons": list(entry.get("reasons") or []),
                    }
        return learned