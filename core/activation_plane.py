from __future__ import annotations

from typing import Any, Callable

from core.config import (
    get_api_admin_token,
    get_api_auth_header,
    get_api_auth_token,
    is_api_auth_enabled,
    load_runtime_profile,
    save_runtime_profile,
)


class ActivationPlane:
    def __init__(
        self,
        *,
        profile_getter: Callable[[], dict[str, Any]],
        refresh_profile: Callable[[], dict[str, Any]],
        credential_store: Any,
        model_registry: Any,
        model_roles: Any,
        bus: Any,
    ) -> None:
        self._profile_getter = profile_getter
        self._refresh_profile = refresh_profile
        self.credential_store = credential_store
        self.model_registry = model_registry
        self.model_roles = model_roles
        self.bus = bus

    def profile(self) -> dict[str, Any]:
        return dict(self._profile_getter() or {})

    def model_registry_status(self) -> dict[str, Any]:
        return self.model_registry.status()

    def credential_status(self) -> dict[str, Any]:
        return self.credential_store.status()

    def fallback_learning_summary(self, registry: dict[str, Any] | None = None) -> dict[str, Any]:
        profile = self.profile()
        registry = registry or self.model_registry.status()
        discovery = registry.get("discovery", {}) if isinstance(registry.get("discovery", {}), dict) else {}
        recommendations = registry.get("recommendations", {}) if isinstance(registry.get("recommendations", {}), dict) else {}
        learned_rankings = recommendations.get("learned_free_rankings", []) if isinstance(recommendations.get("learned_free_rankings", []), list) else []
        ranked_models = []
        degraded_models = []
        for item in learned_rankings:
            if not isinstance(item, dict):
                continue
            ranked_models.append(
                {
                    "id": str(item.get("id") or ""),
                    "query_type": str(item.get("query_type") or "general"),
                    "rank": int(item.get("rank") or 0),
                    "score": float(item.get("score") or 0.0),
                    "confidence": float(item.get("confidence") or 0.0),
                    "degraded": bool(item.get("degraded", False)),
                }
            )
            if bool(item.get("degraded", False)):
                degraded_models.append(str(item.get("id") or ""))
        return {
            "prefer_free_models": bool(profile.get("providers", {}).get("prefer_free_models", False)),
            "scouted_models_available": bool(discovery.get("scouted_models_available", False)),
            "discovered_models_available": bool(discovery.get("discovered_models_available", False)),
            "learned_rankings_available": bool(discovery.get("learned_rankings_available", False)),
            "top_ranked_models": ranked_models[:3],
            "degraded_models": [item for item in degraded_models[:3] if item],
        }

    def provider_activation_status(self) -> dict[str, Any]:
        profile = self.profile()
        registry = self.model_registry.status()
        if not isinstance(registry.get("discovery", {}), dict) or not registry.get("discovery"):
            registry = self.model_registry.refresh()
        return {
            "providers": registry.get("providers", []),
            "preferred_cloud_provider": profile.get("providers", {}).get("preferred_cloud_provider", ""),
            "prefer_free_models": bool(profile.get("providers", {}).get("prefer_free_models", False)),
            "discovery": registry.get("discovery", {}),
            "fallback_learning": self.fallback_learning_summary(registry),
            "model_roles": self.model_roles.status().get("roles", {}),
        }

    def model_role_status(self) -> dict[str, Any]:
        return self.model_roles.status()

    def configure_model_roles(self, overrides: dict[str, Any]) -> dict[str, Any]:
        result = self.model_roles.configure(overrides)
        self._refresh_profile()
        self.bus.publish_nowait("system/model-roles", {"action": "configure", "result": result})
        return result

    def auth_status(self) -> dict[str, Any]:
        auth_enabled = is_api_auth_enabled()
        user_token = get_api_auth_token().strip()
        admin_token = get_api_admin_token().strip()
        return {
            "enabled": auth_enabled,
            "header": get_api_auth_header(),
            "user_token_configured": bool(user_token),
            "admin_token_configured": bool(admin_token),
            "admin_separate_from_user": bool(admin_token and user_token and admin_token != user_token),
            "protected_mutations": True,
        }

    def set_provider_credential(self, provider_id: str, key: str, value: str) -> dict[str, Any]:
        result = self.credential_store.set_provider_credential(provider_id, key, value)
        self.model_registry.refresh()
        self.bus.publish_nowait(
            "system/credentials",
            {"action": "set", "provider_id": provider_id, "key": key, "status": result},
        )
        return result

    def delete_provider_credential(self, provider_id: str, key: str) -> dict[str, Any]:
        result = self.credential_store.delete_provider_credential(provider_id, key)
        self.model_registry.refresh()
        self.bus.publish_nowait(
            "system/credentials",
            {"action": "delete", "provider_id": provider_id, "key": key, "status": result},
        )
        return result

    def refresh_model_registry(self) -> dict[str, Any]:
        result = self.model_registry.refresh()
        self.bus.publish_nowait("system/model-registry", {"action": "refresh", "result": result})
        return result

    def configure_provider_activation(
        self,
        enabled_provider_ids: list[str] | None = None,
        preferred_cloud_provider: str | None = None,
        prefer_free_models: bool | None = None,
    ) -> dict[str, Any]:
        profile = load_runtime_profile()
        providers_config = profile.setdefault("providers", {})
        if enabled_provider_ids is not None:
            providers_config["enabled"] = [str(item) for item in enabled_provider_ids]
        if preferred_cloud_provider is not None:
            providers_config["preferred_cloud_provider"] = str(preferred_cloud_provider)
        if prefer_free_models is not None:
            providers_config["prefer_free_models"] = bool(prefer_free_models)
        save_runtime_profile(profile)
        refreshed_profile = self._refresh_profile()
        self.model_registry.profile = refreshed_profile
        status = self.model_registry.refresh()
        self.bus.publish_nowait(
            "system/providers",
            {
                "action": "configure",
                "enabled": providers_config.get("enabled", []),
                "preferred_cloud_provider": providers_config.get("preferred_cloud_provider", ""),
                "prefer_free_models": bool(providers_config.get("prefer_free_models", False)),
            },
        )
        return {
            "status": "ok",
            "providers": status.get("providers", []),
            "preferred_cloud_provider": providers_config.get("preferred_cloud_provider", ""),
            "prefer_free_models": bool(providers_config.get("prefer_free_models", False)),
            "discovery": status.get("discovery", {}),
        }