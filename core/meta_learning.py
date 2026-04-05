"""OpenChimera Meta-Learning — learning-to-learn engine.

Optimises hyperparameters and strategy selection based on historical
performance data.  Tracks multiple learning strategies, records outcomes,
adapts parameters via exponential-moving-average feedback, and detects
regime shifts that trigger exploration of alternative strategies.

Fully portable — purely in-memory with EventBus notifications.
No hardcoded paths, no external dependencies beyond the core bus.

Architecture
────────────
LearningStrategy       Immutable descriptor for a parameterised strategy.
StrategyOutcome        Result of applying a strategy in a domain.
AdaptationEvent        Record of a parameter change and its reason.
RegimeShift            Detected transition between dominant strategies.
MetaLearning           Main engine combining tracking, adaptation, and selection.

Key capabilities:
1. Strategy registry — named strategies with typed parameter dicts
2. Performance tracking — per-strategy outcome history with timestamps
3. Bayesian-lite adaptation — EMA-based parameter adjustment on feedback
4. Strategy selection — pick best strategy for a domain/context
5. Hyperparameter optimisation — bounded hill-climbing for numeric params
6. Regime detection — trigger exploration when performance declines
7. Snapshot/export — full state serialisation for persistence
"""
from __future__ import annotations

import hashlib
import logging
import random
import statistics
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Deque, Dict, List, Optional, Tuple

from core._bus_fallback import EventBus

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class AdaptationReason(str, Enum):
    """Why a strategy parameter was changed."""
    PERFORMANCE_DECLINE = "performance_decline"
    EXPLORATION = "exploration"
    DOMAIN_SHIFT = "domain_shift"
    FEEDBACK = "feedback"


# ---------------------------------------------------------------------------
# Data objects
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LearningStrategy:
    """A parameterised learning strategy for a given domain."""
    strategy_id: str
    name: str
    parameters: Dict[str, Any]
    domain: str
    created_at: float
    performance_score: float = 0.5


@dataclass(frozen=True)
class StrategyOutcome:
    """Outcome of applying a strategy in a domain."""
    strategy_id: str
    domain: str
    success: bool
    confidence: float
    latency_ms: float
    timestamp: float


@dataclass(frozen=True)
class AdaptationEvent:
    """Record of a single parameter adaptation."""
    strategy_id: str
    parameter: str
    old_value: float
    new_value: float
    reason: AdaptationReason
    timestamp: float


@dataclass(frozen=True)
class RegimeShift:
    """Detected transition between dominant strategies in a domain."""
    domain: str
    old_strategy_id: str
    new_strategy_id: str
    trigger_reason: str
    timestamp: float


# ---------------------------------------------------------------------------
# Meta-Learning engine
# ---------------------------------------------------------------------------

