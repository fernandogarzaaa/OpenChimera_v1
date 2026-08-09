"""Base provider interface."""

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator


class BaseProvider(ABC):
    name: str = "base"

    def __init__(self, api_key: str = "", base_url: str = "", default_model: str = "") -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.default_model = default_model
        self._healthy: bool | None = None
        self._latency_ms: int | None = None

    @abstractmethod
    async def chat(self, messages: list[dict[str, str]], model: str | None = None, tools: list[dict] | None = None) -> dict[str, Any]:
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        ...

    @property
    def healthy(self) -> bool:
        return self._healthy or False

    @property
    def latency_ms(self) -> int | None:
        return self._latency_ms

    def to_status(self) -> dict[str, Any]:
        return {
            "id": self.name,
            "name": self.name.capitalize(),
            "enabled": bool(self.api_key or self.base_url),
            "healthy": self.healthy,
            "latency_ms": self.latency_ms,
            "default_model": self.default_model,
            "models": [self.default_model],
            "last_error": None,
            "last_checked": None,
        }
