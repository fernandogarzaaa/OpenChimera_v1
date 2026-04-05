from __future__ import annotations

import logging
import math
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from core._bus_fallback import EventBus
from core._database_fallback import DatabaseManager
from core.memory.episodic import EpisodicMemory

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DPOSignal — structured preference signal for inference path injection
# ---------------------------------------------------------------------------

@dataclass
class DPOSignal:
    """Carries a single direct preference optimization signal."""
    prompt: str
    chosen: str
    rejected: str
    reward_delta: float = 0.0
    signal_id: str = field(default_factory=lambda: uuid4().hex)
    recorded_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "prompt": self.prompt,
            "chosen": self.chosen,
            "rejected": self.rejected,
            "reward_delta": self.reward_delta,
            "recorded_at": self.recorded_at,
        }


class EvolutionEngine:
    """DPO training pair generation from episodic memory.

    Pairs successful and failed episodes by embedding cosine similarity
    (threshold > 0.85 by default) to ensure genuinely similar goals are
    compared, not just episodes from the same domain.
    """

    def __init__(self, db: DatabaseManager, bus: EventBus) -> None:
        self._db = db
        self._bus = bus
        self._memory = EpisodicMemory(db, bus)
        self._lock = threading.Lock()
        self._cycles_run = 0
        self._total_pairs = 0
        self._last_cycle_ts: float | None = None
        # Inference-path tracking
        self._response_quality: dict[str, dict[str, Any]] = {}  # record_id → outcome record
        self._dpo_signals: dict[str, DPOSignal] = {}  # signal_id → DPOSignal
        self._thresholds: dict[str, float] = {"similarity_threshold": 0.85}

    # ------------------------------------------------------------------
    # Cosine similarity
    # ------------------------------------------------------------------

    @staticmethod
    def _cosine_similarity(emb1: bytes, emb2: bytes) -> float:
        """Pure-Python cosine similarity for float32-packed byte vectors."""
        try:
            if not emb1 or not emb2 or len(emb1) != len(emb2):
                return 0.0
            n = len(emb1) // 4
            vec1 = struct.unpack(f"{n}f", emb1)
            vec2 = struct.unpack(f"{n}f", emb2)
            dot = sum(a * b for a, b in zip(vec1, vec2))
            norm1 = math.sqrt(sum(a * a for a in vec1))
            norm2 = math.sqrt(sum(b * b for b in vec2))
            if norm1 == 0.0 or norm2 == 0.0:
                return 0.0
            return dot / (norm1 * norm2)
        except Exception as exc:
            log.warning("cosine_similarity failed: %s", exc)
            return 0.0

    # ------------------------------------------------------------------
    # DPO pair generation
    # ------------------------------------------------------------------

    def generate_dpo_pairs(
        self,
        domain: str | None = None,
        min_similarity: float = 0.85,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Generate DPO preference pairs from episodic memory.

        Only pairs episodes whose *goal embeddings* have cosine similarity
        above ``min_similarity`` (default 0.85).  Domain filtering is applied
        as a pre-filter but is **not** sufficient on its own — the embedding
        gate is the authoritative check.
        """
        with self._lock:
            successes = self._memory.list_episodes(
                domain=domain, outcome="success", limit=limit,
            )
            failures = self._memory.list_episodes(
                domain=domain, outcome="failure", limit=limit,
            )

        pairs: list[dict[str, Any]] = []

        for success in successes:
            s_emb = success.get("embedding")
            if s_emb is None:
                continue
            for failure in failures:
                f_emb = failure.get("embedding")
                if f_emb is None:
                    continue

                sim = self._cosine_similarity(s_emb, f_emb)
                if sim <= min_similarity:
                    continue

                pair: dict[str, Any] = {
                    "chosen": success,
                    "rejected": failure,
                    "similarity": round(sim, 6),
                    "pair_id": uuid4().hex,
                }
                pairs.append(pair)

                # Mark both as curated
                self._memory.mark_curated(success["id"])
                self._memory.mark_curated(failure["id"])

                self._bus.publish("evolution.dpo_pair.generated", {
                    "pair_id": pair["pair_id"],
                    "similarity": pair["similarity"],
                    "chosen_id": success["id"],
                    "rejected_id": failure["id"],
                })

        pairs.sort(key=lambda p: p["similarity"], reverse=True)

        with self._lock:
            self._total_pairs += len(pairs)

        log.info(
            "Generated %d DPO pairs (domain=%s, min_sim=%.2f)",
            len(pairs), domain, min_similarity,
        )
        return pairs

    # ------------------------------------------------------------------
    # Preference dataset
    # ------------------------------------------------------------------

    @staticmethod
    def generate_preference_dataset(pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert DPO pairs into a training-ready preference dataset."""
        dataset: list[dict[str, Any]] = []
        for pair in pairs:
            chosen_chain = pair["chosen"].get("reasoning_chain", [])
            rejected_chain = pair["rejected"].get("reasoning_chain", [])

            chosen_text = "\n".join(chosen_chain) if isinstance(chosen_chain, list) else str(chosen_chain)
            rejected_text = "\n".join(rejected_chain) if isinstance(rejected_chain, list) else str(rejected_chain)

            if chosen_text == rejected_text:
                continue

            dataset.append({
                "prompt": pair["chosen"].get("goal", ""),
                "chosen": chosen_text,
                "rejected": rejected_text,
                "similarity": pair["similarity"],
            })
        return dataset

    # ------------------------------------------------------------------
    # Model fitness
    # ------------------------------------------------------------------

    def compute_model_fitness(
        self,
        domain: str | None = None,
        limit: int = 200,
    ) -> dict[str, dict[str, Any]]:
        """Aggregate episode outcomes by model to compute fitness metrics."""
        episodes = self._memory.list_episodes(domain=domain, limit=limit)

        model_stats: dict[str, dict[str, Any]] = {}

        for ep in episodes:
            models = ep.get("models_used", [])
            if isinstance(models, str):
                models = [models]
            outcome = ep.get("outcome", "")
            conf = ep.get("confidence_final", 0.0)

            for model in models:
                if model not in model_stats:
                    model_stats[model] = {
                        "successes": 0,
                        "failures": 0,
                        "total_episodes": 0,
                        "confidence_sum": 0.0,
                    }
                stats = model_stats[model]
                stats["total_episodes"] += 1
                stats["confidence_sum"] += conf
                if outcome == "success":
                    stats["successes"] += 1
                elif outcome == "failure":
                    stats["failures"] += 1

        fitness: dict[str, dict[str, Any]] = {}
        for model, stats in model_stats.items():
            total = stats["total_episodes"]
            fitness[model] = {
                "success_rate": stats["successes"] / total if total else 0.0,
                "avg_confidence": stats["confidence_sum"] / total if total else 0.0,
                "total_episodes": total,
                "failures": stats["failures"],
            }

        return fitness

    # ------------------------------------------------------------------
    # Recommendations
    # ------------------------------------------------------------------

    @staticmethod
    def recommend_model_updates(
        fitness: dict[str, dict[str, Any]],
        min_success_rate: float = 0.6,
    ) -> list[dict[str, Any]]:
        """Recommend actions per model based on fitness metrics."""
        recommendations: list[dict[str, Any]] = []
        for model, stats in fitness.items():
            rate = stats.get("success_rate", 0.0)
            total = stats.get("total_episodes", 0)

            if rate < min_success_rate:
                recommendations.append({
                    "model": model,
                    "action": "retrain",
                    "reason": (
                        f"Success rate {rate:.1%} is below threshold "
                        f"{min_success_rate:.0%} over {total} episodes"
                    ),
                })
            elif rate > 0.9:
                recommendations.append({
                    "model": model,
                    "action": "promote",
                    "reason": (
                        f"Success rate {rate:.1%} exceeds 90% "
                        f"over {total} episodes"
                    ),
                })
            else:
                recommendations.append({
                    "model": model,
                    "action": "monitor",
                    "reason": (
                        f"Success rate {rate:.1%} is acceptable; "
                        f"continue monitoring over {total} episodes"
                    ),
                })

        return recommendations

    # ------------------------------------------------------------------
    # Full evolution cycle
    # ------------------------------------------------------------------

    def evolution_cycle(self, domain: str | None = None) -> dict[str, Any]:
        """Run a complete evolution cycle.

        Steps: generate DPO pairs → build preference dataset →
        compute model fitness → generate recommendations.
        """
        pairs = self.generate_dpo_pairs(domain=domain)
        dataset = self.generate_preference_dataset(pairs)
        fitness = self.compute_model_fitness(domain=domain)
        recommendations = self.recommend_model_updates(fitness)

        with self._lock:
            self._cycles_run += 1
            self._last_cycle_ts = time.time()

        result: dict[str, Any] = {
            "pairs": pairs,
            "dataset_size": len(dataset),
            "model_fitness": fitness,
            "recommendations": recommendations,
        }

        self._bus.publish("evolution.cycle.completed", {
            "pairs_count": len(pairs),
            "dataset_size": len(dataset),
            "models_evaluated": len(fitness),
            "domain": domain,
        })

        log.info(
            "Evolution cycle complete: %d pairs, %d dataset items, %d models",
            len(pairs), len(dataset), len(fitness),
        )
        return result

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        """Return aggregate statistics across all evolution cycles."""
        with self._lock:
            return {
                "cycles_run": self._cycles_run,
                "total_pairs_generated": self._total_pairs,
                "last_cycle_timestamp": self._last_cycle_ts,
                "response_outcomes": len(self._response_quality),
                "dpo_signals_recorded": len(self._dpo_signals),
            }

    # ------------------------------------------------------------------
    # Adaptive thresholds (Phase 2 — Self-Awareness)
    # ------------------------------------------------------------------

    def adapt_thresholds(self, metrics: dict[str, Any]) -> dict[str, float]:
        """Auto-tune the DPO pair similarity threshold based on runtime metrics.

        Rules applied to ``metrics["total_pairs"]``:
        - == 0  → decrease ``similarity_threshold`` by 0.05 (floor 0.50)
        - > 10  → increase ``similarity_threshold`` by 0.02 (cap  0.95)
        - Otherwise → no change

        Publishes an ``evolution.threshold.adapted`` event and returns the
        updated thresholds dict.
        """
        total_pairs = int(metrics.get("total_pairs", self._total_pairs))
        with self._lock:
            current = self._thresholds.get("similarity_threshold", 0.85)
            if total_pairs == 0:
                updated = max(0.5, round(current - 0.05, 4))
            elif total_pairs > 10:
                updated = min(0.95, round(current + 0.02, 4))
            else:
                updated = current
            self._thresholds["similarity_threshold"] = updated
            snapshot = dict(self._thresholds)

        self._bus.publish("evolution.threshold.adapted", {
            "previous_similarity_threshold": current,
            "similarity_threshold": updated,
            "total_pairs": total_pairs,
        })
        log.info(
            "[Evolution] Threshold adapted: similarity_threshold %.4f → %.4f (total_pairs=%d)",
            current, updated, total_pairs,
        )
        return snapshot

    # ------------------------------------------------------------------
    # Inference-path DPO signal tracking (Phase 4 additions)
    # ------------------------------------------------------------------

    def __post_init_extras(self) -> None:
        """Extra state initialised alongside __init__."""
        # These are set in __init__ — here for documentation
        pass

    def record_outcome(self, session_id: str, response: str, outcome_score: float) -> dict[str, Any]:
        """Record an outcome score for a response in a session.

        outcome_score: float in [0, 1] — 1.0 = excellent, 0.0 = failure.
        """
        record = {
            "session_id": session_id,
            "response_preview": response[:300],
            "outcome_score": float(outcome_score),
            "recorded_at": time.time(),
            "record_id": uuid4().hex,
        }
        with self._lock:
            self._response_quality[record["record_id"]] = record

        self._bus.publish("evolution.outcome.recorded", {
            "session_id": session_id,
            "outcome_score": outcome_score,
            "record_id": record["record_id"],
        })
        log.debug("[Evolution] Outcome recorded: session=%s score=%.3f", session_id, outcome_score)
        return record

    def apply_dpo_signals(self, context: dict[str, Any]) -> dict[str, Any]:
        """Inject top learned DPO preferences into an inference context dict.

        Adds ``dpo_preferences`` key with the most relevant chosen/rejected pairs
        so the inference layer can condition on them.
        """
        with self._lock:
            signals = list(self._dpo_signals.values())

        # Sort by reward_delta descending — most impactful signals first
        signals.sort(key=lambda s: s.reward_delta, reverse=True)
        top = signals[:5]

        enhanced = dict(context)
        enhanced["dpo_preferences"] = [s.to_dict() for s in top]
        enhanced["dpo_signal_count"] = len(self._dpo_signals)
        return enhanced

    def track_response_quality(self, response_id: str, better_than_id: str) -> DPOSignal | None:
        """Record that response_id is preferred over better_than_id.

        Attempts to create a DPOSignal if both outcome records exist.
        Returns the created DPOSignal or None if records are missing.
        """
        with self._lock:
            chosen_rec = self._response_quality.get(response_id)
            rejected_rec = self._response_quality.get(better_than_id)

        if chosen_rec is None or rejected_rec is None:
            log.warning(
                "[Evolution] track_response_quality: missing record(s) — "
                "response_id=%s better_than_id=%s", response_id, better_than_id,
            )
            return None

        reward_delta = (
            float(chosen_rec.get("outcome_score", 0.5))
            - float(rejected_rec.get("outcome_score", 0.5))
        )
        signal = DPOSignal(
            prompt=chosen_rec.get("session_id", ""),
            chosen=chosen_rec.get("response_preview", ""),
            rejected=rejected_rec.get("response_preview", ""),
            reward_delta=reward_delta,
        )
        with self._lock:
            self._dpo_signals[signal.signal_id] = signal

        self._bus.publish("evolution.dpo_signal.tracked", {
            "signal_id": signal.signal_id,
            "reward_delta": reward_delta,
        })
        log.info("[Evolution] DPO signal tracked: %s (delta=%.3f)", signal.signal_id, reward_delta)
        return signal
