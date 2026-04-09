"""Public re-export of the OpenChimera meta-learning subsystem.

Usage::

    from openchimera.meta_learning import MetaLearning
"""
from __future__ import annotations

from core.meta_learning import (  # noqa: F401
    AdaptationReason,
    LearningStrategy,
    StrategyOutcome,
    AdaptationEvent,
    RegimeShift,
    MetaLearning,
    HyperparameterTuner,
)

__all__ = [
    "AdaptationReason",
    "LearningStrategy",
    "StrategyOutcome",
    "AdaptationEvent",
    "RegimeShift",
    "MetaLearning",
    "HyperparameterTuner",
]
