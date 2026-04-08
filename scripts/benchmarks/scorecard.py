from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AxisThreshold:
    pass_rate_min: float


THRESHOLDS: dict[str, AxisThreshold] = {
    "capability": AxisThreshold(pass_rate_min=0.95),
    "reliability": AxisThreshold(pass_rate_min=0.98),
    "autonomy": AxisThreshold(pass_rate_min=0.95),
}


def summarize_axis(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for r in results if bool(r.get("ok")))
    failed = total - passed
    pass_rate = (passed / total) if total else 0.0
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": round(pass_rate, 6),
    }


def evaluate_scorecard(axis_results: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    axes: dict[str, dict[str, Any]] = {}
    overall_ok = True
    for axis, results in axis_results.items():
        summary = summarize_axis(results)
        threshold = THRESHOLDS[axis]
        meets = summary["pass_rate"] >= threshold.pass_rate_min
        axes[axis] = {
            **summary,
            "thresholds": {"pass_rate_min": threshold.pass_rate_min},
            "meets_threshold": meets,
        }
        if not meets:
            overall_ok = False
    return {"overall_ok": overall_ok, "axes": axes}
