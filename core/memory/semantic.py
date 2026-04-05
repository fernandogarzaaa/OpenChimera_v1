from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any
from uuid import uuid4

from core._bus_fallback import EventBus
from core._database_fallback import DatabaseManager


def _dict_factory(cursor: Any, row: Any) -> dict[str, Any]:
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


class SemanticMemory:
    """Knowledge-graph layer backed by SQLite kg_triples / kg_assertions."""

    def __init__(self, db: DatabaseManager, bus: EventBus) -> None:
        self._db = db
        self._bus = bus
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Triples
    # ------------------------------------------------------------------

    def add_triple(
        self,
        subject: str,
        predicate: str,
        object_: str,
        confidence: float = 1.0,
        source: str = "system",
    ) -> dict[str, Any]:
        ts = int(time.time())
        with self._lock:
            with self._db.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO kg_triples (subject, predicate, object, confidence, source, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(subject, predicate, object)
                    DO UPDATE SET confidence=excluded.confidence,
                                  source=excluded.source,
                                  timestamp=excluded.timestamp
                    """,
                    (subject, predicate, object_, confidence, source, ts),
                )
        triple = {
            "subject": subject,
            "predicate": predicate,
            "object": object_,
            "confidence": confidence,
            "source": source,
            "timestamp": ts,
        }
        self._bus.publish("memory.triple.added", triple)
        return triple

    def get_triples(
        self,
        subject: str | None = None,
        predicate: str | None = None,
        object_: str | None = None,
        min_confidence: float | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if subject is not None:
            clauses.append("subject = ?")
            params.append(subject)
        if predicate is not None:
            clauses.append("predicate = ?")
            params.append(predicate)
        if object_ is not None:
            clauses.append("object = ?")
            params.append(object_)
        if min_confidence is not None:
            clauses.append("confidence >= ?")
            params.append(min_confidence)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        # `where` is built exclusively from controlled string literals; no user
        # data is interpolated into the SQL string itself.
        with self._db.transaction() as conn:
            conn.row_factory = _dict_factory
            rows = conn.execute(
                f"SELECT subject, predicate, object, confidence, source, timestamp FROM kg_triples {where}",
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def update_confidence(
        self, subject: str, predicate: str, object_: str, confidence: float
    ) -> bool:
        with self._lock:
            with self._db.transaction() as conn:
                conn.execute(
                    "UPDATE kg_triples SET confidence = ? WHERE subject = ? AND predicate = ? AND object = ?",
                    (confidence, subject, predicate, object_),
                )
        return True

    def remove_triple(
        self, subject: str, predicate: str, object_: str
    ) -> bool:
        with self._lock:
            with self._db.transaction() as conn:
                conn.execute(
                    "DELETE FROM kg_triples WHERE subject = ? AND predicate = ? AND object = ?",
                    (subject, predicate, object_),
                )
        return True

    # Alias matching task spec
    def delete_triple(self, subject: str, predicate: str, object_: str) -> bool:
        return self.remove_triple(subject, predicate, object_)

    def count(self) -> int:
        with self._db.transaction() as conn:
            row = conn.execute("SELECT COUNT(*) FROM kg_triples").fetchone()
        return row[0] if row else 0

    # ------------------------------------------------------------------
    # Graph traversal
    # ------------------------------------------------------------------

    def subgraph(self, entity: str, depth: int = 2) -> dict[str, Any]:
        """BFS from entity up to *depth* hops; returns nodes/edges dict."""
        # Return empty if entity is completely unknown
        if not self.get_triples(subject=entity) and not self.get_triples(object_=entity):
            return {"nodes": [], "edges": []}

        visited: set[str] = set()
        edges: list[dict[str, Any]] = []
        frontier: set[str] = {entity}

        for _ in range(depth):
            if not frontier:
                break
            next_frontier: set[str] = set()
            for node in frontier:
                visited.add(node)
                for triple in self.get_triples(subject=node):
                    edges.append(triple)
                    obj = triple["object"]
                    if obj not in visited:
                        next_frontier.add(obj)
            frontier = next_frontier - visited

        all_nodes = visited | frontier
        return {
            "nodes": [{"id": n} for n in all_nodes],
            "edges": edges,
        }

    def find_related(
        self, subject: str, max_hops: int = 2
    ) -> list[dict[str, Any]]:
        result = self.subgraph(subject, depth=max_hops)
        return result.get("edges", [])

    def shortest_path(
        self, source: str, target: str
    ) -> list[str] | None:
        """BFS shortest path; returns node list or None if unreachable."""
        if source == target:
            return [source]
        queue: deque[tuple[str, list[str]]] = deque([(source, [source])])
        visited: set[str] = {source}
        while queue:
            node, path = queue.popleft()
            for triple in self.get_triples(subject=node):
                neighbor = triple["object"]
                if neighbor == target:
                    return path + [neighbor]
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [neighbor]))
        return None

    # ------------------------------------------------------------------
    # Assertions
    # ------------------------------------------------------------------

    def add_assertion(
        self,
        subject: str,
        predicate: str,
        object_: str,
        asserted_by: str,
        valid_from: int | None = None,
        valid_until: int | None = None,
    ) -> dict[str, Any]:
        assertion_id = str(uuid4())
        if valid_from is None:
            valid_from = int(time.time())
        row: dict[str, Any] = {
            "id": assertion_id,
            "subject": subject,
            "predicate": predicate,
            "object": object_,
            "asserted_by": asserted_by,
            "valid_from": valid_from,
            "valid_until": valid_until,
        }
        with self._lock:
            with self._db.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO kg_assertions
                        (id, subject, predicate, object, asserted_by, valid_from, valid_until)
                    VALUES
                        (:id, :subject, :predicate, :object, :asserted_by, :valid_from, :valid_until)
                    """,
                    row,
                )
        assertion = {
            "id": assertion_id,
            "subject": subject,
            "predicate": predicate,
            "object": object_,
            "asserted_by": asserted_by,
            "valid_from": valid_from,
            "valid_until": valid_until,
        }
        self._bus.publish("memory.assertion.added", assertion)
        return assertion

    def get_assertions(
        self,
        subject: str | None = None,
        predicate: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if subject is not None:
            clauses.append("subject = ?")
            params.append(subject)
        if predicate is not None:
            clauses.append("predicate = ?")
            params.append(predicate)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        # `where` is built exclusively from controlled string literals.
        with self._db.transaction() as conn:
            conn.row_factory = _dict_factory
            rows = conn.execute(
                f"SELECT * FROM kg_assertions {where} ORDER BY valid_from DESC",
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    def get_active_assertions(
        self,
        subject: str | None = None,
        predicate: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return assertions that have not been retracted (valid_until IS NULL)."""
        clauses: list[str] = ["valid_until IS NULL"]
        params: list[Any] = []
        if subject is not None:
            clauses.append("subject = ?")
            params.append(subject)
        if predicate is not None:
            clauses.append("predicate = ?")
            params.append(predicate)
        where = "WHERE " + " AND ".join(clauses)
        # `where` is built exclusively from controlled string literals.
        with self._db.transaction() as conn:
            conn.row_factory = _dict_factory
            rows = conn.execute(
                f"SELECT * FROM kg_assertions {where} ORDER BY valid_from DESC",
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    def retract_assertion(self, assertion_id: str) -> bool:
        """Soft-delete by setting valid_until to now."""
        ts = int(time.time())
        with self._lock:
            with self._db.transaction() as conn:
                conn.execute(
                    "UPDATE kg_assertions SET valid_until = ? WHERE id = ?",
                    (ts, assertion_id),
                )
        return True

    def expire_assertions(self, before_timestamp: int) -> int:
        """Hard-expire all assertions whose valid_until < before_timestamp."""
        with self._lock:
            with self._db.transaction() as conn:
                cur = conn.execute(
                    "DELETE FROM kg_assertions WHERE valid_until IS NOT NULL AND valid_until < ?",
                    (before_timestamp,),
                )
        return cur.rowcount
