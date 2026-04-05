from __future__ import annotations

import json
import math
import struct
import threading
import time
from typing import Any
from uuid import uuid4

from core._bus_fallback import EventBus
from core._database_fallback import DatabaseManager


def _dict_factory(cursor: Any, row: Any) -> dict[str, Any]:
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


def _cosine_similarity(a: bytes, b: bytes) -> float:
    """Compute cosine similarity between two packed float32 byte buffers."""
    n = len(a) // 4
    if n == 0 or len(a) != len(b):
        return 0.0
    va = struct.unpack(f"{n}f", a)
    vb = struct.unpack(f"{n}f", b)
    dot = sum(x * y for x, y in zip(va, vb))
    mag_a = math.sqrt(sum(x * x for x in va))
    mag_b = math.sqrt(sum(x * x for x in vb))
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return dot / (mag_a * mag_b)


class EpisodicMemory:
    """Persistent episodic memory backed by SQLite."""

    def __init__(self, db: DatabaseManager, bus: EventBus) -> None:
        self._db = db
        self._bus = bus
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Episodes
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
    ) -> dict[str, Any]:
        episode_id = str(uuid4())
        ts = int(time.time())
        row = {
            "id": episode_id,
            "session_id": session_id,
            "timestamp": ts,
            "goal": goal,
            "outcome": outcome,
            "confidence_initial": confidence_initial,
            "confidence_final": confidence_final,
            "models_used": json.dumps(models_used),
            "reasoning_chain": json.dumps(reasoning_chain),
            "failure_reason": failure_reason,
            "domain": domain,
            "embedding": embedding,
            "curated": 0,
        }
        with self._lock:
            with self._db.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO episodes
                        (id, session_id, timestamp, goal, outcome,
                         confidence_initial, confidence_final,
                         models_used, reasoning_chain,
                         failure_reason, domain, embedding, curated)
                    VALUES
                        (:id, :session_id, :timestamp, :goal, :outcome,
                         :confidence_initial, :confidence_final,
                         :models_used, :reasoning_chain,
                         :failure_reason, :domain, :embedding, :curated)
                    """,
                    row,
                )
        episode = self._decode_episode(row)
        self._bus.publish("memory.episode.recorded", {
            "episode_id": episode_id,
            "session_id": session_id,
            "outcome": outcome,
            "domain": domain,
        })
        return episode

    def get_episode(self, episode_id: str) -> dict[str, Any] | None:
        with self._db.transaction() as conn:
            conn.row_factory = _dict_factory
            row = conn.execute(
                "SELECT * FROM episodes WHERE id = ?", (episode_id,)
            ).fetchone()
        if row is None:
            return None
        return self._decode_episode(row)

    def list_episodes(
        self,
        session_id: str | None = None,
        domain: str | None = None,
        outcome: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if session_id is not None:
            clauses.append("session_id = ?")
            params.append(session_id)
        if domain is not None:
            clauses.append("domain = ?")
            params.append(domain)
        if outcome is not None:
            clauses.append("outcome = ?")
            params.append(outcome)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        with self._db.transaction() as conn:
            conn.row_factory = _dict_factory
            rows = conn.execute(
                "SELECT * FROM episodes " + where + " ORDER BY timestamp DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._decode_episode(r) for r in rows]

    # Alias to match task spec naming
    def get_episodes(
        self,
        domain: str | None = None,
        outcome: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return self.list_episodes(domain=domain, outcome=outcome, limit=limit)

    def find_similar(
        self, embedding: bytes, limit: int = 5
    ) -> list[dict[str, Any]]:
        with self._db.transaction() as conn:
            conn.row_factory = _dict_factory
            rows = conn.execute(
                "SELECT * FROM episodes WHERE embedding IS NOT NULL"
            ).fetchall()

        scored = []
        for row in rows:
            emb = row.get("embedding")
            if emb is None:
                continue
            sim = _cosine_similarity(embedding, emb)
            ep = self._decode_episode(row)
            ep["similarity"] = sim
            scored.append(ep)

        scored.sort(key=lambda x: x["similarity"], reverse=True)
        return scored[:limit]

    def mark_curated(self, episode_id: str) -> bool:
        with self._lock:
            with self._db.transaction() as conn:
                conn.execute(
                    "UPDATE episodes SET curated = 1 WHERE id = ?",
                    (episode_id,),
                )
        return True

    def count(
        self, domain: str | None = None, outcome: str | None = None
    ) -> int:
        clauses: list[str] = []
        params: list[Any] = []
        if domain is not None:
            clauses.append("domain = ?")
            params.append(domain)
        if outcome is not None:
            clauses.append("outcome = ?")
            params.append(outcome)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        with self._db.transaction() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM episodes " + where, params
            ).fetchone()
        return row[0] if row else 0

    # ------------------------------------------------------------------
    # Postmortems
    # ------------------------------------------------------------------

    def record_postmortem(
        self,
        episode_id: str,
        failure_mode: str,
        contributing_models: list[str],
        prevention_hypothesis: str,
        correct_reasoning: str | None = None,
        knowledge_gap_description: str | None = None,
        confidence_at_failure: float = 0.0,
        similar_past_failures: list[str] | None = None,
    ) -> dict[str, Any]:
        pm_id = str(uuid4())
        ts = int(time.time())
        row: dict[str, Any] = {
            "id": pm_id,
            "episode_id": episode_id,
            "timestamp": ts,
            "failure_mode": failure_mode,
            "contributing_models": json.dumps(contributing_models),
            "correct_reasoning": correct_reasoning,
            "prevention_hypothesis": prevention_hypothesis,
            "knowledge_gap_description": knowledge_gap_description,
            "confidence_at_failure": confidence_at_failure,
            "similar_past_failures": json.dumps(similar_past_failures or []),
            "incorporated_into_training": 0,
        }
        with self._lock:
            with self._db.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO episode_postmortems
                        (id, episode_id, timestamp, failure_mode,
                         contributing_models, correct_reasoning,
                         prevention_hypothesis, knowledge_gap_description,
                         confidence_at_failure, similar_past_failures,
                         incorporated_into_training)
                    VALUES
                        (:id, :episode_id, :timestamp, :failure_mode,
                         :contributing_models, :correct_reasoning,
                         :prevention_hypothesis, :knowledge_gap_description,
                         :confidence_at_failure, :similar_past_failures,
                         :incorporated_into_training)
                    """,
                    row,
                )
        pm = dict(row)
        pm["contributing_models"] = contributing_models
        pm["similar_past_failures"] = similar_past_failures or []
        self._bus.publish("memory.postmortem.recorded", {
            "id": pm_id,
            "episode_id": episode_id,
            "failure_mode": failure_mode,
        })
        return pm

    # Alias matching task spec
    def add_postmortem(self, episode_id: str, **kwargs: Any) -> dict[str, Any]:
        return self.record_postmortem(episode_id=episode_id, **kwargs)

    def get_postmortems(self, episode_id: str) -> list[dict[str, Any]]:
        with self._db.transaction() as conn:
            conn.row_factory = _dict_factory
            rows = conn.execute(
                "SELECT * FROM episode_postmortems WHERE episode_id = ? ORDER BY timestamp DESC",
                (episode_id,),
            ).fetchall()
        result = []
        for row in rows:
            pm = dict(row)
            pm["contributing_models"] = json.loads(pm.get("contributing_models") or "[]")
            pm["similar_past_failures"] = json.loads(pm.get("similar_past_failures") or "[]")
            result.append(pm)
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _decode_episode(row: dict[str, Any]) -> dict[str, Any]:
        ep = dict(row)
        if isinstance(ep.get("models_used"), str):
            ep["models_used"] = json.loads(ep["models_used"])
        if isinstance(ep.get("reasoning_chain"), str):
            ep["reasoning_chain"] = json.loads(ep["reasoning_chain"])
        return ep


