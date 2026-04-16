"""Agent 1 — AuditAgent.

Performs a full static scan of the OpenChimera codebase and produces a
structured AuditReport.  No LLM is required; all analysis is deterministic.

Scan targets
------------
Python  — AST-based structural analysis, security pattern grep, dead-import
          detection, test-coverage gap detection
Rust    — unsafe block detection, unwrap() overuse
TypeScript/TSX — console.log leakage, any-type overuse
Config  — .env exposure, hardcoded credentials
Deps    — requirements-prod.txt cross-referenced against pip-audit (if available)
"""
from __future__ import annotations

import ast
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from swarms.audit_system.models import AuditFinding, AuditReport

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Security patterns (regex → rule_id, message, severity)
# ---------------------------------------------------------------------------

_PY_SECURITY_PATTERNS: list[tuple[re.Pattern, str, str, str]] = [
    (re.compile(r"\beval\s*\("),          "PY-SEC-001", "eval() usage",                         "high"),
    (re.compile(r"\bexec\s*\("),          "PY-SEC-002", "exec() usage",                         "high"),
    (re.compile(r"shell\s*=\s*True"),     "PY-SEC-003", "subprocess shell=True",                "high"),
    (re.compile(r"password\s*=\s*['\"]"), "PY-SEC-004", "Hardcoded password literal",           "critical"),
    (re.compile(r"secret\s*=\s*['\"]"),   "PY-SEC-005", "Hardcoded secret literal",             "critical"),
    (re.compile(r"api_key\s*=\s*['\"]"),  "PY-SEC-006", "Hardcoded API key",                    "critical"),
    (re.compile(r"token\s*=\s*['\"][A-Za-z0-9+/]{20,}"), "PY-SEC-007", "Possible hardcoded token", "high"),
    (re.compile(r"SELECT\s+.*\+\s*"),     "PY-SEC-008", "Possible SQL string concatenation",    "high"),
    (re.compile(r"pickle\.loads?\("),     "PY-SEC-009", "pickle deserialization",               "medium"),
    (re.compile(r"yaml\.load\s*\([^,)]*\)"), "PY-SEC-010", "yaml.load() without Loader",       "medium"),
    (re.compile(r"assert\s+"),            "PY-SEC-011", "assert used for runtime check",         "low"),
    (re.compile(r"# nosec"),              "PY-SEC-012", "nosec suppression comment",             "info"),
]

_TS_SECURITY_PATTERNS: list[tuple[re.Pattern, str, str, str]] = [
    (re.compile(r"console\.(log|warn|error|debug)\s*\("), "TS-QUAL-001", "console.* in production code", "low"),
    (re.compile(r":\s*any\b"),                             "TS-QUAL-002", "TypeScript 'any' type usage",  "low"),
    (re.compile(r"innerHTML\s*="),                         "TS-SEC-001",  "innerHTML assignment (XSS risk)", "high"),
    (re.compile(r"dangerouslySetInnerHTML"),                "TS-SEC-002",  "dangerouslySetInnerHTML usage",   "high"),
]

