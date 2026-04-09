"""Public re-export of the OpenChimera evolution engine.

Usage::

    from openchimera.evolution import EvolutionEngine
"""
from __future__ import annotations

from core.evolution import (  # noqa: F401
    ContinualLearningPipeline,
    DPOSignal,
    EvolutionEngine,
)

__all__ = ["ContinualLearningPipeline", "DPOSignal", "EvolutionEngine"]
