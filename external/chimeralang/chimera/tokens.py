"""Token definitions for ChimeraLang."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto


class TokenKind(Enum):
    # Literals
    INT_LIT = auto()
    FLOAT_LIT = auto()
    STRING_LIT = auto()
    BOOL_LIT = auto()

    # Identifiers
    IDENT = auto()

    # Keywords — language
    VAL = auto()
    FN = auto()
    GATE = auto()
    GOAL = auto()
    REASON = auto()
    ABOUT = auto()
    END = auto()
    RETURN = auto()
    IF = auto()
    ELSE = auto()
    MATCH = auto()
    FOR = auto()
    IN = auto()
    ASSERT = auto()
    EMIT = auto()

    # Keywords — constraint
    MUST = auto()
    ALLOW = auto()
    FORBIDDEN = auto()
    GIVEN = auto()
    EXPLORE = auto()
    EVALUATE = auto()
    COMMIT = auto()

    # Keywords — gate config
    BRANCHES = auto()
    COLLAPSE = auto()
    THRESHOLD = auto()
    FALLBACK = auto()
    CONSTRAINTS = auto()
    QUALITY = auto()
    EXPLORE_BUDGET = auto()

    # Keywords — collapse strategies
    MAJORITY = auto()
    WEIGHTED_VOTE = auto()
    HIGHEST_CONFIDENCE = auto()
    ESCALATE = auto()

    # Keywords — probabilistic types
    CONFIDENT = auto()
    EXPLORE_TYPE = auto()  # 'Explore' as a type
    CONVERGE = auto()
    PROVISIONAL = auto()
    EPHEMERAL = auto()
    PERSISTENT = auto()

    # Keywords — primitive types
    INT_TYPE = auto()
    FLOAT_TYPE = auto()
    BOOL_TYPE = auto()
    TEXT_TYPE = auto()
    VOID_TYPE = auto()
    LIST_TYPE = auto()
    MAP_TYPE = auto()
    OPTION_TYPE = auto()
    RESULT_TYPE = auto()

    # Operators
    PLUS = auto()
    MINUS = auto()
    STAR = auto()
    SLASH = auto()
    PERCENT = auto()
    EQ = auto()
    NEQ = auto()
    LT = auto()
    GT = auto()
    LTE = auto()
    GTE = auto()
    AND = auto()
    OR = auto()
    NOT = auto()
    ASSIGN = auto()
    ARROW = auto()       # ->
    FAT_ARROW = auto()   # =>

    # Delimiters
    LPAREN = auto()
    RPAREN = auto()
    LBRACKET = auto()
    RBRACKET = auto()
    LBRACE = auto()
    RBRACE = auto()
    COMMA = auto()
    COLON = auto()
    DOT = auto()
    PIPE = auto()

    # Special
    NEWLINE = auto()
    EOF = auto()


@dataclass(frozen=True, slots=True)
class SourceSpan:
    """Location in source code."""
    line: int
    col: int
    offset: int
    length: int
    file: str = "<stdin>"


@dataclass(frozen=True, slots=True)
class Token:
    kind: TokenKind
    value: str
    span: SourceSpan

    def __repr__(self) -> str:
        return f"Token({self.kind.name}, {self.value!r}, L{self.span.line}:{self.span.col})"


# Keyword lookup table
KEYWORDS: dict[str, TokenKind] = {
    "val": TokenKind.VAL,
    "fn": TokenKind.FN,
    "gate": TokenKind.GATE,
    "goal": TokenKind.GOAL,
    "reason": TokenKind.REASON,
    "about": TokenKind.ABOUT,
    "end": TokenKind.END,
    "return": TokenKind.RETURN,
    "if": TokenKind.IF,
    "else": TokenKind.ELSE,
    "match": TokenKind.MATCH,
    "for": TokenKind.FOR,
    "in": TokenKind.IN,
    "assert": TokenKind.ASSERT,
    "emit": TokenKind.EMIT,
    "must": TokenKind.MUST,
    "allow": TokenKind.ALLOW,
    "forbidden": TokenKind.FORBIDDEN,
    "given": TokenKind.GIVEN,
    "explore": TokenKind.EXPLORE,
    "evaluate": TokenKind.EVALUATE,
    "commit": TokenKind.COMMIT,
    "branches": TokenKind.BRANCHES,
    "collapse": TokenKind.COLLAPSE,
    "threshold": TokenKind.THRESHOLD,
    "fallback": TokenKind.FALLBACK,
    "constraints": TokenKind.CONSTRAINTS,
    "quality": TokenKind.QUALITY,
    "explore_budget": TokenKind.EXPLORE_BUDGET,
    "majority": TokenKind.MAJORITY,
    "weighted_vote": TokenKind.WEIGHTED_VOTE,
    "highest_confidence": TokenKind.HIGHEST_CONFIDENCE,
    "escalate": TokenKind.ESCALATE,
    "true": TokenKind.BOOL_LIT,
    "false": TokenKind.BOOL_LIT,
    "and": TokenKind.AND,
    "or": TokenKind.OR,
    "not": TokenKind.NOT,
    # Probabilistic type keywords
    "Confident": TokenKind.CONFIDENT,
    "Explore": TokenKind.EXPLORE_TYPE,
    "Converge": TokenKind.CONVERGE,
    "Provisional": TokenKind.PROVISIONAL,
    "Ephemeral": TokenKind.EPHEMERAL,
    "Persistent": TokenKind.PERSISTENT,
    # Primitive type keywords
    "Int": TokenKind.INT_TYPE,
    "Float": TokenKind.FLOAT_TYPE,
    "Bool": TokenKind.BOOL_TYPE,
    "Text": TokenKind.TEXT_TYPE,
    "Void": TokenKind.VOID_TYPE,
    "List": TokenKind.LIST_TYPE,
    "Map": TokenKind.MAP_TYPE,
    "Option": TokenKind.OPTION_TYPE,
    "Result": TokenKind.RESULT_TYPE,
}