class MetaLearning:
    """
    Learning-to-learn engine that tracks strategies, records outcomes,
    adapts parameters, and detects regime shifts.

    Thread-safe.  Publishes meta-learning events to EventBus.

    Parameters
    ──────────
    bus               EventBus for publishing events.
    alpha             EMA smoothing factor for performance updates (0..1).
    exploration_rate  Probability of selecting a random strategy instead of best.
    history_limit     Maximum outcome records retained per strategy.
    """

    def __init__(
        self,
        bus: EventBus,
        alpha: float = 0.2,
        exploration_rate: float = 0.1,
        history_limit: int = 500,
    ) -> None:
        self._bus = bus
        self._alpha = max(0.01, min(1.0, alpha))
        self._exploration_rate = max(0.0, min(1.0, exploration_rate))
        self._history_limit = max(10, history_limit)
        self._lock = threading.RLock()

        # strategy_id → mutable dict mirroring LearningStrategy fields
        self._strategies: Dict[str, Dict[str, Any]] = {}

        # strategy_id → deque[StrategyOutcome]
        self._outcomes: Dict[str, Deque[StrategyOutcome]] = {}

        # domain → list[strategy_id]
        self._domain_index: Dict[str, List[str]] = {}

        # adaptation log
        self._adaptations: List[AdaptationEvent] = []

        # regime shifts log
        self._regime_shifts: List[RegimeShift] = []

        # domain → currently selected strategy_id
        self._active: Dict[str, str] = {}

        log.info(
            "MetaLearning initialised (alpha=%.2f, exploration_rate=%.2f, "
            "history_limit=%d)",
            self._alpha, self._exploration_rate, self._history_limit,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_id(name: str, domain: str) -> str:
        """Deterministic strategy id from name + domain."""
        raw = f"{name}::{domain}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _build_strategy(self, data: Dict[str, Any]) -> LearningStrategy:
        """Build an immutable LearningStrategy from the internal dict."""
        return LearningStrategy(
            strategy_id=data["strategy_id"],
            name=data["name"],
            parameters=dict(data["parameters"]),
            domain=data["domain"],
            created_at=data["created_at"],
            performance_score=data["performance_score"],
        )

    # ------------------------------------------------------------------
    # Strategy registry
    # ------------------------------------------------------------------

    def register_strategy(
        self,
        name: str,
        parameters: Dict[str, Any],
        domain: str,
    ) -> LearningStrategy:
        """Register a new learning strategy. Returns the created entry."""
        sid = self._make_id(name, domain)
        now = time.time()
        with self._lock:
            if sid in self._strategies:
                log.debug("[MetaLearning] Strategy %s already exists, returning", sid)
                return self._build_strategy(self._strategies[sid])
            data: Dict[str, Any] = {
                "strategy_id": sid,
                "name": name,
                "parameters": dict(parameters),
                "domain": domain,
                "created_at": now,
                "performance_score": 0.5,
            }
            self._strategies[sid] = data
            self._outcomes[sid] = deque(maxlen=self._history_limit)
            self._domain_index.setdefault(domain, []).append(sid)
        self._bus.publish("meta_learning.strategy_registered", {
            "strategy_id": sid, "name": name, "domain": domain,
        })
        log.debug("[MetaLearning] Registered strategy %s (%s) in %s", sid, name, domain)
        return self._build_strategy(data)

    def get_strategy(self, strategy_id: str) -> Optional[LearningStrategy]:
        """Return a strategy by id, or None."""
        with self._lock:
            data = self._strategies.get(strategy_id)
            if data is None:
                return None
            return self._build_strategy(data)

    def list_strategies(self, domain: Optional[str] = None) -> List[LearningStrategy]:
        """List strategies, optionally filtered by domain."""
        with self._lock:
            if domain is not None:
                sids = self._domain_index.get(domain, [])
                return [
                    self._build_strategy(self._strategies[s])
                    for s in sids if s in self._strategies
                ]
            return [self._build_strategy(d) for d in self._strategies.values()]

    # ------------------------------------------------------------------
    # Outcome recording
    # ------------------------------------------------------------------

    def record_outcome(
        self,
        strategy_id: str,
        success: bool,
        confidence: float = 1.0,
        latency_ms: float = 0.0,
        domain: Optional[str] = None,
    ) -> StrategyOutcome:
        """
        Record the outcome of applying a strategy.
        Updates the EMA-based performance score.
        """
        now = time.time()
        with self._lock:
            data = self._strategies.get(strategy_id)
            if data is None:
                raise KeyError(f"Unknown strategy_id: {strategy_id}")
            resolved_domain = domain or data["domain"]
            outcome = StrategyOutcome(
                strategy_id=strategy_id,
                domain=resolved_domain,
                success=success,
                confidence=max(0.0, min(1.0, confidence)),
                latency_ms=max(0.0, latency_ms),
                timestamp=now,
            )
            self._outcomes[strategy_id].append(outcome)
            # EMA update: score ← α·reward + (1-α)·score
            reward = confidence if success else 0.0
            old_score = data["performance_score"]
            data["performance_score"] = (
                self._alpha * reward + (1.0 - self._alpha) * old_score
            )
        self._bus.publish("meta_learning.outcome_recorded", {
            "strategy_id": strategy_id,
            "success": success,
            "confidence": confidence,
            "domain": resolved_domain,
        })
        log.debug(
            "[MetaLearning] Outcome for %s: success=%s conf=%.2f",
            strategy_id, success, confidence,
        )
        return outcome

    # ------------------------------------------------------------------
    # Strategy selection
    # ------------------------------------------------------------------

    def select_strategy(
        self,
        domain: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[LearningStrategy]:
        """
        Select the best strategy for a domain.

        With probability ``exploration_rate`` a random strategy is chosen
        instead of the highest-scoring one (epsilon-greedy).
        """
        with self._lock:
            sids = self._domain_index.get(domain, [])
            candidates = [
                self._strategies[s]
                for s in sids if s in self._strategies
            ]
            if not candidates:
                return None
            # Epsilon-greedy exploration
            if random.random() < self._exploration_rate and len(candidates) > 1:
                chosen = random.choice(candidates)
                self._bus.publish("meta_learning.exploration", {
                    "domain": domain,
                    "strategy_id": chosen["strategy_id"],
                })
            else:
                chosen = max(candidates, key=lambda d: d["performance_score"])
            self._active[domain] = chosen["strategy_id"]
            return self._build_strategy(chosen)

    # ------------------------------------------------------------------
    # Parameter adaptation
    # ------------------------------------------------------------------

    def adapt_parameters(
        self,
        strategy_id: str,
        feedback_success: bool,
    ) -> List[AdaptationEvent]:
        """
        Adjust numeric parameters of a strategy based on outcome feedback.

        On success the current values are nudged toward more aggressive
        settings (higher exploration, lower thresholds). On failure the
        opposite direction is applied. Uses the instance ``alpha`` as
        the adaptation magnitude.

        Returns the list of adaptation events produced.
        """
        events: List[AdaptationEvent] = []
        now = time.time()
        direction = 1.0 if feedback_success else -1.0
        reason = (
            AdaptationReason.FEEDBACK
            if feedback_success
            else AdaptationReason.PERFORMANCE_DECLINE
        )
        with self._lock:
            data = self._strategies.get(strategy_id)
            if data is None:
                raise KeyError(f"Unknown strategy_id: {strategy_id}")
            params = data["parameters"]
            new_params: Dict[str, Any] = {}
            for key, value in params.items():
                if not isinstance(value, (int, float)):
                    new_params[key] = value
                    continue
                old_val = float(value)
                # Nudge by alpha * direction, clamped to [0, 1] for
                # values already in that range, else unbounded nudge.
                delta = self._alpha * direction * 0.1
                if 0.0 <= old_val <= 1.0:
                    new_val = max(0.0, min(1.0, old_val + delta))
                else:
                    new_val = old_val + delta * abs(old_val if old_val != 0 else 1.0)
                new_params[key] = new_val
                if new_val != old_val:
                    evt = AdaptationEvent(
                        strategy_id=strategy_id,
                        parameter=key,
                        old_value=old_val,
                        new_value=new_val,
                        reason=reason,
                        timestamp=now,
                    )
                    events.append(evt)
                    self._adaptations.append(evt)
            data["parameters"] = new_params
        for evt in events:
            self._bus.publish("meta_learning.adaptation", {
                "strategy_id": strategy_id,
                "parameter": evt.parameter,
                "old_value": evt.old_value,
                "new_value": evt.new_value,
                "reason": evt.reason.value,
            })
        if events:
            log.debug(
                "[MetaLearning] Adapted %d params for %s (success=%s)",
                len(events), strategy_id, feedback_success,
            )
        return events

    # ------------------------------------------------------------------
    # Hyperparameter optimisation (bounded hill-climbing)
    # ------------------------------------------------------------------

    def optimize_parameter(
        self,
        strategy_id: str,
        param_name: str,
        min_val: float,
        max_val: float,
        step: float = 0.05,
    ) -> AdaptationEvent:
        """
        One hill-climbing step for a single numeric parameter.

        Looks at recent outcomes to decide direction:
        - if recent success rate > 0.5 → move toward ``max_val``
        - otherwise → move toward ``min_val``

        Returns the adaptation event.
        """
        now = time.time()
        with self._lock:
            data = self._strategies.get(strategy_id)
            if data is None:
                raise KeyError(f"Unknown strategy_id: {strategy_id}")
            params = data["parameters"]
            old_val = float(params.get(param_name, (min_val + max_val) / 2.0))

            # Recent success rate from last 20 outcomes
            recent = list(self._outcomes.get(strategy_id, []))[-20:]
            if recent:
                rate = sum(1 for o in recent if o.success) / len(recent)
            else:
                rate = 0.5

            direction = 1.0 if rate > 0.5 else -1.0
            new_val = max(min_val, min(max_val, old_val + step * direction))
            params[param_name] = new_val

            evt = AdaptationEvent(
                strategy_id=strategy_id,
                parameter=param_name,
                old_value=old_val,
                new_value=new_val,
                reason=AdaptationReason.FEEDBACK,
                timestamp=now,
            )
            self._adaptations.append(evt)
        self._bus.publish("meta_learning.adaptation", {
            "strategy_id": strategy_id,
            "parameter": param_name,
            "old_value": old_val,
            "new_value": new_val,
            "reason": AdaptationReason.FEEDBACK.value,
        })
        log.debug(
            "[MetaLearning] Optimised %s.%s: %.4f → %.4f (rate=%.2f)",
            strategy_id, param_name, old_val, new_val, rate,
        )
        return evt

    # ------------------------------------------------------------------
    # Regime detection
    # ------------------------------------------------------------------

    def detect_regime_shift(
        self,
        domain: str,
        window: int = 20,
    ) -> Optional[RegimeShift]:
        """
        Detect whether the active strategy for *domain* is under-performing
        relative to alternatives.

        Compares the active strategy's recent success rate against the best
        alternative.  If the alternative beats active by > 0.15, a regime
        shift is triggered and the active strategy is switched.

        Returns a ``RegimeShift`` if a switch occurred, else ``None``.
        """
        threshold = 0.15
        now = time.time()
        with self._lock:
            active_sid = self._active.get(domain)
            sids = self._domain_index.get(domain, [])
            if not active_sid or len(sids) < 2:
                return None

            def _recent_rate(sid: str) -> float:
                recent = list(self._outcomes.get(sid, []))[-window:]
                if not recent:
                    return 0.5
                return sum(1 for o in recent if o.success) / len(recent)

            active_rate = _recent_rate(active_sid)
            best_sid = active_sid
            best_rate = active_rate
            for sid in sids:
                if sid == active_sid:
                    continue
                r = _recent_rate(sid)
                if r > best_rate:
                    best_rate = r
                    best_sid = sid

            if best_sid == active_sid or (best_rate - active_rate) < threshold:
                return None

            # Switch
            self._active[domain] = best_sid
            shift = RegimeShift(
                domain=domain,
                old_strategy_id=active_sid,
                new_strategy_id=best_sid,
                trigger_reason=(
                    f"active_rate={active_rate:.2f} < "
                    f"alternative_rate={best_rate:.2f}"
                ),
                timestamp=now,
            )
            self._regime_shifts.append(shift)
        self._bus.publish("meta_learning.regime_shift", {
            "domain": domain,
            "old_strategy_id": active_sid,
            "new_strategy_id": best_sid,
            "active_rate": active_rate,
            "alternative_rate": best_rate,
        })
        log.info(
            "[MetaLearning] Regime shift in %s: %s → %s",
            domain, active_sid, best_sid,
        )
        return shift

    # ------------------------------------------------------------------
    # Snapshot / export
    # ------------------------------------------------------------------

    def export_state(self) -> Dict[str, Any]:
        """Export full engine state as a JSON-serialisable dict."""
        with self._lock:
            strategies = []
            for data in self._strategies.values():
                strategies.append({
                    "strategy_id": data["strategy_id"],
                    "name": data["name"],
                    "parameters": dict(data["parameters"]),
                    "domain": data["domain"],
                    "created_at": data["created_at"],
                    "performance_score": data["performance_score"],
                })
            outcomes = []
            for dq in self._outcomes.values():
                for o in dq:
                    outcomes.append(asdict(o))
            adaptations = [asdict(a) for a in self._adaptations]
            for a in adaptations:
                if isinstance(a.get("reason"), AdaptationReason):
                    a["reason"] = a["reason"].value
            regime_shifts = [asdict(r) for r in self._regime_shifts]
            return {
                "strategies": strategies,
                "outcomes": outcomes,
                "adaptations": adaptations,
                "regime_shifts": regime_shifts,
                "active": dict(self._active),
            }

    def import_state(self, data: Dict[str, Any]) -> int:
        """
        Import previously exported state.  Merges with current state.
        Returns the number of strategies loaded.
        """
        loaded = 0
        with self._lock:
            for s in data.get("strategies", []):
                sid = s["strategy_id"]
                self._strategies[sid] = {
                    "strategy_id": sid,
                    "name": s["name"],
                    "parameters": dict(s.get("parameters", {})),
                    "domain": s["domain"],
                    "created_at": s.get("created_at", time.time()),
                    "performance_score": s.get("performance_score", 0.5),
                }
                if sid not in self._outcomes:
                    self._outcomes[sid] = deque(maxlen=self._history_limit)
                self._domain_index.setdefault(s["domain"], [])
                if sid not in self._domain_index[s["domain"]]:
                    self._domain_index[s["domain"]].append(sid)
                loaded += 1
            for o in data.get("outcomes", []):
                sid = o.get("strategy_id", "")
                if sid in self._outcomes:
                    self._outcomes[sid].append(StrategyOutcome(
                        strategy_id=sid,
                        domain=o.get("domain", ""),
                        success=o.get("success", False),
                        confidence=o.get("confidence", 0.0),
                        latency_ms=o.get("latency_ms", 0.0),
                        timestamp=o.get("timestamp", 0.0),
                    ))
            for act in data.get("active", {}).items():
                self._active[act[0]] = act[1]
        log.info("[MetaLearning] Imported %d strategies", loaded)
        return loaded

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        """Return summary statistics for the meta-learning engine."""
        with self._lock:
            total_outcomes = sum(len(dq) for dq in self._outcomes.values())
            scores = [
                d["performance_score"] for d in self._strategies.values()
            ]
            return {
                "strategy_count": len(self._strategies),
                "domain_count": len(self._domain_index),
                "total_outcomes": total_outcomes,
                "total_adaptations": len(self._adaptations),
                "total_regime_shifts": len(self._regime_shifts),
                "avg_performance": (
                    statistics.mean(scores) if scores else 0.0
                ),
                "active_strategies": dict(self._active),
                "alpha": self._alpha,
                "exploration_rate": self._exploration_rate,
            }
