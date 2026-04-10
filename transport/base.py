# CHIMERA_HARNESS: base_transport
"""
ChimeraTransport: Abstract base class for streaming and event transport in OpenChimera.
"""
from abc import ABC, abstractmethod
from typing import Any, Dict

class ChimeraTransport(ABC):
    """Abstract base for Chimera streaming/event transports."""
    @abstractmethod
    async def send_event(self, event_type: str, data: Dict[str, Any]) -> None:
        pass

    @abstractmethod
    async def stream_tokens(self, token_generator) -> None:
        pass

    @abstractmethod
    async def send_tool_result(self, tool_name: str, result: Dict[str, Any]) -> None:
        pass
