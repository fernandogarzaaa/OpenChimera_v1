"""AETHER stub — EventBus (OpenChimera bundled implementation)."""
import asyncio
import logging

log = logging.getLogger(__name__)


class EventBus:
    async def start(self) -> None:
        log.info("[AETHER] EventBus running (stub mode)")
        while True:
            await asyncio.sleep(3600)

    def publish_nowait(self, event: str, data: object = None) -> None:
        log.debug("[AETHER] Event: %s", event)


bus: EventBus | None = None
