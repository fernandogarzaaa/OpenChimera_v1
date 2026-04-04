from __future__ import annotations

try:
    from chimera_core.bus import EventBus, EventReceiver  # noqa: F401  Rust fast path
    _BACKEND = "rust"
except ImportError:  # pragma: no cover
    from core._bus_fallback import EventBus  # noqa: F401  pure-Python fallback
    EventReceiver = None
    _BACKEND = "python"


def backend() -> str:
    """Return 'rust' or 'python' to identify the active backend."""
    return _BACKEND
