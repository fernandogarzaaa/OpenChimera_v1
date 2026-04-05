"""Tests for core.meta_learning — MetaLearning engine."""
from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock

from core._bus_fallback import EventBus
from core.meta_learning import (
    AdaptationEvent,
    AdaptationReason,
    LearningStrategy,
    MetaLearning,
    RegimeShift,
    StrategyOutcome,
)


def _bus() -> EventBus:
    return EventBus(history_size=128)


class TestMetaLearningInit(unittest.TestCase):
    """Construction and defaults."""

    def test_default_construction(self) -> None:
        ml = MetaLearning(bus=_bus())
        st = ml.status()
        self.assertEqual(st["strategy_count"], 0)
        self.assertEqual(st["total_outcomes"], 0)
        self.assertAlmostEqual(st["alpha"], 0.2)

    def test_custom_params_clamped(self) -> None:
        ml = MetaLearning(bus=_bus(), alpha=5.0, exploration_rate=-1.0)
        st = ml.status()
        self.assertEqual(st["alpha"], 1.0)
        self.assertEqual(st["exploration_rate"], 0.0)


class TestStrategyRegistry(unittest.TestCase):
    """Register, get, list strategies."""

    def setUp(self) -> None:
        self.ml = MetaLearning(bus=_bus())

    def test_register_and_get(self) -> None:
        s = self.ml.register_strategy("greedy", {"threshold": 0.5}, "math")
        self.assertIsInstance(s, LearningStrategy)
        self.assertEqual(s.name, "greedy")
        self.assertEqual(s.domain, "math")
        fetched = self.ml.get_strategy(s.strategy_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.strategy_id, s.strategy_id)

    def test_duplicate_returns_existing(self) -> None:
        s1 = self.ml.register_strategy("a", {}, "d")
        s2 = self.ml.register_strategy("a", {}, "d")
        self.assertEqual(s1.strategy_id, s2.strategy_id)

    def test_list_all(self) -> None:
        self.ml.register_strategy("a", {}, "x")
        self.ml.register_strategy("b", {}, "y")
        self.assertEqual(len(self.ml.list_strategies()), 2)

    def test_list_by_domain(self) -> None:
        self.ml.register_strategy("a", {}, "x")
        self.ml.register_strategy("b", {}, "y")
        self.assertEqual(len(self.ml.list_strategies(domain="x")), 1)

    def test_get_missing(self) -> None:
        self.assertIsNone(self.ml.get_strategy("nope"))


class TestOutcomeRecording(unittest.TestCase):
    """Record outcomes and EMA update."""

    def setUp(self) -> None:
        self.ml = MetaLearning(bus=_bus(), alpha=0.5)
        self.s = self.ml.register_strategy("test", {"lr": 0.1}, "d")

    def test_record_success_increases_score(self) -> None:
        initial = self.ml.get_strategy(self.s.strategy_id).performance_score
        self.ml.record_outcome(self.s.strategy_id, True, confidence=0.9)
        updated = self.ml.get_strategy(self.s.strategy_id).performance_score
        self.assertGreater(updated, initial)

    def test_record_failure_decreases_score(self) -> None:
        # First bump it up
        for _ in range(5):
            self.ml.record_outcome(self.s.strategy_id, True, confidence=0.9)
        before = self.ml.get_strategy(self.s.strategy_id).performance_score
        self.ml.record_outcome(self.s.strategy_id, False, confidence=0.1)
        after = self.ml.get_strategy(self.s.strategy_id).performance_score
        self.assertLess(after, before)

    def test_record_invalid_strategy(self) -> None:
        with self.assertRaises(KeyError):
            self.ml.record_outcome("bad_id", True)

    def test_outcome_counted(self) -> None:
        self.ml.record_outcome(self.s.strategy_id, True)
        self.assertEqual(self.ml.status()["total_outcomes"], 1)

    def test_outcome_returns_dto(self) -> None:
        o = self.ml.record_outcome(self.s.strategy_id, True, confidence=0.8)
        self.assertIsInstance(o, StrategyOutcome)
        self.assertTrue(o.success)
        self.assertAlmostEqual(o.confidence, 0.8)


