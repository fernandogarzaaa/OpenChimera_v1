"""Quantum Consensus Virtual Machine for ChimeraLang.

Executes ChimeraLang AST with:
- Probabilistic value tracking
- Multi-branch gate execution with collapse strategies
- Exploration-budget-bounded goal execution
- Reasoning trace capture
"""

from __future__ import annotations

import copy
import hashlib
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from chimera.ast_nodes import (
    AllowConstraint,
    AssertStmt,
    BinaryOp,
    BoolLiteral,
    CallExpr,
    Declaration,
    EmitStmt,
    Expr,
    ExprStmt,
    FloatLiteral,
    FnDecl,
    ForbiddenConstraint,
    GateDecl,
    GoalDecl,
    Identifier,
    IfExpr,
    IntLiteral,
    ListLiteral,
    MemberExpr,
    MustConstraint,
    Program,
    ReasonDecl,
    ReturnStmt,
    Statement,
    StringLiteral,
    UnaryOp,
    ValDecl,
)
from chimera.types import (
    ChimeraValue,
    Confidence,
    ConfidenceViolation,
    ConfidentValue,
    ConvergeValue,
    ExploreValue,
    MemoryScope,
    ProvisionalValue,
)


# ---------------------------------------------------------------------------
# VM Environment
# ---------------------------------------------------------------------------

@dataclass
class VMEnv:
    """Scoped runtime environment."""
    bindings: dict[str, ChimeraValue] = field(default_factory=dict)
    parent: VMEnv | None = None

    def get(self, name: str) -> ChimeraValue | None:
        if name in self.bindings:
            return self.bindings[name]
        if self.parent is not None:
            return self.parent.get(name)
        return None

    def set(self, name: str, value: ChimeraValue) -> None:
        self.bindings[name] = value

    def child(self) -> VMEnv:
        return VMEnv(parent=self)


class ReturnSignal(Exception):
    """Control flow signal for return statements."""
    def __init__(self, value: ChimeraValue) -> None:
        self.value = value


class AssertionFailed(Exception):
    """Raised when a ChimeraLang assert fails."""
    def __init__(self, message: str, trace: list[str] | None = None) -> None:
        self.trace = trace or []
        super().__init__(message)


# ---------------------------------------------------------------------------
# Execution Result
# ---------------------------------------------------------------------------

@dataclass
class ExecutionResult:
    """Result of a full program execution."""
    emitted: list[ChimeraValue] = field(default_factory=list)
    trace: list[str] = field(default_factory=list)
    gate_logs: list[dict[str, Any]] = field(default_factory=list)
    assertions_passed: int = 0
    assertions_failed: int = 0
    errors: list[str] = field(default_factory=list)
    duration_ms: float = 0.0


# ---------------------------------------------------------------------------
# Quantum Consensus VM
# ---------------------------------------------------------------------------

