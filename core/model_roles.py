from __future__ import annotations

from typing import Any

from core.config import load_runtime_profile, save_runtime_profile
from core.model_registry import ModelRegistry


ROLE_TO_QUERY_TYPE = {
    "main_loop_model": "general",
    "fast_model": "fast",
    "code_model": "code",
    "reasoning_model": "reasoning",
    "advisor_model": "reasoning",
    "fallback_model": "fallback",
}


class ModelRoleManager:
    def __init__(self, model_registry: ModelRegistry):
        self.model_registry = model_registry

    def status(self) -> dict[str, Any]:
        profile = load_runtime_profile()
        registry = self.model_registry.status()
        overrides = profile.get("local_runtime", {}).get("model_roles", {})
        roles = self._resolve_roles(registry=registry, overrides=overrides)
        return {
            "roles": roles,
            "overrides": overrides if isinstance(overrides, dict) else {},
            "available_local_models": [item.get("id") for item in registry.get("local_models", []) if item.get("available_locally")],
            "available_cloud_models": [item.get("id") for item in registry.get("cloud_models", [])[:20]],
        }

    def configure(self, overrides: dict[str, Any]) -> dict[str, Any]:
        profile = load_runtime_profile()
        local_runtime = profile.setdefault("local_runtime", {})
        stored = local_runtime.setdefault("model_roles", {})
        allowed = {
            "main_loop_model",
            "fast_model",
            "code_model",
            "reasoning_model",
            "advisor_model",
            "fallback_model",
            "consensus_ensemble",
        }
        for key, value in overrides.items():
            if key not in allowed:
                continue
            if key == "consensus_ensemble":
                if isinstance(value, list):
                    stored[key] = [str(item) for item in value if str(item).strip()]
                continue
            if value is None:
                stored.pop(key, None)
                continue
            text = str(value).strip()
            if text:
                stored[key] = text
            else:
                stored.pop(key, None)
        save_runtime_profile(profile)
        self.model_registry.profile = load_runtime_profile()
        self.model_registry.refresh()
        return self.status()

    def select_model_for_query_type(self, query_type: str, exclude: list[str] | None = None) -> dict[str, Any]:
        exclude_set = {str(item) for item in (exclude or [])}
        status = self.status()
        roles = status.get("roles", {})
        role_key = self._role_for_query_type(query_type)
        ordered_roles = [role_key, "main_loop_model", "fallback_model"]
        seen: set[str] = set()
        for candidate_role in ordered_roles:
            if candidate_role in seen:
                continue
            seen.add(candidate_role)
            entry = roles.get(candidate_role, {}) if isinstance(roles, dict) else {}
            model = str(entry.get("model") or "").strip()
            if model and model not in exclude_set:
                return {
                    "role": candidate_role,
                    "model": model,
                    "source": entry.get("source", "resolved"),
                }
        return {"role": role_key, "model": None, "source": "unresolved"}

    def _resolve_roles(self, registry: dict[str, Any], overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        overrides = overrides if isinstance(overrides, dict) else {}
        local_models = registry.get("local_models", []) if isinstance(registry.get("local_models", []), list) else []
        cloud_models = registry.get("cloud_models", []) if isinstance(registry.get("cloud_models", []), list) else []
        local_by_id = {str(item.get("id")): item for item in local_models if isinstance(item, dict)}
        cloud_by_id = {str(item.get("id")): item for item in cloud_models if isinstance(item, dict)}

        roles = {
            "main_loop_model": self._pick_role_model("general", local_models, cloud_models),
            "fast_model": self._pick_role_model("fast", local_models, cloud_models),
            "code_model": self._pick_role_model("code", local_models, cloud_models),
            "reasoning_model": self._pick_role_model("reasoning", local_models, cloud_models),
            "advisor_model": self._pick_role_model("reasoning", local_models, cloud_models, prefer_cloud=True),
            "fallback_model": self._pick_role_model("fallback", local_models, cloud_models, prefer_cloud=True),
            "consensus_ensemble": self._pick_consensus_ensemble(local_models, cloud_models),
        }

        for role_name, override_value in overrides.items():
            if role_name == "consensus_ensemble" and isinstance(override_value, list):
                roles[role_name] = {
                    "models": [str(item) for item in override_value if str(item).strip()],
                    "source": "override",
                }
                continue
            model_id = str(override_value or "").strip()
            if not model_id:
                continue
            source = "override"
            if model_id in local_by_id:
                source = "override-local"
            elif model_id in cloud_by_id:
                source = "override-cloud"
            roles[role_name] = {"model": model_id, "source": source}
        return roles

    def _pick_role_model(
        self,
        query_type: str,
        local_models: list[dict[str, Any]],
        cloud_models: list[dict[str, Any]],
        prefer_cloud: bool = False,
    ) -> dict[str, Any]:
        local_candidates = self._matching_local_models(local_models, query_type)
        cloud_candidates = self._matching_cloud_models(cloud_models, query_type)
        if prefer_cloud and cloud_candidates:
            return {"model": cloud_candidates[0], "source": "cloud-catalog"}
        if local_candidates:
            return {"model": local_candidates[0], "source": "local-catalog"}
        if cloud_candidates:
            return {"model": cloud_candidates[0], "source": "cloud-catalog"}
        if local_models:
            return {"model": str(local_models[0].get("id")), "source": "local-fallback"}
        if cloud_models:
            return {"model": str(cloud_models[0].get("id")), "source": "cloud-fallback"}
        return {"model": None, "source": "unresolved"}

    def _pick_consensus_ensemble(self, local_models: list[dict[str, Any]], cloud_models: list[dict[str, Any]]) -> dict[str, Any]:
        preferred = []
        preferred.extend(self._matching_local_models(local_models, "reasoning")[:2])
        preferred.extend(self._matching_local_models(local_models, "code")[:1])
        if len(preferred) < 3:
            preferred.extend(self._matching_cloud_models(cloud_models, "reasoning")[: 3 - len(preferred)])
        deduped: list[str] = []
        for item in preferred:
            if item not in deduped:
                deduped.append(item)
        return {"models": deduped[:3], "source": "resolved"}

    def _matching_local_models(self, local_models: list[dict[str, Any]], query_type: str) -> list[str]:
        candidates = []
        for item in local_models:
            if not isinstance(item, dict):
                continue
            if not item.get("available_locally"):
                continue
            if not item.get("runnable_on_detected_hardware", True):
                continue
            recommended = [str(entry) for entry in item.get("recommended_for", [])]
            if query_type in recommended or (query_type == "fallback" and recommended):
                candidates.append((float(item.get("min_vram_gb", 0.0)), str(item.get("id"))))
        candidates.sort(key=lambda entry: (entry[0], entry[1]))
        return [item[1] for item in candidates]

    def _matching_cloud_models(self, cloud_models: list[dict[str, Any]], query_type: str) -> list[str]:
        candidates = []
        for item in cloud_models:
            if not isinstance(item, dict):
                continue
            recommended = [str(entry) for entry in item.get("recommended_for", [])]
            if query_type in recommended or (query_type == "fallback" and recommended):
                candidates.append(str(item.get("id")))
        return candidates

    def _role_for_query_type(self, query_type: str) -> str:
        for role_name, mapped_query_type in ROLE_TO_QUERY_TYPE.items():
            if mapped_query_type == query_type:
                return role_name
        return "main_loop_model"