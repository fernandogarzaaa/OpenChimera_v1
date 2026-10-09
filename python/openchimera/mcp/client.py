"""MCP client wrapper with server registry."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from openchimera.config import load_settings


class MCPClient:
    """MCP stdio client for connecting to external tool servers."""

    def __init__(self, command: str, args: list[str] | None = None, env: dict[str, str] | None = None) -> None:
        self.command = command
        self.args = args or []
        self.env = env or {}
        self._session: Any = None

    async def connect(self) -> None:
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client

            server_params = StdioServerParameters(
                command=self.command,
                args=self.args,
                env=self.env,
            )
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    self._session = session
        except ImportError:
            raise RuntimeError("mcp package not installed. Run: pip install mcp")

    async def list_tools(self) -> list[dict[str, Any]]:
        if not self._session:
            return []
        tools = await self._session.list_tools()
        return [
            {"name": t.name, "description": t.description, "input_schema": t.inputSchema}
            for t in tools.tools
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if not self._session:
            return {"error": "Not connected"}
        result = await self._session.call_tool(name, arguments=arguments)
        return result


class MCPRegistry:
    """Registry of configured MCP servers."""

    def __init__(self) -> None:
        self._servers: dict[str, MCPClient] = {}
        self._load_registry()

    def _load_registry(self) -> None:
        settings = load_settings()
        path = Path(settings.mcp.registry_path)
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for name, cfg in data.get("servers", {}).items():
                self._servers[name] = MCPClient(
                    command=cfg["command"],
                    args=cfg.get("args", []),
                    env=cfg.get("env", {}),
                )
        except Exception:
            pass

    def list_servers(self) -> list[str]:
        return list(self._servers.keys())

    def get_client(self, name: str) -> MCPClient | None:
        return self._servers.get(name)

    async def list_all_tools(self) -> list[dict[str, Any]]:
        all_tools = []
        for name, client in self._servers.items():
            try:
                await client.connect()
                tools = await client.list_tools()
                for t in tools:
                    t["server"] = name
                all_tools.extend(tools)
            except Exception:
                continue
        return all_tools
