"""Public re-export of the OpenChimera multi-agent orchestrator.

Usage::

    from openchimera.orchestrator import MultiAgentOrchestrator
"""
from __future__ import annotations

from core.multi_agent_orchestrator import (  # noqa: F401
    MultiAgentOrchestrator,
    OrchestratorResult,
)

__all__ = ["MultiAgentOrchestrator", "OrchestratorResult"]
