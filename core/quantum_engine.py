"""OpenChimera Quantum Engine — async-first consensus voting.

Promoted from chimera.quantum_engine (Upgrade 2A) and adapted for
the OpenChimera control plane.

Provides weighted multi-agent consensus with:
  - Speculative gather: returns as soon as quorum + early-exit confidence met,
    skipping stragglers to reduce tail latency
  - Weighted voting: dynamic per-agent reputation via exponential moving average,
    updated on feedback
  - Answer fingerprint similarity for soft deduplication and vote grouping
  - Hard timeout with partial-result consensus fallback
  - Destructive interference: contradicting high-weight groups reduce confidence
  - Domain-aware reputation tracking
  - Optional embedding-based answer similarity (sentence-transformers)
  - Optional reputation persistence via SemanticMemory
"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lazy embedding model singleton
# ---------------------------------------------------------------------------

_EMBED_MODEL: Optional[Any] = None
_EMBED_LOCK = threading.Lock()


def _get_embed_model():
    """Return the embedding model singleton, or None if unavailable."""
    global _EMBED_MODEL
    if _EMBED_MODEL is None:
        with _EMBED_LOCK:
            if _EMBED_MODEL is None:
                try:
                    from sentence_transformers import SentenceTransformer
                    _EMBED_MODEL = SentenceTransformer(
                        "all-MiniLM-L6-v2", device="cpu"
                    )
                except ImportError:
                    _EMBED_MODEL = "unavailable"
    return _EMBED_MODEL if _EMBED_MODEL != "unavailable" else None


# ---------------------------------------------------------------------------
# Data transfer objects
# ---------------------------------------------------------------------------

@dataclass
class AgentResponse:
    """Single agent answer with latency and optional confidence estimate."""
    agent_id: str
    answer: Any
    latency_ms: float
    confidence: float = 1.0
    domain: str = "general"

    def answer_hash(self) -> str:
        """Stable fingerprint for dedup / similarity grouping."""
        return hashlib.sha256(str(self.answer).encode("utf-8")).hexdigest()


@dataclass
class ConsensusResult:
    """Final result returned by QuantumEngine.gather()."""
    answer: Any
    confidence: float
    participating: int
    total_invited: int
    latency_ms: float
    vote_breakdown: Dict[str, float] = field(default_factory=dict)
    early_exit: bool = False
    partial: bool = False
    contradictions_found: int = 0


# ---------------------------------------------------------------------------
# Reputation / weight tracking
# ---------------------------------------------------------------------------

class AgentReputation:
    """
    Exponential moving average of each agent's answer quality.
    Updated after ground-truth or user-feedback scoring via .update().
    Supports domain-aware scoring keyed by (agent_id, domain).
    Optional persistence to SemanticMemory.
    """

    def __init__(
        self,
        alpha: float = 0.15,
        default_weight: float = 0.7,
        persistence: Optional[Any] = None,
    ) -> None:
        self._alpha = alpha
        self._default = default_weight
        self._scores: Dict[tuple[str, str], float] = {}
        self._persistence = persistence
        self._update_count = 0
        if self._persistence is not None:
            self.load_from_persistence()

    def weight(self, agent_id: str, domain: str = "general") -> float:
        """Return the current reputation weight (0-1) for an agent."""
        return (
            self._scores.get((agent_id, domain))
            or self._scores.get((agent_id, "general"))
            or self._default
        )

    def update(self, agent_id: str, correct: bool,
               domain: str = "general") -> None:
        """Update EMA reputation for agent_id based on correctness feedback."""
        key = (agent_id, domain)
        old = self._scores.get(key, self._default)
        signal = 1.0 if correct else 0.0
        new_score = old * (1 - self._alpha) + signal * self._alpha
        self._scores[key] = new_score
        log.debug(
            "[Reputation] %s[%s]: %.3f → %.3f (%s)",
            agent_id, domain, old, new_score,
            "correct" if correct else "wrong",
        )
        self._update_count += 1
        if self._update_count % 10 == 0:
            self.save()

    def snapshot(self) -> Dict[str, float]:
        """Return a copy of all current scores (flattened for serialisation)."""
        return {f"{aid}::{dom}": w for (aid, dom), w in self._scores.items()}

    def load(self, flat: Dict[str, float]) -> None:
        """Restore from a snapshot() dict."""
        for key, w in flat.items():
            if "::" in key:
                aid, dom = key.split("::", 1)
                self._scores[(aid, dom)] = w

    def save(self) -> None:
        """Persist current scores to SemanticMemory if available."""
        if self._persistence is None:
            return
        snap = self.snapshot()
        try:
            self._persistence.assert_fact(
                subject="quantum_engine",
                predicate="reputation_snapshot",
                object=json.dumps(snap),
                confidence=1.0,
                source="agent_reputation",
            )
        except Exception as exc:
            log.warning("[Reputation] Failed to persist: %s", exc)

    def load_from_persistence(self) -> None:
        """Restore scores from SemanticMemory on startup."""
        if self._persistence is None:
            return
        try:
            triples = self._persistence.query(
                subject="quantum_engine",
                predicate="reputation_snapshot",
            )
            if triples:
                snap = json.loads(triples[-1].object)
                self.load(snap)
                log.info(
                    "[Reputation] Loaded %d scores from SemanticMemory",
                    len(snap),
                )
        except Exception as exc:
            log.warning("[Reputation] Failed to load: %s", exc)


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------

class QuantumEngine:
    """
    Runs speculative multi-agent consensus.

    Key parameters
    ──────────────
    quorum          Minimum number of responses before voting can begin.
    early_exit_conf Confidence threshold for early exit (0–1). When the
                    current quorum reaches this confidence, remaining agents
                    are not awaited.
    hard_timeout_ms Absolute wall-clock timeout in ms. Partial consensus is
                    returned if this fires before quorum.
    similarity_fn   Optional callable(a, b) → float in [0,1]. Defaults to
                    embedding cosine similarity (falls back to exact match
                    if sentence-transformers is not installed).
    reputation      Optional AgentReputation instance shared across rounds.
    """

    def __init__(
        self,
        quorum: int = 2,
        early_exit_conf: float = 0.8,
        hard_timeout_ms: int = 5000,
        similarity_fn: Optional[Callable[[Any, Any], float]] = None,
        reputation: Optional[AgentReputation] = None,
    ) -> None:
        self._round = 0
        self.quorum = max(1, quorum)
        self.early_exit_conf = float(early_exit_conf)
        self.hard_timeout_ms = int(hard_timeout_ms)
        self.similarity_fn: Callable[[Any, Any], float] = (
            similarity_fn or self._embedding_sim
        )
        self.reputation = reputation or AgentReputation()
        self.profiler: Optional[ConsensusProfiler] = None

    def with_profiler(self) -> "QuantumEngine":
        """Enable built-in profiling. Returns self for chaining."""
        self.profiler = ConsensusProfiler()
        return self

    async def gather(
        self,
        task: Any,
        agents: Dict[str, Callable[..., Any]],
        context: Optional[dict] = None,
    ) -> ConsensusResult:
        """
        Dispatch `task` to all agents concurrently.
        Return ConsensusResult as soon as quorum + early-exit conditions are met.
        """
        self._round += 1
        round_id = self._round
        invited = list(agents.keys())
        timeout_s = self.hard_timeout_ms / 1000.0

        log.info(
            "[QE round=%d] Dispatching to %d agents (quorum=%d timeout=%dms)",
            round_id, len(invited), self.quorum, self.hard_timeout_ms,
        )

        start = time.perf_counter()
        responses: List[AgentResponse] = []

        # Launch all agents concurrently
        loop = asyncio.get_running_loop()
        futures = {
            agent_id: loop.create_task(
                self._timed_call(agent_id, fn, task, context or {})
            )
            for agent_id, fn in agents.items()
        }

        # Speculative gather: collect results as they arrive
        deadline = start + timeout_s
        remaining = list(futures.keys())
        done_ids: set[str] = set()
        early_exit = False

        while remaining:
            now = time.perf_counter()
            time_left = deadline - now
            if time_left <= 0:
                # Hard timeout: cancel pending tasks
                for aid in remaining:
                    if aid not in done_ids:
                        futures[aid].cancel()
                log.warning(
                    "[QE round=%d] Hard timeout hit with %d pending",
                    round_id, len(remaining),
                )
                break

            # Wait for the next task to finish (with remaining deadline)
            done, _ = await asyncio.wait(
                [futures[aid] for aid in remaining if aid not in done_ids],
                timeout=time_left,
                return_when=asyncio.FIRST_COMPLETED,
            )

            if not done:
                # Timeout fired
                for aid in remaining:
                    if aid not in done_ids:
                        futures[aid].cancel()
                break

            for task_obj in done:
                # Identify which agent_id this task belongs to
                for aid, ft in futures.items():
                    if ft is task_obj and aid not in done_ids:
                        done_ids.add(aid)
                        result = task_obj.result()
                        if result is not None:
                            responses.append(result)
                        break

            remaining = [aid for aid in invited if aid not in done_ids]

            # Check for early exit
            if len(responses) >= self.quorum:
                conf = self._compute_confidence(responses)
                if conf >= self.early_exit_conf:
                    early_exit = True
                    log.info(
                        "[QE round=%d] Early exit at conf=%.2f "
                        "with %d/%d responses",
                        round_id, conf, len(responses), len(invited),
                    )
                    # Cancel remaining tasks
                    for aid in remaining:
                        futures[aid].cancel()
                    break

        wall_ms = (time.perf_counter() - start) * 1000.0

        if not responses:
            raise ConsensusFailure(
                f"[QE round={round_id}] All {len(invited)} agents "
                f"failed or timed out"
            )

        partial = len(responses) < self.quorum
        result = self._vote(responses, invited, wall_ms, early_exit)
        result.partial = partial

        log.info(
            "[QE round=%d] Consensus: conf=%.2f latency=%.0fms "
            "early_exit=%s partial=%s",
            round_id, result.confidence, result.latency_ms,
            early_exit, partial,
        )

        if self.profiler is not None:
            self.profiler.record(result)

        return result

    async def _timed_call(
        self,
        agent_id: str,
        fn: Callable[..., Any],
        task: Any,
        context: dict,
    ) -> Optional[AgentResponse]:
        """Run a single agent callable; return AgentResponse or None on failure."""
        t0 = time.perf_counter()
        try:
            if inspect.iscoroutinefunction(fn):
                raw = await fn(task, context)
            else:
                raw = await asyncio.get_running_loop().run_in_executor(
                    None, fn, task, context,
                )
            latency_ms = (time.perf_counter() - t0) * 1000.0

            # Parse structured response or apply heuristic confidence
            if isinstance(raw, dict) and "answer" in raw and "confidence" in raw:
                answer = raw["answer"]
                confidence = float(raw["confidence"])
                domain = raw.get("domain", "general")
            else:
                answer = raw
                domain = "general"
                # Fallback: heuristic confidence from answer length + hedging words
                text = str(answer)
                hedging = {
                    "maybe", "possibly", "perhaps",
                    "uncertain", "not sure", "unclear",
                }
                hedge_count = sum(1 for w in hedging if w in text.lower())
                base = min(1.0, len(text) / 300)
                confidence = max(0.1, base - (hedge_count * 0.1))

            return AgentResponse(
                agent_id=agent_id,
                answer=answer,
                latency_ms=latency_ms,
                confidence=confidence,
                domain=domain,
            )
        except Exception as exc:
            log.warning("[QE] Agent '%s' failed: %s", agent_id, exc)
            return None

    def _is_contradiction(self, a: Any, b: Any) -> bool:
        """Heuristic contradiction detection between two answers."""
        sa, sb = str(a).lower().strip(), str(b).lower().strip()
        # Explicit negation pairs
        neg_pairs = [
            ("yes", "no"), ("true", "false"), ("correct", "incorrect"),
            ("positive", "negative"), ("valid", "invalid"),
        ]
        for pos, neg in neg_pairs:
            if (pos in sa and neg in sb) or (neg in sa and pos in sb):
                return True
        # Numerical disagreement: both contain numbers, numbers differ > 20%
        nums_a = [float(x) for x in re.findall(r"-?\d+\.?\d*", sa)]
        nums_b = [float(x) for x in re.findall(r"-?\d+\.?\d*", sb)]
        if nums_a and nums_b:
            ratio = abs(nums_a[0] - nums_b[0]) / (abs(nums_a[0]) + 1e-9)
            if ratio > 0.20:
                return True
        return False

    def _vote(
        self,
        responses: List[AgentResponse],
        invited: List[str],
        wall_ms: float,
        early_exit: bool,
    ) -> ConsensusResult:
        """
        Weighted voting with destructive interference.

        Constructive: score(answer) = Σ reputation(agent, domain) × confidence
        Destructive: high-weight contradicting groups penalise winner confidence.
        """
        # Group by similarity: map each response to a canonical index
        groups: List[List[AgentResponse]] = []
        for resp in responses:
            placed = False
            for group in groups:
                if self.similarity_fn(resp.answer, group[0].answer) >= 0.9:
                    group.append(resp)
                    placed = True
                    break
            if not placed:
                groups.append([resp])

        # Score each group
        group_scores: List[tuple[float, Any, List[AgentResponse]]] = []
        for group in groups:
            score = sum(
                self.reputation.weight(r.agent_id, domain=r.domain)
                * r.confidence
                for r in group
            )
            group_scores.append((score, group[0].answer, group))

        group_scores.sort(key=lambda x: x[0], reverse=True)

        total_weight = sum(s for s, _, _ in group_scores)
        best_score, best_answer, best_group = group_scores[0]

        # Destructive interference: high-weight contradicting groups
        # reduce confidence
        opposition_weight = sum(
            score for score, ans, _ in group_scores[1:]
            if score > 0.15 * total_weight
            and self._is_contradiction(best_answer, ans)
        )
        raw_confidence = best_score / total_weight if total_weight else 0.0
        interference_penalty = (
            (opposition_weight / total_weight) * 0.5 if total_weight else 0.0
        )
        final_confidence = max(0.05, raw_confidence - interference_penalty)

        # Count significant contradictions for postmortem flagging
        contradictions_found = sum(
            1 for score, ans, _ in group_scores[1:]
            if score > 0.15 * total_weight
            and self._is_contradiction(best_answer, ans)
        )

        vote_breakdown: Dict[str, float] = {
            str(ans): round(s / total_weight, 4) if total_weight > 0 else 0.0
            for s, ans, _ in group_scores
        }

        return ConsensusResult(
            answer=best_answer,
            confidence=min(1.0, final_confidence),
            participating=len(responses),
            total_invited=len(invited),
            latency_ms=wall_ms,
            vote_breakdown=vote_breakdown,
            early_exit=early_exit,
            contradictions_found=contradictions_found,
        )

    def _compute_confidence(self, responses: List[AgentResponse]) -> float:
        """Quick confidence estimate during streaming (before final vote)."""
        if not responses:
            return 0.0
        weights = [
            self.reputation.weight(r.agent_id, domain=r.domain) * r.confidence
            for r in responses
        ]
        return sum(weights) / len(weights)

    @staticmethod
    def _embedding_sim(a: Any, b: Any) -> float:
        """Embedding cosine similarity; falls back to exact match."""
        model = _get_embed_model()
        if model is None:
            return 1.0 if str(a).strip() == str(b).strip() else 0.0
        import numpy as np
        vecs = model.encode([str(a), str(b)], normalize_embeddings=True)
        return float(np.dot(vecs[0], vecs[1]))

    @staticmethod
    def _exact_sim(a: Any, b: Any) -> float:
        """Exact string equality similarity."""
        return 1.0 if str(a).strip() == str(b).strip() else 0.0


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------

class ConsensusFailure(RuntimeError):
    """Raised when no quorum can be formed before timeout."""


# ---------------------------------------------------------------------------
# Profiler
# ---------------------------------------------------------------------------

class ConsensusProfiler:
    """
    Collects per-round stats. Access via `profiler.summary()` for dashboards.
    """

    def __init__(self) -> None:
        self._rounds: List[dict] = []

    def record(self, result: ConsensusResult) -> None:
        self._rounds.append({
            "latency_ms": result.latency_ms,
            "confidence": result.confidence,
            "participating": result.participating,
            "early_exit": result.early_exit,
            "partial": result.partial,
            "contradictions_found": result.contradictions_found,
        })

    def summary(self) -> dict:
        if not self._rounds:
            return {
                "rounds": 0,
                "p50_latency_ms": 0.0,
                "p95_latency_ms": 0.0,
                "avg_confidence": 0.0,
                "early_exit_pct": 0.0,
                "partial_pct": 0.0,
            }
        latencies = sorted(r["latency_ms"] for r in self._rounds)
        n = len(latencies)
        p50 = latencies[int(n * 0.50)]
        p95 = latencies[min(int(n * 0.95), n - 1)]
        avg_conf = sum(r["confidence"] for r in self._rounds) / n
        early_pct = 100.0 * sum(
            1 for r in self._rounds if r["early_exit"]
        ) / n
        partial_pct = 100.0 * sum(
            1 for r in self._rounds if r["partial"]
        ) / n
        return {
            "rounds": n,
            "p50_latency_ms": round(p50, 1),
            "p95_latency_ms": round(p95, 1),
            "avg_confidence": round(avg_conf, 4),
            "early_exit_pct": round(early_pct, 1),
            "partial_pct": round(partial_pct, 1),
        }