class ChimeraVM:
    def __init__(self, *, seed: int | None = None) -> None:
        self._env = VMEnv()
        self._functions: dict[str, FnDecl] = {}
        self._gates: dict[str, GateDecl] = {}
        self._result = ExecutionResult()
        self._rng = random.Random(seed)
        self._register_builtins()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute(self, program: Program) -> ExecutionResult:
        start = time.perf_counter()
        try:
            # First pass: register declarations
            for decl in program.declarations:
                if isinstance(decl, FnDecl):
                    self._functions[decl.name] = decl
                elif isinstance(decl, GateDecl):
                    self._gates[decl.name] = decl

            # Second pass: execute top-level
            for decl in program.declarations:
                if isinstance(decl, FnDecl):
                    continue
                if isinstance(decl, GateDecl):
                    continue
                self._exec_decl(decl)
        except AssertionFailed as e:
            self._result.errors.append(f"Assertion failed: {e}")
            self._result.assertions_failed += 1
        except ConfidenceViolation as e:
            self._result.errors.append(f"Confidence violation: {e}")
        except Exception as e:
            self._result.errors.append(f"Runtime error: {e}")

        self._result.duration_ms = (time.perf_counter() - start) * 1000
        return self._result

    # ------------------------------------------------------------------
    # Built-ins
    # ------------------------------------------------------------------

    def _register_builtins(self) -> None:
        # confidence-checking functions
        self._builtins: dict[str, Callable[..., ChimeraValue]] = {
            "confident": self._builtin_confident,
            "consensus": self._builtin_consensus,
            "no_hallucination": self._builtin_no_hallucination,
            "confidence_of": self._builtin_confidence_of,
            "print": self._builtin_print,
        }

    def _builtin_confident(self, *args: ChimeraValue) -> ChimeraValue:
        if args:
            return self._wrap(args[0].confidence.value >= 0.95)
        return self._wrap(True)

    def _builtin_consensus(self, *args: ChimeraValue) -> ChimeraValue:
        if args and isinstance(args[0], ConvergeValue):
            return self._wrap(len(args[0].branch_values) >= 2)
        return self._wrap(True)

    def _builtin_no_hallucination(self, *args: ChimeraValue) -> ChimeraValue:
        # Simplified: a value is "hallucination-free" if confidence > 0.5 and has trace
        if args:
            v = args[0]
            ok = v.confidence.value > 0.5 and len(v.trace) > 0
            return self._wrap(ok)
        return self._wrap(True)

    def _builtin_confidence_of(self, *args: ChimeraValue) -> ChimeraValue:
        if args:
            return self._wrap(args[0].confidence.value)
        return self._wrap(0.0)

    def _builtin_print(self, *args: ChimeraValue) -> ChimeraValue:
        text = " ".join(str(a.raw) for a in args)
        self._trace(f"[print] {text}")
        return self._wrap(None)

    # ------------------------------------------------------------------
    # Declaration execution
    # ------------------------------------------------------------------

    def _exec_decl(self, node: Declaration | Statement) -> None:
        if isinstance(node, ValDecl):
            self._exec_val(node)
        elif isinstance(node, GoalDecl):
            self._exec_goal(node)
        elif isinstance(node, ReasonDecl):
            self._exec_reason(node)
        elif isinstance(node, Statement):
            self._exec_stmt(node)

    # ------------------------------------------------------------------
    # Statement execution
    # ------------------------------------------------------------------

    def _exec_stmt(self, stmt: Statement) -> None:
        if isinstance(stmt, ValDecl):
            self._exec_val(stmt)
        elif isinstance(stmt, ReturnStmt):
            value = self._eval(stmt.value) if stmt.value else self._wrap(None)
            raise ReturnSignal(value)
        elif isinstance(stmt, AssertStmt):
            self._exec_assert(stmt)
        elif isinstance(stmt, EmitStmt):
            val = self._eval(stmt.value)
            self._result.emitted.append(val)
            self._trace(f"[emit] {val.raw} (confidence={val.confidence.value:.2f})")
        elif isinstance(stmt, ExprStmt):
            self._eval(stmt.expr)

    def _exec_val(self, val: ValDecl) -> None:
        if val.value is not None:
            value = self._eval(val.value)
        else:
            value = self._wrap(None)
        value.trace.append(f"bound to '{val.name}'")
        self._env.set(val.name, value)

    def _exec_assert(self, assrt: AssertStmt) -> None:
        val = self._eval(assrt.condition)
        if val.raw:
            self._result.assertions_passed += 1
            self._trace(f"[assert] PASSED (confidence={val.confidence.value:.2f})")
        else:
            self._result.assertions_failed += 1
            raise AssertionFailed(
                f"Assertion failed (confidence={val.confidence.value:.2f})",
                trace=val.trace,
            )

    # ------------------------------------------------------------------
    # Expression evaluation
    # ------------------------------------------------------------------

    def _eval(self, expr: Expr) -> ChimeraValue:
        if isinstance(expr, IntLiteral):
            return self._wrap(expr.value, confidence=1.0)

        if isinstance(expr, FloatLiteral):
            return self._wrap(expr.value, confidence=1.0)

        if isinstance(expr, StringLiteral):
            return self._wrap(expr.value, confidence=1.0)

        if isinstance(expr, BoolLiteral):
            return self._wrap(expr.value, confidence=1.0)

        if isinstance(expr, ListLiteral):
            elements = [self._eval(e) for e in expr.elements]
            avg_conf = sum(e.confidence.value for e in elements) / max(len(elements), 1)
            return self._wrap([e.raw for e in elements], confidence=avg_conf)

        if isinstance(expr, Identifier):
            return self._eval_ident(expr)

        if isinstance(expr, BinaryOp):
            return self._eval_binary(expr)

        if isinstance(expr, UnaryOp):
            return self._eval_unary(expr)

        if isinstance(expr, CallExpr):
            return self._eval_call(expr)

        if isinstance(expr, MemberExpr):
            return self._eval_member(expr)

        if isinstance(expr, IfExpr):
            return self._eval_if(expr)

        return self._wrap(None)

    def _eval_ident(self, ident: Identifier) -> ChimeraValue:
        val = self._env.get(ident.name)
        if val is not None:
            return val
        return self._wrap(None, confidence=0.0)

    def _eval_binary(self, expr: BinaryOp) -> ChimeraValue:
        left = self._eval(expr.left)
        right = self._eval(expr.right)
        combined_conf = left.confidence.combine(right.confidence)

        ops: dict[str, Callable[[Any, Any], Any]] = {
            "+": lambda a, b: a + b,
            "-": lambda a, b: a - b,
            "*": lambda a, b: a * b,
            "/": lambda a, b: a / b if b != 0 else 0,
            "%": lambda a, b: a % b if b != 0 else 0,
            "==": lambda a, b: a == b,
            "!=": lambda a, b: a != b,
            "<": lambda a, b: a < b,
            ">": lambda a, b: a > b,
            "<=": lambda a, b: a <= b,
            ">=": lambda a, b: a >= b,
            "and": lambda a, b: bool(a) and bool(b),
            "or": lambda a, b: bool(a) or bool(b),
        }

        op_fn = ops.get(expr.op)
        if op_fn is None:
            return self._wrap(None)

        try:
            result = op_fn(left.raw, right.raw)
        except (TypeError, ValueError):
            result = None

        return ChimeraValue(
            raw=result,
            confidence=combined_conf,
            trace=[*left.trace, *right.trace, f"op:{expr.op}"],
        )

    def _eval_unary(self, expr: UnaryOp) -> ChimeraValue:
        operand = self._eval(expr.operand)
        if expr.op == "-":
            return ChimeraValue(raw=-operand.raw, confidence=operand.confidence,
                                trace=[*operand.trace, "negate"])
        if expr.op == "not":
            return ChimeraValue(raw=not operand.raw, confidence=operand.confidence,
                                trace=[*operand.trace, "not"])
        return operand

    def _eval_call(self, expr: CallExpr) -> ChimeraValue:
        # Evaluate arguments first
        args = [self._eval(a) for a in expr.args]

        if isinstance(expr.callee, Identifier):
            name = expr.callee.name

            # Check builtins
            if name in self._builtins:
                return self._builtins[name](*args)

            # Probabilistic wrapper constructors
            if name == "Confident":
                raw = args[0].raw if args else None
                conf = args[0].confidence.value if args else 0.95
                return ConfidentValue(
                    raw=raw,
                    confidence=Confidence(max(conf, 0.95), "Confident_constructor"),
                    trace=[f"Confident({raw})"],
                )
            if name == "Explore":
                raw = args[0].raw if args else None
                budget = args[1].raw if len(args) > 1 else 1.0
                return ExploreValue(
                    raw=raw,
                    confidence=Confidence(0.5, "Explore_constructor"),
                    trace=[f"Explore({raw})"],
                    exploration_budget=budget,
                )
            if name == "Converge":
                raw = args[0].raw if args else None
                return ConvergeValue(
                    raw=raw,
                    confidence=Confidence(0.7, "Converge_constructor"),
                    trace=[f"Converge({raw})"],
                    branch_values=args,
                )
            if name == "Provisional":
                raw = args[0].raw if args else None
                return ProvisionalValue(
                    raw=raw,
                    confidence=Confidence(0.6, "Provisional_constructor"),
                    memory_scope=MemoryScope.PROVISIONAL,
                    trace=[f"Provisional({raw})"],
                )

            # User-defined function
            if name in self._functions:
                return self._call_fn(self._functions[name], args)

            # Gate invocation
            if name in self._gates:
                return self._call_gate(self._gates[name], args)

            # Check env for callable (e.g. reason blocks registered as functions)
            val = self._env.get(name)
            if callable(val):
                return val(*args)

        # Generic call
        return self._wrap(None)

    def _eval_member(self, expr: MemberExpr) -> ChimeraValue:
        obj = self._eval(expr.obj)
        if expr.member == "confidence":
            return self._wrap(obj.confidence.value)
        if expr.member == "raw":
            return self._wrap(obj.raw)
        if expr.member == "fingerprint":
            return self._wrap(obj.fingerprint)
        return self._wrap(None)

    def _eval_if(self, expr: IfExpr) -> ChimeraValue:
        cond = self._eval(expr.condition)
        scope = self._env.child()
        old_env = self._env
        self._env = scope
        try:
            if cond.raw:
                for s in expr.then_body:
                    self._exec_stmt(s)
            elif expr.else_body:
                for s in expr.else_body:
                    self._exec_stmt(s)
        except ReturnSignal:
            raise
        finally:
            self._env = old_env
        return self._wrap(None)

    # ------------------------------------------------------------------
    # Constraint enforcement
    # ------------------------------------------------------------------

    def _enforce_constraints(self, constraints: list, fn_name: str) -> None:
        """Evaluate must/allow/forbidden constraints for a function or gate."""
        for constraint in constraints:
            if isinstance(constraint, MustConstraint):
                val = self._eval(constraint.expr)
                if not val.raw:
                    raise AssertionFailed(
                        f"[{fn_name}] must-constraint violated: "
                        f"'{constraint.expr}' (confidence={val.confidence.value:.2f})",
                        trace=val.trace,
                    )
                self._trace(
                    f"[{fn_name}] must-constraint satisfied "
                    f"(confidence={val.confidence.value:.2f})"
                )
            elif isinstance(constraint, AllowConstraint):
                caps = ", ".join(constraint.capabilities)
                self._trace(f"[{fn_name}] allow: {caps}")
            elif isinstance(constraint, ForbiddenConstraint):
                caps = ", ".join(constraint.capabilities)
                self._trace(f"[{fn_name}] forbidden: {caps}")
                # Record forbidden capabilities in the current scope so downstream
                # tooling can inspect what is not permitted.
                forbidden_key = f"__forbidden_{fn_name}__"
                existing = self._env.get(forbidden_key)
                combined = (existing.raw if existing else []) + constraint.capabilities
                self._env.set(forbidden_key, self._wrap(combined))

    # ------------------------------------------------------------------
    # Function call
    # ------------------------------------------------------------------

    def _call_fn(self, fn: FnDecl, args: list[ChimeraValue]) -> ChimeraValue:
        scope = self._env.child()
        for param, arg in zip(fn.params, args):
            scope.set(param.name, arg)
        old_env = self._env
        self._env = scope
        result = self._wrap(None)
        try:
            self._enforce_constraints(fn.constraints, fn.name)
            for stmt in fn.body:
                self._exec_stmt(stmt)
        except ReturnSignal as sig:
            result = sig.value
        finally:
            self._env = old_env
        return result

    # ------------------------------------------------------------------
    # Gate execution (QUANTUM CONSENSUS)
    # ------------------------------------------------------------------

    def _call_gate(self, gate: GateDecl, args: list[ChimeraValue]) -> ChimeraValue:
        self._trace(f"[gate] Spawning {gate.branches} branches for '{gate.name}'")
        branches: list[ChimeraValue] = []

        for i in range(gate.branches):
            self._trace(f"[gate] Branch {i+1}/{gate.branches} executing...")
            scope = self._env.child()

            # Expose per-branch metadata so body code can produce divergent outputs.
            branch_seed = self._rng.randint(0, 2**32 - 1)
            scope.set("branch_index", self._wrap(i, confidence=1.0))
            scope.set("branch_seed", self._wrap(branch_seed, confidence=1.0))

            for param, arg in zip(gate.params, args):
                # Inject slight randomness to simulate diverse reasoning paths.
                # Both confidence AND a per-branch seed diverge so that branches
                # using branch_index / branch_seed produce genuinely different values.
                noisy_conf = min(1.0, max(0.0, arg.confidence.value + self._rng.gauss(0, 0.05)))
                noisy = ChimeraValue(
                    raw=arg.raw,
                    confidence=Confidence(noisy_conf, f"branch_{i}"),
                    trace=[*arg.trace, f"branch_{i}_input"],
                )
                scope.set(param.name, noisy)

            old_env = self._env
            self._env = scope
            result = self._wrap(None)
            try:
                for stmt in gate.body:
                    self._exec_stmt(stmt)
            except ReturnSignal as sig:
                result = sig.value
            finally:
                self._env = old_env

            # Tag the branch result with its index for consensus tracing.
            result.trace.append(f"branch_{i}_output")
            branches.append(result)

        # Collapse
        collapsed = self._collapse(branches, gate.collapse, gate.threshold)

        self._result.gate_logs.append({
            "gate": gate.name,
            "branches": gate.branches,
            "collapse": gate.collapse,
            "branch_confidences": [b.confidence.value for b in branches],
            "result_confidence": collapsed.confidence.value,
            "result_value": collapsed.raw,
        })

        self._trace(
            f"[gate] Collapsed '{gate.name}': "
            f"confidence={collapsed.confidence.value:.3f}, value={collapsed.raw}"
        )

        return collapsed

    def _collapse(
        self,
        branches: list[ChimeraValue],
        strategy: str,
        threshold: float,
    ) -> ChimeraValue:
        if not branches:
            return self._wrap(None, confidence=0.0)

        if strategy == "highest_confidence":
            best = max(branches, key=lambda b: b.confidence.value)
            return ConvergeValue(
                raw=best.raw,
                confidence=best.confidence,
                branch_values=branches,
                trace=[f"collapsed:highest_confidence"],
            )

        if strategy == "weighted_vote":
            # Weight each branch's vote by confidence
            vote_weights: dict[Any, float] = {}
            for b in branches:
                key = str(b.raw)
                vote_weights[key] = vote_weights.get(key, 0.0) + b.confidence.value
            winner_key = max(vote_weights, key=vote_weights.get)  # type: ignore[arg-type]
            winner = next(b for b in branches if str(b.raw) == winner_key)
            total_weight = sum(vote_weights.values())
            winner_weight = vote_weights[winner_key]
            consensus_conf = winner_weight / total_weight if total_weight > 0 else 0.0
            return ConvergeValue(
                raw=winner.raw,
                confidence=Confidence(consensus_conf, "weighted_vote"),
                branch_values=branches,
                trace=[f"collapsed:weighted_vote({consensus_conf:.3f})"],
            )

        # Default: majority
        votes: dict[str, list[ChimeraValue]] = {}
        for b in branches:
            key = str(b.raw)
            votes.setdefault(key, []).append(b)
        majority_key = max(votes, key=lambda k: len(votes[k]))
        majority_group = votes[majority_key]
        avg_conf = sum(b.confidence.value for b in majority_group) / len(majority_group)

        if avg_conf < threshold:
            self._trace(f"[gate] Consensus below threshold ({avg_conf:.3f} < {threshold})")

        return ConvergeValue(
            raw=majority_group[0].raw,
            confidence=Confidence(avg_conf, "majority"),
            branch_values=branches,
            trace=[f"collapsed:majority({len(majority_group)}/{len(branches)})"],
        )

    # ------------------------------------------------------------------
    # Goal execution
    # ------------------------------------------------------------------

    def _exec_goal(self, goal: GoalDecl) -> None:
        self._trace(f'[goal] Pursuing: "{goal.description}"')
        self._trace(f"[goal] Budget: {goal.explore_budget}, Constraints: {goal.constraints_list}")
        scope = self._env.child()
        old_env = self._env
        self._env = scope
        try:
            for stmt in goal.body:
                self._exec_stmt(stmt)
        except ReturnSignal:
            pass
        finally:
            self._env = old_env
        self._trace(f'[goal] Completed: "{goal.description}"')

    # ------------------------------------------------------------------
    # Reason execution
    # ------------------------------------------------------------------

    def _exec_reason(self, reason: ReasonDecl) -> None:
        """Register the reason block as a callable function in the current scope."""
        # The reason block name comes from the AST. For `reason about(...)`, the
        # parser stores the identifier after 'about' — but currently the parser
        # stores name="reason" for all reason blocks. The *call* name used in
        # source is "about", so register under "about".
        def _invoke(*args: ChimeraValue) -> ChimeraValue:
            self._trace(f"[reason] Starting reasoning with given: {reason.given}")
            scope = self._env.child()
            # Bind parameters
            for param, arg in zip(reason.params, args):
                scope.set(param.name, arg)
            old_env = self._env
            self._env = scope
            result: ChimeraValue | None = None
            try:
                for stmt in reason.body:
                    self._exec_stmt(stmt)
            except ReturnSignal as ret:
                result = ret.value
            finally:
                self._env = old_env
            self._trace(f"[reason] Committed via: {reason.commit_strategy}")
            return result if result is not None else self._wrap(None)

        self._env.set(reason.name, _invoke)

    # ------------------------------------------------------------------
    # Value construction helpers
    # ------------------------------------------------------------------

    def _wrap(self, raw: Any, confidence: float = 1.0) -> ChimeraValue:
        return ChimeraValue(
            raw=raw,
            confidence=Confidence(confidence, "literal"),
            trace=[],
        )

    def _trace(self, msg: str) -> None:
        self._result.trace.append(msg)
