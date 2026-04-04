from __future__ import annotations

import logging
import threading
from collections import deque
from typing import Any, Callable


LOGGER = logging.getLogger(__name__)


class EventBus:
    def __init__(self, history_size: int = 256):
        self._subscribers: dict[str, list[Callable[[Any], None]]] = {}
        self._history = deque(maxlen=history_size)
        self._lock = threading.RLock()

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

    def publish(self, topic: str, data: Any = None) -> None:
        with self._lock:
            callbacks = list(self._subscribers.get(topic, []))
            self._history.append({"topic": topic, "data": data})

        for callback in callbacks:
            try:
                callback(data)
            except Exception as exc:
                LOGGER.warning("EventBus subscriber failed for topic %s: %s", topic, exc)

    def publish_nowait(self, topic: str, data: Any = None) -> None:
        self.publish(topic, data)

    def recent_events(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._history)
