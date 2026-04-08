from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _run(cmd: list[str]) -> int:
    proc = subprocess.run(cmd, cwd=str(ROOT))
    return proc.returncode


def main() -> int:
    steps = [
        [sys.executable, "-m", "pytest", "-q", "tests/benchmarks/test_superiority_harness.py"],
        [sys.executable, "-m", "pytest", "-q", "tests/benchmarks/test_capability_regression.py"],
        [sys.executable, "-m", "pytest", "-q", "tests/benchmarks/test_reliability_regression.py"],
        [sys.executable, "-m", "pytest", "-q", "tests/benchmarks/test_autonomy_regression.py"],
        [sys.executable, "scripts/benchmarks/run_superiority_bench.py"],
    ]
    for cmd in steps:
        code = _run(cmd)
        if code != 0:
            return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
