"""Public re-export of the OpenChimera knowledge base.

Usage::

    from openchimera.knowledge_base import KnowledgeBase
"""
from __future__ import annotations

from core.knowledge_base import (  # noqa: F401
    KnowledgeEntry,
    KnowledgeBase,
)

__all__ = ["KnowledgeEntry", "KnowledgeBase"]
