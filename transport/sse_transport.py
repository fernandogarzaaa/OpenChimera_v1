# CHIMERA_HARNESS: sse_transport
"""
SSETransport: Server-Sent Events transport for OpenChimera using FastAPI StreamingResponse.
"""
from typing import Any, Dict, AsyncGenerator
from fastapi.responses import StreamingResponse
from .base import ChimeraTransport

class SSETransport(ChimeraTransport):
    async def send_event(self, event_type: str, data: Dict[str, Any]) -> StreamingResponse:
        async def event_stream():
            yield f"event: {event_type}\ndata: {data}\n\n"
        return StreamingResponse(event_stream(), media_type="text/event-stream")

    async def stream_tokens(self, token_generator: AsyncGenerator[str, None]) -> StreamingResponse:
        async def token_stream():
            async for token in token_generator:
                yield f"data: {token}\n\n"
        return StreamingResponse(token_stream(), media_type="text/event-stream")

    async def send_tool_result(self, tool_name: str, result: Dict[str, Any]) -> StreamingResponse:
        return await self.send_event(f"tool_result:{tool_name}", result)
