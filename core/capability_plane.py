from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from core.mcp_registry import (
    delete_mcp_registry_entry,
    list_mcp_registry_with_health,
    probe_all_mcp_registry_entries,
    probe_mcp_registry_entry,
    upsert_mcp_registry_entry,
)
from core.tool_runtime import ToolMetadata, ToolRegistry, ToolResult

log = logging.getLogger(__name__)


class CapabilityPlane:
    def __init__(self, *, capabilities: Any, plugins: Any, bus: Any, tool_runtime: Any | None = None) -> None:
        self.capabilities = capabilities
        self.plugins = plugins
        self.bus = bus
        self.tool_runtime = tool_runtime  # RuntimeToolRegistry, wired from kernel

        # Internal ToolRegistry for ToolMetadata-based tools (Phase 1)
        self._tool_registry = ToolRegistry(bus=bus)

        # Skill registry: name → dict metadata
        self._skills: dict[str, dict[str, Any]] = {}

        # Loaded plugin manifests: plugin_id → manifest dict
        self._loaded_plugins: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Status helpers
    # ------------------------------------------------------------------

    def capability_status(self) -> dict[str, Any]:
        return self.capabilities.status()

    def list_capabilities(self, kind: str) -> list[dict[str, Any]]:
        return self.capabilities.list_kind(kind)

    # ------------------------------------------------------------------
    # Tool CRUD (ToolMetadata-based registry)
    # ------------------------------------------------------------------

    def register_tool(self, tool: ToolMetadata) -> dict[str, Any]:
        """Register a tool by ToolMetadata descriptor."""
        registered = self._tool_registry.register(tool)
        self.bus.publish_nowait("system/tools", {"action": "register", "tool_name": registered.name})
        return registered.to_dict()

    def unregister_tool(self, name: str) -> bool:
        """Unregister a tool by name. Returns True if removed."""
        removed = self._tool_registry.unregister(name)
        if removed:
            self.bus.publish_nowait("system/tools", {"action": "unregister", "tool_name": name})
        return removed

    def list_tools(self) -> list[dict[str, Any]]:
        """List all tools from the ToolMetadata registry."""
        return self._tool_registry.list_tools()

    def describe_tool(self, name: str) -> dict[str, Any]:
        """Describe a registered tool by name."""
        return self._tool_registry.describe(name).to_dict()

    def execute_tool(self, name: str, arguments: dict[str, Any] | None = None) -> ToolResult:
        """Execute a registered tool and return a ToolResult."""
        return self._tool_registry.execute(name, arguments)

    # ------------------------------------------------------------------
    # Skill CRUD
    # ------------------------------------------------------------------

    def register_skill(self, name: str, metadata: dict[str, Any]) -> dict[str, Any]:
        """Register a skill by name with metadata dict."""
        entry = {"name": name, **metadata}
        self._skills[name] = entry
        self.bus.publish_nowait("system/skills", {"action": "register", "skill_name": name})
        return entry

    def unregister_skill(self, name: str) -> bool:
        """Unregister a skill by name. Returns True if removed."""
        removed = self._skills.pop(name, None) is not None
        if removed:
            self.bus.publish_nowait("system/skills", {"action": "unregister", "skill_name": name})
        return removed

    def list_skills(self) -> list[dict[str, Any]]:
        """List all registered skills."""
        return list(self._skills.values())

    def describe_skill(self, name: str) -> dict[str, Any]:
        """Return metadata for a specific skill."""
        skill = self._skills.get(name)
        if skill is None:
            raise ValueError(f"Unknown skill: {name!r}")
        return dict(skill)

    # ------------------------------------------------------------------
    # Plugin manifest loading
    # ------------------------------------------------------------------

    def load_plugin_manifest(self, manifest_path: str | Path) -> dict[str, Any]:
        """Load a JSON plugin manifest and return parsed content."""
        path = Path(manifest_path)
        if not path.exists():
            raise FileNotFoundError(f"Plugin manifest not found: {path}")
        raw = path.read_text(encoding="utf-8")
        try:
            manifest = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid plugin manifest JSON at {path}: {exc}") from exc
        if not isinstance(manifest, dict):
            raise ValueError(f"Plugin manifest must be a JSON object: {path}")
        return manifest

    def load_plugin(self, manifest_path: str | Path) -> dict[str, Any]:
        """Load a plugin from its manifest, register its tools/skills.

        Plugin isolation: errors during loading are caught and reported,
        so a bad plugin cannot crash the capability plane.
        """
        try:
            manifest = self.load_plugin_manifest(manifest_path)
        except Exception as exc:
            log.warning("Failed to load plugin manifest %s: %s", manifest_path, exc)
            return {"status": "error", "error": str(exc), "manifest_path": str(manifest_path)}

        plugin_id = str(manifest.get("id") or Path(manifest_path).stem)

        try:
            # Register plugin tools as simple ToolMetadata entries
            for tool_name in manifest.get("tools", []):
                tool = ToolMetadata(
                    name=str(tool_name),
                    description=f"Provided by plugin {plugin_id}",
                    tags=[plugin_id, "plugin"],
                )
                self._tool_registry.register(tool)

            # Register plugin skills
            for skill_name in manifest.get("skills", []):
                self.register_skill(str(skill_name), {"source": plugin_id, "kind": "plugin"})

            self._loaded_plugins[plugin_id] = manifest
            self.bus.publish_nowait("system/plugins", {"action": "loaded", "plugin_id": plugin_id})
            log.info("Plugin loaded: %s (tools=%d skills=%d)", plugin_id,
                     len(manifest.get("tools", [])), len(manifest.get("skills", [])))
            return {"status": "ok", "plugin_id": plugin_id, "manifest": manifest}

        except Exception as exc:
            log.warning("Plugin %s load failed during registration: %s", plugin_id, exc)
            return {"status": "error", "plugin_id": plugin_id, "error": str(exc)}

    def list_plugins(self) -> list[dict[str, Any]]:
        """List all successfully loaded plugins."""
        return [
            {
                "plugin_id": pid,
                "name": manifest.get("name", pid),
                "version": manifest.get("version", ""),
                "tools": manifest.get("tools", []),
                "skills": manifest.get("skills", []),
            }
            for pid, manifest in self._loaded_plugins.items()
        ]

    # ------------------------------------------------------------------
    # MCP adapter hookup
    # ------------------------------------------------------------------

    def connect_mcp_adapter(self, server_id: str, **kwargs: Any) -> dict[str, Any]:
        """Connect an MCP adapter by server_id and optional transport kwargs."""
        return self.register_mcp_connector(server_id, **kwargs)

    # ------------------------------------------------------------------
    # Discovery chaining: find_capability(name) → tool → skill → plugin → MCP → None
    # ------------------------------------------------------------------

    def find_capability(self, name: str) -> dict[str, Any] | None:
        """Discover a capability by name across all registered surfaces.

        Resolution order: ToolRegistry → Skill registry → Loaded plugins → MCP servers
        Returns a normalized dict describing the capability, or None.
        """
        # 1. Tool registry
        tool = self._tools_lookup(name)
        if tool is not None:
            return {"kind": "tool", **tool}

        # 2. Skill registry
        skill = self._skills.get(name)
        if skill is not None:
            return {"kind": "skill", **skill}

        # 3. Loaded plugin manifests (check if tool/skill name is listed)
        for pid, manifest in self._loaded_plugins.items():
            if name in manifest.get("tools", []) or name in manifest.get("skills", []):
                return {"kind": "plugin", "plugin_id": pid, "name": name}

        # 4. MCP registry
        mcp_servers = list_mcp_registry_with_health()
        for server in mcp_servers:
            if str(server.get("id") or server.get("name") or "") == name:
                return {"kind": "mcp", **server}

        return None

    def _tools_lookup(self, name: str) -> dict[str, Any] | None:
        """Internal lookup in the ToolMetadata registry."""
        try:
            return self._tool_registry.describe(name).to_dict()
        except ValueError:
            return None

    # ------------------------------------------------------------------
    # MCP status and CRUD (pre-existing, unchanged)
    # ------------------------------------------------------------------

    def mcp_status(self) -> dict[str, Any]:
        servers = self.capabilities.list_kind("mcp")
        registry_servers = list_mcp_registry_with_health()
        return {
            "counts": {
                "total": len(servers),
                "healthy": sum(1 for item in servers if str(item.get("status", "")).lower() in {"healthy", "discovered"}),
                "registered": len(registry_servers),
            },
            "servers": servers,
            "registry": {
                "counts": {
                    "total": len(registry_servers),
                    "healthy": sum(1 for item in registry_servers if str(item.get("status", "")).lower() == "healthy"),
                    "enabled": sum(1 for item in registry_servers if bool(item.get("enabled", True))),
                },
                "servers": registry_servers,
            },
        }

    def mcp_registry_status(self) -> dict[str, Any]:
        servers = list_mcp_registry_with_health()
        return {
            "counts": {
                "total": len(servers),
                "healthy": sum(1 for item in servers if str(item.get("status", "")).lower() == "healthy"),
                "enabled": sum(1 for item in servers if bool(item.get("enabled", True))),
            },
            "servers": servers,
        }

    def register_mcp_connector(
        self,
        server_id: str,
        *,
        transport: str,
        name: str | None = None,
        description: str | None = None,
        url: str | None = None,
        command: str | None = None,
        args: list[str] | None = None,
        enabled: bool = True,
    ) -> dict[str, Any]:
        result = upsert_mcp_registry_entry(
            server_id,
            transport=transport,
            name=name,
            description=description,
            url=url,
            command=command,
            args=args,
            enabled=enabled,
        )
        self.capabilities.refresh()
        self.bus.publish_nowait("system/mcp", {"action": "register", "connector": result})
        return result

    def unregister_mcp_connector(self, server_id: str) -> dict[str, Any]:
        result = delete_mcp_registry_entry(server_id)
        self.capabilities.refresh()
        self.bus.publish_nowait("system/mcp", {"action": "unregister", "result": result})
        return result

    def probe_mcp_connectors(self, server_id: str | None = None, timeout_seconds: float = 3.0) -> dict[str, Any]:
        if server_id:
            result = probe_mcp_registry_entry(server_id, timeout_seconds=timeout_seconds)
            payload = {"counts": {"total": 1, "healthy": 1 if str(result.get("status", "")).lower() == "healthy" else 0}, "servers": [result]}
        else:
            payload = probe_all_mcp_registry_entries(timeout_seconds=timeout_seconds)
        self.capabilities.refresh()
        self.bus.publish_nowait("system/mcp", {"action": "probe", "result": payload})
        return payload

    def plugin_status(self) -> dict[str, Any]:
        return self.plugins.status()

    def install_plugin(self, plugin_id: str) -> dict[str, Any]:
        result = self.plugins.install(plugin_id)
        self.bus.publish_nowait("system/plugins", {"action": "install", "result": result})
        return result

    def uninstall_plugin(self, plugin_id: str) -> dict[str, Any]:
        result = self.plugins.uninstall(plugin_id)
        self.bus.publish_nowait("system/plugins", {"action": "uninstall", "result": result})
        return result