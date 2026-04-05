"""Tests for core.ethical_reasoning — EthicalReasoning engine."""
from __future__ import annotations

import unittest

from core._bus_fallback import EventBus
from core.ethical_reasoning import (
    EthicalConstraint,
    EthicalReasoning,
    EvalOutcome,
    EvaluationResult,
    PolicyViolation,
    Severity,
    VetoRecord,
)


def _bus() -> EventBus:
    return EventBus(history_size=128)


class TestEthicalReasoningInit(unittest.TestCase):
    """Construction and defaults."""

    def test_default_construction(self) -> None:
        er = EthicalReasoning(bus=_bus())
        st = er.status()
        # Defaults register 4 built-in constraints
        self.assertEqual(st["constraint_count"], 4)
        self.assertEqual(st["enabled_count"], 4)
        self.assertEqual(st["total_evaluated"], 0)

    def test_no_defaults(self) -> None:
        er = EthicalReasoning(bus=_bus(), enable_defaults=False)
        self.assertEqual(er.status()["constraint_count"], 0)


class TestConstraintRegistry(unittest.TestCase):
    """Register, get, list, enable/disable constraints."""

    def setUp(self) -> None:
        self.er = EthicalReasoning(bus=_bus(), enable_defaults=False)

    def test_register_and_get(self) -> None:
        c = self.er.register_constraint("no_harm", "Block harm", Severity.CRITICAL)
        self.assertIsInstance(c, EthicalConstraint)
        self.assertEqual(c.name, "no_harm")
        fetched = self.er.get_constraint(c.constraint_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.constraint_id, c.constraint_id)

    def test_duplicate_returns_existing(self) -> None:
        c1 = self.er.register_constraint("a", "desc", Severity.LOW)
        c2 = self.er.register_constraint("a", "desc", Severity.LOW)
        self.assertEqual(c1.constraint_id, c2.constraint_id)

    def test_list_all(self) -> None:
        self.er.register_constraint("a", "d", Severity.LOW)
        self.er.register_constraint("b", "d", Severity.HIGH)
        self.assertEqual(len(self.er.list_constraints()), 2)

    def test_list_by_domain(self) -> None:
        self.er.register_constraint("a", "d", Severity.LOW, domain="medical")
        self.er.register_constraint("b", "d", Severity.LOW, domain="finance")
        self.assertEqual(len(self.er.list_constraints(domain="medical")), 1)

    def test_disable_enable(self) -> None:
        c = self.er.register_constraint("a", "d", Severity.LOW)
        self.assertTrue(self.er.disable_constraint(c.constraint_id))
        self.assertFalse(self.er.get_constraint(c.constraint_id).enabled)
        self.assertTrue(self.er.enable_constraint(c.constraint_id))
        self.assertTrue(self.er.get_constraint(c.constraint_id).enabled)

    def test_disable_nonexistent(self) -> None:
        self.assertFalse(self.er.disable_constraint("nope"))

    def test_get_missing(self) -> None:
        self.assertIsNone(self.er.get_constraint("nope"))


