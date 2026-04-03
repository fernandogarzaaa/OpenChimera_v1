from __future__ import annotations

from typing import Any

from core.mcp_registry import (
    delete_mcp_registry_entry,
    list_mcp_registry_with_health,
    probe_all_mcp_registry_entries,
    probe_mcp_registry_entry,
    upsert_mcp_registry_entry,
)


class CapabilityPlane:
    def __init__(self, *, capabilities: Any, plugins: Any, bus: Any) -> None:
        self.capabilities = capabilities
        self.plugins = plugins
        self.bus = bus

    def capability_status(self) -> dict[str, Any]:
        return self.capabilities.status()

    def list_capabilities(self, kind: str) -> list[dict[str, Any]]:
        return self.capabilities.list_kind(kind)

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