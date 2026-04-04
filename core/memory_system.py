from __future__ import annotations

import logging
from typing import Any

from core._bus_fallback import EventBus
from core._database_fallback import DatabaseManager
from core.memory.working import WorkingMemory
from core.memory.episodic import EpisodicMemory
from core.memory.semantic import SemanticMemory

logger = logging.getLogger(__name__)


class MemorySystem:
    """Unified facade over working, episodic, and semantic memory."""

    def __init__(
        self,
        db: DatabaseManager,
        bus: EventBus,
        working_max_size: int = 128,
    ) -> None:
        self._working = WorkingMemory(max_size=working_max_size)
        self._episodic = EpisodicMemory(db=db, bus=bus)
        self._semantic = SemanticMemory(db=db, bus=bus)
        self._bus = bus
        logger.info(
            "MemorySystem initialised (working_max=%d)", working_max_size
        )

    # ------------------------------------------------------------------
    # Sub-memory accessors
    # ------------------------------------------------------------------

    @property
    def working(self) -> WorkingMemory:
        return self._working

    @property
    def episodic(self) -> EpisodicMemory:
        return self._episodic

    @property
    def semantic(self) -> SemanticMemory:
        return self._semantic

    # ------------------------------------------------------------------
    # Working-memory convenience
    # ------------------------------------------------------------------

    def cache_get(self, key: str) -> Any | None:
        return self._working.get(key)

    def cache_put(self, key: str, value: Any) -> None:
        self._working.put(key, value)

    # ------------------------------------------------------------------
    # Episodic convenience
    # ------------------------------------------------------------------

    def record_episode(
        self,
        session_id: str,
        goal: str,
        outcome: str,
        confidence_initial: float,
        confidence_final: float,
        models_used: list[str],
        reasoning_chain: list[str],
        failure_reason: str | None = None,
        domain: str = "general",
        embedding: bytes | None = None,
    ) -> dict:
        return self._episodic.record_episode(
            session_id=session_id,
            goal=goal,
            outcome=outcome,
            confidence_initial=confidence_initial,
            confidence_final=confidence_final,
            models_used=models_used,
            reasoning_chain=reasoning_chain,
            failure_reason=failure_reason,
            domain=domain,
            embedding=embedding,
        )

    def find_similar_episodes(
        self, embedding: bytes, limit: int = 5
    ) -> list[dict]:
        return self._episodic.find_similar(embedding, limit=limit)

    # ------------------------------------------------------------------
    # Semantic convenience
    # ------------------------------------------------------------------

    def add_knowledge(
        self,
        subject: str,
        predicate: str,
        object_: str,
        confidence: float = 1.0,
        source: str = "system",
    ) -> None:
        self._semantic.add_triple(
            subject, predicate, object_, confidence=confidence, source=source
        )

    def query_knowledge(
        self,
        subject: str | None = None,
        predicate: str | None = None,
        object_: str | None = None,
    ) -> list[dict]:
        return self._semantic.get_triples(
            subject=subject, predicate=predicate, object_=object_
        )

    def explore_entity(self, entity: str, depth: int = 2) -> dict:
        return self._semantic.subgraph(entity, depth=depth)

    # ------------------------------------------------------------------
    # Cross-memory operations
    # ------------------------------------------------------------------

    def store_and_link(
        self,
        session_id: str,
        goal: str,
        outcome: str,
        confidence_initial: float,
        confidence_final: float,
        models_used: list[str],
        reasoning_chain: list[str],
        failure_reason: str | None = None,
        domain: str = "general",
        embedding: bytes | None = None,
        knowledge_triples: list[tuple[str, str, str]] | None = None,
    ) -> dict[str, Any]:
        episode = self._episodic.record_episode(
            session_id=session_id,
            goal=goal,
            outcome=outcome,
            confidence_initial=confidence_initial,
            confidence_final=confidence_final,
            models_used=models_used,
            reasoning_chain=reasoning_chain,
            failure_reason=failure_reason,
            domain=domain,
            embedding=embedding,
        )

        triples_added = 0
        if knowledge_triples:
            for subj, pred, obj in knowledge_triples:
                self._semantic.add_triple(subj, pred, obj)
                triples_added += 1

        self._bus.publish(
            "memory.linked",
            {
                "episode_id": episode.get("episode_id"),
                "triples_added": triples_added,
            },
        )
        logger.info(
            "store_and_link: episode=%s triples=%d",
            episode.get("episode_id"),
            triples_added,
        )
        return {"episode": episode, "triples_added": triples_added}

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        all_triples = self._semantic.get_triples()
        return {
            "working_size": len(self._working),
            "working_snapshot": self._working.snapshot(),
            "episodic_recent": self._episodic.list_episodes(limit=5),
            "semantic_assertions": self._semantic.get_active_assertions(),
            "knowledge_triples_sample": all_triples[:10],
        }