class TestActionEvaluation(unittest.TestCase):
    """Evaluate actions against constraints."""

    def setUp(self) -> None:
        self.er = EthicalReasoning(bus=_bus())  # with defaults

    def test_safe_action_approved(self) -> None:
        result = self.er.evaluate("compute average score")
        self.assertIsInstance(result, EvaluationResult)
        self.assertEqual(result.outcome, EvalOutcome.APPROVED)
        self.assertAlmostEqual(result.score, 1.0)
        self.assertEqual(len(result.violations), 0)

    def test_harmful_action_vetoed(self) -> None:
        result = self.er.evaluate("delete all user data")
        self.assertEqual(result.outcome, EvalOutcome.VETOED)
        self.assertGreater(len(result.violations), 0)
        self.assertLess(result.score, 1.0)

    def test_privacy_violation_vetoed(self) -> None:
        result = self.er.evaluate("expose pii to third party")
        self.assertEqual(result.outcome, EvalOutcome.VETOED)
        self.assertGreater(len(result.violations), 0)

    def test_resource_abuse_vetoed(self) -> None:
        result = self.er.evaluate("start fork bomb in production")
        self.assertEqual(result.outcome, EvalOutcome.VETOED)

    def test_scope_warning(self) -> None:
        ctx = {"allowed_domains": ["math"], "action_domain": "weapons"}
        result = self.er.evaluate("research topic", context=ctx)
        # Scope violation is MEDIUM → warning
        self.assertIn(result.outcome, (EvalOutcome.WARNING, EvalOutcome.APPROVED))

    def test_disabled_constraint_skipped(self) -> None:
        constraints = self.er.list_constraints()
        for c in constraints:
            self.er.disable_constraint(c.constraint_id)
        result = self.er.evaluate("delete all user data")
        # All disabled → no violations found
        self.assertEqual(result.outcome, EvalOutcome.APPROVED)

    def test_counters_increment(self) -> None:
        self.er.evaluate("safe action")
        self.er.evaluate("delete all records")
        st = self.er.status()
        self.assertEqual(st["total_evaluated"], 2)
        self.assertGreaterEqual(st["total_approved"] + st["total_vetoed"], 2)


class TestVetoAndOverride(unittest.TestCase):
    """Veto enforcement and override mechanism."""

    def setUp(self) -> None:
        self.er = EthicalReasoning(bus=_bus())

    def test_critical_cannot_be_overridden(self) -> None:
        result = self.er.override("delete all data", reason="emergency")
        # "delete all" triggers CRITICAL → override denied
        self.assertEqual(result.outcome, EvalOutcome.VETOED)

    def test_high_can_be_overridden(self) -> None:
        # Privacy is HIGH severity
        er = EthicalReasoning(bus=_bus(), enable_defaults=False)
        er.register_constraint(
            "test_high", "test", Severity.HIGH,
            checker=lambda a, c: "violation" if "test_trigger" in a else None,
        )
        result = er.override("test_trigger action", reason="approved by admin")
        self.assertEqual(result.outcome, EvalOutcome.OVERRIDDEN)

    def test_safe_override_passes_through(self) -> None:
        result = self.er.override("compute stats", reason="test")
        self.assertEqual(result.outcome, EvalOutcome.APPROVED)


class TestCustomConstraints(unittest.TestCase):
    """User-defined constraints with custom checkers."""

    def test_custom_checker(self) -> None:
        er = EthicalReasoning(bus=_bus(), enable_defaults=False)
        er.register_constraint(
            "no_sql", "Prevent raw SQL", Severity.HIGH,
            checker=lambda a, c: "SQL detected" if "SELECT" in a.upper() else None,
        )
        result = er.evaluate("SELECT * FROM users")
        self.assertEqual(result.outcome, EvalOutcome.VETOED)
        self.assertEqual(len(result.violations), 1)
        self.assertIn("SQL detected", result.violations[0].reason)

    def test_domain_scoped_constraint(self) -> None:
        er = EthicalReasoning(bus=_bus(), enable_defaults=False)
        er.register_constraint(
            "medical_only", "Medical domain rule", Severity.MEDIUM,
            domain="medical",
            checker=lambda a, c: "medical flag" if True else None,
        )
        # Evaluate in medical domain → triggers
        res_med = er.evaluate("action", domain="medical")
        self.assertEqual(len(res_med.warnings), 1)
        # Evaluate in another domain → doesn't trigger
        res_other = er.evaluate("action", domain="finance")
        self.assertEqual(len(res_other.warnings), 0)


