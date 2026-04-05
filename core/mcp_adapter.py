"""
MCPAdapter
==========
Runtime connection manager for MCP (Model Context Protocol) servers.

Wraps ``mcp_registry.py`` (CRUD and health state) and provides a runtime
layer for connecting to and calling tools on registered MCP servers.

Supports HTTP (JSON-RPC 2.0) and stdio (command-resolution only) transports.

Usage::

    adapter = MCPAdapter(bus=bus, timeout_seconds=5.0)

    # Register and connect
    adapter.register_server("my-server", transport="http", url="http://localhost:8080")
    adapter.connect("my-server")

    # Discover and call tools
    tools = adapter.list_server_tools("my-server")
    result = adapter.call_tool("my-server", "some_tool", {"arg": "value"})

    # Health
    print(adapter.health_status())
"""
from __future__ import annotations

import json
import time
from typing import Any
from urllib import error, request

from core.mcp_registry import (
    delete_mcp_registry_entry,
    list_mcp_registry_with_health,
    probe_mcp_registry_entry,
    upsert_mcp_registry_entry,
)


class MCPConnectionError(RuntimeError):
    """Raised when an MCP server connection or call fails."""


class MCPAdapter:
    """Runtime connection manager for MCP servers.

    Parameters
    ----------
    bus:
        Optional event bus for publish_nowait calls.
    timeout_seconds:
        HTTP and probe timeout.  Defaults to 5.0 seconds.
    """

    def __init__(self, bus: Any | None = None, timeout_seconds: float = 5.0) -> None:
        self._bus = bus
        self._timeout = float(timeout_seconds)
        # server_id → last healthy probe result
        self._connected: dict[str, dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Server management
    # ------------------------------------------------------------------

    def list_servers(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        """Return all registered MCP servers with their health state."""
        servers = list_mcp_registry_with_health()
        if enabled_only:
            servers = [s for s in servers if bool(s.get("enabled", True))]
        return servers

    def connect(self, server_id: str) -> dict[str, Any]:
        """Probe a server and mark it as connected if healthy.

        Returns the probe result dict.  The server is only added to the
        connected set when the probe status is ``"healthy"``.
        """
        result = probe_mcp_registry_entry(server_id, timeout_seconds=self._timeout)
        status = str(result.get("status", "")).lower()
        if status == "healthy":
            self._connected[server_id] = result
            self._publish("mcp/connected", {"server_id": server_id, "status": status})
        else:
            self._connected.pop(server_id, None)
            self._publish("mcp/connect_failed", {
                "server_id": server_id,
                "status": status,
                "error": result.get("last_error"),
            })
        return result

    def disconnect(self, server_id: str) -> dict[str, Any]:
        """Remove a server from the connected set.

        Does not affect the registry entry.  Always succeeds even if the
        server was not connected.
        """
        was_connected = server_id in self._connected
        self._connected.pop(server_id, None)
        self._publish("mcp/disconnected", {
            "server_id": server_id,
            "was_connected": was_connected,
        })
        return {"server_id": server_id, "disconnected": True, "was_connected": was_connected}

    def connected_servers(self) -> list[str]:
        """Return ids of servers currently in the connected set."""
        return sorted(self._connected)

    # ------------------------------------------------------------------
    # Tool discovery
    # ------------------------------------------------------------------

    def list_server_tools(self, server_id: str) -> list[dict[str, Any]]:
        """Fetch the tool list from an HTTP MCP server via ``tools/list``.

        Returns an empty list for stdio servers (no live protocol call is
        made without a running process).
        """
        entry = self._get_entry(server_id)
        transport = str(entry.get("transport", "")).lower()
        if transport != "http":
            return []
        url = str(entry.get("url", "")).strip()
        if not url:
            return []
        payload = {
            "jsonrpc": "2.0",
            "id": f"list-tools-{server_id}",
            "method": "tools/list",
            "params": {},
        }
        response = self._http_call(url, payload)
        result = response.get("result", {})
        tools = result.get("tools", []) if isinstance(result, dict) else []
        return [dict(t) for t in tools if isinstance(t, dict)]

    # ------------------------------------------------------------------
    # Tool invocation
    # ------------------------------------------------------------------

    def call_tool(
        self,
        server_id: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Forward a ``tools/call`` JSON-RPC request to an HTTP MCP server.

        Returns a normalized result dict::

            {"server_id": ..., "tool_name": ..., "status": "ok", "result": ..., "latency_ms": ...}

        Raises ``MCPConnectionError`` for transport errors or non-HTTP servers.
        """
        entry = self._get_entry(server_id)
        transport = str(entry.get("transport", "")).lower()
        if transport != "http":
            raise MCPConnectionError(
                f"Tool calls only supported for HTTP transport; "
                f"server {server_id!r} uses {transport!r}"
            )
        url = str(entry.get("url", "")).strip()
        if not url:
            raise MCPConnectionError(f"No URL configured for MCP server: {server_id!r}")

        payload = {
            "jsonrpc": "2.0",
            "id": f"call-{server_id}-{tool_name}-{int(time.time())}",
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": dict(arguments or {})},
        }
        started = time.perf_counter()
        response = self._http_call(url, payload)
        latency_ms = (time.perf_counter() - started) * 1000.0

        self._publish("mcp/tool_called", {
            "server_id": server_id,
            "tool_name": tool_name,
            "latency_ms": round(latency_ms, 3),
        })

        if "error" in response:
            return {
                "server_id": server_id,
                "tool_name": tool_name,
                "status": "error",
                "error": response["error"],
                "latency_ms": round(latency_ms, 3),
            }
        return {
            "server_id": server_id,
            "tool_name": tool_name,
            "status": "ok",
            "result": response.get("result"),
            "latency_ms": round(latency_ms, 3),
        }

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def health_status(self) -> dict[str, Any]:
        """Return aggregate health across all registered servers."""
        servers = self.list_servers()
        healthy = sum(1 for s in servers if str(s.get("status", "")).lower() == "healthy")
        disabled = sum(1 for s in servers if not bool(s.get("enabled", True)))
        return {
            "counts": {
                "total": len(servers),
                "healthy": healthy,
                "connected": len(self._connected),
                "disabled": disabled,
            },
            "connected": sorted(self._connected),
            "servers": servers,
        }

    # ------------------------------------------------------------------
    # Registry delegation
    # ------------------------------------------------------------------

    def register_server(
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
        """Register a new MCP server in the persistent registry."""
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
        self._publish("mcp/registered", {"server_id": server_id, "transport": transport})
        return result

    def unregister_server(self, server_id: str) -> dict[str, Any]:
        """Remove an MCP server from the registry and the connected set."""
        self._connected.pop(server_id, None)
        result = delete_mcp_registry_entry(server_id)
        self._publish("mcp/unregistered", {"server_id": server_id})
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_entry(self, server_id: str) -> dict[str, Any]:
        for entry in list_mcp_registry_with_health():
            if str(entry.get("id", "")) == server_id:
                return entry
        raise ValueError(f"Unknown MCP server: {server_id!r}")

    def _http_call(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        req = request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self._timeout) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else {}
        except error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            raise MCPConnectionError(f"HTTP {exc.code} from {url}: {raw}") from exc
        except (error.URLError, TimeoutError) as exc:
            raise MCPConnectionError(f"Connection failed to {url}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise MCPConnectionError(f"Invalid JSON response from {url}: {exc}") from exc

    def _publish(self, topic: str, payload: dict[str, Any]) -> None:
        if self._bus is None:
            return
        try:
            self._bus.publish_nowait(topic, payload)
        except Exception:
            pass
