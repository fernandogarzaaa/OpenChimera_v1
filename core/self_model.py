"""OpenChimera Self-Model — reflective awareness of system state and capabilities.

Tracks performance deltas, capability evolution, subsystem health, and
state transitions over time. Enables the system to reason about its own
strengths, weaknesses, and learning trajectory.

Fully portable — all persistence is through MemorySystem (optional) and
EventBus. No hardcoded paths.

Architecture
────────────
CapabilitySnapshot     Immutable point-in-time capability measure.
PerformanceDelta       Computed change between two snapshots.
SubsystemHealth        Health/readiness of a single subsystem.
SelfModel              Main reflective engine.

The Self-Model is the prerequisite for recursive self-improvement:
without knowing *what* the system can do and *how well* it does it,
no principled improvement strategy is possible.
"""
from __future__ import annotations

import logging
import statistics
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from core._bus_fallback import EventBus

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class HealthStatus(str, Enum):
    """Subsystem operational status."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    UNKNOWN = "unknown"


class TrendDirection(str, Enum):
    """Direction of a performance metric over time."""
    IMPROVING = "improving"
    STABLE = "stable"
    DECLINING = "declining"


# ---------------------------------------------------------------------------
# Data transfer objects
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CapabilitySnapshot:
    """Point-in-time measurement of a capability dimension."""
    domain: str
    metric: str
    value: float
    timestamp: float
    sample_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PerformanceDelta:
    """Computed change between two capability snapshots."""
    domain: str
    metric: str
    old_value: float
    new_value: float
    delta: float
    percent_change: float
    trend: TrendDirection
    window_seconds: float


@dataclass(frozen=True)
class SubsystemHealth:
    """Health assessment for a single subsystem."""
    name: str
    status: HealthStatus
    latency_ms: float = 0.0
    error_rate: float = 0.0
    last_check: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Self-Model engine
# ---------------------------------------------------------------------------

class SelfModel:
    """
    Reflective self-model that tracks the system's own state, performance,
    capabilities, and evolution over time.

    Thread-safe. Publishes state change events to EventBus.
    Optionally persists snapshots to MemorySystem.

    Parameters
    ──────────
    bus             EventBus for publishing self-model events.
    memory          Optional MemorySystem for snapshot persistence.
    history_limit   Max snapshots retained per (domain, metric) key.
    health_ttl_s    Seconds before a health check is considered stale.
    """

    def __init__(
        self,
        bus: EventBus,
        memory: Optional[Any] = None,
        history_limit: int = 200,
        health_ttl_s: float = 300.0,
    ) -> None:
        self._bus = bus
        self._memory = memory
        self._history_limit = max(10, history_limit)
        self._health_ttl_s = health_ttl_s
        self._lock = threading.RLock()

        # (domain, metric) → list[CapabilitySnapshot] ordered by timestamp
        self._snapshots: Dict[tuple[str, str], List[CapabilitySnapshot]] = {}

        # subsystem_name → SubsystemHealth
        self._health: Dict[str, SubsystemHealth] = {}

        # State transition log: list of (timestamp, event_type, details)
        self._transitions: List[tuple[float, str, Dict[str, Any]]] = []

        log.info(
            "SelfModel initialised (history_limit=%d, health_ttl=%.0fs)",
            self._history_limit, self._health_ttl_s,
        )

    # ------------------------------------------------------------------
    # Capability tracking
    # ------------------------------------------------------------------

    def record_capability(
        self,
        domain: str,
        metric: str,
        value: float,
        sample_count: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CapabilitySnapshot:
        """Record a new capability measurement. Returns the snapshot created."""
        snap = CapabilitySnapshot(
            domain=domain,
            metric=metric,
            value=float(value),
            timestamp=time.time(),
            sample_count=sample_count,
            metadata=metadata or {},
        )
        with self._lock:
            key = (domain, metric)
            history = self._snapshots.setdefault(key, [])
            history.append(snap)
            # Trim oldest if over limit
            if len(history) > self._history_limit:
                self._snapshots[key] = history[-self._history_limit:]
            self._record_transition(
                "capability_recorded",
                {"domain": domain, "metric": metric, "value": value},
            )
        self._bus.publish("self_model.capability_recorded", {
            "domain": domain, "metric": metric, "value": value,
        })
        log.debug(
            "[SelfModel] Recorded %s/%s = %.4f", domain, metric, value,
        )
        return snap

    def get_capability(
        self, domain: str, metric: str,
    ) -> Optional[CapabilitySnapshot]:
        """Return the most recent snapshot for (domain, metric), or None."""
        with self._lock:
            history = self._snapshots.get((domain, metric))
            if not history:
                return None
            return history[-1]

    def get_capability_history(
        self, domain: str, metric: str, limit: int = 50,
    ) -> List[CapabilitySnapshot]:
        """Return up to `limit` most recent snapshots for a capability."""
        with self._lock:
            history = self._snapshots.get((domain, metric), [])
            return list(history[-limit:])

    def list_capabilities(self) -> List[CapabilitySnapshot]:
        """Return the latest snapshot for every tracked capability."""
        with self._lock:
            return [hist[-1] for hist in self._snapshots.values() if hist]

    # ------------------------------------------------------------------
    # Performance deltas
    # ------------------------------------------------------------------

    def compute_delta(
        self,
        domain: str,
        metric: str,
        window_seconds: float = 3600.0,
    ) -> Optional[PerformanceDelta]:
        """
        Compute performance change over a time window.

        Compares the latest value against the average of values older than
        `window_seconds` ago. Returns None if insufficient history.
        """
        with self._lock:
            history = self._snapshots.get((domain, metric), [])
            if len(history) < 2:
                return None

            now = time.time()
            cutoff = now - window_seconds
            old_values = [s.value for s in history if s.timestamp < cutoff]
            if not old_values:
                # Use the oldest available as baseline
                old_values = [history[0].value]

            old_avg = statistics.mean(old_values)
            new_value = history[-1].value
            delta = new_value - old_avg
            pct = (delta / abs(old_avg)) * 100.0 if old_avg != 0 else 0.0

            if abs(pct) < 2.0:
                trend = TrendDirection.STABLE
            elif delta > 0:
                trend = TrendDirection.IMPROVING
            else:
                trend = TrendDirection.DECLINING

            return PerformanceDelta(
                domain=domain,
                metric=metric,
                old_value=old_avg,
                new_value=new_value,
                delta=delta,
                percent_change=pct,
                trend=trend,
                window_seconds=window_seconds,
            )

    def compute_all_deltas(
        self, window_seconds: float = 3600.0,
    ) -> List[PerformanceDelta]:
        """Compute deltas for every tracked capability dimension."""
        with self._lock:
            keys = list(self._snapshots.keys())
        results = []
        for domain, metric in keys:
            d = self.compute_delta(domain, metric, window_seconds)
            if d is not None:
                results.append(d)
        return results

    # ------------------------------------------------------------------
    # Subsystem health
    # ------------------------------------------------------------------

    def report_health(
        self,
        name: str,
        status: HealthStatus,
        latency_ms: float = 0.0,
        error_rate: float = 0.0,
        details: Optional[Dict[str, Any]] = None,
    ) -> SubsystemHealth:
        """Report the current health of a named subsystem."""
        health = SubsystemHealth(
            name=name,
            status=status,
            latency_ms=latency_ms,
            error_rate=error_rate,
            last_check=time.time(),
            details=details or {},
        )
        with self._lock:
            prev = self._health.get(name)
            self._health[name] = health
            if prev is not None and prev.status != status:
                self._record_transition(
                    "health_changed",
                    {"subsystem": name, "old": prev.status.value,
                     "new": status.value},
                )
        self._bus.publish("self_model.health_reported", {
            "name": name, "status": status.value,
        })
        return health

    def get_health(self, name: str) -> Optional[SubsystemHealth]:
        """Return the latest health for a subsystem, or None."""
        with self._lock:
            return self._health.get(name)

    def list_health(self) -> List[SubsystemHealth]:
        """All subsystem health entries."""
        with self._lock:
            return list(self._health.values())

    def is_system_healthy(self) -> bool:
        """True if no subsystem is in FAILED state and none are stale."""
        now = time.time()
        with self._lock:
            for h in self._health.values():
                if h.status == HealthStatus.FAILED:
                    return False
                if (now - h.last_check) > self._health_ttl_s:
                    return False
        return True

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def _record_transition(
        self, event_type: str, details: Dict[str, Any],
    ) -> None:
        """Internal: append a state transition (caller holds _lock)."""
        self._transitions.append((time.time(), event_type, details))
        # Keep bounded
        if len(self._transitions) > 1000:
            self._transitions = self._transitions[-500:]

    def get_transitions(self, limit: int = 50) -> List[dict]:
        """Return recent state transitions as dicts."""
        with self._lock:
            entries = self._transitions[-limit:]
        return [
            {"timestamp": ts, "event": ev, "details": det}
            for ts, ev, det in entries
        ]

    # ------------------------------------------------------------------
    # Introspection & self-assessment
    # ------------------------------------------------------------------

    def self_assessment(self) -> Dict[str, Any]:
        """
        Produce a comprehensive self-assessment summarising:
        - capability count and domain coverage
        - improvement/decline trends
        - subsystem health summary
        - recent transitions
        """
        with self._lock:
            cap_count = len(self._snapshots)
            domains = {k[0] for k in self._snapshots.keys()}
            metrics = {k[1] for k in self._snapshots.keys()}

            healthy = sum(
                1 for h in self._health.values()
                if h.status == HealthStatus.HEALTHY
            )
            degraded = sum(
                1 for h in self._health.values()
                if h.status == HealthStatus.DEGRADED
            )
            failed = sum(
                1 for h in self._health.values()
                if h.status == HealthStatus.FAILED
            )
            total_subs = len(self._health)

        deltas = self.compute_all_deltas()
        improving = sum(1 for d in deltas if d.trend == TrendDirection.IMPROVING)
        declining = sum(1 for d in deltas if d.trend == TrendDirection.DECLINING)
        stable = sum(1 for d in deltas if d.trend == TrendDirection.STABLE)

        # Compute overall fitness as fraction of improving capabilities
        if deltas:
            overall_fitness = (improving + 0.5 * stable) / len(deltas)
        else:
            overall_fitness = 0.5  # neutral when no data

        return {
            "capabilities_tracked": cap_count,
            "domains": sorted(domains),
            "metrics": sorted(metrics),
            "trends": {
                "improving": improving,
                "stable": stable,
                "declining": declining,
            },
            "overall_fitness": round(overall_fitness, 4),
            "subsystems": {
                "total": total_subs,
                "healthy": healthy,
                "degraded": degraded,
                "failed": failed,
            },
            "system_healthy": self.is_system_healthy(),
            "recent_transitions": self.get_transitions(limit=10),
        }

    def strengths(self) -> List[Dict[str, Any]]:
        """Return capabilities that are improving or have high values."""
        with self._lock:
            result = []
            for (domain, metric), history in self._snapshots.items():
                if not history:
                    continue
                latest = history[-1]
                if latest.value >= 0.7:
                    result.append({
                        "domain": domain,
                        "metric": metric,
                        "value": latest.value,
                        "trend": "high_value",
                    })
        deltas = self.compute_all_deltas()
        for d in deltas:
            if d.trend == TrendDirection.IMPROVING and d.percent_change > 5.0:
                result.append({
                    "domain": d.domain,
                    "metric": d.metric,
                    "value": d.new_value,
                    "trend": "improving",
                    "percent_change": d.percent_change,
                })
        return result

    def weaknesses(self) -> List[Dict[str, Any]]:
        """Return capabilities that are declining or have low values."""
        with self._lock:
            result = []
            for (domain, metric), history in self._snapshots.items():
                if not history:
                    continue
                latest = history[-1]
                if latest.value < 0.3:
                    result.append({
                        "domain": domain,
                        "metric": metric,
                        "value": latest.value,
                        "trend": "low_value",
                    })
        deltas = self.compute_all_deltas()
        for d in deltas:
            if d.trend == TrendDirection.DECLINING and d.percent_change < -5.0:
                result.append({
                    "domain": d.domain,
                    "metric": d.metric,
                    "value": d.new_value,
                    "trend": "declining",
                    "percent_change": d.percent_change,
                })
        return result

    # ------------------------------------------------------------------
    # Snapshot export / import (for persistence or sharing)
    # ------------------------------------------------------------------

    def export_state(self) -> Dict[str, Any]:
        """Export the entire self-model state as a serialisable dict."""
        with self._lock:
            caps = {}
            for (domain, metric), history in self._snapshots.items():
                key = f"{domain}::{metric}"
                caps[key] = [
                    {"value": s.value, "timestamp": s.timestamp,
                     "sample_count": s.sample_count}
                    for s in history
                ]
            health = {
                name: {
                    "status": h.status.value,
                    "latency_ms": h.latency_ms,
                    "error_rate": h.error_rate,
                    "last_check": h.last_check,
                }
                for name, h in self._health.items()
            }
            return {
                "capabilities": caps,
                "health": health,
                "transitions": [
                    {"timestamp": ts, "event": ev, "details": det}
                    for ts, ev, det in self._transitions[-100:]
                ],
            }

    def import_state(self, state: Dict[str, Any]) -> None:
        """Restore from an export_state() dict."""
        with self._lock:
            for key, entries in state.get("capabilities", {}).items():
                if "::" not in key:
                    continue
                domain, metric = key.split("::", 1)
                snaps = [
                    CapabilitySnapshot(
                        domain=domain,
                        metric=metric,
                        value=e["value"],
                        timestamp=e["timestamp"],
                        sample_count=e.get("sample_count", 0),
                    )
                    for e in entries
                ]
                self._snapshots[(domain, metric)] = snaps

            for name, h in state.get("health", {}).items():
                self._health[name] = SubsystemHealth(
                    name=name,
                    status=HealthStatus(h.get("status", "unknown")),
                    latency_ms=h.get("latency_ms", 0.0),
                    error_rate=h.get("error_rate", 0.0),
                    last_check=h.get("last_check", 0.0),
                )
