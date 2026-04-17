"""Agent 1 — RepoScanner: full codebase scan wrapping the existing AuditAgent."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from swarms.audit_system.agent1_auditor import AuditAgent
from swarms.audit_system.chimera_client import ChimeraClient
from swarms.audit_system.models import AuditReport

log = logging.getLogger(__name__)


class RepoScanner:
    """Wraps AuditAgent and augments with git context."""

    def __init__(self, workspace: str, chimera: ChimeraClient | None = None) -> None:
        self.workspace = Path(workspace)
        self.chimera = chimera or ChimeraClient()

    def _git_context(self) -> str:
        try:
            result = subprocess.run(
                ["git", "log", "--oneline", "-30"],
                capture_output=True, text=True, cwd=self.workspace, timeout=10,
            )
            return result.stdout.strip()
        except Exception:
            return ""

    async def run_async(self, run_id: str, artifacts_dir: Path) -> AuditReport:
        log.info("[RepoScanner] Starting full codebase scan (run_id=%s)", run_id)
        git_ctx = self._git_context()
        if git_ctx:
            log.info("[RepoScanner] Recent commits:\n%s", git_ctx[:500])

        auditor = AuditAgent(workspace=str(self.workspace), chimera=self.chimera)
        report = await auditor.run_async(run_id=run_id, artifacts_dir=artifacts_dir)

        audit_result = await self.chimera.audit("scan", {
            "files_scanned": report.total_files_scanned,
            "findings": len(report.findings),
        })
        report.trust_score = audit_result.get("trust_score", 1.0)
        report.chimera_audit_result = audit_result

        # Compress report before writing to reduce artifact size
        import json
        raw = json.dumps(report.model_dump())
        compressed = await self.chimera.compress(raw, max_chars=len(raw), mode="summary")
        log.info(
            "[RepoScanner] Scan complete: %d files, %d findings, trust=%.2f",
            report.total_files_scanned, len(report.findings), report.trust_score,
        )
        return report

    def run(self, run_id: str, artifacts_dir: Path) -> AuditReport:
        import asyncio
        return asyncio.run(self.run_async(run_id, artifacts_dir))
