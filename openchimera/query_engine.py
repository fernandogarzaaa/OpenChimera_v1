"""Public re-export of the OpenChimera query engine.

Usage::

    from openchimera.query_engine import QueryEngine
"""
from __future__ import annotations

from core.query_engine import QueryEngine  # noqa: F401

__all__ = ["QueryEngine"]
