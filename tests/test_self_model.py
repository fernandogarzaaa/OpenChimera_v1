"""Tests for core.self_model — SelfModel reflective self-awareness engine."""
from __future__ import annotations

import time

import pytest

from core._bus_fallback import EventBus
from core.self_model import (
    CapabilitySnapshot,
    HealthStatus,
    PerformanceDelta,
    SelfModel,
    SubsystemHealth,
    TrendDirection,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def model(bus):
    return SelfModel(bus=bus, history_limit=50)


# ---------------------------------------------------------------------------
# Capability recording
# ---------------------------------------------------------------------------

class TestCapabilityRecording:
    def test_record_and_retrieve(self, model: SelfModel):
        model.record_capability("reasoning", "accuracy", 0.85)
        snap = model.get_capability("reasoning", "accuracy")
        assert snap is not None
        assert snap.domain == "reasoning"
        assert snap.metric == "accuracy"
        assert snap.value == 0.85

    def test_record_stores_raw_value(self, model: SelfModel):
        model.record_capability("domain", "metric", 2.5)
        snap = model.get_capability("domain", "metric")
        assert snap is not None
        assert snap.value == 2.5  # no clamping, stores raw float

        model.record_capability("domain", "metric2", -1.0)
        snap2 = model.get_capability("domain", "metric2")
        assert snap2 is not None
        assert snap2.value == -1.0

    def test_get_missing_capability_returns_none(self, model: SelfModel):
        assert model.get_capability("nonexistent", "nope") is None

    def test_history_accumulates(self, model: SelfModel):
        for i in range(5):
            model.record_capability("d", "m", 0.1 * i)
        history = model.get_capability_history("d", "m")
        assert len(history) == 5
        assert history[-1].value == pytest.approx(0.4)

    def test_history_bounded(self, model: SelfModel):
        for i in range(60):
            model.record_capability("d", "m", float(i) / 100)
        history = model.get_capability_history("d", "m")
        # history_limit=50
        assert len(history) == 50

    def test_list_capabilities(self, model: SelfModel):
        model.record_capability("reasoning", "speed", 0.7)
        model.record_capability("vision", "accuracy", 0.9)
        caps = model.list_capabilities()
        assert any(c.domain == "reasoning" and c.metric == "speed" for c in caps)
        assert any(c.domain == "vision" and c.metric == "accuracy" for c in caps)


# ---------------------------------------------------------------------------
# Performance deltas
# ---------------------------------------------------------------------------

class TestPerformanceDelta:
    def test_compute_delta_improving(self, model: SelfModel):
        # Record old values, then a new higher one
        for _ in range(3):
            model.record_capability("d", "m", 0.5)
        model.record_capability("d", "m", 0.9)

        delta = model.compute_delta("d", "m", window_seconds=3600)
        assert delta is not None
        assert delta.trend == TrendDirection.IMPROVING
        assert delta.delta > 0

    def test_compute_delta_declining(self, model: SelfModel):
        for _ in range(3):
            model.record_capability("d", "m", 0.9)
        model.record_capability("d", "m", 0.3)

        delta = model.compute_delta("d", "m", window_seconds=3600)
        assert delta is not None
        assert delta.trend == TrendDirection.DECLINING
        assert delta.delta < 0

    def test_compute_delta_stable(self, model: SelfModel):
        for _ in range(5):
            model.record_capability("d", "m", 0.5)

        delta = model.compute_delta("d", "m", window_seconds=3600)
        assert delta is not None
        assert delta.trend == TrendDirection.STABLE

    def test_compute_delta_missing_returns_none(self, model: SelfModel):
        assert model.compute_delta("x", "y") is None

    def test_compute_all_deltas(self, model: SelfModel):
        for _ in range(3):
            model.record_capability("d1", "m1", 0.5)
            model.record_capability("d2", "m2", 0.7)
        model.record_capability("d1", "m1", 0.9)
        model.record_capability("d2", "m2", 0.2)

        deltas = model.compute_all_deltas()
        assert len(deltas) == 2
        domains = {d.domain for d in deltas}
        assert domains == {"d1", "d2"}


# ---------------------------------------------------------------------------
# Health monitoring
# ---------------------------------------------------------------------------

class TestHealthMonitoring:
    def test_report_and_get_health(self, model: SelfModel):
        model.report_health("quantum_engine", HealthStatus.HEALTHY, latency_ms=12.5)
        health = model.get_health("quantum_engine")
        assert health is not None
        assert health.status == HealthStatus.HEALTHY
        assert health.latency_ms == 12.5

    def test_is_system_healthy(self, model: SelfModel):
        model.report_health("engine", HealthStatus.HEALTHY)
        assert model.is_system_healthy() is True

        model.report_health("broken", HealthStatus.FAILED)
        assert model.is_system_healthy() is False

    def test_list_health(self, model: SelfModel):
        model.report_health("a", HealthStatus.HEALTHY)
        model.report_health("b", HealthStatus.DEGRADED)
        all_h = model.list_health()
        assert len(all_h) == 2

    def test_transitions_recorded(self, model: SelfModel):
        model.report_health("x", HealthStatus.HEALTHY)
        model.report_health("x", HealthStatus.DEGRADED)
        model.report_health("x", HealthStatus.FAILED)
        transitions = model.get_transitions()
        # Two transitions: HEALTHY→DEGRADED, DEGRADED→FAILED
        assert len(transitions) >= 2

    def test_missing_health_returns_none(self, model: SelfModel):
        assert model.get_health("nope") is None


# ---------------------------------------------------------------------------
# Self assessment
# ---------------------------------------------------------------------------

class TestSelfAssessment:
    def test_self_assessment_structure(self, model: SelfModel):
        model.record_capability("reasoning", "accuracy", 0.85)
        model.record_capability("vision", "f1", 0.6)
        model.report_health("engine", HealthStatus.HEALTHY)

        assessment = model.self_assessment()
        assert "capabilities_tracked" in assessment
        assert "overall_fitness" in assessment
        assert "subsystems" in assessment
        assert assessment["capabilities_tracked"] == 2

    def test_assessment_fitness_range(self, model: SelfModel):
        model.record_capability("d", "m", 0.5)
        assessment = model.self_assessment()
        assert 0.0 <= assessment["overall_fitness"] <= 1.0


# ---------------------------------------------------------------------------
# Strengths and weaknesses
# ---------------------------------------------------------------------------

class TestStrengthsWeaknesses:
    def test_strengths(self, model: SelfModel):
        model.record_capability("math", "score", 0.95)
        model.record_capability("art", "score", 0.2)
        strong = model.strengths()
        # math should be a strength (≥0.7)
        domains = {s["domain"] for s in strong}
        assert "math" in domains

    def test_weaknesses(self, model: SelfModel):
        model.record_capability("math", "score", 0.95)
        model.record_capability("art", "score", 0.15)
        weak = model.weaknesses()
        domains = {w["domain"] for w in weak}
        assert "art" in domains

    def test_empty_strengths(self, model: SelfModel):
        assert model.strengths() == []


# ---------------------------------------------------------------------------
# Export and import
# ---------------------------------------------------------------------------

class TestExportImport:
    def test_round_trip(self, model: SelfModel, bus: EventBus):
        model.record_capability("domain", "m1", 0.8)
        model.record_capability("domain", "m2", 0.4)
        model.report_health("eng", HealthStatus.HEALTHY)

        exported = model.export_state()
        assert "capabilities" in exported
        assert "health" in exported

        model2 = SelfModel(bus=bus)
        model2.import_state(exported)

        snap = model2.get_capability("domain", "m1")
        assert snap is not None
        assert snap.value == 0.8

    def test_import_empty(self, bus: EventBus):
        model = SelfModel(bus=bus)
        model.import_state({})
        assert model.list_capabilities() == []


# ---------------------------------------------------------------------------
# EventBus integration
# ---------------------------------------------------------------------------

class TestEventBusIntegration:
    def test_capability_event_published(self, bus: EventBus, model: SelfModel):
        events = []
        bus.subscribe("self_model.capability_recorded", lambda e: events.append(e))
        model.record_capability("d", "m", 0.5)
        assert len(events) == 1
        assert events[0]["domain"] == "d"

    def test_health_event_published(self, bus: EventBus, model: SelfModel):
        events = []
        bus.subscribe("self_model.health_reported", lambda e: events.append(e))
        model.report_health("eng", HealthStatus.HEALTHY)
        assert len(events) == 1


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------

class TestThreadSafety:
    def test_concurrent_recording(self, model: SelfModel):
        import threading

        def record(domain_prefix, count):
            for i in range(count):
                model.record_capability(f"{domain_prefix}", "m", float(i) / count)

        threads = [
            threading.Thread(target=record, args=(f"d{i}", 20))
            for i in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        caps = model.list_capabilities()
        assert len(caps) == 5


# ---------------------------------------------------------------------------
# Frozen dataclass verifications
# ---------------------------------------------------------------------------

class TestFrozenDataclasses:
    def test_capability_snapshot_immutable(self):
        snap = CapabilitySnapshot(
            domain="d", metric="m", value=0.5,
            timestamp=time.time(), sample_count=1,
        )
        with pytest.raises(AttributeError):
            snap.value = 0.9  # type: ignore[misc]

    def test_subsystem_health_immutable(self):
        sh = SubsystemHealth(
            name="x", status=HealthStatus.HEALTHY,
            latency_ms=10.0, error_rate=0.0,
            last_check=time.time(),
        )
        with pytest.raises(AttributeError):
            sh.status = HealthStatus.FAILED  # type: ignore[misc]
