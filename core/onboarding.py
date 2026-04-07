from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any
from urllib import error, request

from core.channels import ChannelManager
from core.config import (
    DEFAULT_AETHER_ROOT,
    DEFAULT_EVO_ROOT,
    DEFAULT_HARNESS_REPO_ROOT,
    DEFAULT_LEGACY_WORKSPACE_ROOT,
    DEFAULT_MINIMIND_ROOT,
    DEFAULT_OPENCLAW_ROOT,
    DEFAULT_WRAITH_ROOT,
    DEFAULT_AEGIS_MOBILE_ROOT,
    DEFAULT_APPFORGE_ROOT,
    ROOT,
    is_supported_harness_repo_root,
    load_runtime_profile,
    normalize_runtime_profile,
    resolve_root,
    save_runtime_profile,
)
from core.credential_store import CredentialStore
from core.local_model_inventory import identify_model_name_for_path
from core.model_registry import ModelRegistry
from core.transactions import atomic_write_json


# Read-only probe endpoint for each cloud provider used by validate_credential().
# The request is a simple GET that lists models (or any lightweight endpoint).
_CREDENTIAL_PROBE_URLS: dict[str, str] = {
    "openai": "https://api.openai.com/v1/models",
    "anthropic": "https://api.anthropic.com/v1/models",
    "google": "https://generativelanguage.googleapis.com/v1beta/models",
    "groq": "https://api.groq.com/openai/v1/models",
    "openrouter": "https://openrouter.ai/api/v1/models",
    "moonshot": "https://api.moonshot.cn/v1/models",
    "xai": "https://api.x.ai/v1/models",
    "huggingface-inference": "https://api-inference.huggingface.co/models",
}

# Providers that use a non-standard auth header instead of Bearer.
# A value of "" means use the credential value itself as the header value.
_CREDENTIAL_AUTH_HEADERS: dict[str, dict[str, str]] = {
    "anthropic": {"x-api-key": "", "anthropic-version": "2023-06-01"},
}


