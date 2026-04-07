"""AST node definitions for ChimeraLang."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from chimera.tokens import SourceSpan


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

@dataclass
class ASTNode:
    span: SourceSpan | None = field(default=None, repr=False, kw_only=True)


# ---------------------------------------------------------------------------
# Type Expressions
# ---------------------------------------------------------------------------

@dataclass
class TypeExpr(ASTNode):
    """Base for all type expressions."""


@dataclass
class PrimitiveType(TypeExpr):
    name: str  # Int, Float, Bool, Text, Void


@dataclass
class ProbabilisticType(TypeExpr):
    """Confident<T>, Explore<T>, Converge<T>, Provisional<T>"""
    wrapper: str  # Confident | Explore | Converge | Provisional
    inner: TypeExpr


@dataclass
class MemoryType(TypeExpr):
    """Ephemeral<T>, Persistent<T>"""
    scope: str  # Ephemeral | Persistent
    inner: TypeExpr


@dataclass
class GenericType(TypeExpr):
    """List<T>, Map<K,V>, Option<T>, Result<T,E>"""
    name: str
    params: list[TypeExpr]


@dataclass
class NamedType(TypeExpr):
    """User-defined type reference."""
    name: str


# ---------------------------------------------------------------------------
# Expressions
# ---------------------------------------------------------------------------

@dataclass
class Expr(ASTNode):
    """Base for all expressions."""


@dataclass
class IntLiteral(Expr):
    value: int


@dataclass
class FloatLiteral(Expr):
    value: float


@dataclass
class StringLiteral(Expr):
    value: str


@dataclass
class BoolLiteral(Expr):
    value: bool


@dataclass
class ListLiteral(Expr):
    elements: list[Expr]


@dataclass
class Identifier(Expr):
    name: str


@dataclass
class BinaryOp(Expr):
    op: str
    left: Expr
    right: Expr


@dataclass
class UnaryOp(Expr):
    op: str
    operand: Expr


@dataclass
class CallExpr(Expr):
    callee: Expr
    args: list[Expr]


@dataclass
class MemberExpr(Expr):
    obj: Expr
    member: str


@dataclass
class IfExpr(Expr):
    condition: Expr
    then_body: list[Statement]
    else_body: list[Statement] | None = None


@dataclass
class CompareChain(Expr):
    """quality: security > performance > readability"""
    items: list[str]


# ---------------------------------------------------------------------------
# Statements
# ---------------------------------------------------------------------------

@dataclass
class Statement(ASTNode):
    """Base for all statements."""


@dataclass
class ValDecl(Statement):
    name: str
    type_ann: TypeExpr | None = None
    value: Expr | None = None


@dataclass
class ReturnStmt(Statement):
    value: Expr | None = None


@dataclass
class ExprStmt(Statement):
    expr: Expr


@dataclass
class AssertStmt(Statement):
    condition: Expr
    message: str | None = None


@dataclass
class EmitStmt(Statement):
    value: Expr


# ---------------------------------------------------------------------------
# Constraint Blocks (inside fn / gate / goal / reason)
# ---------------------------------------------------------------------------

@dataclass
class Constraint(ASTNode):
    """Base for must/allow/forbidden."""


@dataclass
class MustConstraint(Constraint):
    expr: Expr


@dataclass
class AllowConstraint(Constraint):
    capabilities: list[str]


@dataclass
class ForbiddenConstraint(Constraint):
    capabilities: list[str]


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------

@dataclass
class Param(ASTNode):
    name: str
    type_ann: TypeExpr


# ---------------------------------------------------------------------------
# Declarations
# ---------------------------------------------------------------------------

@dataclass
class Declaration(ASTNode):
    """Base for top-level declarations."""


@dataclass
class FnDecl(Declaration):
    name: str
    params: list[Param]
    return_type: TypeExpr | None = None
    constraints: list[Constraint] = field(default_factory=list)
    body: list[Statement] = field(default_factory=list)


@dataclass
class GateDecl(Declaration):
    name: str
    params: list[Param]
    return_type: TypeExpr | None = None
    branches: int = 3
    collapse: str = "majority"
    threshold: float = 0.85
    fallback: str = "escalate"
    body: list[Statement] = field(default_factory=list)


@dataclass
class GoalDecl(Declaration):
    description: str
    constraints_list: list[str] = field(default_factory=list)
    quality_axes: list[str] = field(default_factory=list)
    explore_budget: float = 1.0
    body: list[Statement] = field(default_factory=list)


@dataclass
class ReasonDecl(Declaration):
    name: str
    params: list[Param]
    return_type: TypeExpr | None = None
    given: list[str] = field(default_factory=list)
    explore_expr: Expr | None = None
    evaluate_expr: Expr | None = None
    commit_strategy: str = "highest_consensus"
    body: list[Statement] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Program (root node)
# ---------------------------------------------------------------------------

@dataclass
class Program(ASTNode):
    declarations: list[Declaration | Statement] = field(default_factory=list)
