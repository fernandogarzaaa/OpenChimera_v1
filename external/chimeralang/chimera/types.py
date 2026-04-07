"""Probabilistic type system for ChimeraLang.

Defines the runtime type wrappers and confidence propagation.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, TypeVar

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Confidence & Memory
# ---------------------------------------------------------------------------

class ConfidenceLevel(Enum):
    """Semantic confidence tiers (not arbitrary floats)."""
    HIGH = auto()       # >= 0.95 — "Confident"
    MEDIUM = auto()     # 0.5 – 0.95 — explorable range
    LOW = auto()        # < 0.5 — very uncertain
    UNKNOWN = auto()    # no confidence info


class MemoryScope(Enum):
    EPHEMERAL = auto()    # dies when scope exits
    PERSISTENT = auto()   # survives across executions
    PROVISIONAL = auto()  # held until contradicted


@dataclass(slots=True)
class Confidence:
    """Numerical confidence with a source trace."""
    value: float
    source: str = "inferred"
    timestamp: float = field(default_factory=time.time)

    @property
    def level(self) -> ConfidenceLevel:
        if self.value >= 0.95:
            return ConfidenceLevel.HIGH
        if self.value >= 0.5:
            return ConfidenceLevel.MEDIUM
        if self.value > 0.0:
            return ConfidenceLevel.LOW
        return ConfidenceLevel.UNKNOWN

    def combine(self, other: Confidence) -> Confidence:
        """Weighted combination for consensus."""
        avg = (self.value + other.value) / 2.0
        return Confidence(value=avg, source=f"combined({self.source},{other.source})")


# ---------------------------------------------------------------------------
# Probabilistic value wrappers
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ChimeraValue:
    """Base for all ChimeraLang runtime values."""
    raw: Any
    confidence: Confidence
    memory_scope: MemoryScope = MemoryScope.EPHEMERAL
    trace: list[str] = field(default_factory=list)
    _fingerprint: str = field(default="", init=False, repr=False)

    def __post_init__(self) -> None:
        self._fingerprint = self._compute_fingerprint()

    def _compute_fingerprint(self) -> str:
        data = f"{type(self.raw).__name__}:{self.raw}:{self.confidence.value}"
        return hashlib.sha256(data.encode()).hexdigest()[:16]

    @property
    def fingerprint(self) -> str:
        return self._fingerprint


@dataclass(slots=True)
class ConfidentValue(ChimeraValue):
    """Value with >= 0.95 confidence. Assertion fails on creation if below."""
    def __post_init__(self) -> None:
        if self.confidence.value < 0.95:
            raise ConfidenceViolation(
                f"Confident<> requires confidence >= 0.95, got {self.confidence.value}"
            )
        super().__post_init__()


@dataclass(slots=True)
class ExploreValue(ChimeraValue):
    """Value in exploration space — hallucination explicitly allowed."""
    exploration_budget: float = 1.0


@dataclass(slots=True)
class ConvergeValue(ChimeraValue):
    """Value requiring multi-branch consensus."""
    branch_values: list[ChimeraValue] = field(default_factory=list)
    consensus_method: str = "majority"


@dataclass(slots=True)
class ProvisionalValue(ChimeraValue):
    """Revocable value — valid until contradicted."""
    revoked: bool = False

    def revoke(self) -> ProvisionalValue:
        return ProvisionalValue(
            raw=self.raw,
            confidence=Confidence(0.0, "revoked"),
            memory_scope=self.memory_scope,
            trace=[*self.trace, "REVOKED"],
            revoked=True,
        )


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ConfidenceViolation(Exception):
    """Raised when a confidence boundary is violated."""


class TypeMismatch(Exception):
    """Raised when static type check fails."""


class PromotionViolation(Exception):
    """Raised when an unsafe promotion (Explore -> Confident) is attempted."""


# ---------------------------------------------------------------------------
# Type descriptors (for static checking)
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ChimeraType:
    """Base type descriptor."""
    name: str


@dataclass(frozen=True, slots=True)
class PrimitiveTypeDesc(ChimeraType):
    """Int, Float, Bool, Text, Void."""


@dataclass(frozen=True, slots=True)
class ProbTypeDesc(ChimeraType):
    """Confident<T>, Explore<T>, Converge<T>, Provisional<T>."""
    wrapper: str
    inner: ChimeraType


@dataclass(frozen=True, slots=True)
class MemTypeDesc(ChimeraType):
    """Ephemeral<T>, Persistent<T>."""
    scope: str
    inner: ChimeraType


@dataclass(frozen=True, slots=True)
class GenericTypeDesc(ChimeraType):
    """List<T>, Map<K,V>, etc."""
    params: tuple[ChimeraType, ...]


@dataclass(frozen=True, slots=True)
class FnTypeDesc(ChimeraType):
    """Function signature type."""
    param_types: tuple[ChimeraType, ...]
    return_type: ChimeraType


# ---------------------------------------------------------------------------
# Built-in type singletons
# ---------------------------------------------------------------------------

INT_T = PrimitiveTypeDesc(name="Int")
FLOAT_T = PrimitiveTypeDesc(name="Float")
BOOL_T = PrimitiveTypeDesc(name="Bool")
TEXT_T = PrimitiveTypeDesc(name="Text")
VOID_T = PrimitiveTypeDesc(name="Void")

BUILTINS: dict[str, ChimeraType] = {
    "Int": INT_T,
    "Float": FLOAT_T,
    "Bool": BOOL_T,
    "Text": TEXT_T,
    "Void": VOID_T,
}
