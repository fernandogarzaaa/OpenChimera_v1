from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.benchmarks.scorecard import evaluate_scorecard

ARTIFACT_DIR = ROOT / "artifacts" / "benchmarks"
JSON_PATH = ARTIFACT_DIR / "superiority-report.json"
MD_PATH = ARTIFACT_DIR / "superiority-report.md"


BENCH_SUITES: dict[str, list[str]] = {
    "capability": [
        "tests/benchmarks/test_capability_regression.py",
    ],
    "reliability": [
        "tests/benchmarks/test_reliability_regression.py",
    ],
    "autonomy": [
        "tests/benchmarks/test_autonomy_regression.py",
    ],
}


def _run_pytest(test_path: str) -> dict[str, Any]:
    cmd = [sys.executable, "-m", "pytest", "-q", test_path]
    started = time.time()
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    elapsed = round(time.time() - started, 4)
    return {
        "test": test_path,
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "duration_seconds": elapsed,
        "stdout": proc.stdout[-2000:],
        "stderr": proc.stderr[-2000:],
    }


def _render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# OpenChimera Superiority Benchmark Report",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- overall_ok: `{report['scorecard']['overall_ok']}`",
        "",
        "## Axis Summary",
        "",
        "| Axis | Passed | Total | Pass Rate | Threshold | Meets |",
        "|---|---:|---:|---:|---:|:---:|",
    ]
    for axis, axis_data in report["scorecard"]["axes"].items():
        lines.append(
            f"| {axis} | {axis_data['passed']} | {axis_data['total']} | "
            f"{axis_data['pass_rate']:.3f} | {axis_data['thresholds']['pass_rate_min']:.2f} | "
            f"{'PASS' if axis_data['meets_threshold'] else 'FAIL'} |"
        )
    lines.append("")
    lines.append("## Detailed Results")
    lines.append("")
    for axis, results in report["results"].items():
        lines.append(f"### {axis}")
        for r in results:
            lines.append(
                f"- `{r['test']}`: {'PASS' if r['ok'] else 'FAIL'} "
                f"(duration={r['duration_seconds']:.2f}s)"
            )
    lines.append("")
    return "\n".join(lines)


def run() -> dict[str, Any]:
    axis_results: dict[str, list[dict[str, Any]]] = {}
    for axis, tests in BENCH_SUITES.items():
        axis_results[axis] = [_run_pytest(t) for t in tests]

    scorecard = evaluate_scorecard(axis_results)
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "results": axis_results,
        "scorecard": scorecard,
    }

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    JSON_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    MD_PATH.write_text(_render_markdown(report), encoding="utf-8")
    return report


def main() -> int:
    report = run()
    print(json.dumps(report["scorecard"], indent=2))
    return 0 if report["scorecard"]["overall_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
