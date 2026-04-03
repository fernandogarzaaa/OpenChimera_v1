from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.config import ROOT
from core.database import DatabaseManager


class CredentialStore:
    def __init__(
        self,
        store_path: Path | None = None,
        database: DatabaseManager | None = None,
        database_path: Path | None = None,
    ):
        self.store_path = store_path or (ROOT / "data" / "credentials.json")
        self.database = database or DatabaseManager(db_path=database_path or (self.store_path.parent / "openchimera.db"))
        self.database.initialize()

    def load(self) -> dict[str, Any]:
        return self.database.load_credentials()

    def status(self) -> dict[str, Any]:
        raw = self.load()
        providers = raw.get("providers", {})
        result: dict[str, Any] = {"providers": {}}
        for provider_id, values in providers.items():
            if not isinstance(values, dict):
                continue
            masked = {}
            for key, value in values.items():
                if value is None:
                    continue
                text = str(value)
                masked[key] = self._mask_value(text)
            result["providers"][str(provider_id)] = {
                "configured": bool(masked),
                "keys": sorted(masked.keys()),
                "masked": masked,
            }
        return result

    def get_provider_credentials(self, provider_id: str) -> dict[str, str]:
        providers = self.load().get("providers", {})
        raw = providers.get(provider_id, {})
        if not isinstance(raw, dict):
            return {}
        return {str(key): str(value) for key, value in raw.items() if value not in {None, ""}}

    def has_provider_credentials(self, provider_id: str, candidate_keys: list[str] | None = None) -> bool:
        credentials = self.get_provider_credentials(provider_id)
        if not credentials:
            return False
        if not candidate_keys:
            return True
        return any(credentials.get(key) for key in candidate_keys)

    def set_provider_credential(self, provider_id: str, key: str, value: str) -> dict[str, Any]:
        self.database.set_credential(provider_id, str(key), str(value))
        return self.status().get("providers", {}).get(provider_id, {"configured": True, "keys": [key]})

    def delete_provider_credential(self, provider_id: str, key: str) -> dict[str, Any]:
        self.database.delete_credential(provider_id, key)
        return self.status().get("providers", {}).get(provider_id, {"configured": False, "keys": [], "masked": {}})

    def _mask_value(self, value: str) -> str:
        if len(value) <= 4:
            return "*" * len(value)
        return value[:2] + ("*" * max(0, len(value) - 4)) + value[-2:]