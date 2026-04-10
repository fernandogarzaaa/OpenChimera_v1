# CHIMERA_HARNESS: ws_transport
"""
WSTransport: WebSocket transport for persistent connections in OpenChimera.
"""
from typing import Any, Dict, AsyncGenerator
from fastapi import WebSocket
from .base import ChimeraTransport

class WSTransport(ChimeraTransport):
    def __init__(self, websocket: WebSocket) -> None:
        self.websocket = websocket

    async def send_event(self, event_type: str, data: Dict[str, Any]) -> None:
        await self.websocket.send_json({"event": event_type, "data": data})

    async def stream_tokens(self, token_generator: AsyncGenerator[str, None]) -> None:
        async for token in token_generator:
            await self.websocket.send_text(token)

    async def send_tool_result(self, tool_name: str, result: Dict[str, Any]) -> None:
        await self.send_event(f"tool_result:{tool_name}", result)
