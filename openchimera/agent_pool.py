"""Public re-export of the OpenChimera agent pool.

Usage::

    from openchimera.agent_pool import AgentPool, AgentSpec, AgentRole
"""
from __future__ import annotations

from core.agent_pool import (  # noqa: F401
    AgentPool,
    AgentRole,
    AgentSpec,
    AgentStatus,
    create_pool,
)

__all__ = ["AgentPool", "AgentRole", "AgentSpec", "AgentStatus", "create_pool"]
