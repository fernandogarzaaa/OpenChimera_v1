from __future__ import annotations

try:
    from chimera_core.db import Database  # noqa: F401  Rust fast path
    _BACKEND = "rust"
except ImportError:  # pragma: no cover
    from core._database_fallback import DatabaseManager as Database  # noqa: F401
    _BACKEND = "python"

# Re-export legacy name so any 'from core.database import DatabaseManager' keeps working.
try:
    from chimera_core.db import Database as DatabaseManager  # noqa: F401
except ImportError:  # pragma: no cover
    from core._database_fallback import DatabaseManager  # noqa: F401


def backend() -> str:
    """Return 'rust' or 'python' to identify the active backend."""
    return _BACKEND
