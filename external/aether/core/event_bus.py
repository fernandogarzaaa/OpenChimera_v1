"""
AETHER EventBus — OpenChimera external integration.

Provides a thread-safe publish/subscribe event bus compatible with the
AetherKernelAdapter contract:
  - EventBus class with start(), publish_nowait(), publish(), subscribe()
  - Module-level `bus` singleton picked up automatically by the adapter
"""
from __future__ import annotations

import logging
import threading
from collections import deque
from typing import Any, Callable


LOGGER = logging.getLogger("aether.event_bus")


class EventBus:
    """Thread-safe synchronous event bus."""

    def __init__(self, history_size: int = 256):
        self._subscribers: dict[str, list[Callable[[Any], None]]] = {}
        self._history: deque[dict[str, Any]] = deque(maxlen=history_size)
        self._lock = threading.RLock()
        self._running = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """
        Mark the bus as running.
        Returns None (not a coroutine) — the adapter handles both cases.
        """
        with self._lock:
            self._running = True
        LOGGER.info("[AETHER EventBus] started.")

    def stop(self) -> None:
        with self._lock:
            self._running = False
        LOGGER.info("[AETHER EventBus] stopped.")

    # ------------------------------------------------------------------
    # Subscriptions
    # ------------------------------------------------------------------

    def subscribe(self, topic: str, callback: Callable[[Any], None]) -> None:
        with self._lock:
            self._subscribers.setdefault(topic, []).append(callback)

    def unsubscribe(self, topic: str, callback: Callable[[Any], None]) -> None:
        with self._lock:
            callbacks = self._subscribers.get(topic, [])
            if callback in callbacks:
                callbacks.remove(callback)
            if not callbacks and topic in self._subscribers:
                del self._subscribers[topic]

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    def publish(self, topic: str, data: Any = None) -> None:
        with self._lock:
            callbacks = list(self._subscribers.get(topic, []))
            self._history.append({"topic": topic, "data": data})

        for callback in callbacks:
            try:
                callback(data)
            except Exception as exc:
                LOGGER.warning("Subscriber error on topic %r: %s", topic, exc)

    def publish_nowait(self, topic: str, data: Any = None) -> None:
        """Alias for publish() — provided for async-compatible callers."""
        self.publish(topic, data)

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    def recent_events(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._history)

    def subscriber_count(self, topic: str) -> int:
        with self._lock:
            return len(self._subscribers.get(topic, []))


# Module-level singleton — picked up by AetherKernelAdapter via getattr(module, "bus")
bus = EventBus()