class OnboardingManager:
    def __init__(
        self,
        model_registry: ModelRegistry,
        credential_store: CredentialStore,
        channels: ChannelManager,
        state_path: Path | None = None,
        profile_loader: Any | None = None,
        profile_saver: Any | None = None,
    ):
        self.model_registry = model_registry
        self.credential_store = credential_store
        self.channels = channels
        self.state_path = state_path or (ROOT / "data" / "onboarding_state.json")
        self._profile_loader = profile_loader or load_runtime_profile
        self._profile_saver = profile_saver or save_runtime_profile

    def status(self) -> dict[str, Any]:
        state = self._load_state()
        profile = self._profile_loader()
        registry_status = self.model_registry.status()
        recommendations = registry_status.get("onboarding", {}) if isinstance(registry_status.get("onboarding", {}), dict) else {}
        discovery = registry_status.get("discovery", {}) if isinstance(registry_status.get("discovery", {}), dict) else {}
        validation = self._validate_roots(profile)
        state["steps"] = self._derive_steps(profile, recommendations, validation, discovery)
        state["recommendations"] = recommendations
        state["model_discovery"] = discovery
        state["validation"] = validation
        state["provider_activation"] = self._provider_activation_status(profile)
        state["channel_preferences"] = self._channel_preferences(profile)
        state["blockers"] = self._derive_blockers(state.get("steps", []), validation)
        state["next_actions"] = self._derive_next_actions(state, recommendations, discovery)
        state["current_profile"] = {
            "preferred_local_models": profile.get("local_runtime", {}).get("preferred_local_models", []),
            "channel_count": self.channels.status().get("counts", {}).get("total", 0),
            "credential_providers": sorted(self.credential_store.status().get("providers", {}).keys()),
            "enabled_providers": profile.get("providers", {}).get("enabled", []),
            "preferred_cloud_provider": profile.get("providers", {}).get("preferred_cloud_provider", ""),
            "prefer_free_models": bool(profile.get("providers", {}).get("prefer_free_models", False)),
            "local_model_assets_available": bool(discovery.get("local_model_assets_available", False)),
            "local_search_roots": list(discovery.get("local_search_roots") or []),
        }
        state["completed"] = all(step.get("completed") for step in state.get("steps", []))
        return state

    def apply(self, payload: dict[str, Any]) -> dict[str, Any]:
        profile = self._profile_loader()
        normalized, _ = normalize_runtime_profile(profile)

        selected_model = str(payload.get("preferred_local_model", "")).strip()
        if selected_model:
            preferred = list(normalized.get("local_runtime", {}).get("preferred_local_models", []))
            normalized["local_runtime"]["preferred_local_models"] = [selected_model] + [item for item in preferred if item != selected_model]

        selected_cloud_provider = str(payload.get("preferred_cloud_provider", "")).strip()
        if selected_cloud_provider:
            normalized.setdefault("providers", {})
            normalized["providers"]["preferred_cloud_provider"] = selected_cloud_provider
            normalized.setdefault("onboarding", {})
            normalized["onboarding"]["selected_cloud_provider"] = selected_cloud_provider

        enabled_provider_ids = payload.get("enabled_provider_ids")
        if isinstance(enabled_provider_ids, list):
            normalized.setdefault("providers", {})
            normalized["providers"]["enabled"] = [str(item) for item in enabled_provider_ids]

        if "prefer_free_models" in payload:
            normalized.setdefault("providers", {})
            normalized["providers"]["prefer_free_models"] = bool(payload.get("prefer_free_models"))

        local_model_asset_path = str(payload.get("local_model_asset_path") or payload.get("register_local_model_path") or "").strip()
        local_model_asset_id = str(payload.get("local_model_asset_id") or payload.get("register_local_model_id") or "").strip()
        if local_model_asset_path:
            asset_path = Path(local_model_asset_path).expanduser()
            if not asset_path.exists() or not asset_path.is_file():
                raise ValueError(f"Local model asset does not exist: {asset_path}")
            if asset_path.suffix.lower() != ".gguf":
                raise ValueError("Local model asset registration requires a .gguf file")
            detected_model_id = local_model_asset_id or identify_model_name_for_path(asset_path)
            if not detected_model_id:
                raise ValueError(
                    "Could not infer a supported local model id from the GGUF filename. Pass --register-local-model-id explicitly."
                )
            normalized.setdefault("model_inventory", {})
            model_inventory = normalized["model_inventory"]
            existing_files = model_inventory.get("model_files", {}) if isinstance(model_inventory.get("model_files", {}), dict) else {}
            existing_files[str(detected_model_id)] = str(asset_path)
            model_inventory["model_files"] = existing_files
            search_roots = model_inventory.get("search_roots", []) if isinstance(model_inventory.get("search_roots", []), list) else []
            parent_root = str(asset_path.parent)
            if parent_root not in search_roots:
                search_roots.append(parent_root)
            model_inventory["search_roots"] = search_roots
            available_models = [str(item) for item in model_inventory.get("available_models", []) if item]
            if str(detected_model_id) not in available_models:
                available_models.append(str(detected_model_id))
            model_inventory["available_models"] = available_models
            preferred = list(normalized.get("local_runtime", {}).get("preferred_local_models", []))
            normalized.setdefault("local_runtime", {})
            normalized["local_runtime"]["preferred_local_models"] = [str(detected_model_id)] + [item for item in preferred if item != str(detected_model_id)]

        runtime_roots = payload.get("runtime_roots", {}) if isinstance(payload.get("runtime_roots", {}), dict) else {}
        if runtime_roots:
            normalized.setdefault("external_roots", {})
            normalized.setdefault("integration_roots", {})
            mapping = {
                "aether": ("external_roots", "aether"),
                "wraith": ("external_roots", "wraith"),
                "evo": ("external_roots", "evo"),
                "legacy_workspace": ("external_roots", "legacy_workspace"),
                "openclaw": ("external_roots", "openclaw"),
                "appforge": ("external_roots", "appforge"),
                "aegis_mobile": ("external_roots", "aegis_mobile"),
                "harness_repo": ("integration_roots", "harness_repo"),
                "minimind": ("integration_roots", "minimind"),
            }
            for key, value in runtime_roots.items():
                target = mapping.get(str(key))
                if target and value:
                    normalized[target[0]][target[1]] = str(value)

        auth = payload.get("api_auth", {}) if isinstance(payload.get("api_auth", {}), dict) else {}
        if auth:
            normalized.setdefault("api", {}).setdefault("auth", {})
            if "enabled" in auth:
                normalized["api"]["auth"]["enabled"] = bool(auth.get("enabled"))
            if auth.get("token"):
                normalized["api"]["auth"]["token"] = str(auth.get("token"))
            if auth.get("admin_token"):
                normalized["api"]["auth"]["admin_token"] = str(auth.get("admin_token"))

        provider_credentials = payload.get("provider_credentials", {}) if isinstance(payload.get("provider_credentials", {}), dict) else {}
        for provider_id, values in provider_credentials.items():
            if not isinstance(values, dict):
                continue
            for key, value in values.items():
                if value:
                    self.credential_store.set_provider_credential(str(provider_id), str(key), str(value))

        channel_subscription = payload.get("channel_subscription", {}) if isinstance(payload.get("channel_subscription", {}), dict) else {}
        if channel_subscription:
            saved_subscription = self.channels.upsert_subscription(channel_subscription)
            normalized.setdefault("onboarding", {})
            normalized["onboarding"]["preferred_channel_id"] = str(saved_subscription.get("id", ""))

        preferred_channel_id = str(payload.get("preferred_channel_id", "")).strip()
        if preferred_channel_id:
            normalized.setdefault("onboarding", {})
            normalized["onboarding"]["preferred_channel_id"] = preferred_channel_id

        normalized.setdefault("onboarding", {})
        normalized["onboarding"]["completed_at"] = int(time.time())
        self._profile_saver(normalized)
        self.model_registry.profile = self._profile_loader()
        refreshed_registry = self.model_registry.refresh()

        state = self._load_state()
        state["last_applied_at"] = int(time.time())
        state["last_payload"] = self._sanitize_payload(payload)
        current_profile = self._profile_loader()
        refreshed_discovery = refreshed_registry.get("discovery", {}) if isinstance(refreshed_registry.get("discovery", {}), dict) else {}
        state["steps"] = self._derive_steps(current_profile, refreshed_registry.get("onboarding", {}), self._validate_roots(current_profile), refreshed_discovery)
        state["completed"] = all(step.get("completed") for step in state.get("steps", []))
        self._save_state(state)
        return self.status()

    def reset(self) -> dict[str, Any]:
        state = {
            "started_at": int(time.time()),
            "last_applied_at": None,
            "last_payload": {},
            "steps": [],
            "completed": False,
        }
        self._save_state(state)
        return self.status()

    def validate_credential(self, provider_id: str, key: str, value: str) -> dict[str, Any]:
        """Perform a lightweight probe to verify a provider credential before persisting it.

        Makes a read-only API call (e.g. list models) to confirm the credential
        is accepted by the provider.  Returns a dict with ``valid`` (bool),
        ``provider_id``, ``key``, and an optional ``error`` message.

        Providers that require no credentials (Ollama, llama.cpp) are treated as
        always valid when no value is required.
        """
        provider_id = str(provider_id).strip().lower()
        key = str(key).strip()
        value = str(value).strip()

        if not value:
            return {"valid": False, "provider_id": provider_id, "key": key, "error": "Credential value must not be empty"}

        probe_url = _CREDENTIAL_PROBE_URLS.get(provider_id)
        if probe_url is None:
            return {"valid": True, "provider_id": provider_id, "key": key, "note": "No probe endpoint configured for this provider; credential accepted without validation"}

        try:
            headers: dict[str, str] = {"Accept": "application/json"}
            extra_headers = _CREDENTIAL_AUTH_HEADERS.get(provider_id, {})
            for h_key, h_val in extra_headers.items():
                headers[h_key] = h_val if h_val else value
            if provider_id not in _CREDENTIAL_AUTH_HEADERS:
                headers["Authorization"] = f"Bearer {value}"

            if provider_id == "google":
                separator = "&" if "?" in probe_url else "?"
                probe_url = f"{probe_url}{separator}key={value}"

            req = request.Request(probe_url, headers=headers, method="GET")
            with request.urlopen(req, timeout=10) as resp:
                if resp.status in (200, 206):
                    return {"valid": True, "provider_id": provider_id, "key": key}
                return {
                    "valid": False,
                    "provider_id": provider_id,
                    "key": key,
                    "error": f"Provider returned HTTP {resp.status}",
                }
        except error.HTTPError as exc:
            if exc.code == 401:
                return {"valid": False, "provider_id": provider_id, "key": key, "error": "Invalid or expired credential (HTTP 401)"}
            if exc.code == 403:
                return {"valid": False, "provider_id": provider_id, "key": key, "error": "Credential lacks required permissions (HTTP 403)"}
            if exc.code in (429, 503):
                return {
                    "valid": True,
                    "provider_id": provider_id,
                    "key": key,
                    "note": f"Provider rate-limited or temporarily unavailable (HTTP {exc.code}); credential may still be valid",
                }
            return {"valid": False, "provider_id": provider_id, "key": key, "error": f"HTTP {exc.code} from provider probe"}
        except (error.URLError, OSError) as exc:
            return {"valid": False, "provider_id": provider_id, "key": key, "error": f"Network error reaching provider: {exc}"}

    def _derive_steps(self, profile: dict[str, Any], recommendations: dict[str, Any], validation: dict[str, Any], discovery: dict[str, Any]) -> list[dict[str, Any]]:
        credentials = self.credential_store.status().get("providers", {})
        channels = self.channels.status().get("counts", {})
        preferred_models = list(profile.get("local_runtime", {}).get("preferred_local_models", []))
        cloud_credentials_required = self._cloud_credentials_required(profile)
        local_assets_available = bool(discovery.get("local_model_assets_available", False))
        local_discovered_models = list(discovery.get("local_discovered_models") or [])
        return [
            {
                "id": "local-model",
                "completed": local_assets_available,
                "detail": {
                    "preferred": preferred_models[0] if preferred_models else (recommendations.get("suggested_local_models", [{}])[0].get("id") if recommendations.get("suggested_local_models") else "cloud-fallback"),
                    "assets_available": local_assets_available,
                    "discovered_models": local_discovered_models,
                },
            },
            {
                "id": "provider-credentials",
                "completed": (not cloud_credentials_required) or bool(credentials),
                "detail": {
                    "configured_providers": sorted(credentials.keys()),
                    "required": cloud_credentials_required,
                },
            },
            {
                "id": "provider-activation",
                "completed": bool(profile.get("providers", {}).get("enabled", [])),
                "detail": profile.get("providers", {}).get("enabled", []),
            },
            {
                "id": "channels",
                "completed": int(channels.get("total", 0)) > 0,
                "detail": channels,
            },
            {
                "id": "runtime-roots",
                "completed": True,
                "detail": validation,
            },
        ]

    def _validate_roots(self, profile: dict[str, Any]) -> dict[str, Any]:
        external = profile.get("external_roots", {}) if isinstance(profile.get("external_roots", {}), dict) else {}
        integration = profile.get("integration_roots", {}) if isinstance(profile.get("integration_roots", {}), dict) else {}

        configured_harness = Path(str(integration.get("harness_repo"))).expanduser() if integration.get("harness_repo") else None
        env_harness = os.getenv("OPENCHIMERA_HARNESS_ROOT")
        if env_harness:
            harness_root = Path(env_harness).expanduser()
        elif configured_harness and configured_harness.exists() and is_supported_harness_repo_root(configured_harness):
            harness_root = configured_harness
        elif DEFAULT_HARNESS_REPO_ROOT.exists() and is_supported_harness_repo_root(DEFAULT_HARNESS_REPO_ROOT):
            harness_root = DEFAULT_HARNESS_REPO_ROOT
        else:
            harness_root = configured_harness or DEFAULT_HARNESS_REPO_ROOT

        expected = {
            "aether": resolve_root("AETHER_ROOT", Path(str(external.get("aether"))).expanduser() if external.get("aether") else None, DEFAULT_AETHER_ROOT),
            "wraith": resolve_root("WRAITH_ROOT", Path(str(external.get("wraith"))).expanduser() if external.get("wraith") else None, DEFAULT_WRAITH_ROOT),
            "evo": resolve_root("EVO_ROOT", Path(str(external.get("evo"))).expanduser() if external.get("evo") else None, DEFAULT_EVO_ROOT),
            "legacy_workspace": resolve_root(
                "OPENCHIMERA_LEGACY_ROOT",
                Path(str(external.get("legacy_workspace") or external.get("openclaw"))).expanduser() if (external.get("legacy_workspace") or external.get("openclaw")) else None,
                DEFAULT_LEGACY_WORKSPACE_ROOT or DEFAULT_OPENCLAW_ROOT,
            ),
            "appforge": resolve_root("APPFORGE_ROOT", Path(str(external.get("appforge"))).expanduser() if external.get("appforge") else None, DEFAULT_APPFORGE_ROOT),
            "aegis_mobile": resolve_root(
                "AEGIS_MOBILE_ROOT",
                Path(str(external.get("aegis_mobile"))).expanduser() if external.get("aegis_mobile") else None,
                DEFAULT_AEGIS_MOBILE_ROOT,
            ),
            "harness_repo": harness_root,
            "minimind": resolve_root(
                "MINIMIND_ROOT",
                Path(str(integration.get("minimind"))).expanduser() if integration.get("minimind") else None,
                DEFAULT_MINIMIND_ROOT,
            ),
        }
        roots = {name: {"path": str(path), "exists": path.exists()} for name, path in expected.items()}
        missing_required = [name for name, details in roots.items() if name in {"harness_repo", "minimind"} and not details["exists"]]
        return {"roots": roots, "missing_required_roots": missing_required}

    def _provider_activation_status(self, profile: dict[str, Any]) -> dict[str, Any]:
        provider_status = self.model_registry.status().get("providers", [])
        enabled = profile.get("providers", {}).get("enabled", [])
        return {
            "enabled": enabled,
            "preferred_cloud_provider": profile.get("providers", {}).get("preferred_cloud_provider", ""),
            "prefer_free_models": bool(profile.get("providers", {}).get("prefer_free_models", False)),
            "available": provider_status,
        }

    def _channel_preferences(self, profile: dict[str, Any]) -> dict[str, Any]:
        onboarding = profile.get("onboarding", {}) if isinstance(profile.get("onboarding", {}), dict) else {}
        return {
            "preferred_channel_id": onboarding.get("preferred_channel_id", ""),
            "available_subscriptions": self.channels.list_subscriptions(),
        }

    def _derive_blockers(self, steps: list[dict[str, Any]], validation: dict[str, Any]) -> list[str]:
        blockers: list[str] = []
        incomplete = {str(step.get("id")) for step in steps if not step.get("completed")}
        if "local-model" in incomplete:
            blockers.append("No local GGUF model assets are configured or discovered for the local runtime.")
        if "provider-credentials" in incomplete:
            blockers.append("Cloud provider credentials are required for the selected remote provider configuration.")
        if "channels" in incomplete:
            blockers.append("No push channel configured for operator notifications.")
        return blockers

    def _derive_next_actions(self, state: dict[str, Any], recommendations: dict[str, Any], discovery: dict[str, Any]) -> list[str]:
        steps = state.get("steps", []) if isinstance(state.get("steps", []), list) else []
        incomplete = {str(step.get("id")) for step in steps if not step.get("completed")}
        actions: list[str] = []
        if not bool(discovery.get("local_model_assets_available", False)):
            actions.append("If you already have a GGUF file, register it with openchimera onboard --register-local-model-path <path-to-model.gguf> [--register-local-model-id <model-id>].")
        if "local-model" in incomplete:
            suggested = recommendations.get("suggested_local_models", [])
            if suggested:
                actions.append("Select a preferred local model such as " + str(suggested[0].get("id", "unknown")) + ".")
            else:
                cloud = recommendations.get("suggested_cloud_models", [])
                if cloud:
                    actions.append("Configure a cloud provider credential and select " + str(cloud[0].get("provider", "a cloud provider")) + " as fallback.")
        if "provider-credentials" in incomplete:
            actions.append("Store at least one provider credential so fallback and remote providers are usable.")
        if "provider-activation" in incomplete:
            actions.append("Choose which providers should be enabled for this installation.")
        if not bool(state.get("current_profile", {}).get("prefer_free_models", False)) and recommendations.get("suggested_free_models"):
            actions.append("Enable free-model fallback if you want OpenChimera to bias no-cost recovery paths before paid providers.")
        if "channels" in incomplete:
            actions.append("Run openchimera channels --channel filesystem --file-path data/channels/operator-feed.jsonl --subscription-id ops-local-feed to configure a local operator notification feed.")
        return actions

    def _cloud_credentials_required(self, profile: dict[str, Any]) -> bool:
        providers = profile.get("providers", {}) if isinstance(profile.get("providers", {}), dict) else {}
        onboarding = profile.get("onboarding", {}) if isinstance(profile.get("onboarding", {}), dict) else {}
        preferred_cloud_provider = str(providers.get("preferred_cloud_provider", "")).strip()
        selected_cloud_provider = str(onboarding.get("selected_cloud_provider", "")).strip()
        return bool(preferred_cloud_provider or selected_cloud_provider)

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"started_at": int(time.time()), "last_applied_at": None, "last_payload": {}, "steps": [], "completed": False}
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"started_at": int(time.time()), "last_applied_at": None, "last_payload": {}, "steps": [], "completed": False}
        return raw if isinstance(raw, dict) else {"started_at": int(time.time()), "last_applied_at": None, "last_payload": {}, "steps": [], "completed": False}

    def _save_state(self, payload: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.state_path, payload)

    def _sanitize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        sanitized = json.loads(json.dumps(payload))
        credentials = sanitized.get("provider_credentials", {})
        if isinstance(credentials, dict):
            for provider_id, values in credentials.items():
                if not isinstance(values, dict):
                    continue
                for key, value in list(values.items()):
                    text = str(value)
                    values[key] = (text[:2] + "***" + text[-2:]) if len(text) > 4 else ("*" * len(text))
        channel_subscription = sanitized.get("channel_subscription", {})
        if isinstance(channel_subscription, dict) and channel_subscription.get("bot_token"):
            text = str(channel_subscription["bot_token"])
            channel_subscription["bot_token"] = (text[:2] + "***" + text[-2:]) if len(text) > 4 else ("*" * len(text))
        return sanitized