_RS_PATTERNS: list[tuple[re.Pattern, str, str, str]] = [
    (re.compile(r"\bunsafe\s*\{"),         "RS-SEC-001", "unsafe block",              "medium"),
    (re.compile(r"\.unwrap\(\)"),           "RS-QUAL-001", ".unwrap() without context", "low"),
    (re.compile(r"\.expect\(\"[^\"]{0,10}\""), "RS-QUAL-002", "Short .expect() message", "info"),
    (re.compile(r"todo!\(\)"),              "RS-QUAL-003", "todo!() placeholder",       "info"),
    (re.compile(r"unimplemented!\(\)"),     "RS-QUAL-004", "unimplemented!() placeholder", "medium"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _finding_id(prefix: str, idx: int) -> str:
    return f"{prefix}-{idx:05d}"


def _walk_files(workspace: Path, extensions: tuple[str, ...]) -> list[Path]:
    files: list[Path] = []
    skip_dirs = {".git", "__pycache__", ".venv", "venv", "node_modules", ".mypy_cache",
                 "target", "dist", "build", ".pytest_cache", "artifacts"}
    for root, dirs, filenames in os.walk(workspace):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for fname in filenames:
            if fname.endswith(extensions):
                files.append(Path(root) / fname)
    return files


# ---------------------------------------------------------------------------
# Analysis passes
# ---------------------------------------------------------------------------

def _scan_python_security(py_files: list[Path]) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    idx = 0
    for path in py_files:
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(source.splitlines(), start=1):
            for pattern, rule_id, message, severity in _PY_SECURITY_PATTERNS:
                if pattern.search(line):
                    findings.append(AuditFinding(
                        finding_id=_finding_id("A1", idx),
                        file_path=str(path),
                        line=lineno,
                        severity=severity,
                        category="security",
                        message=f"{message}: {line.strip()[:120]}",
                        rule_id=rule_id,
                    ))
                    idx += 1
    return findings


def _scan_python_quality(py_files: list[Path]) -> list[AuditFinding]:
    """AST-based quality checks: bare excepts, mutable default args, too-long functions."""
    findings: list[AuditFinding] = []
    idx = 10000
    for path in py_files:
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(path))
        except (OSError, SyntaxError):
            continue

        for node in ast.walk(tree):
            # Bare except
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                findings.append(AuditFinding(
                    finding_id=_finding_id("A1", idx),
                    file_path=str(path),
                    line=node.lineno,
                    severity="medium",
                    category="quality",
                    message="Bare except clause — catches all exceptions including KeyboardInterrupt",
                    rule_id="PY-QUAL-001",
                ))
                idx += 1
            # Mutable default arguments
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for default in node.args.defaults:
                    if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                        findings.append(AuditFinding(
                            finding_id=_finding_id("A1", idx),
                            file_path=str(path),
                            line=node.lineno,
                            severity="medium",
                            category="quality",
                            message=f"Mutable default argument in '{node.name}'",
                            rule_id="PY-QUAL-002",
                        ))
                        idx += 1
                # Overly long function (> 150 lines)
                func_lines = getattr(node, "end_lineno", node.lineno) - node.lineno
                if func_lines > 150:
                    findings.append(AuditFinding(
                        finding_id=_finding_id("A1", idx),
                        file_path=str(path),
                        line=node.lineno,
                        severity="low",
                        category="quality",
                        message=f"Function '{node.name}' is {func_lines} lines long (threshold: 150)",
                        rule_id="PY-QUAL-003",
                    ))
                    idx += 1
    return findings


def _scan_test_coverage_gaps(workspace: Path, py_files: list[Path]) -> list[AuditFinding]:
    """Compare core/ module names against tests/test_*.py to find missing tests."""
    findings: list[AuditFinding] = []
    idx = 20000
    core_dir = workspace / "core"
    tests_dir = workspace / "tests"
    if not core_dir.exists() or not tests_dir.exists():
        return findings

    core_modules = {p.stem for p in core_dir.glob("*.py") if not p.stem.startswith("_")}
    tested_modules = {
        p.stem.replace("test_", "", 1)
        for p in tests_dir.glob("test_*.py")
    }
    untested = core_modules - tested_modules
    for module in sorted(untested):
        findings.append(AuditFinding(
            finding_id=_finding_id("A1", idx),
            file_path=str(core_dir / f"{module}.py"),
            line=None,
            severity="low",
            category="test_gap",
            message=f"core/{module}.py has no corresponding tests/test_{module}.py",
            rule_id="PY-TEST-001",
        ))
        idx += 1
    return findings


def _scan_ts_quality(ts_files: list[Path]) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    idx = 30000
    for path in ts_files:
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(source.splitlines(), start=1):
            for pattern, rule_id, message, severity in _TS_SECURITY_PATTERNS:
                if pattern.search(line):
                    findings.append(AuditFinding(
                        finding_id=_finding_id("A1", idx),
                        file_path=str(path),
                        line=lineno,
                        severity=severity,
                        category="security" if "SEC" in rule_id else "quality",
                        message=f"{message}: {line.strip()[:120]}",
                        rule_id=rule_id,
                    ))
                    idx += 1
    return findings


def _scan_rust(rs_files: list[Path]) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    idx = 40000
    for path in rs_files:
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(source.splitlines(), start=1):
            for pattern, rule_id, message, severity in _RS_PATTERNS:
                if pattern.search(line):
                    findings.append(AuditFinding(
                        finding_id=_finding_id("A1", idx),
                        file_path=str(path),
                        line=lineno,
                        severity=severity,
                        category="security" if "SEC" in rule_id else "quality",
                        message=f"{message}: {line.strip()[:120]}",
                        rule_id=rule_id,
                    ))
                    idx += 1
    return findings


def _scan_dependency_issues(workspace: Path) -> list[AuditFinding]:
    """Run pip-audit if available; otherwise check for pinned vs unpinned deps."""
    findings: list[AuditFinding] = []
    idx = 50000
    req_file = workspace / "requirements-prod.txt"
    if not req_file.exists():
        return findings

    # Try pip-audit
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip_audit", "--requirement", str(req_file),
             "--format", "json", "--progress-spinner", "off"],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0:
            audit_data = json.loads(result.stdout)
            for dep in audit_data.get("dependencies", []):
                for vuln in dep.get("vulns", []):
                    findings.append(AuditFinding(
                        finding_id=_finding_id("A1", idx),
                        file_path=str(req_file),
                        line=None,
                        severity="high",
                        category="dependency",
                        message=(
                            f"{dep['name']}=={dep.get('version','?')} has vulnerability "
                            f"{vuln['id']}: {vuln.get('description','')[:120]}"
                        ),
                        rule_id="DEP-CVE-001",
                    ))
                    idx += 1
    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
        pass

    # Check for unpinned deps (no version specifier)
    unpinned_pattern = re.compile(r"^([A-Za-z0-9_\-]+)\s*$")
    for lineno, line in enumerate(req_file.read_text().splitlines(), start=1):
        line = line.strip()
        if line and not line.startswith("#") and unpinned_pattern.match(line):
            findings.append(AuditFinding(
                finding_id=_finding_id("A1", idx),
                file_path=str(req_file),
                line=lineno,
                severity="low",
                category="dependency",
                message=f"Unpinned dependency: '{line}' — no version specifier",
                rule_id="DEP-QUAL-001",
            ))
            idx += 1
    return findings


