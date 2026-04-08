"""OpenChimera — local-first LLM orchestration runtime.

This package re-exports the public surface of the ``core`` package and
provides convenience shims so that callers can use either::

    import core
    import openchimera

interchangeably.
"""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _version

try:
    __version__: str = _version("openchimera")
except PackageNotFoundError:  # running from source without installation
    __version__ = "0.0.0.dev0"

__all__ = ["__version__"]
