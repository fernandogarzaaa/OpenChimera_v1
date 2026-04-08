"""OpenChimera — local-first LLM orchestration runtime.

This package re-exports the public surface of the ``core`` package so
that callers can use either namespace interchangeably::

    from core.kernel import Kernel
    from openchimera.kernel import Kernel       # identical

Available sub-modules
─────────────────────
    openchimera.api_server      — HTTP API server
    openchimera.agent_pool      — Agent pool and spec types
    openchimera.chimera_bridge  — ChimeraLang bridge
    openchimera.cli             — CLI entry-point
    openchimera.config          — Runtime configuration
    openchimera.kernel          — Bootstrap kernel
    openchimera.memory          — Unified memory facade
    openchimera.orchestrator    — Multi-agent orchestrator
    openchimera.provider        — LLM provider
    openchimera.quantum_engine  — Quantum consensus engine
    openchimera.query_engine    — Query engine
    openchimera.session_memory  — Session memory persistence
"""
from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as _version

try:
    __version__: str = _version("openchimera")
except PackageNotFoundError:  # running from source without installation
    __version__ = "0.0.0.dev0"

__all__ = ["__version__"]
