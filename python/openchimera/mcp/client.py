"""MCP client wrapper."""

import json
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


class MCPClient:
    def __init__(self, command: str, args: list[str] | None = None) -> None:
        self.command = command
        self.args = args or []
        self._session: ClientSession | None = None

    async def connect(self) -> None:
        server_params = StdioServerParameters(command=self.command, args=self.args)
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                self._session = session

    async def list_tools(self) -> list[dict[str, Any]]:
        if not self._session:
            return []
        tools = await self._session.list_tools()
        return [{"name": t.name, "description": t.description} for t in tools.tools]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if not self._session:
            return {"error": "Not connected"}
        result = await self._session.call_tool(name, arguments=arguments)
        return result
