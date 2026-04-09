"""Public re-export of the OpenChimera self-model subsystem.

Usage::

    from openchimera.self_model import SelfModel
"""
from __future__ import annotations

from core.self_model import (  # noqa: F401
    HealthStatus,
    TrendDirection,
    CapabilitySnapshot,
    PerformanceDelta,
    SubsystemHealth,
    SelfModel,
)

__all__ = [
    "HealthStatus",
    "TrendDirection",
    "CapabilitySnapshot",
    "PerformanceDelta",
    "SubsystemHealth",
    "SelfModel",
]
