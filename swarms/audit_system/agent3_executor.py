"""Agent 3 — ExecutorAgent.

Applies the RecommendationSet produced by Agent 2 as actual code changes.

Every change is:
  1. Validated against safety constraints via chimera_constrain before writing
  2. Given a cryptographic integrity proof via chimera_prove after writing
  3. Logged in the ExecutionLog with status applied/skipped/failed

Safety constraints enforced:
  - Never delete test files
  - Never modify config/runtime_profile.json
  - Never write outside the workspace root
  - Dry-run pass: describe changes without writing (default)
"""
from __future__ import annotations

import ast
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from core.transactions import atomic_write_text
from swarms.audit_system.chimera_client import ChimeraClient
from swarms.audit_system.models import (
    ExecutionLog,
    ExecutionRecord,
    Recommendation,
    RecommendationSet,
)

log = logging.getLogger(__name__)

# Files / directories that the executor must never modify
_PROTECTED_PATHS: set[str] = {
    "config/runtime_profile.json",
    ".env",
    ".mcp.json",
}

# Category label → handler method name
_ACTION_HANDLERS = {
    "fix": "_apply_security_fix",
    "refactor": "_apply_refactor",
    "delete": "_apply_dead_code_removal",
    "add_test": "_generate_test_stub",
    "update_dep": "_update_dependency",
}


