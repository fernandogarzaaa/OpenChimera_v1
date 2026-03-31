from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, request

from core.config import ROOT, load_runtime_profile


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
    {"id": "huggingface-inference", "kind": "cloud", "module": "external.huggingface", "configurable": True, "auth_env_vars": ["HUGGINGFACEHUB_API_TOKEN"], "docs_path": "/providers/huggingface"},
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
    def __init__(self):
        self.profile = load_runtime_profile()
        self.registry_path = ROOT / "data" / "model_registry.json"

    def status(self) -> dict[str, Any]:
        if self.registry_path.exists():
            try:
                raw = json.loads(self.registry_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                raw = None
            if isinstance(raw, dict):
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
        self.registry_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload

    def onboarding_status(self) -> dict[str, Any]:
        return self.status().get("onboarding", {})

    def _detect_hardware(self) -> dict[str, Any]:
        hardware = self.profile.get("hardware", {})
        gpu = hardware.get("gpu", {}) if isinstance(hardware.get("gpu", {}), dict) else {}
        cpu_count = int(hardware.get("cpu_count") or (os.cpu_count() or 4))
        ram_gb = float(hardware.get("ram_gb") or 0.0)
        vram_gb = float(gpu.get("vram_gb") or 0.0)
        gpu_name = str(gpu.get("name") or "unknown")
        if vram_gb <= 0.0:
            gpu_name = "cpu-only"
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

    def _build_local_model_catalog(self, hardware: dict[str, Any]) -> list[dict[str, Any]]:
        model_inventory = self.profile.get("model_inventory", {})
        local_runtime = self.profile.get("local_runtime", {})
        available_models = list(model_inventory.get("available_models") or [])
        model_files = model_inventory.get("model_files", {}) or {}
        endpoint_overrides = local_runtime.get("model_endpoints", {}) or {}
        models_dir = Path(model_inventory.get("models_dir") or ROOT / "models")

        known_model_names = sorted(set(LOCAL_MODEL_SEEDS.keys()) | set(available_models))
        catalog: list[dict[str, Any]] = []
        for model_name in known_model_names:
            seed = LOCAL_MODEL_SEEDS.get(model_name, {})
            configured_file = model_files.get(model_name)
            model_path = Path(configured_file) if configured_file else None
            if model_path is not None and not model_path.is_absolute():
                model_path = models_dir / model_path
            model_path_exists = bool(model_path and model_path.exists())
            catalog.append(
                {
                    "id": model_name,
                    "family": seed.get("family", "unknown"),
                    "provider_module": seed.get("provider_module", "local-llama-cpp"),
                    "available_locally": model_name in available_models or model_path_exists,
                    "configured_endpoint": endpoint_overrides.get(model_name),
                    "configured_model_path": str(model_path) if model_path else None,
                    "model_path_exists": model_path_exists,
                    "min_vram_gb": float(seed.get("min_vram_gb", 0.0)),
                    "min_ram_gb": float(seed.get("min_ram_gb", 0.0)),
                    "recommended_for": list(seed.get("recommended_for", ["general"])),
                    "runnable_on_detected_hardware": self._is_runnable(seed, hardware),
                    "compatibility": {
                        "openchimera": True,
                        "openclaw_style_local_runtime": True,
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
        return list(deduped.values())

    def _build_provider_catalog(self, local_models: list[dict[str, Any]]) -> list[dict[str, Any]]:
        providers: list[dict[str, Any]] = []
        for provider in PROVIDER_MODULE_SEEDS:
            item = dict(provider)
            if item["id"] == "local-llama-cpp":
                item["discovered_models"] = sorted(model["id"] for model in local_models if model["provider_module"] == "local-llama-cpp")
            item["enabled"] = item["id"] in {"openchimera-gateway", "local-llama-cpp", "minimind"}
            item["auth_configured"] = any(os.getenv(env_var) for env_var in item.get("auth_env_vars", []))
            providers.append(item)
        return providers

    def _build_recommendations(
        self,
        hardware: dict[str, Any],
        local_models: list[dict[str, Any]],
        cloud_models: list[dict[str, Any]],
    ) -> dict[str, Any]:
        local_candidates = [model for model in local_models if model["runnable_on_detected_hardware"]]
        local_candidates.sort(key=lambda item: (not item["available_locally"], item["min_vram_gb"], item["id"]))
        cloud_candidates = []
        if not local_candidates or float(hardware.get("gpu", {}).get("vram_gb", 0.0)) < 6.0:
            cloud_candidates = cloud_models[:3]
        return {
            "suggested_local_models": local_candidates[:4],
            "suggested_cloud_models": cloud_candidates,
            "needs_cloud_fallback": not bool(local_candidates) or float(hardware.get("gpu", {}).get("vram_gb", 0.0)) < 4.0,
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
            "setup_notes": setup_notes,
            "minimind_optimization_profile": self._build_minimind_optimization_profile(hardware),
        }

    def _build_discovery_status(self) -> dict[str, Any]:
        scouted_path = ROOT / "data" / "autonomy" / "scouted_models_registry.json"
        sources = self.profile.get("model_inventory", {}).get("discovery_sources", [])
        return {
            "scouted_models_path": str(scouted_path),
            "scouted_models_available": scouted_path.exists(),
            "remote_sources": [str(source.get("name") or source.get("url") or "unnamed") for source in sources if isinstance(source, dict)],
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