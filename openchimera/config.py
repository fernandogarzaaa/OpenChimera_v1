"""Public re-export of the OpenChimera configuration module.

Usage::

    from openchimera.config import ROOT, load_runtime_profile
"""
from __future__ import annotations

from core.config import ROOT, load_runtime_profile  # noqa: F401

__all__ = ["ROOT", "load_runtime_profile"]