class TestAuditTrail(unittest.TestCase):
    """Audit trail and veto log."""

    def setUp(self) -> None:
        self.er = EthicalReasoning(bus=_bus())

    def test_audit_trail_populated(self) -> None:
        self.er.evaluate("safe action")
        self.er.evaluate("delete all data")
        trail = self.er.get_audit_trail()
        self.assertEqual(len(trail), 2)
        self.assertIn("outcome", trail[0])

    def test_veto_log_populated(self) -> None:
        self.er.evaluate("delete all data")
        vetoes = self.er.get_veto_log()
        self.assertGreaterEqual(len(vetoes), 1)
        self.assertEqual(vetoes[0]["outcome"], "vetoed")

    def test_audit_limit(self) -> None:
        er = EthicalReasoning(bus=_bus(), audit_limit=10)
        for i in range(20):
            er.evaluate(f"action {i}")
        trail = er.get_audit_trail(limit=100)
        self.assertLessEqual(len(trail), 10)


class TestExportImport(unittest.TestCase):
    """State export/import round-trip."""

    def test_round_trip(self) -> None:
        er1 = EthicalReasoning(bus=_bus(), enable_defaults=False)
        er1.register_constraint("rule_a", "desc", Severity.HIGH)
        er1.register_constraint("rule_b", "desc", Severity.LOW)
        state = er1.export_state()
        er2 = EthicalReasoning(bus=_bus(), enable_defaults=False)
        loaded = er2.import_state(state)
        self.assertEqual(loaded, 2)
        self.assertEqual(er2.status()["constraint_count"], 2)

    def test_import_empty(self) -> None:
        er = EthicalReasoning(bus=_bus(), enable_defaults=False)
        self.assertEqual(er.import_state({}), 0)


class TestEventPublishing(unittest.TestCase):
    """Verify events are published on the bus."""

    def test_constraint_registered_event(self) -> None:
        bus = _bus()
        events = []
        bus.subscribe("ethical.constraint_registered", lambda d: events.append(d))
        er = EthicalReasoning(bus=bus, enable_defaults=False)
        er.register_constraint("x", "d", Severity.LOW)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["name"], "x")

    def test_evaluation_event(self) -> None:
        bus = _bus()
        events = []
        bus.subscribe("ethical.evaluation", lambda d: events.append(d))
        er = EthicalReasoning(bus=bus, enable_defaults=False)
        er.evaluate("harmless action")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["outcome"], "approved")

    def test_veto_event(self) -> None:
        bus = _bus()
        events = []
        bus.subscribe("ethical.veto", lambda d: events.append(d))
        er = EthicalReasoning(bus=bus)  # with defaults
        er.evaluate("delete all records")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["outcome"], "vetoed")


class TestDTOs(unittest.TestCase):
    """DTO immutability and correctness."""

    def test_constraint_frozen(self) -> None:
        er = EthicalReasoning(bus=_bus(), enable_defaults=False)
        c = er.register_constraint("x", "d", Severity.LOW)
        with self.assertRaises(AttributeError):
            c.name = "changed"

    def test_evaluation_result_frozen(self) -> None:
        er = EthicalReasoning(bus=_bus())
        r = er.evaluate("safe")
        with self.assertRaises(AttributeError):
            r.score = 0.0

    def test_policy_violation_dto(self) -> None:
        pv = PolicyViolation(
            constraint_id="c1", constraint_name="rule",
            severity=Severity.HIGH, reason="test", confidence=0.9,
        )
        self.assertEqual(pv.severity, Severity.HIGH)
        with self.assertRaises(AttributeError):
            pv.reason = "changed"


class TestStatus(unittest.TestCase):
    """Status method returns expected keys."""

    def test_status_keys(self) -> None:
        er = EthicalReasoning(bus=_bus())
        st = er.status()
        expected = {
            "constraint_count", "enabled_count", "total_evaluated",
            "total_vetoed", "total_approved", "total_warnings",
            "audit_size", "veto_log_size",
        }
        self.assertTrue(expected.issubset(st.keys()))


if __name__ == "__main__":
    unittest.main()
