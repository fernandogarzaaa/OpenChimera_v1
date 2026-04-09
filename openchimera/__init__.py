"""OpenChimera — local-first LLM orchestration runtime.

This package re-exports the public surface of the ``core`` package so
that callers can use either namespace interchangeably::

    from core.kernel import Kernel
    from openchimera.kernel import Kernel       # identical

Available sub-modules
─────────────────────
    openchimera.api_server          — HTTP API server
    openchimera.agent_pool          — Agent pool and spec types
    openchimera.causal_reasoning    — Causal reasoning engine
    openchimera.chimera_bridge      — ChimeraLang bridge
    openchimera.cli                 — CLI entry-point
    openchimera.config              — Runtime configuration
    openchimera.deliberation        — Deliberation graph and engine
    openchimera.embodied_interaction — Embodied interaction subsystem
    openchimera.ethical_reasoning   — Ethical reasoning engine
    openchimera.evolution           — Evolution engine
    openchimera.goal_planner        — Goal planner
    openchimera.kernel              — Bootstrap kernel
    openchimera.knowledge_base      — Knowledge base
    openchimera.memory              — Unified memory facade
    openchimera.meta_learning       — Meta-learning subsystem
    openchimera.metacognition       — Metacognition engine
    openchimera.orchestrator        — Multi-agent orchestrator
    openchimera.plan_mode           — Plan mode subsystem
    openchimera.provider            — LLM provider
    openchimera.quantum_engine      — Quantum consensus engine
    openchimera.query_engine        — Query engine
    openchimera.safety_layer        — Safety layer
    openchimera.self_model          — Self-model subsystem
    openchimera.session_memory      — Session memory persistence
    openchimera.social_cognition    — Social cognition subsystem
    openchimera.transfer_learning   — Transfer learning subsystem
    openchimera.world_model         — World model
"""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _version

try:
    __version__: str = _version("openchimera")
except PackageNotFoundError:  # running from source without installation
    __version__ = "0.0.0.dev0"

__all__ = ["__version__"]