class ExecutorAgent:
    """Agent 3 — applies recommendations as code changes under chimera governance."""

    def __init__(
        self,
        workspace: str | Path | None = None,
        chimera: ChimeraClient | None = None,
        dry_run: bool = True,
    ) -> None:
        self._workspace = Path(workspace).resolve() if workspace else Path.cwd()
        self._chimera = chimera or ChimeraClient()
        self._dry_run = dry_run

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run_async(
        self, run_id: str, rec_set: RecommendationSet
    ) -> ExecutionLog:
        log.info(
            "[ExecutorAgent] Executing %d recommendations (dry_run=%s, run_id=%s)",
            len(rec_set.recommendations), self._dry_run, run_id,
        )
        records: list[ExecutionRecord] = []
        for rec in rec_set.by_priority():
            record = await self._process_recommendation(rec)
            records.append(record)

        return ExecutionLog(run_id=run_id, records=records)

    def run(self, run_id: str, rec_set: RecommendationSet) -> ExecutionLog:
        import asyncio
        return asyncio.run(self.run_async(run_id, rec_set))

    # ------------------------------------------------------------------
    # Recommendation processing
    # ------------------------------------------------------------------

    async def _process_recommendation(self, rec: Recommendation) -> ExecutionRecord:
        """Apply a single recommendation with chimera governance."""
        # 1. Safety constraint check before touching any files
        constrain_result = await self._chimera.constrain(
            value=rec.model_dump_json(),
            constraints=[
                "no modification of protected config files",
                "no changes outside workspace root",
                "test files must not be deleted",
            ],
        )
        if not constrain_result.get("satisfied", True):
            violations = constrain_result.get("violations", [])
            log.warning("[ExecutorAgent] Rec %s failed constraint: %s", rec.rec_id, violations)
            return ExecutionRecord(
                recommendation_id=rec.rec_id,
                status="skipped",
                chimera_constrain_result=constrain_result,
                skip_reason=f"Constraint violation: {'; '.join(violations)}",
            )

        # 2. Check against static protected path list
        for af in rec.affected_files:
            rel = Path(af).name
            if any(af.endswith(p) for p in _PROTECTED_PATHS):
                return ExecutionRecord(
                    recommendation_id=rec.rec_id,
                    status="skipped",
                    skip_reason=f"Protected file: {af}",
                )

        # 3. Dispatch to the right handler
        handler_name = _ACTION_HANDLERS.get(rec.action, "_apply_generic")
        handler = getattr(self, handler_name, self._apply_generic)
        try:
            files_changed, diff_summary = await handler(rec)
        except Exception as exc:
            log.error("[ExecutorAgent] Rec %s handler failed: %s", rec.rec_id, exc)
            return ExecutionRecord(
                recommendation_id=rec.rec_id,
                status="failed",
                diff_summary=str(exc),
            )

        # 4. Generate integrity proof for the applied change
        proof_content = f"run:{rec.rec_id}::files:{','.join(files_changed)}::diff:{diff_summary}"
        prove_result = await self._chimera.prove(proof_content)

        return ExecutionRecord(
            recommendation_id=rec.rec_id,
            status="applied" if not self._dry_run else "skipped",
            files_changed=files_changed,
            diff_summary=diff_summary,
            integrity_proof=prove_result.get("proof"),
            chimera_prove_result=prove_result,
            chimera_constrain_result=constrain_result,
            skip_reason="dry_run=True — change described but not written" if self._dry_run else None,
        )

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    async def _apply_security_fix(self, rec: Recommendation) -> tuple[list[str], str]:
        """Replace hardcoded secrets with os.getenv() calls."""
        files_changed: list[str] = []
        diffs: list[str] = []
        secret_patterns = [
            (re.compile(r'(password\s*=\s*)["\']([^"\']+)["\']'), r'\1os.getenv("PASSWORD", "")'),
            (re.compile(r'(api_key\s*=\s*)["\']([^"\']+)["\']'),  r'\1os.getenv("API_KEY", "")'),
            (re.compile(r'(secret\s*=\s*)["\']([^"\']+)["\']'),   r'\1os.getenv("SECRET", "")'),
            (re.compile(r'(token\s*=\s*)["\']([A-Za-z0-9+/]{20,})["\']'), r'\1os.getenv("TOKEN", "")'),
        ]
        for file_path in rec.affected_files:
            path = Path(file_path)
            if not path.exists() or path.suffix != ".py":
                continue
            original = path.read_text(encoding="utf-8", errors="replace")
            patched = original
            for pattern, replacement in secret_patterns:
                patched = pattern.sub(replacement, patched)
            if patched != original:
                diffs.append(f"Replaced hardcoded credential in {path.name}")
                if not self._dry_run:
                    # Ensure os is imported
                    if "import os" not in patched:
                        patched = "import os\n" + patched
                    atomic_write_text(path, patched)
                files_changed.append(file_path)
        return files_changed, "; ".join(diffs) or "No applicable changes found"

    async def _apply_refactor(self, rec: Recommendation) -> tuple[list[str], str]:
        """Refactoring — currently handles bare except → except Exception."""
        files_changed: list[str] = []
        diffs: list[str] = []
        bare_except = re.compile(r"^(\s*)except\s*:", re.MULTILINE)
        for file_path in rec.affected_files:
            path = Path(file_path)
            if not path.exists() or path.suffix != ".py":
                continue
            original = path.read_text(encoding="utf-8", errors="replace")
            patched = bare_except.sub(r"\1except Exception:", original)
            if patched != original:
                count = len(bare_except.findall(original))
                diffs.append(f"Replaced {count} bare except(s) in {path.name}")
                if not self._dry_run:
                    atomic_write_text(path, patched)
                files_changed.append(file_path)
        return files_changed, "; ".join(diffs) or "No refactoring applied"

    async def _apply_dead_code_removal(self, rec: Recommendation) -> tuple[list[str], str]:
        """Flag dead code — does not auto-delete; generates a comment marker."""
        files_changed: list[str] = []
        diffs: list[str] = []
        for file_path in rec.affected_files:
            path = Path(file_path)
            if not path.exists():
                continue
            diffs.append(f"[DEAD_CODE_CANDIDATE] {path.name} — manual review recommended")
            # Dry-run friendly: we only annotate, never auto-delete
        return files_changed, "; ".join(diffs) or "No dead code removal performed"

    async def _generate_test_stub(self, rec: Recommendation) -> tuple[list[str], str]:
        """Generate a minimal pytest stub for untested modules."""
        files_changed: list[str] = []
        diffs: list[str] = []
        tests_dir = self._workspace / "tests"
        tests_dir.mkdir(exist_ok=True)
        for file_path in rec.affected_files:
            path = Path(file_path)
            if path.suffix != ".py":
                continue
            module_name = path.stem
            # Determine import path relative to workspace
            try:
                rel = path.relative_to(self._workspace)
                import_path = str(rel.with_suffix("")).replace("/", ".").replace("\\", ".")
            except ValueError:
                import_path = module_name
            stub_path = tests_dir / f"test_{module_name}_stub.py"
            if stub_path.exists():
                continue
            stub = (
                f'"""Auto-generated stub by audit system — replace with real tests."""\n'
                f"import pytest\n\n"
                f"def test_{module_name}_imports():\n"
                f"    \"\"\"Verify the module imports without error.\"\"\"\n"
                f"    import importlib\n"
                f"    importlib.import_module(\"{import_path}\")\n\n"
                f"def test_{module_name}_placeholder():\n"
                f"    \"\"\"Placeholder — implement real test coverage here.\"\"\"\n"
                f"    pytest.skip(\"Not yet implemented\")\n"
            )
            diffs.append(f"Generated test stub: {stub_path.name}")
            if not self._dry_run:
                atomic_write_text(stub_path, stub)
            files_changed.append(str(stub_path))
        return files_changed, "; ".join(diffs) or "No test stubs generated"

    async def _update_dependency(self, rec: Recommendation) -> tuple[list[str], str]:
        """Pin unpinned dependencies to their currently installed version."""
        files_changed: list[str] = []
        diffs: list[str] = []
        import importlib.metadata as im

        req_file = self._workspace / "requirements-prod.txt"
        if not req_file.exists():
            return [], "requirements-prod.txt not found"

        lines = req_file.read_text(encoding="utf-8").splitlines()
        patched_lines = []
        unpinned_pattern = re.compile(r"^([A-Za-z0-9_\-]+)\s*$")
        changed = False
        for line in lines:
            m = unpinned_pattern.match(line.strip())
            if m:
                pkg = m.group(1)
                try:
                    version = im.version(pkg)
                    patched_lines.append(f"{pkg}=={version}")
                    diffs.append(f"Pinned {pkg}=={version}")
                    changed = True
                except im.PackageNotFoundError:
                    patched_lines.append(line)
            else:
                patched_lines.append(line)
        if changed:
            if not self._dry_run:
                atomic_write_text(req_file, "\n".join(patched_lines) + "\n")
            files_changed.append(str(req_file))
        return files_changed, "; ".join(diffs) or "No dependency pinning needed"

    async def _apply_generic(self, rec: Recommendation) -> tuple[list[str], str]:
        """Catch-all for unhandled action types."""
        return [], f"No handler for action='{rec.action}' — manual fix required"
