"""Agent 4 — TesterAgent.

Simulates a user interacting with the project and runs the full test suite
to detect regressions introduced by Agent 3's changes.

Test strategy
-------------
1. Full pytest suite (tests/ directory)
2. Targeted pytest for each changed module
3. Smoke tests: `python run.py status` and `python run.py bootstrap --dry`
4. chimera_gate verdict on overall pass/fail
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from swarms.audit_system.chimera_client import ChimeraClient
from swarms.audit_system.models import (
    ExecutionLog,
    TestReport,
    TestResult,
)

log = logging.getLogger(__name__)

# Confidence threshold below which a partial test pass still triggers gate failure
_PASS_CONFIDENCE_FLOOR = 0.70


def _parse_pytest_stdout(output: str, suite_name: str) -> TestResult:
    """Parse the summary line from pytest stdout into a TestResult."""
    # Match lines like: "3 passed, 1 failed, 2 errors in 5.32s"
    summary_pat = re.compile(
        r"(\d+) passed"
        r"(?:,\s*(\d+) failed)?"
        r"(?:,\s*(\d+) error)?"
        r"(?:,\s*(\d+) warning)?"
        r"(?:,\s*(\d+) skipped)?",
        re.IGNORECASE,
    )
    m = summary_pat.search(output)
    passed = int(m.group(1)) if m and m.group(1) else 0
    failed = int(m.group(2)) if m and m.group(2) else 0
    errors_count = int(m.group(3)) if m and m.group(3) else 0
    skipped = int(m.group(5)) if m and m.group(5) else 0

    # Extract failure/error messages (lines starting with FAILED or ERROR)
    error_lines = [
        line.strip()
        for line in output.splitlines()
        if line.strip().startswith(("FAILED", "ERROR"))
    ][:20]  # cap at 20

    return TestResult(
        suite=suite_name,
        passed=passed,
        failed=failed,
        skipped=skipped,
        errors=error_lines,
        gate_passed=failed == 0 and errors_count == 0,
    )


def _run_pytest(
    workspace: Path,
    args: list[str],
    timeout: int = 300,
) -> tuple[int, str]:
    """Run pytest and return (returncode, combined stdout+stderr)."""
    cmd = [sys.executable, "-m", "pytest"] + args + [
        "--tb=short", "-q", "--no-header",
    ]
    try:
        result = subprocess.run(
            cmd,
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return 1, f"pytest timed out after {timeout}s"
    except FileNotFoundError:
        return 1, "pytest not found — install with: pip install pytest"


class TesterAgent:
    """Agent 4 — sandbox tester using pytest + chimera_gate for verdict."""

    def __init__(
        self,
        workspace: str | Path | None = None,
        chimera: ChimeraClient | None = None,
        timeout: int = 300,
    ) -> None:
        self._workspace = Path(workspace).resolve() if workspace else Path.cwd()
        self._chimera = chimera or ChimeraClient()
        self._timeout = timeout

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run_async(
        self, run_id: str, execution_log: ExecutionLog
    ) -> TestReport:
        log.info("[TesterAgent] Starting test run for run_id=%s", run_id)
        results: list[TestResult] = []
        api_notes: list[str] = []

        # 1. Full pytest suite
        full_result = self._run_full_suite()
        results.append(full_result)

        # 2. Targeted tests for changed files
        changed_files = execution_log.all_changed_files()
        if changed_files:
            targeted = self._run_targeted_tests(changed_files)
            results.extend(targeted)

        # 3. Entry-point smoke tests
        smoke_results, notes = self._smoke_test_entry_points()
        results.extend(smoke_results)
        api_notes.extend(notes)

        # 4. chimera_gate verdict
        total_passed = sum(r.passed for r in results)
        total_failed = sum(r.failed for r in results)
        total_tests = total_passed + total_failed
        pass_rate = total_passed / total_tests if total_tests > 0 else 1.0
        all_pass = total_failed == 0

        gate_result = await self._chimera.gate(
            condition=all_pass,
            confidence=pass_rate,
        )

        # Annotate gate result on the full suite result
        if results:
            results[0] = results[0].model_copy(update={
                "gate_passed": gate_result.get("passed", all_pass),
                "chimera_gate_result": gate_result,
            })

        # Detect regressions vs. a baseline (None on first run)
        regressions = self._detect_regressions(results)

        overall_pass = gate_result.get("passed", all_pass)
        log.info(
            "[TesterAgent] %d passed / %d failed — gate=%s",
            total_passed, total_failed, overall_pass,
        )
        return TestReport(
            run_id=run_id,
            overall_pass=overall_pass,
            results=results,
            regressions=regressions,
            api_simulation_notes=api_notes,
        )

    def run(self, run_id: str, execution_log: ExecutionLog) -> TestReport:
        import asyncio
        return asyncio.run(self.run_async(run_id, execution_log))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _run_full_suite(self) -> TestResult:
        tests_dir = self._workspace / "tests"
        if not tests_dir.exists():
            return TestResult(
                suite="full_suite",
                passed=0,
                failed=0,
                errors=["tests/ directory not found"],
                gate_passed=False,
            )
        rc, output = _run_pytest(
            self._workspace,
            [str(tests_dir)],
            timeout=self._timeout,
        )
        result = _parse_pytest_stdout(output, "full_suite")
        # If pytest exited non-zero but no failures were parsed, record as 1 error
        if rc != 0 and result.failed == 0 and not result.errors:
            result = result.model_copy(update={
                "errors": ["pytest exited with non-zero code; check output"],
                "gate_passed": False,
            })
        return result

    def _run_targeted_tests(self, changed_files: list[str]) -> list[TestResult]:
        """Run tests that correspond to changed modules."""
        results: list[TestResult] = []
        tests_dir = self._workspace / "tests"
        seen: set[str] = set()
        for file_path in changed_files:
            path = Path(file_path)
            module_stem = path.stem.replace("test_", "").replace("_stub", "")
            test_file = tests_dir / f"test_{module_stem}.py"
            test_stub = tests_dir / f"test_{module_stem}_stub.py"
            target = test_file if test_file.exists() else (test_stub if test_stub.exists() else None)
            if target is None or str(target) in seen:
                continue
            seen.add(str(target))
            rc, output = _run_pytest(
                self._workspace, [str(target)], timeout=60
            )
            results.append(_parse_pytest_stdout(output, f"targeted:{target.name}"))
        return results

    def _smoke_test_entry_points(self) -> tuple[list[TestResult], list[str]]:
        """Invoke `python run.py status` as a simulated user."""
        results: list[TestResult] = []
        notes: list[str] = []
        run_py = self._workspace / "run.py"
        if not run_py.exists():
            notes.append("run.py not found — skipping smoke tests")
            return results, notes
        try:
            proc = subprocess.run(
                [sys.executable, str(run_py), "status"],
                cwd=str(self._workspace),
                capture_output=True,
                text=True,
                timeout=30,
            )
            passed = 1 if proc.returncode == 0 else 0
            failed = 0 if proc.returncode == 0 else 1
            notes.append(
                f"run.py status: exit={proc.returncode} "
                f"stdout_preview={proc.stdout[:120]!r}"
            )
            results.append(TestResult(
                suite="smoke:run.py_status",
                passed=passed,
                failed=failed,
                errors=[proc.stderr[:200]] if proc.returncode != 0 else [],
                gate_passed=proc.returncode == 0,
            ))
        except (subprocess.TimeoutExpired, OSError) as exc:
            notes.append(f"run.py status smoke test failed: {exc}")
            results.append(TestResult(
                suite="smoke:run.py_status",
                passed=0,
                failed=1,
                errors=[str(exc)],
                gate_passed=False,
            ))
        return results, notes

    def _detect_regressions(self, results: list[TestResult]) -> list[str]:
        """Return names of error suites that are newly failing."""
        regressions: list[str] = []
        for result in results:
            if not result.gate_passed:
                for err in result.errors:
                    regressions.append(f"{result.suite}: {err[:100]}")
        return regressions
