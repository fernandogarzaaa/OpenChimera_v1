"""Agent 3 — FixExecutor: resolves priority-1/2 findings (wraps ExecutorAgent + TesterAgent)."""
from __future__ import annotations

import logging
from pathlib import Path

from swarms.audit_system.agent3_executor import ExecutorAgent
from swarms.audit_system.agent4_tester import TesterAgent
from swarms.audit_system.chimera_client import ChimeraClient
from swarms.audit_system.models import ExecutionLog, RecommendationSet, TestReport

log = logging.getLogger(__name__)


class FixExecutor:
    """Applies priority-1 and priority-2 recommendations only, then runs tests."""

    def __init__(
        self,
        workspace: str,
        dry_run: bool = True,
        chimera: ChimeraClient | None = None,
    ) -> None:
        self.workspace = Path(workspace)
        self.dry_run = dry_run
        self.chimera = chimera or ChimeraClient()

    async def run_async(
        self,
        run_id: str,
        artifacts_dir: Path,
        rec_set: RecommendationSet,
    ) -> tuple[ExecutionLog, TestReport]:
        log.info("[FixExecutor] Executing fixes (dry_run=%s, run_id=%s)", self.dry_run, run_id)

        # Filter to critical + high priority only
        filtered_recs = [r for r in rec_set.recommendations if r.priority <= 2]
        log.info("[FixExecutor] %d/%d recommendations in scope (priority ≤ 2)", len(filtered_recs), len(rec_set.recommendations))

        filtered_set = rec_set.model_copy(update={"recommendations": filtered_recs})

        executor = ExecutorAgent(
            workspace=str(self.workspace),
            dry_run=self.dry_run,
            chimera=self.chimera,
        )
        exec_log = await executor.run_async(run_id=run_id, artifacts_dir=artifacts_dir, rec_set=filtered_set)

        tester = TesterAgent(workspace=str(self.workspace), chimera=self.chimera)
        test_report = await tester.run_async(run_id=run_id, artifacts_dir=artifacts_dir, exec_log=exec_log)

        gate = await self.chimera.gate(
            condition=test_report.overall_pass,
            confidence=sum(1 for r in test_report.results if r.passed > 0) / max(len(test_report.results), 1),
        )
        log.info("[FixExecutor] Test gate: passed=%s confidence=%.2f", gate["passed"], gate["confidence"])
        return exec_log, test_report

    def run(self, run_id: str, artifacts_dir: Path, rec_set: RecommendationSet) -> tuple[ExecutionLog, TestReport]:
        import asyncio
        return asyncio.run(self.run_async(run_id, artifacts_dir, rec_set))
