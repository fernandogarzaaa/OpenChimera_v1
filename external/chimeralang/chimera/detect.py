"""Hallucination detection for ChimeraLang.

Analyzes reasoning traces and gate branch results to detect:
- Branch divergence (branches producing wildly different results)
- Confidence anomalies (sudden drops without explanation)
- Promotion violations (Explore→Confident without gate consensus)
- Source trace gaps (values lacking provenance)
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from chimera.types import (
    ChimeraValue,
    ConfidentValue,
    ConvergeValue,
    ExploreValue,
    ProvisionalValue,
)


class HallucinationKind(Enum):
    BRANCH_DIVERGENCE = auto()     # gate branches disagree significantly
    CONFIDENCE_ANOMALY = auto()    # unexplained confidence spike/drop
    PROMOTION_VIOLATION = auto()   # Explore→Confident without gate
    SOURCE_GAP = auto()            # value has no provenance trace
    FINGERPRINT_MISMATCH = auto()  # computed fingerprint doesn't match stored


@dataclass(frozen=True, slots=True)
class HallucinationFlag:
    kind: HallucinationKind
    severity: float          # 0.0–1.0
    description: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class DetectionReport:
    flags: list[HallucinationFlag] = field(default_factory=list)
    values_scanned: int = 0
    gates_scanned: int = 0
    clean: bool = True

    def add(self, flag: HallucinationFlag) -> None:
        self.flags.append(flag)
        self.clean = False


class HallucinationDetector:
    """Scans execution results for hallucination indicators."""

    def __init__(
        self,
        divergence_threshold: float = 0.3,
        confidence_spike_threshold: float = 0.4,
    ) -> None:
        self._div_threshold = divergence_threshold
        self._spike_threshold = confidence_spike_threshold

    def scan_gate_log(
        self, gate_log: dict[str, Any], report: DetectionReport
    ) -> None:
        """Analyze a single gate execution log."""
        report.gates_scanned += 1
        confidences: list[float] = gate_log.get("branch_confidences", [])
        if not confidences:
            return

        # Branch divergence: check spread of branch confidences
        max_c = max(confidences)
        min_c = min(confidences)
        spread = max_c - min_c
        if spread > self._div_threshold:
            report.add(HallucinationFlag(
                kind=HallucinationKind.BRANCH_DIVERGENCE,
                severity=min(spread, 1.0),
                description=(
                    f"Gate '{gate_log['gate']}' branches diverged: "
                    f"spread={spread:.3f} (threshold={self._div_threshold})"
                ),
                evidence={
                    "gate": gate_log["gate"],
                    "confidences": confidences,
                    "spread": spread,
                },
            ))

        # Confidence anomaly: result confidence much higher than average branch
        avg_branch = sum(confidences) / len(confidences)
        result_conf: float = gate_log.get("result_confidence", 0.0)
        spike = result_conf - avg_branch
        if spike > self._spike_threshold:
            report.add(HallucinationFlag(
                kind=HallucinationKind.CONFIDENCE_ANOMALY,
                severity=min(spike, 1.0),
                description=(
                    f"Gate '{gate_log['gate']}' result confidence ({result_conf:.3f}) "
                    f"is suspiciously higher than branch average ({avg_branch:.3f})"
                ),
                evidence={
                    "gate": gate_log["gate"],
                    "result_confidence": result_conf,
                    "avg_branch_confidence": avg_branch,
                    "spike": spike,
                },
            ))

    def scan_value(self, value: ChimeraValue, report: DetectionReport) -> None:
        """Analyze a single runtime value for hallucination indicators."""
        report.values_scanned += 1

        # Source gap: no trace at all
        if not value.trace:
            report.add(HallucinationFlag(
                kind=HallucinationKind.SOURCE_GAP,
                severity=0.5,
                description=f"Value '{value.raw}' has no provenance trace",
                evidence={"raw": value.raw, "confidence": value.confidence.value},
            ))

        # Promotion violation: ConfidentValue with low source confidence
        if isinstance(value, ConfidentValue):
            if value.confidence.source == "Explore_constructor":
                report.add(HallucinationFlag(
                    kind=HallucinationKind.PROMOTION_VIOLATION,
                    severity=0.9,
                    description="Confident value was created from Explore source",
                    evidence={"raw": value.raw, "source": value.confidence.source},
                ))

        # Fingerprint integrity
        data = f"{type(value.raw).__name__}:{value.raw}:{value.confidence.value}"
        expected_fp = hashlib.sha256(data.encode()).hexdigest()[:16]
        if value.fingerprint and value.fingerprint != expected_fp:
            report.add(HallucinationFlag(
                kind=HallucinationKind.FINGERPRINT_MISMATCH,
                severity=0.8,
                description=f"Value fingerprint mismatch (stored: {value.fingerprint})",
                evidence={
                    "stored": value.fingerprint,
                    "computed": expected_fp,
                },
            ))

    def full_scan(
        self,
        gate_logs: list[dict[str, Any]],
        emitted_values: list[ChimeraValue],
    ) -> DetectionReport:
        """Run a complete hallucination scan over an execution result."""
        report = DetectionReport()
        for gl in gate_logs:
            self.scan_gate_log(gl, report)
        for val in emitted_values:
            self.scan_value(val, report)
        return report