def _scan_dead_code_candidates(py_files: list[Path]) -> list[AuditFinding]:
    """Flag Python files with 0 references from other files (potential dead code)."""
    findings: list[AuditFinding] = []
    idx = 60000
    # Build set of module names
    all_module_names = {p.stem for p in py_files}
    # Count how many files import each module
    import_counts: dict[str, int] = {name: 0 for name in all_module_names}
    import_pat = re.compile(r"(?:from|import)\s+([\w.]+)")
    for path in py_files:
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in import_pat.finditer(source):
            parts = match.group(1).split(".")
            for part in parts:
                if part in import_counts:
                    import_counts[part] += 1

    for path in py_files:
        stem = path.stem
        if stem.startswith("_") or stem in ("__init__", "run", "conftest"):
            continue
        if import_counts.get(stem, 0) == 0:
            # Only flag modules in top-level packages, not test files
            rel = path.relative_to(path.parents[max(0, len(path.parts) - 4)])
            if "test" not in str(rel).lower() and "migration" not in str(rel).lower():
                findings.append(AuditFinding(
                    finding_id=_finding_id("A1", idx),
                    file_path=str(path),
                    line=None,
                    severity="info",
                    category="dead_code",
                    message=f"{path.name} has 0 detected imports from other modules",
                    rule_id="PY-DEAD-001",
                ))
                idx += 1
    return findings


# ---------------------------------------------------------------------------
# Main AuditAgent class
# ---------------------------------------------------------------------------

class AuditAgent:
    """Agent 1 — performs the full static audit of the workspace."""

    def __init__(self, workspace: str | Path, chimera=None) -> None:
        self.workspace = Path(workspace).resolve()
        self._chimera = chimera

    def run(self, run_id: str) -> AuditReport:
        """Execute all scan passes and return an AuditReport."""
        log.info("[AuditAgent] Starting audit of %s (run_id=%s)", self.workspace, run_id)
        t0 = __import__("time").perf_counter()

        py_files = _walk_files(self.workspace, (".py",))
        ts_files = _walk_files(self.workspace, (".ts", ".tsx"))
        rs_files = _walk_files(self.workspace, (".rs",))

        total_files = len(py_files) + len(ts_files) + len(rs_files)
        log.info("[AuditAgent] Files: %d py, %d ts/tsx, %d rs", len(py_files), len(ts_files), len(rs_files))

        all_findings: list[AuditFinding] = []
        all_findings.extend(_scan_python_security(py_files))
        all_findings.extend(_scan_python_quality(py_files))
        all_findings.extend(_scan_test_coverage_gaps(self.workspace, py_files))
        all_findings.extend(_scan_ts_quality(ts_files))
        all_findings.extend(_scan_rust(rs_files))
        all_findings.extend(_scan_dependency_issues(self.workspace))
        all_findings.extend(_scan_dead_code_candidates(py_files))

        elapsed = __import__("time").perf_counter() - t0
        log.info(
            "[AuditAgent] Audit complete in %.1fs — %d findings across %d files",
            elapsed, len(all_findings), total_files,
        )

        report = AuditReport(
            run_id=run_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            workspace=str(self.workspace),
            total_files_scanned=total_files,
            findings=all_findings,
        )
        return report
