from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from core.capabilities import CapabilityRegistry
from core.config import ROOT
from core.transactions import atomic_write_json


class PluginManager:
    def __init__(self, capability_registry: CapabilityRegistry, state_path: Path | None = None):
        self.capability_registry = capability_registry
        self.state_path = state_path or (ROOT / "data" / "plugins_state.json")

    def status(self) -> dict[str, Any]:
        plugins = self.list_plugins()
        installed = [item for item in plugins if item.get("installed")]
        return {
            "counts": {
                "total": len(plugins),
                "installed": len(installed),
            },
            "plugins": plugins,
        }

    def list_plugins(self) -> list[dict[str, Any]]:
        discovered = self.capability_registry.list_kind("plugins")
        state = self._load_state()
        installed_ids = {str(item.get("id")) for item in state.get("installed", []) if isinstance(item, dict)}
        installed_at = {
            str(item.get("id")): item.get("installed_at")
            for item in state.get("installed", [])
            if isinstance(item, dict)
        }
        result = []
        for plugin in discovered:
            item = dict(plugin)
            plugin_id = str(item.get("id"))
            item["installed"] = plugin_id in installed_ids
            item["installed_at"] = installed_at.get(plugin_id)
            result.append(item)
        return result

    def install(self, plugin_id: str) -> dict[str, Any]:
        plugin = self._find_plugin(plugin_id)
        state = self._load_state()
        installed = [item for item in state.get("installed", []) if isinstance(item, dict) and item.get("id") != plugin_id]
        installed.append({"id": plugin_id, "installed_at": int(time.time())})
        self._save_state({"installed": installed})
        return {
            "status": "installed",
            "plugin": plugin,
            "installed_at": installed[-1]["installed_at"],
        }

    def uninstall(self, plugin_id: str) -> dict[str, Any]:
        plugin = self._find_plugin(plugin_id)
        state = self._load_state()
        installed = [item for item in state.get("installed", []) if isinstance(item, dict) and item.get("id") != plugin_id]
        self._save_state({"installed": installed})
        return {
            "status": "uninstalled",
            "plugin": plugin,
        }

    def _find_plugin(self, plugin_id: str) -> dict[str, Any]:
        for plugin in self.capability_registry.list_kind("plugins"):
            if str(plugin.get("id")) == plugin_id:
                return plugin
        raise ValueError(f"Unknown plugin: {plugin_id}")

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"installed": []}
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"installed": []}
        if not isinstance(raw, dict):
            return {"installed": []}
        installed = raw.get("installed", [])
        if not isinstance(installed, list):
            installed = []
        return {"installed": installed}

    def _save_state(self, payload: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.state_path, payload)