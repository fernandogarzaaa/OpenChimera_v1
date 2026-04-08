"""Shim exposing ``core.api_server`` under the ``openchimera`` namespace.

Usage::

    from openchimera.api_server import OpenChimeraAPIServer
"""
from __future__ import annotations

from core.api_server import OpenChimeraAPIServer, RequestValidationFailure  # noqa: F401

__all__ = ["OpenChimeraAPIServer", "RequestValidationFailure"]
