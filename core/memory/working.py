from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any


class WorkingMemory:
    """Bounded LRU cache backed by an OrderedDict."""

    def __init__(self, max_size: int = 128) -> None:
        self._max_size = max_size
        self._cache: OrderedDict[str, Any] = OrderedDict()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Core access
    # ------------------------------------------------------------------

    def get(self, key: str) -> Any | None:
        with self._lock:
            if key not in self._cache:
                return None
            self._cache.move_to_end(key)
            return self._cache[key]

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                self._cache[key] = value
            else:
                self._cache[key] = value
                if len(self._cache) > self._max_size:
                    self._cache.popitem(last=False)

    def evict(self, key: str) -> bool:
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    # Alias used by the task spec
    def delete(self, key: str) -> bool:
        return self.evict(key)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    def size(self) -> int:
        with self._lock:
            return len(self._cache)

    def keys(self) -> list[str]:
        with self._lock:
            return list(self._cache.keys())

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._cache)

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __contains__(self, key: str) -> bool:
        with self._lock:
            return key in self._cache

    def __len__(self) -> int:
        with self._lock:
            return len(self._cache)
