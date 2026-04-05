"""OpenChimera Ethical Reasoning — constraint evaluator and safety guardrails.

Evaluates proposed actions against configurable ethical constraints, safety
rules, and domain-specific policies.  Provides a veto mechanism that can
block unsafe actions before they reach execution, plus an audit trail of
every evaluation decision.

Fully portable — purely in-memory with EventBus notifications.
No hardcoded paths, no external dependencies beyond the core bus.

Architecture
────────────
EthicalConstraint     Immutable rule with severity, scope, and evaluation fn.
EvaluationResult      Outcome of testing an action against all active constraints.
VetoRecord            Audit entry when an action is blocked.
PolicyViolation       Individual constraint violation found during evaluation.
EthicalReasoning      Main engine combining constraint management, evaluation,
                      veto enforcement, and audit trail.

Key capabilities:
1. Constraint registry — named rules with severity and domain scope
2. Action evaluation — test proposed actions against all applicable rules
3. Veto enforcement — block actions that violate CRITICAL constraints
4. Audit trail — full history of evaluations, vetoes, and overrides
5. Policy profiles — predefined constraint sets for common domains
6. Confidence-weighted scoring — softer violations may pass with warnings
7. Override mechanism — authorised override with reason tracking
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Callable, Deque, Dict, List, Optional

from core._bus_fallback import EventBus

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class Severity(str, Enum):
    """How serious a constraint violation is."""
    CRITICAL = "critical"    # Must veto — no override allowed
    HIGH = "high"            # Should veto — override with reason
    MEDIUM = "medium"        # Warning — log but allow
    LOW = "low"              # Advisory — informational only


class EvalOutcome(str, Enum):
    """Outcome of an ethical evaluation."""
    APPROVED = "approved"
    VETOED = "vetoed"
    WARNING = "warning"
    OVERRIDDEN = "overridden"


# ---------------------------------------------------------------------------
# Data objects
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EthicalConstraint:
    """A named ethical rule with severity and optional domain scope."""
    constraint_id: str
    name: str
    description: str
    severity: Severity
    domain: Optional[str]    # None means applies globally
    created_at: float
    enabled: bool = True


@dataclass(frozen=True)
class PolicyViolation:
    """A single constraint violation found during evaluation."""
    constraint_id: str
    constraint_name: str
    severity: Severity
    reason: str
    confidence: float        # 0-1 how confident violation is real


@dataclass(frozen=True)
class EvaluationResult:
    """Outcome of evaluating an action against all active constraints."""
    action: str
    domain: str
    outcome: EvalOutcome
    violations: tuple         # tuple[PolicyViolation, ...]
    warnings: tuple           # tuple[PolicyViolation, ...]
    score: float              # 0-1 : 1.0 = fully compliant
    timestamp: float
    evaluation_ms: float


@dataclass(frozen=True)
class VetoRecord:
    """Audit entry for a vetoed or overridden action."""
    action: str
    domain: str
    outcome: EvalOutcome
    violations: tuple
    override_reason: Optional[str]
    timestamp: float


# ---------------------------------------------------------------------------
# Built-in constraint checkers
# ---------------------------------------------------------------------------

def _check_harmful_content(action: str, context: Dict[str, Any]) -> Optional[str]:
    """Flag actions containing known-harmful intent markers."""
    markers = [
        "delete all", "drop table", "rm -rf", "format disk",
        "disable security", "bypass auth", "leak credentials",
        "exfiltrate", "inject payload",
    ]
    action_lower = action.lower()
    for marker in markers:
        if marker in action_lower:
            return f"Action contains harmful marker: '{marker}'"
    return None


def _check_privacy_violation(action: str, context: Dict[str, Any]) -> Optional[str]:
    """Flag actions that may violate privacy constraints."""
    markers = [
        "expose pii", "share personal", "log password",
        "store credentials in plain", "broadcast user data",
    ]
    action_lower = action.lower()
    for marker in markers:
        if marker in action_lower:
            return f"Potential privacy violation: '{marker}'"
    return None


def _check_resource_abuse(action: str, context: Dict[str, Any]) -> Optional[str]:
    """Flag actions that may consume excessive resources."""
    markers = [
        "infinite loop", "unbounded allocation", "fork bomb",
        "mine crypto", "denial of service",
    ]
    action_lower = action.lower()
    for marker in markers:
        if marker in action_lower:
            return f"Resource abuse detected: '{marker}'"
    return None


def _check_scope_violation(action: str, context: Dict[str, Any]) -> Optional[str]:
    """Flag actions outside permitted scope."""
    allowed_domains = context.get("allowed_domains", [])
    action_domain = context.get("action_domain", "")
    if allowed_domains and action_domain and action_domain not in allowed_domains:
        return f"Action domain '{action_domain}' not in allowed set"
    return None


# ---------------------------------------------------------------------------
# Ethical Reasoning engine
# ---------------------------------------------------------------------------

_DEFAULT_CHECKERS: List[tuple] = [
    ("harmful_content", "Block actions with harmful intent markers", Severity.CRITICAL, _check_harmful_content),
    ("privacy_violation", "Block actions violating privacy", Severity.HIGH, _check_privacy_violation),
    ("resource_abuse", "Block resource-abusive actions", Severity.CRITICAL, _check_resource_abuse),
    ("scope_violation", "Warn on out-of-scope actions", Severity.MEDIUM, _check_scope_violation),
]


class EthicalReasoning:
    """
    Constraint evaluator and safety guardrail engine.

    Manages a set of ethical constraints, evaluates proposed actions
    against them, applies veto logic for critical violations, and
    maintains a full audit trail.

    Thread-safe.  Publishes events to EventBus.

    Parameters
    ──────────
    bus                 EventBus for publishing events.
    enable_defaults     Whether to register the built-in safety checkers.
    audit_limit         Maximum audit records retained.
    """

    def __init__(
        self,
        bus: EventBus,
        enable_defaults: bool = True,
        audit_limit: int = 1000,
    ) -> None:
        self._bus = bus
        self._lock = threading.RLock()
        self._audit_limit = max(10, audit_limit)

        # constraint_id → mutable dict mirroring EthicalConstraint
        self._constraints: Dict[str, Dict[str, Any]] = {}

        # constraint_id → checker callable(action, context) → Optional[str]
        self._checkers: Dict[str, Callable[[str, Dict[str, Any]], Optional[str]]] = {}

        # domain → list[constraint_id]
        self._domain_index: Dict[str, List[str]] = {}

        # Audit logs
        self._evaluations: Deque[EvaluationResult] = deque(maxlen=self._audit_limit)
        self._vetoes: Deque[VetoRecord] = deque(maxlen=self._audit_limit)

        # Counters
        self._total_evaluated = 0
        self._total_vetoed = 0
        self._total_approved = 0
        self._total_warnings = 0

        if enable_defaults:
            self._register_defaults()

        log.info(
            "EthicalReasoning initialised (defaults=%s, audit_limit=%d)",
            enable_defaults, self._audit_limit,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_id(name: str) -> str:
        return hashlib.sha256(name.encode()).hexdigest()[:16]

    def _build_constraint(self, data: Dict[str, Any]) -> EthicalConstraint:
        return EthicalConstraint(
            constraint_id=data["constraint_id"],
            name=data["name"],
            description=data["description"],
            severity=Severity(data["severity"]) if isinstance(data["severity"], str) else data["severity"],
            domain=data["domain"],
            created_at=data["created_at"],
            enabled=data["enabled"],
        )

    def _register_defaults(self) -> None:
        """Register built-in safety constraints."""
        for name, description, severity, checker in _DEFAULT_CHECKERS:
            self.register_constraint(name, description, severity, checker=checker)

    # ------------------------------------------------------------------
    # Constraint registry
    # ------------------------------------------------------------------

    def register_constraint(
        self,
        name: str,
        description: str,
        severity: Severity,
        domain: Optional[str] = None,
        checker: Optional[Callable[[str, Dict[str, Any]], Optional[str]]] = None,
    ) -> EthicalConstraint:
        """Register an ethical constraint. Returns the created entry."""
        cid = self._make_id(name)
        now = time.time()
        with self._lock:
            if cid in self._constraints:
                return self._build_constraint(self._constraints[cid])
            data: Dict[str, Any] = {
                "constraint_id": cid,
                "name": name,
                "description": description,
                "severity": severity.value if isinstance(severity, Severity) else severity,
                "domain": domain,
                "created_at": now,
                "enabled": True,
            }
            self._constraints[cid] = data
            if checker is not None:
                self._checkers[cid] = checker
            scope = domain or "__global__"
            self._domain_index.setdefault(scope, []).append(cid)
        self._bus.publish("ethical.constraint_registered", {
            "constraint_id": cid, "name": name, "severity": severity.value if isinstance(severity, Severity) else severity,
        })
        log.debug("[EthicalReasoning] Registered constraint: %s (%s)", name, severity)
        return self._build_constraint(data)

    def enable_constraint(self, constraint_id: str) -> bool:
        """Enable a previously disabled constraint."""
        with self._lock:
            data = self._constraints.get(constraint_id)
            if data is None:
                return False
            data["enabled"] = True
        return True

    def disable_constraint(self, constraint_id: str) -> bool:
        """Disable a constraint without removing it."""
        with self._lock:
            data = self._constraints.get(constraint_id)
            if data is None:
                return False
            data["enabled"] = False
        return True

    def get_constraint(self, constraint_id: str) -> Optional[EthicalConstraint]:
        """Return a constraint by id, or None."""
        with self._lock:
            data = self._constraints.get(constraint_id)
            if data is None:
                return None
            return self._build_constraint(data)

    def list_constraints(self, domain: Optional[str] = None) -> List[EthicalConstraint]:
        """List constraints, optionally filtered by domain."""
        with self._lock:
            if domain is not None:
                cids = self._domain_index.get(domain, [])
                return [
                    self._build_constraint(self._constraints[c])
                    for c in cids if c in self._constraints
                ]
            return [self._build_constraint(d) for d in self._constraints.values()]

    # ------------------------------------------------------------------
    # Action evaluation
    # ------------------------------------------------------------------

    def evaluate(
        self,
        action: str,
        domain: str = "general",
        context: Optional[Dict[str, Any]] = None,
    ) -> EvaluationResult:
        """
        Evaluate a proposed action against all applicable constraints.

        Constraints are selected by domain match or global scope.
        Each constraint with an associated checker function is tested.
        Violations are collected and classified by severity.

        Returns an EvaluationResult with outcome, violations, and score.
        """
        ctx = context or {}
        started = time.perf_counter()
        violations: List[PolicyViolation] = []
        warnings: List[PolicyViolation] = []

        with self._lock:
            # Gather applicable constraint IDs (domain-specific + global)
            applicable_cids: List[str] = []
            for cid_list in [
                self._domain_index.get(domain, []),
                self._domain_index.get("__global__", []),
            ]:
                applicable_cids.extend(cid_list)

            # De-duplicate
            seen = set()
            unique_cids = []
            for cid in applicable_cids:
                if cid not in seen:
                    seen.add(cid)
                    unique_cids.append(cid)

            for cid in unique_cids:
                data = self._constraints.get(cid)
                if data is None or not data["enabled"]:
                    continue
                checker = self._checkers.get(cid)
                if checker is None:
                    continue
                try:
                    reason = checker(action, ctx)
                except Exception as exc:
                    log.warning(
                        "[EthicalReasoning] Checker %s failed: %s", cid, exc
                    )
                    continue
                if reason is None:
                    continue
                sev = Severity(data["severity"]) if isinstance(data["severity"], str) else data["severity"]
                pv = PolicyViolation(
                    constraint_id=cid,
                    constraint_name=data["name"],
                    severity=sev,
                    reason=reason,
                    confidence=0.9,
                )
                if sev in (Severity.CRITICAL, Severity.HIGH):
                    violations.append(pv)
                else:
                    warnings.append(pv)

        elapsed_ms = (time.perf_counter() - started) * 1000.0

        # Determine outcome
        has_critical = any(v.severity == Severity.CRITICAL for v in violations)
        has_high = any(v.severity == Severity.HIGH for v in violations)

        if has_critical:
            outcome = EvalOutcome.VETOED
        elif has_high:
            outcome = EvalOutcome.VETOED
        elif warnings:
            outcome = EvalOutcome.WARNING
        else:
            outcome = EvalOutcome.APPROVED

        # Score: 1.0 = fully compliant.  Deductions by severity.
        total_violations = len(violations) + len(warnings)
        if total_violations == 0:
            score = 1.0
        else:
            deduction = 0.0
            for v in violations:
                deduction += 0.4 if v.severity == Severity.CRITICAL else 0.25
            for w in warnings:
                deduction += 0.1 if w.severity == Severity.MEDIUM else 0.05
            score = max(0.0, 1.0 - deduction)

        result = EvaluationResult(
            action=action,
            domain=domain,
            outcome=outcome,
            violations=tuple(violations),
            warnings=tuple(warnings),
            score=score,
            timestamp=time.time(),
            evaluation_ms=elapsed_ms,
        )

        with self._lock:
            self._evaluations.append(result)
            self._total_evaluated += 1
            if outcome == EvalOutcome.VETOED:
                self._total_vetoed += 1
                veto = VetoRecord(
                    action=action,
                    domain=domain,
                    outcome=outcome,
                    violations=tuple(violations),
                    override_reason=None,
                    timestamp=result.timestamp,
                )
                self._vetoes.append(veto)
            elif outcome == EvalOutcome.APPROVED:
                self._total_approved += 1
            elif outcome == EvalOutcome.WARNING:
                self._total_warnings += 1

        topic = (
            "ethical.veto" if outcome == EvalOutcome.VETOED
            else "ethical.evaluation"
        )
        self._bus.publish(topic, {
            "action": action[:200],
            "domain": domain,
            "outcome": outcome.value,
            "violation_count": len(violations),
            "warning_count": len(warnings),
            "score": score,
        })
        log.debug(
            "[EthicalReasoning] Evaluated action: outcome=%s score=%.2f violations=%d",
            outcome.value, score, len(violations),
        )
        return result

    # ------------------------------------------------------------------
    # Veto / override
    # ------------------------------------------------------------------

    def override(
        self,
        action: str,
        domain: str = "general",
        reason: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> EvaluationResult:
        """
        Evaluate and, if vetoed at HIGH level, override with reason.

        CRITICAL violations cannot be overridden — the veto stands.
        """
        result = self.evaluate(action, domain=domain, context=context)
        if result.outcome != EvalOutcome.VETOED:
            return result
        # Check if all violations are HIGH (overridable) vs CRITICAL
        has_critical = any(v.severity == Severity.CRITICAL for v in result.violations)
        if has_critical:
            log.warning(
                "[EthicalReasoning] Override denied — CRITICAL violation for: %s",
                action[:80],
            )
            return result
        # Allow override for HIGH-only vetoes
        overridden = EvaluationResult(
            action=result.action,
            domain=result.domain,
            outcome=EvalOutcome.OVERRIDDEN,
            violations=result.violations,
            warnings=result.warnings,
            score=result.score,
            timestamp=time.time(),
            evaluation_ms=result.evaluation_ms,
        )
        with self._lock:
            self._evaluations.append(overridden)
            veto = VetoRecord(
                action=action,
                domain=domain,
                outcome=EvalOutcome.OVERRIDDEN,
                violations=result.violations,
                override_reason=reason,
                timestamp=overridden.timestamp,
            )
            self._vetoes.append(veto)
        self._bus.publish("ethical.override", {
            "action": action[:200],
            "domain": domain,
            "reason": reason,
            "violation_count": len(result.violations),
        })
        log.info("[EthicalReasoning] Override accepted for: %s", action[:80])
        return overridden

    # ------------------------------------------------------------------
    # Audit trail
    # ------------------------------------------------------------------

    def get_audit_trail(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return recent evaluation records as dicts."""
        with self._lock:
            recent = list(self._evaluations)[-limit:]
            return [
                {
                    "action": r.action,
                    "domain": r.domain,
                    "outcome": r.outcome.value,
                    "violation_count": len(r.violations),
                    "warning_count": len(r.warnings),
                    "score": r.score,
                    "timestamp": r.timestamp,
                }
                for r in recent
            ]

    def get_veto_log(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return recent veto/override records as dicts."""
        with self._lock:
            recent = list(self._vetoes)[-limit:]
            return [
                {
                    "action": r.action,
                    "domain": r.domain,
                    "outcome": r.outcome.value,
                    "override_reason": r.override_reason,
                    "timestamp": r.timestamp,
                }
                for r in recent
            ]

    # ------------------------------------------------------------------
    # Export / import
    # ------------------------------------------------------------------

    def export_state(self) -> Dict[str, Any]:
        """Export constraint definitions (not checkers — those are code)."""
        with self._lock:
            constraints = []
            for data in self._constraints.values():
                constraints.append({
                    "constraint_id": data["constraint_id"],
                    "name": data["name"],
                    "description": data["description"],
                    "severity": data["severity"],
                    "domain": data["domain"],
                    "enabled": data["enabled"],
                })
            return {
                "constraints": constraints,
                "total_evaluated": self._total_evaluated,
                "total_vetoed": self._total_vetoed,
                "total_approved": self._total_approved,
            }

    def import_state(self, data: Dict[str, Any]) -> int:
        """Import constraint definitions. Returns count loaded."""
        loaded = 0
        with self._lock:
            for c in data.get("constraints", []):
                cid = c["constraint_id"]
                self._constraints[cid] = {
                    "constraint_id": cid,
                    "name": c["name"],
                    "description": c.get("description", ""),
                    "severity": c["severity"],
                    "domain": c.get("domain"),
                    "created_at": c.get("created_at", time.time()),
                    "enabled": c.get("enabled", True),
                }
                scope = c.get("domain") or "__global__"
                self._domain_index.setdefault(scope, [])
                if cid not in self._domain_index[scope]:
                    self._domain_index[scope].append(cid)
                loaded += 1
        log.info("[EthicalReasoning] Imported %d constraints", loaded)
        return loaded

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        """Return summary statistics for the ethical reasoning engine."""
        with self._lock:
            return {
                "constraint_count": len(self._constraints),
                "enabled_count": sum(
                    1 for d in self._constraints.values() if d["enabled"]
                ),
                "total_evaluated": self._total_evaluated,
                "total_vetoed": self._total_vetoed,
                "total_approved": self._total_approved,
                "total_warnings": self._total_warnings,
                "audit_size": len(self._evaluations),
                "veto_log_size": len(self._vetoes),
            }
