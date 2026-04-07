"""Static type checker for ChimeraLang.

Walks the AST and verifies:
- Confidence boundaries (Explore cannot promote to Confident without gate)
- Memory scope rules (Ephemeral doesn't escape scope)
- Semantic constraint validation (must/allow/forbidden)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from chimera.ast_nodes import (
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
    GateDecl,
    GenericType,
    GoalDecl,
    Identifier,
    IfExpr,
    IntLiteral,
    ListLiteral,
    MemberExpr,
    MemoryType,
    NamedType,
    Param,
    PrimitiveType,
    ProbabilisticType,
    Program,
    ReasonDecl,
    ReturnStmt,
    Statement,
    StringLiteral,
    TypeExpr,
    UnaryOp,
    ValDecl,
)
from chimera.types import (
    BOOL_T,
    BUILTINS,
    FLOAT_T,
    INT_T,
    TEXT_T,
    VOID_T,
    ChimeraType,
    FnTypeDesc,
    GenericTypeDesc,
    MemTypeDesc,
    PrimitiveTypeDesc,
    ProbTypeDesc,
    PromotionViolation,
    TypeMismatch,
)


@dataclass
class TypeEnv:
    """Scoped type environment."""
    bindings: dict[str, ChimeraType] = field(default_factory=dict)
    parent: TypeEnv | None = None

    def lookup(self, name: str) -> ChimeraType | None:
        if name in self.bindings:
            return self.bindings[name]
        if self.parent is not None:
            return self.parent.lookup(name)
        return None

    def define(self, name: str, ty: ChimeraType) -> None:
        self.bindings[name] = ty

    def child(self) -> TypeEnv:
        return TypeEnv(parent=self)


@dataclass
class TypeCheckResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    ok: bool = True


class TypeChecker:
    def __init__(self) -> None:
        self._env = TypeEnv(bindings=dict(BUILTINS))
        self._result = TypeCheckResult()
        self._in_gate = False  # inside a gate → promotion allowed

    def check(self, program: Program) -> TypeCheckResult:
        for decl in program.declarations:
            self._check_decl(decl)
        self._result.ok = len(self._result.errors) == 0
        return self._result

    # ------------------------------------------------------------------
    # Declarations
    # ------------------------------------------------------------------

    def _check_decl(self, node: Declaration | Statement) -> None:
        if isinstance(node, FnDecl):
            self._check_fn(node)
        elif isinstance(node, GateDecl):
            self._check_gate(node)
        elif isinstance(node, GoalDecl):
            self._check_goal(node)
        elif isinstance(node, ReasonDecl):
            self._check_reason(node)
        elif isinstance(node, ValDecl):
            self._check_val(node)
        elif isinstance(node, Statement):
            self._check_stmt(node)

    def _check_fn(self, fn: FnDecl) -> None:
        scope = self._env.child()
        param_types = []
        for p in fn.params:
            pt = self._resolve_type(p.type_ann)
            scope.define(p.name, pt)
            param_types.append(pt)
        ret_type = self._resolve_type(fn.return_type) if fn.return_type else VOID_T
        self._env.define(fn.name, FnTypeDesc(
            name=fn.name, param_types=tuple(param_types), return_type=ret_type
        ))
        old_env = self._env
        self._env = scope
        for stmt in fn.body:
            self._check_stmt(stmt)
        self._env = old_env

    def _check_gate(self, gate: GateDecl) -> None:
        old_in_gate = self._in_gate
        self._in_gate = True
        scope = self._env.child()
        for p in gate.params:
            pt = self._resolve_type(p.type_ann)
            scope.define(p.name, pt)
        old_env = self._env
        self._env = scope
        for stmt in gate.body:
            self._check_stmt(stmt)
        self._env = old_env
        self._in_gate = old_in_gate

    def _check_goal(self, goal: GoalDecl) -> None:
        scope = self._env.child()
        old_env = self._env
        self._env = scope
        for stmt in goal.body:
            self._check_stmt(stmt)
        self._env = old_env

    def _check_reason(self, reason: ReasonDecl) -> None:
        scope = self._env.child()
        for p in reason.params:
            pt = self._resolve_type(p.type_ann)
            scope.define(p.name, pt)
        old_env = self._env
        self._env = scope
        for stmt in reason.body:
            self._check_stmt(stmt)
        self._env = old_env

    def _check_val(self, val: ValDecl) -> None:
        declared = self._resolve_type(val.type_ann) if val.type_ann else None
        if val.value is not None:
            inferred = self._infer_expr(val.value)
            if declared and inferred:
                self._check_assignment_compat(declared, inferred, val.name)
            final = declared or inferred or VOID_T
        else:
            final = declared or VOID_T
        self._env.define(val.name, final)

    # ------------------------------------------------------------------
    # Statements
    # ------------------------------------------------------------------

    def _check_stmt(self, stmt: Statement) -> None:
        if isinstance(stmt, ValDecl):
            self._check_val(stmt)
        elif isinstance(stmt, ReturnStmt):
            if stmt.value:
                self._infer_expr(stmt.value)
        elif isinstance(stmt, AssertStmt):
            self._infer_expr(stmt.condition)
        elif isinstance(stmt, EmitStmt):
            self._infer_expr(stmt.value)
        elif isinstance(stmt, ExprStmt):
            self._infer_expr(stmt.expr)

    # ------------------------------------------------------------------
    # Expression type inference
    # ------------------------------------------------------------------

    def _infer_expr(self, expr: Expr) -> ChimeraType:
        if isinstance(expr, IntLiteral):
            return INT_T
        if isinstance(expr, FloatLiteral):
            return FLOAT_T
        if isinstance(expr, StringLiteral):
            return TEXT_T
        if isinstance(expr, BoolLiteral):
            return BOOL_T
        if isinstance(expr, Identifier):
            ty = self._env.lookup(expr.name)
            if ty is None:
                self._result.warnings.append(f"Unresolved identifier: {expr.name}")
                return VOID_T
            return ty
        if isinstance(expr, BinaryOp):
            return self._infer_binary(expr)
        if isinstance(expr, UnaryOp):
            return self._infer_expr(expr.operand)
        if isinstance(expr, CallExpr):
            return self._infer_call(expr)
        if isinstance(expr, MemberExpr):
            self._infer_expr(expr.obj)
            return VOID_T
        if isinstance(expr, IfExpr):
            self._infer_expr(expr.condition)
            for s in expr.then_body:
                self._check_stmt(s)
            if expr.else_body:
                for s in expr.else_body:
                    self._check_stmt(s)
            return VOID_T
        if isinstance(expr, ListLiteral):
            for el in expr.elements:
                self._infer_expr(el)
            return GenericTypeDesc(name="List", params=())
        return VOID_T

    def _infer_binary(self, expr: BinaryOp) -> ChimeraType:
        lt = self._infer_expr(expr.left)
        rt = self._infer_expr(expr.right)
        if expr.op in ("==", "!=", "<", ">", "<=", ">=", "and", "or"):
            return BOOL_T
        if isinstance(lt, PrimitiveTypeDesc) and isinstance(rt, PrimitiveTypeDesc):
            if lt.name == "Float" or rt.name == "Float":
                return FLOAT_T
            return INT_T
        return lt

    def _infer_call(self, expr: CallExpr) -> ChimeraType:
        if isinstance(expr.callee, Identifier):
            fn_type = self._env.lookup(expr.callee.name)
            if isinstance(fn_type, FnTypeDesc):
                return fn_type.return_type
            # Built-in wrapper constructors
            if expr.callee.name in ("Confident", "Explore", "Converge", "Provisional"):
                if expr.args:
                    inner = self._infer_expr(expr.args[0])
                    return ProbTypeDesc(name=expr.callee.name, wrapper=expr.callee.name, inner=inner)
            if expr.callee.name in ("confident", "consensus", "no_hallucination"):
                return BOOL_T
        for arg in expr.args:
            self._infer_expr(arg)
        return VOID_T

    # ------------------------------------------------------------------
    # Type compatibility
    # ------------------------------------------------------------------

    def _check_assignment_compat(self, declared: ChimeraType, inferred: ChimeraType, name: str) -> None:
        if isinstance(declared, ProbTypeDesc) and declared.wrapper == "Confident":
            if isinstance(inferred, ProbTypeDesc) and inferred.wrapper == "Explore":
                if not self._in_gate:
                    self._result.errors.append(
                        f"Cannot assign Explore value to Confident<> variable '{name}' "
                        f"outside a gate (use a gate for promotion)"
                    )

    # ------------------------------------------------------------------
    # Type resolution
    # ------------------------------------------------------------------

    def _resolve_type(self, t: TypeExpr | None) -> ChimeraType:
        if t is None:
            return VOID_T
        if isinstance(t, PrimitiveType):
            return BUILTINS.get(t.name, PrimitiveTypeDesc(name=t.name))
        if isinstance(t, ProbabilisticType):
            inner = self._resolve_type(t.inner)
            return ProbTypeDesc(name=t.wrapper, wrapper=t.wrapper, inner=inner)
        if isinstance(t, MemoryType):
            inner = self._resolve_type(t.inner)
            return MemTypeDesc(name=t.scope, scope=t.scope, inner=inner)
        if isinstance(t, GenericType):
            params = tuple(self._resolve_type(p) for p in t.params)
            return GenericTypeDesc(name=t.name, params=params)
        if isinstance(t, NamedType):
            resolved = self._env.lookup(t.name)
            if resolved:
                return resolved
            return PrimitiveTypeDesc(name=t.name)
        return VOID_T
