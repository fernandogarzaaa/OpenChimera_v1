"""Cloud LLM provider authentication profiles.

Manages API-key and OAuth-token storage for cloud providers (OpenAI, Anthropic,
Google, Groq, OpenRouter, xAI, etc.) with per-provider failover, cooldown
tracking, and round-robin rotation — inspired by OpenClaw's auth-profile system
but implemented in pure Python with the existing CredentialStore backend.

Concepts
────────
AuthProfile     Immutable descriptor for one auth credential (api_key or oauth).
CloudProvider   Provider metadata (base URL, auth header, models endpoint).
CloudAuthManager  Top-level manager: CRUD profiles, rotate, cooldown, failover.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from core.credential_store import CredentialStore

log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────

COOLDOWN_BASE_SECONDS = 60        # 1 min initial cooldown
COOLDOWN_MAX_SECONDS = 3600       # 1 hr cap
BILLING_COOLDOWN_BASE = 18000     # 5 hr initial billing disable
BILLING_COOLDOWN_MAX = 86400      # 24 hr cap


class AuthType(str, Enum):
    API_KEY = "api_key"
    OAUTH = "oauth"


# ── Cloud provider descriptors ──────────────────────────────────────────

@dataclass(frozen=True)
class CloudProvider:
    provider_id: str
    display_name: str
    base_url: str
    models_endpoint: str
    auth_header: str = "Authorization"
    auth_prefix: str = "Bearer "
    extra_headers: tuple[tuple[str, str], ...] = ()

    def build_auth_headers(self, key_or_token: str) -> dict[str, str]:
        headers = {self.auth_header: f"{self.auth_prefix}{key_or_token}"}
        for k, v in self.extra_headers:
            headers[k] = v
        return headers


CLOUD_PROVIDERS: dict[str, CloudProvider] = {
    "openai": CloudProvider(
        provider_id="openai",
        display_name="OpenAI",
        base_url="https://api.openai.com/v1",
        models_endpoint="https://api.openai.com/v1/models",
    ),
    "anthropic": CloudProvider(
        provider_id="anthropic",
        display_name="Anthropic",
        base_url="https://api.anthropic.com/v1",
        models_endpoint="https://api.anthropic.com/v1/models",
        auth_header="x-api-key",
        auth_prefix="",
        extra_headers=(("anthropic-version", "2023-06-01"),),
    ),
    "google": CloudProvider(
        provider_id="google",
        display_name="Google AI (Gemini)",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        models_endpoint="https://generativelanguage.googleapis.com/v1beta/models",
        auth_header="x-goog-api-key",
        auth_prefix="",
    ),
    "groq": CloudProvider(
        provider_id="groq",
        display_name="Groq",
        base_url="https://api.groq.com/openai/v1",
        models_endpoint="https://api.groq.com/openai/v1/models",
    ),
    "openrouter": CloudProvider(
        provider_id="openrouter",
        display_name="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        models_endpoint="https://openrouter.ai/api/v1/models",
    ),
    "xai": CloudProvider(
        provider_id="xai",
        display_name="xAI (Grok)",
        base_url="https://api.x.ai/v1",
        models_endpoint="https://api.x.ai/v1/models",
    ),
    "deepseek": CloudProvider(
        provider_id="deepseek",
        display_name="DeepSeek",
        base_url="https://api.deepseek.com/v1",
        models_endpoint="https://api.deepseek.com/v1/models",
    ),
    "together": CloudProvider(
        provider_id="together",
        display_name="Together AI",
        base_url="https://api.together.xyz/v1",
        models_endpoint="https://api.together.xyz/v1/models",
    ),
}


# ── Auth profile ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class AuthProfile:
    profile_id: str       # e.g. "openai:default" or "google:user@gmail.com"
    provider_id: str      # e.g. "openai"
    auth_type: AuthType
    api_key: str = ""
    access_token: str = ""
    refresh_token: str = ""
    expires_at: float = 0.0
    email: str = ""

    @property
    def credential_value(self) -> str:
        if self.auth_type == AuthType.API_KEY:
            return self.api_key
        return self.access_token

    @property
    def is_expired(self) -> bool:
        if self.auth_type == AuthType.OAUTH and self.expires_at > 0:
            return time.time() > self.expires_at
        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "provider_id": self.provider_id,
            "auth_type": self.auth_type.value,
            "api_key": self.api_key,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "email": self.email,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AuthProfile":
        return cls(
            profile_id=str(data.get("profile_id", "")),
            provider_id=str(data.get("provider_id", "")),
            auth_type=AuthType(data.get("auth_type", "api_key")),
            api_key=str(data.get("api_key", "")),
            access_token=str(data.get("access_token", "")),
            refresh_token=str(data.get("refresh_token", "")),
            expires_at=float(data.get("expires_at", 0.0)),
            email=str(data.get("email", "")),
        )


# ── Cooldown tracker ────────────────────────────────────────────────────

class _CooldownTracker:
    """Exponential-backoff cooldown per profile_id."""

    def __init__(self) -> None:
        self._failures: dict[str, int] = {}
        self._until: dict[str, float] = {}

    def record_failure(self, profile_id: str, *, billing: bool = False) -> None:
        count = self._failures.get(profile_id, 0) + 1
        self._failures[profile_id] = count
        base = BILLING_COOLDOWN_BASE if billing else COOLDOWN_BASE_SECONDS
        cap = BILLING_COOLDOWN_MAX if billing else COOLDOWN_MAX_SECONDS
        backoff = min(base * (2 ** (count - 1)), cap)
        self._until[profile_id] = time.time() + backoff
        log.info("Cooldown %s for %.0fs (failure #%d)", profile_id, backoff, count)

    def is_cooled_down(self, profile_id: str) -> bool:
        deadline = self._until.get(profile_id, 0.0)
        if time.time() >= deadline:
            return False
        return True

    def clear(self, profile_id: str) -> None:
        self._failures.pop(profile_id, None)
        self._until.pop(profile_id, None)


# ── Cloud Auth Manager ──────────────────────────────────────────────────

class CloudAuthManager:
    """Manages cloud LLM auth profiles with rotation and cooldown."""

    def __init__(self, credential_store: CredentialStore | None = None) -> None:
        self.credential_store = credential_store or CredentialStore()
        self._cooldowns = _CooldownTracker()
        self._rotation_index: dict[str, int] = {}

    # ── Profile CRUD ────────────────────────────────────────────────────

    def add_api_key(self, provider_id: str, api_key: str, label: str = "default") -> AuthProfile:
        profile_id = f"{provider_id}:{label}"
        profile = AuthProfile(
            profile_id=profile_id,
            provider_id=provider_id,
            auth_type=AuthType.API_KEY,
            api_key=api_key,
        )
        self._save_profile(profile)
        return profile

    def add_oauth_token(
        self,
        provider_id: str,
        access_token: str,
        refresh_token: str = "",
        expires_at: float = 0.0,
        email: str = "",
    ) -> AuthProfile:
        label = email if email else "default"
        profile_id = f"{provider_id}:{label}"
        profile = AuthProfile(
            profile_id=profile_id,
            provider_id=provider_id,
            auth_type=AuthType.OAUTH,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
            email=email,
        )
        self._save_profile(profile)
        return profile

    def remove_profile(self, profile_id: str) -> bool:
        provider_id, _, label = profile_id.partition(":")
        if not label:
            return False
        self.credential_store.delete_provider_credential(provider_id, f"profile:{label}")
        self._cooldowns.clear(profile_id)
        return True

    def list_profiles(self, provider_id: str | None = None) -> list[AuthProfile]:
        all_creds = self.credential_store.load().get("providers", {})
        profiles: list[AuthProfile] = []
        for pid, creds in all_creds.items():
            if provider_id and pid != provider_id:
                continue
            if not isinstance(creds, dict):
                continue
            for key, value in creds.items():
                if not str(key).startswith("profile:"):
                    continue
                try:
                    data = json.loads(str(value))
                    profiles.append(AuthProfile.from_dict(data))
                except (json.JSONDecodeError, ValueError):
                    continue
        return profiles

    def get_profile(self, profile_id: str) -> AuthProfile | None:
        provider_id, _, label = profile_id.partition(":")
        if not label:
            return None
        creds = self.credential_store.get_provider_credentials(provider_id)
        raw = creds.get(f"profile:{label}", "")
        if not raw:
            return None
        try:
            return AuthProfile.from_dict(json.loads(raw))
        except (json.JSONDecodeError, ValueError):
            return None

    # ── Rotation ────────────────────────────────────────────────────────

    def next_available_profile(self, provider_id: str) -> AuthProfile | None:
        profiles = self.list_profiles(provider_id)
        if not profiles:
            return None
        available = [
            p for p in profiles
            if not self._cooldowns.is_cooled_down(p.profile_id)
            and not p.is_expired
        ]
        if not available:
            log.warning("All profiles for %s are on cooldown or expired", provider_id)
            return None
        idx = self._rotation_index.get(provider_id, 0) % len(available)
        self._rotation_index[provider_id] = idx + 1
        return available[idx]

    def report_success(self, profile_id: str) -> None:
        self._cooldowns.clear(profile_id)

    def report_failure(self, profile_id: str, *, billing: bool = False) -> None:
        self._cooldowns.record_failure(profile_id, billing=billing)

    # ── Config integration ──────────────────────────────────────────────

    def configured_providers(self) -> list[str]:
        return [
            p.provider_id
            for p in self.list_profiles()
            if not self._cooldowns.is_cooled_down(p.profile_id) and not p.is_expired
        ]

    def status(self) -> dict[str, Any]:
        profiles = self.list_profiles()
        by_provider: dict[str, list[dict[str, Any]]] = {}
        for p in profiles:
            entry = {
                "profile_id": p.profile_id,
                "auth_type": p.auth_type.value,
                "cooled_down": self._cooldowns.is_cooled_down(p.profile_id),
                "expired": p.is_expired,
            }
            if p.email:
                entry["email"] = p.email
            by_provider.setdefault(p.provider_id, []).append(entry)
        return {
            "providers": by_provider,
            "available_provider_ids": self.configured_providers(),
        }

    # ── Internal ────────────────────────────────────────────────────────

    def _save_profile(self, profile: AuthProfile) -> None:
        provider_id = profile.provider_id
        _, _, label = profile.profile_id.partition(":")
        self.credential_store.set_provider_credential(
            provider_id, f"profile:{label}", json.dumps(profile.to_dict())
        )
