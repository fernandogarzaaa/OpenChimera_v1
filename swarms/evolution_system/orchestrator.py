"""EvolutionOrchestrator — meta-admin coordinating the 6-agent evolution pipeline."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from swarms.audit_system.chimera_client import ChimeraClient
from swarms.audit_system.models import StageResult
from swarms.evolution_system.agent1_repo_scanner import RepoScanner
from swarms.evolution_system.agent2_gap_auditor import GapAuditor
from swarms.evolution_system.agent3_fix_executor import FixExecutor
from swarms.evolution_system.agent4_agi_researcher import AGIResearcher
from swarms.evolution_system.agent5_capability_integrator import CapabilityIntegrator
from swarms.evolution_system.agent6_refactor_documenter import RefactorDocumenter
from swarms.evolution_system.models import EvolutionReport

log = logging.getLogger(__name__)

_STAGE_NAMES = ["scan", "audit", "fix", "research", "integrate", "refactor"]


class EvolutionOrchestrator:
    """Admin orchestrator for the 6-agent AGI evolution pipeline.

    Coordinates agents sequentially with chimera quality gates at every boundary.
    Hallucination threshold: 0.10 — stages with h_score > 0.10 are retried (max 3x).
    """

    HALLUCINATION_THRESHOLD = 0.10
    CONFIDENCE_GATE = 0.85
    MAX_RETRIES = 3

    def __init__(
        self,
        workspace: str = "/home/user/OpenChimera_v1",
        dry_run: bool = True,
        skip_agents: list[int] | None = None,
        only_agents: list[int] | None = None,
    ) -> None:
        self.workspace = Path(workspace)
        self.dry_run = dry_run
        self.skip_agents: set[int] = set(skip_agents or [])
        self.only_agents: set[int] = set(only_agents) if only_agents else set(range(1, 7))
        self.chimera = ChimeraClient()
        self._trust_chain: list[float] = []

    def _should_run(self, agent_num: int) -> bool:
        return agent_num in self.only_agents and agent_num not in self.skip_agents

    async def _run_stage(
        self,
        name: str,
        agent_num: int,
        coro,
    ) -> tuple[StageResult, object]:
        """Run a single stage with chimera detect + audit gates. Retries on hallucination."""
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                result = await coro()

                # Optimize stage name before sending to chimera
                opt = await self.chimera.optimize(f"auditing pipeline stage: {name}")
                result_json = result.model_dump_json() if hasattr(result, "model_dump_json") else str(result)

                # Compress result before detection scan
                compressed = await self.chimera.compress(result_json, max_chars=4096)
                detect = await self.chimera.detect(
                    compressed.get("compressed", result_json),
                    strategies=["semantic", "cross_reference"],
                )

                h_score = detect.get("score", 0.0)
                if h_score > self.HALLUCINATION_THRESHOLD and attempt < self.MAX_RETRIES:
                    log.warning(
                        "[EvolutionOrchestrator] Stage %s hallucination score %.2f > %.2f — retry %d/%d",
                        name, h_score, self.HALLUCINATION_THRESHOLD, attempt, self.MAX_RETRIES,
                    )
                    continue

                audit = await self.chimera.audit(name, {"attempt": attempt, "h_score": h_score})
                trust = audit.get("trust_score", 1.0)
                self._trust_chain.append(trust)

                stage = StageResult(
                    stage=name,
                    status="passed",
                    trust_score=trust,
                    hallucination_events=len(detect.get("strategies_fired", [])),
                    retry_count=attempt - 1,
                    notes=f"h_score={h_score:.3f} trust={trust:.2f}",
                )
                return stage, result

            except Exception as exc:
                log.error("[EvolutionOrchestrator] Stage %s attempt %d failed: %s", name, attempt, exc)
                if attempt == self.MAX_RETRIES:
                    stage = StageResult(
                        stage=name,
                        status="aborted",
                        trust_score=0.0,
                        hallucination_events=0,
                        retry_count=attempt - 1,
                        notes=str(exc),
                    )
                    return stage, None

        stage = StageResult(
            stage=name, status="failed", trust_score=0.0,
            hallucination_events=0, retry_count=self.MAX_RETRIES, notes="max retries exceeded",
        )
        return stage, None

    async def run(self, run_id: str | None = None) -> EvolutionReport:
        if run_id is None:
            run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        artifacts_dir = self.workspace / "artifacts" / "evolution_runs" / run_id
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        ts_start = datetime.now(timezone.utc).isoformat()
        log.info("[EvolutionOrchestrator] Pipeline START run_id=%s dry_run=%s", run_id, self.dry_run)

        stages: list[StageResult] = []
        audit_report = rec_set = exec_log = test_report = research = capability_log = None

        # ── Agent 1: Scan ────────────────────────────────────────────────
        if self._should_run(1):
            scanner = RepoScanner(str(self.workspace), chimera=self.chimera)
            stage, audit_report = await self._run_stage(
                "scan", 1, lambda: scanner.run_async(run_id, artifacts_dir),
            )
            stages.append(stage)
            if stage.status == "aborted":
                return self._finalize(run_id, ts_start, stages, [], artifacts_dir)
        else:
            log.info("[EvolutionOrchestrator] Skipping Agent 1 (scan)")

        # ── Agent 2: Audit ───────────────────────────────────────────────
        if self._should_run(2) and audit_report:
            auditor = GapAuditor(str(self.workspace), chimera=self.chimera)
            stage, rec_set = await self._run_stage(
                "audit", 2, lambda: auditor.run_async(run_id, artifacts_dir, audit_report),
            )
            stages.append(stage)
            if stage.status == "aborted":
                return self._finalize(run_id, ts_start, stages, [], artifacts_dir)
        else:
            log.info("[EvolutionOrchestrator] Skipping Agent 2 (audit)")

        # ── Agent 3: Fix ─────────────────────────────────────────────────
        if self._should_run(3) and rec_set:
            fixer = FixExecutor(str(self.workspace), dry_run=self.dry_run, chimera=self.chimera)
            stage, fix_result = await self._run_stage(
                "fix", 3, lambda: fixer.run_async(run_id, artifacts_dir, rec_set),
            )
            stages.append(stage)
            if fix_result:
                exec_log, test_report = fix_result
        else:
            log.info("[EvolutionOrchestrator] Skipping Agent 3 (fix)")

        # ── Agent 4: Research ────────────────────────────────────────────
        if self._should_run(4):
            researcher = AGIResearcher(str(self.workspace), chimera=self.chimera)
            stage, research = await self._run_stage(
                "research", 4, lambda: researcher.run_async(run_id, artifacts_dir),
            )
            stages.append(stage)
        else:
            log.info("[EvolutionOrchestrator] Skipping Agent 4 (research)")

        # ── Agent 5: Integrate ───────────────────────────────────────────
        capabilities_added: list[str] = []
        if self._should_run(5) and research:
            integrator = CapabilityIntegrator(str(self.workspace), dry_run=self.dry_run, chimera=self.chimera)
            stage, capability_log = await self._run_stage(
                "integrate", 5, lambda: integrator.run_async(run_id, artifacts_dir, research),
            )
            stages.append(stage)
            if capability_log:
                capabilities_added = [
                    r.candidate_name for r in capability_log.records
                    if r.action_taken in ("added_dep", "extracted_pattern")
                ]
        else:
            log.info("[EvolutionOrchestrator] Skipping Agent 5 (integrate)")

        # ── Agent 6: Refactor ────────────────────────────────────────────
        if self._should_run(6):
            documenter = RefactorDocumenter(str(self.workspace), dry_run=self.dry_run, chimera=self.chimera)
            stage, _ = await self._run_stage(
                "refactor", 6, lambda: documenter.run_async(run_id, artifacts_dir),
            )
            stages.append(stage)
        else:
            log.info("[EvolutionOrchestrator] Skipping Agent 6 (refactor)")

        return self._finalize(run_id, ts_start, stages, capabilities_added, artifacts_dir)

    def _finalize(
        self,
        run_id: str,
        ts_start: str,
        stages: list[StageResult],
        capabilities_added: list[str],
        artifacts_dir: Path,
    ) -> EvolutionReport:
        ts_end = datetime.now(timezone.utc).isoformat()
        passed = sum(1 for s in stages if s.status == "passed")
        total = len(stages)
        final_trust = (
            sum(self._trust_chain) / len(self._trust_chain) if self._trust_chain else 0.0
        )

        if passed == total and total > 0:
            verdict = "success"
        elif passed > 0:
            verdict = "partial"
        elif any(s.status == "aborted" for s in stages):
            verdict = "aborted"
        else:
            verdict = "failed"

        report = EvolutionReport(
            run_id=run_id,
            timestamp_start=ts_start,
            timestamp_end=ts_end,
            workspace=str(self.workspace),
            stages=stages,
            overall_verdict=verdict,
            capabilities_added=capabilities_added,
            final_trust=round(final_trust, 4),
            artifacts_dir=str(artifacts_dir),
        )

        out = artifacts_dir / "evolution_report.json"
        out.write_text(report.model_dump_json(indent=2))

        log.info(
            "[EvolutionOrchestrator] Pipeline DONE verdict=%s trust=%.2f stages=%d/%d caps=%d",
            verdict, final_trust, passed, total, len(capabilities_added),
        )
        print(f"\n{'='*60}")
        print(f"  EVOLUTION PIPELINE COMPLETE")
        print(f"  verdict      : {verdict}")
        print(f"  stages       : {passed}/{total} passed")
        print(f"  trust        : {final_trust:.3f}")
        print(f"  capabilities : {len(capabilities_added)} added")
        print(f"  artifacts    : {artifacts_dir}")
        print(f"{'='*60}\n")
        return report
