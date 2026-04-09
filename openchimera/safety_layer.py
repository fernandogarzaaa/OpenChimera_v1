"""Public re-export of the OpenChimera safety layer.

Usage::

    from openchimera.safety_layer import SafetyLayer
"""
from __future__ import annotations

from core.safety_layer import SafetyLayer  # noqa: F401

__all__ = ["SafetyLayer"]