class TestStrategySelection(unittest.TestCase):
    """Select best strategy with epsilon-greedy."""

    def setUp(self) -> None:
        self.ml = MetaLearning(bus=_bus(), exploration_rate=0.0)
        self.s1 = self.ml.register_strategy("good", {}, "d")
        self.s2 = self.ml.register_strategy("bad", {}, "d")
        # Make s1 much better
        for _ in range(10):
            self.ml.record_outcome(self.s1.strategy_id, True, confidence=0.9)
            self.ml.record_outcome(self.s2.strategy_id, False, confidence=0.1)

    def test_selects_best(self) -> None:
        chosen = self.ml.select_strategy("d")
        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.strategy_id, self.s1.strategy_id)

    def test_empty_domain_returns_none(self) -> None:
        self.assertIsNone(self.ml.select_strategy("nonexistent"))


class TestAdaptation(unittest.TestCase):
    """Parameter adaptation on feedback."""

    def setUp(self) -> None:
        self.ml = MetaLearning(bus=_bus(), alpha=0.5)
        self.s = self.ml.register_strategy("adapt", {"rate": 0.5, "tag": "text"}, "d")

    def test_adapt_on_success(self) -> None:
        events = self.ml.adapt_parameters(self.s.strategy_id, True)
        # Only numeric params adapted; "tag" is text
        numeric_events = [e for e in events if e.parameter == "rate"]
        self.assertEqual(len(numeric_events), 1)
        self.assertGreater(numeric_events[0].new_value, numeric_events[0].old_value)

    def test_adapt_on_failure(self) -> None:
        events = self.ml.adapt_parameters(self.s.strategy_id, False)
        numeric_events = [e for e in events if e.parameter == "rate"]
        self.assertEqual(len(numeric_events), 1)
        self.assertLess(numeric_events[0].new_value, numeric_events[0].old_value)

    def test_adapt_invalid_strategy(self) -> None:
        with self.assertRaises(KeyError):
            self.ml.adapt_parameters("nope", True)

    def test_adaptation_event_dto(self) -> None:
        events = self.ml.adapt_parameters(self.s.strategy_id, True)
        for e in events:
            self.assertIsInstance(e, AdaptationEvent)
            self.assertIsInstance(e.reason, AdaptationReason)


class TestHyperparameterOptimization(unittest.TestCase):
    """Hill-climbing parameter optimization."""

    def setUp(self) -> None:
        self.ml = MetaLearning(bus=_bus())
        self.s = self.ml.register_strategy("opt", {"lr": 0.5}, "d")

    def test_optimize_upward_on_success(self) -> None:
        for _ in range(5):
            self.ml.record_outcome(self.s.strategy_id, True)
        evt = self.ml.optimize_parameter(self.s.strategy_id, "lr", 0.0, 1.0, 0.1)
        self.assertGreater(evt.new_value, evt.old_value)

    def test_optimize_downward_on_failure(self) -> None:
        for _ in range(5):
            self.ml.record_outcome(self.s.strategy_id, False)
        evt = self.ml.optimize_parameter(self.s.strategy_id, "lr", 0.0, 1.0, 0.1)
        self.assertLess(evt.new_value, evt.old_value)

    def test_optimize_respects_bounds(self) -> None:
        for _ in range(20):
            self.ml.record_outcome(self.s.strategy_id, True)
            self.ml.optimize_parameter(self.s.strategy_id, "lr", 0.0, 1.0, 0.1)
        s = self.ml.get_strategy(self.s.strategy_id)
        self.assertLessEqual(s.parameters["lr"], 1.0)

    def test_optimize_invalid_strategy(self) -> None:
        with self.assertRaises(KeyError):
            self.ml.optimize_parameter("nope", "x", 0.0, 1.0)


