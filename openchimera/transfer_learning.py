"""Public re-export of the OpenChimera transfer learning subsystem.

Usage::

    from openchimera.transfer_learning import TransferLearning
"""
from __future__ import annotations

from core.transfer_learning import (  # noqa: F401
    PatternType,
    PatternEntry,
    TransferCandidate,
    DomainProfile,
    DomainWorldModel,
    TransferLearning,
    SkillSynthesizer,
)

__all__ = [
    "PatternType",
    "PatternEntry",
    "TransferCandidate",
    "DomainProfile",
    "DomainWorldModel",
    "TransferLearning",
    "SkillSynthesizer",
]
