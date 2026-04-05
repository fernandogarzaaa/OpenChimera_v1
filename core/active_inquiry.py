"""OpenChimera Active Inquiry — contradiction detection and clarifying questions.

Scans the semantic knowledge graph for contradictions (same subject+predicate
with differing objects) and generates natural-language clarifying questions.
Maintains an open-question queue with resolve/pending lifecycle management.

Architecture
────────────
ActiveInquiry   Main engine: detect → generate → post → resolve.

Key capabilities:
1. Contradiction detection — same (subject, predicate) with multiple objects
2. Question generation — natural-language phrasing of contradictions
3. Question lifecycle — post, resolve, pending
4. Inquiry cycles — run_inquiry_cycle() orchestrates the full pipeline
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


class ActiveInquiry:
    """Detects contradictions in knowledge/memory and generates clarifying questions.

    Operates over a :class:`~core.memory.semantic.SemanticMemory` (triple
    store) and an optional :class:`~core.memory.episodic.EpisodicMemory`
    (episode store).  All public methods are thread-safe.

    Parameters
    ──────────
    semantic   SemanticMemory instance to scan for contradictions.
    episodic   EpisodicMemory instance (reserved for future episode-based
               contradiction detection; may be None).
    """

    def __init__(self, semantic: Any, episodic: Any) -> None:
        self._semantic = semantic
        self._episodic = episodic
        self._open_questions: List[Dict[str, Any]] = []
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Contradiction detection
    # ------------------------------------------------------------------

    def detect_contradictions(
        self, domain: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Scan semantic triples for contradictions.

        A contradiction exists when the same (subject, predicate) pair maps to
        **multiple** objects with **different** confidence scores.

        Parameters
        ──────────
        domain  Unused filter reserved for future domain-scoped scanning.
                Currently ignored — all triples are scanned.

        Returns
        ──────
        List of contradiction dicts:
            subject, predicate, values (list of {object, confidence}),
            contradiction_score (float: stdev of confidence scores, or
            1.0 - min_conf/max_conf when len > 1).
        """
        # Fetch all triples (optionally we could filter by domain metadata
        # in future; for now, scan everything)
        all_triples: List[Dict[str, Any]] = self._semantic.get_triples()

        # Group by (subject, predicate)
        groups: Dict[tuple, List[Dict[str, Any]]] = {}
        for triple in all_triples:
            key = (triple["subject"], triple["predicate"])
            groups.setdefault(key, []).append(triple)

        contradictions: List[Dict[str, Any]] = []
        for (subject, predicate), triples in groups.items():
            if len(triples) < 2:
                continue

            # Only flag if there are different objects
            objects = [t["object"] for t in triples]
            if len(set(objects)) < 2:
                continue

            confidences = [t["confidence"] for t in triples]
            min_c = min(confidences)
            max_c = max(confidences)
            if max_c > 0:
                contradiction_score = round(1.0 - min_c / max_c, 4)
            else:
                contradiction_score = 0.0

            contradictions.append({
                "subject": subject,
                "predicate": predicate,
                "values": [
                    {"object": t["object"], "confidence": t["confidence"]}
                    for t in triples
                ],
                "contradiction_score": contradiction_score,
            })

        log.debug(
            "[ActiveInquiry] detect_contradictions: found %d contradiction(s)",
            len(contradictions),
        )
        return contradictions

    # ------------------------------------------------------------------
    # Question generation
    # ------------------------------------------------------------------

    def generate_question(self, contradiction: Dict[str, Any]) -> str:
        """Generate a natural-language clarifying question for a contradiction.

        Parameters
        ──────────
        contradiction  A dict as returned by :meth:`detect_contradictions`.

        Returns
        ──────
        A human-readable question string.
        """
        subject = contradiction.get("subject", "?")
        predicate = contradiction.get("predicate", "?")
        values = contradiction.get("values", [])

        if not values:
            return f"What is the {predicate} of {subject}?"

        if len(values) == 1:
            return (
                f"Is {subject}'s {predicate} really "
                f"'{values[0].get('object', '?')}'?"
            )

        # Build "is it A or B (or C...)?" phrasing
        objects = [v.get("object", "?") for v in values]
        if len(objects) == 2:
            choice = f"'{objects[0]}' or '{objects[1]}'"
        else:
            joined = "', '".join(objects[:-1])
            choice = f"'{joined}', or '{objects[-1]}'"

        return f"For {subject}'s {predicate}, is it {choice}?"

    # ------------------------------------------------------------------
    # Question lifecycle
    # ------------------------------------------------------------------

    def post_question(
        self,
        question: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Post a clarifying question to the open questions list.

        Parameters
        ──────────
        question  The question string.
        context   Optional metadata dict (e.g. the originating contradiction).

        Returns
        ──────
        dict with keys: question_id, question, context, created_at, resolved.
        """
        qid = str(uuid.uuid4())
        entry: Dict[str, Any] = {
            "question_id": qid,
            "question": question,
            "context": context or {},
            "created_at": time.time(),
            "resolved": False,
            "answer": None,
        }
        with self._lock:
            self._open_questions.append(entry)

        log.debug("[ActiveInquiry] Posted question %s: %r", qid[:8], question[:80])
        return entry

    def resolve_question(self, question_id: str, answer: str) -> bool:
        """Mark a question as resolved with the given answer.

        Parameters
        ──────────
        question_id  The UUID of the question to resolve.
        answer       The resolution answer string.

        Returns
        ──────
        True if the question was found and marked resolved; False otherwise.
        """
        with self._lock:
            for q in self._open_questions:
                if q["question_id"] == question_id:
                    q["resolved"] = True
                    q["answer"] = answer
                    q["resolved_at"] = time.time()
                    log.debug(
                        "[ActiveInquiry] Resolved question %s", question_id[:8],
                    )
                    return True
        return False

    def pending_questions(self) -> List[Dict[str, Any]]:
        """Return all unresolved questions (snapshot, not live view)."""
        with self._lock:
            return [dict(q) for q in self._open_questions if not q["resolved"]]

    # ------------------------------------------------------------------
    # Full inquiry cycle
    # ------------------------------------------------------------------

    def run_inquiry_cycle(
        self, domain: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Run a full contradiction → question → post cycle.

        1. Detect contradictions in semantic memory.
        2. For each contradiction, generate a clarifying question.
        3. Post the question (if not already posted for same subject+predicate).

        Parameters
        ──────────
        domain  Optional domain filter passed to :meth:`detect_contradictions`.

        Returns
        ──────
        List of newly posted question dicts.
        """
        contradictions = self.detect_contradictions(domain=domain)
        newly_posted: List[Dict[str, Any]] = []

        # Avoid double-posting for the same (subject, predicate) pair
        with self._lock:
            existing_keys: set = set()
            for q in self._open_questions:
                ctx = q.get("context", {})
                key = (ctx.get("subject"), ctx.get("predicate"))
                if key[0] is not None:
                    existing_keys.add(key)

        for contradiction in contradictions:
            key = (contradiction["subject"], contradiction["predicate"])
            if key in existing_keys:
                continue

            question = self.generate_question(contradiction)
            entry = self.post_question(question, context=contradiction)
            newly_posted.append(entry)
            existing_keys.add(key)

        log.info(
            "[ActiveInquiry] Inquiry cycle: %d contradiction(s) → %d new question(s)",
            len(contradictions),
            len(newly_posted),
        )
        return newly_posted
