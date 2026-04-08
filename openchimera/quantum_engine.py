"""Public re-export of the OpenChimera quantum consensus engine.

Usage::

    from openchimera.quantum_engine import QuantumEngine, ConsensusResult
"""
from __future__ import annotations

from core.quantum_engine import (  # noqa: F401
    ConsensusFailure,
    ConsensusResult,
    QuantumEngine,
)

__all__ = ["ConsensusFailure", "ConsensusResult", "QuantumEngine"]