class TestRegimeDetection(unittest.TestCase):
    """Regime shift detection."""

    def setUp(self) -> None:
        self.ml = MetaLearning(bus=_bus(), exploration_rate=0.0)
        self.good = self.ml.register_strategy("good", {}, "d")
        self.bad = self.ml.register_strategy("bad", {}, "d")

    def test_no_shift_when_active_is_best(self) -> None:
        self.ml.select_strategy("d")  # set active
        for _ in range(10):
            self.ml.record_outcome(self.good.strategy_id, True)
            self.ml.record_outcome(self.bad.strategy_id, False)
        shift = self.ml.detect_regime_shift("d")
        self.assertIsNone(shift)

    def test_shift_detected(self) -> None:
        # Start with "bad" as active
        self.ml.select_strategy("d")
        # Force bad to be active
        self.ml._active["d"] = self.bad.strategy_id
        # Make bad fail and good succeed
        for _ in range(25):
            self.ml.record_outcome(self.bad.strategy_id, False)
            self.ml.record_outcome(self.good.strategy_id, True)
        shift = self.ml.detect_regime_shift("d")
        self.assertIsNotNone(shift)
        self.assertIsInstance(shift, RegimeShift)
        self.assertEqual(shift.new_strategy_id, self.good.strategy_id)

    def test_no_shift_single_strategy(self) -> None:
        ml = MetaLearning(bus=_bus())
        ml.register_strategy("only", {}, "x")
        ml.select_strategy("x")
        self.assertIsNone(ml.detect_regime_shift("x"))


class TestExportImport(unittest.TestCase):
    """State serialisation round-trip."""

    def test_round_trip(self) -> None:
        ml1 = MetaLearning(bus=_bus())
        ml1.register_strategy("a", {"x": 1}, "d1")
        ml1.register_strategy("b", {"y": 2}, "d2")
        ml1.record_outcome(
            ml1.list_strategies(domain="d1")[0].strategy_id, True
        )
        state = ml1.export_state()
        ml2 = MetaLearning(bus=_bus())
        loaded = ml2.import_state(state)
        self.assertEqual(loaded, 2)
        self.assertEqual(ml2.status()["strategy_count"], 2)

    def test_import_empty(self) -> None:
        ml = MetaLearning(bus=_bus())
        self.assertEqual(ml.import_state({}), 0)


class TestEventPublishing(unittest.TestCase):
    """Verify events are published on the bus."""

    def test_strategy_registered_event(self) -> None:
        bus = _bus()
        events = []
        bus.subscribe("meta_learning.strategy_registered", lambda d: events.append(d))
        ml = MetaLearning(bus=bus)
        ml.register_strategy("x", {}, "d")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["name"], "x")

    def test_outcome_recorded_event(self) -> None:
        bus = _bus()
        events = []
        bus.subscribe("meta_learning.outcome_recorded", lambda d: events.append(d))
        ml = MetaLearning(bus=bus)
        s = ml.register_strategy("x", {}, "d")
        ml.record_outcome(s.strategy_id, True)
        self.assertEqual(len(events), 1)

    def test_adaptation_event(self) -> None:
        bus = _bus()
        events = []
        bus.subscribe("meta_learning.adaptation", lambda d: events.append(d))
        ml = MetaLearning(bus=bus, alpha=0.5)
        s = ml.register_strategy("x", {"val": 0.5}, "d")
        ml.adapt_parameters(s.strategy_id, True)
        self.assertGreaterEqual(len(events), 1)


class TestStatus(unittest.TestCase):
    """Status method returns expected keys."""

    def test_status_keys(self) -> None:
        ml = MetaLearning(bus=_bus())
        st = ml.status()
        expected = {
            "strategy_count", "domain_count", "total_outcomes",
            "total_adaptations", "total_regime_shifts",
            "avg_performance", "active_strategies",
            "alpha", "exploration_rate",
        }
        self.assertTrue(expected.issubset(st.keys()))


if __name__ == "__main__":
    unittest.main()
