"""Agent 5 — OrchestratorAgent (Admin).

Acts as the pipeline administrator.  Coordinates Agents 1-4 in sequence and
uses chimeralang-mcp tools at every stage boundary to:

  - Detect hallucinations in each agent's output (chimera_detect)
  - Gate stage transitions on confidence (chimera_confident, chimera_gate)
  - Track trust propagation across the pipeline (chimera_audit)
  - Verify integrity of final state (chimera_prove)
  - Explore multi-path consensus before forwarding ambiguous outputs (chimera_explore)
  - Redirect agents when hallucination score exceeds threshold (max 3 retries/stage)

All artifacts are written atomically to artifacts/audit_runs/<run_id>/ via
core.transactions.atomic_write_json.

State machine
-------------
  PENDING → RUNNING → PASSED  (gate passed)
                    ↘ REDIRECTED → RUNNING (retry, max 3x)
                                 ↘ ABORTED (retries exhausted)
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from core.transactions import atomic_write_json
from swarms.audit_system.agent1_auditor import AuditAgent
from swarms.audit_system.agent2_recommender import RecommenderAgent
from swarms.audit_system.agent3_executor import ExecutorAgent
from swarms.audit_system.agent4_tester import TesterAgent
from swarms.audit_system.chimera_client import ChimeraClient
from swarms.audit_system.models import (
    AuditReport,
    ExecutionLog,
    OrchestrationReport,
    RecommendationSet,
    StageResult,
    TestReport,
)

log = logging.getLogger(__name__)

# Chimera thresholds
_HALLUCINATION_THRESHOLD = 0.10    # score above this triggers redirect
_CONFIDENCE_GATE_THRESHOLD = 0.85  # for chimera_confident calls
_MAX_RETRIES = 3                   # per stage


@dataclass
class _HallucinationEvent:
    stage: str
    attempt: int
    score: float
    flags: list[dict]
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


class StageAbortedError(RuntimeError):
    """Raised when a stage fails all retries."""
    def __init__(self, stage: str, events: list[_HallucinationEvent]):
        super().__init__(f"Stage '{stage}' aborted after {_MAX_RETRIES} retries")
        self.stage = stage
        self.events = events


class OrchestratorAgent:
    """Agent 5 — admin orchestrator with full chimera governance over the pipeline."""

    def __init__(
        self,
        workspace: str | Path | None = None,
        chimera: ChimeraClient | None = None,
        dry_run: bool = True,
        skip_execute: bool = False,
        skip_tests: bool = False,
    ) -> None:
        self._workspace = Path(workspace).resolve() if workspace else Path.cwd()
        self._chimera = chimera or ChimeraClient()
        self._dry_run = dry_run
        self._skip_execute = skip_execute
        self._skip_tests = skip_tests

        self._artifacts_dir = self._workspace / "artifacts" / "audit_runs"
        self._hallucination_events: list[_HallucinationEvent] = []
        self._trust_chain: list[dict] = []
        self._stage_results: list[StageResult] = []

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run(self, run_id: str) -> OrchestrationReport:
        """Execute the full 4-stage pipeline under chimera governance."""
        log.info("[OrchestratorAgent] Pipeline START run_id=%s", run_id)
        run_dir = self._artifacts_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        timestamp_start = datetime.now(timezone.utc).isoformat()
        current_trust = 1.0

        overall_verdict = "success"

        # ── Stage 1: Audit ──────────────────────────────────────────────
        try:
            audit_report, current_trust = await self._run_stage_with_gates(
                stage="audit",
                run_id=run_id,
                trust_in=current_trust,
                runner=lambda ctx: self._stage_audit(run_id, ctx),
                artifact_file=run_dir / "audit_report.json",
            )
        except StageAbortedError as e:
            overall_verdict = "aborted"
            return self._finalize_report(run_id, timestamp_start, overall_verdict, current_trust, run_dir)

        # ── Stage 2: Recommend ──────────────────────────────────────────
        try:
            rec_set, current_trust = await self._run_stage_with_gates(
                stage="recommend",
                run_id=run_id,
                trust_in=current_trust,
                runner=lambda ctx: self._stage_recommend(run_id, audit_report, ctx),
                artifact_file=run_dir / "recommendations.json",
            )
        except StageAbortedError:
            overall_verdict = "aborted"
            return self._finalize_report(run_id, timestamp_start, overall_verdict, current_trust, run_dir)

        # ── Stage 3: Execute ────────────────────────────────────────────
        if self._skip_execute:
            execution_log = ExecutionLog(run_id=run_id, records=[])
        else:
            try:
                execution_log, current_trust = await self._run_stage_with_gates(
                    stage="execute",
                    run_id=run_id,
                    trust_in=current_trust,
                    runner=lambda ctx: self._stage_execute(run_id, rec_set, ctx),
                    artifact_file=run_dir / "execution_log.json",
                )
            except StageAbortedError:
                overall_verdict = "partial"
                execution_log = ExecutionLog(run_id=run_id, records=[])

        # ── Stage 4: Test ───────────────────────────────────────────────
        if self._skip_tests:
            test_report = TestReport(run_id=run_id, overall_pass=True, results=[])
        else:
            try:
                test_report, current_trust = await self._run_stage_with_gates(
                    stage="test",
                    run_id=run_id,
                    trust_in=current_trust,
                    runner=lambda ctx: self._stage_test(run_id, execution_log, ctx),
                    artifact_file=run_dir / "test_report.json",
                )
                if not test_report.overall_pass:
                    overall_verdict = "partial"
            except StageAbortedError:
                overall_verdict = "partial"
                test_report = TestReport(run_id=run_id, overall_pass=False, results=[])

        # ── Final integrity proof ───────────────────────────────────────
        pipeline_summary = {
            "run_id": run_id,
            "stages_completed": len(self._stage_results),
            "hallucination_events": len(self._hallucination_events),
            "final_trust": current_trust,
            "verdict": overall_verdict,
        }
        prove_result = await self._chimera.prove(json.dumps(pipeline_summary))
        log.info(
            "[OrchestratorAgent] Pipeline DONE verdict=%s trust=%.3f proof_valid=%s",
            overall_verdict, current_trust, prove_result.get("valid"),
        )

        return self._finalize_report(run_id, timestamp_start, overall_verdict, current_trust, run_dir)

    # ------------------------------------------------------------------
    # Stage runners
    # ------------------------------------------------------------------

    async def _stage_audit(self, run_id: str, context: dict) -> AuditReport:
        agent = AuditAgent(workspace=self._workspace, chimera=self._chimera)
        return agent.run(run_id)

    async def _stage_recommend(
        self, run_id: str, audit_report: AuditReport, context: dict
    ) -> RecommendationSet:
        agent = RecommenderAgent(workspace=self._workspace, chimera=self._chimera)
        if context.get("redirect_reason"):
            log.info(
                "[OrchestratorAgent] Recommend retry context: %s",
                context["redirect_reason"],
            )
        return await agent.run_async(run_id, audit_report)

    async def _stage_execute(
        self, run_id: str, rec_set: RecommendationSet, context: dict
    ) -> ExecutionLog:
        agent = ExecutorAgent(
            workspace=self._workspace,
            chimera=self._chimera,
            dry_run=self._dry_run,
        )
        return await agent.run_async(run_id, rec_set)

    async def _stage_test(
        self, run_id: str, execution_log: ExecutionLog, context: dict
    ) -> TestReport:
        agent = TesterAgent(workspace=self._workspace, chimera=self._chimera)
        return await agent.run_async(run_id, execution_log)

    # ------------------------------------------------------------------
    # Chimera gate loop
    # ------------------------------------------------------------------

    async def _run_stage_with_gates(
        self,
        stage: str,
        run_id: str,
        trust_in: float,
        runner: Callable[[dict], Any],
        artifact_file: Path,
    ) -> tuple[Any, float]:
        """Execute *runner* and apply chimera gates; retry on hallucination."""
        context: dict = {}
        stage_events: list[_HallucinationEvent] = []

        for attempt in range(1, _MAX_RETRIES + 1):
            log.info("[OrchestratorAgent] Stage '%s' attempt %d/%d", stage, attempt, _MAX_RETRIES)
            t0 = time.perf_counter()
            result = await runner(context)
            latency_ms = (time.perf_counter() - t0) * 1000

            # Serialize result for chimera inspection
            try:
                result_dict = result.model_dump() if hasattr(result, "model_dump") else vars(result)
            except Exception:
                result_dict = {"stage": stage, "attempt": attempt}

            # Gate 1: chimera_detect (semantic + cross-reference)
            detect_sem = await self._chimera.detect(
                content=json.dumps(result_dict)[:4000],
                strategies=["semantic", "cross_reference"],
                context=f"pipeline stage: {stage}",
            )
            h_score = detect_sem.get("score", 0.0)
            flags = detect_sem.get("strategies_fired", [])

            # Gate 2: chimera_audit (trust propagation)
            audit_result = await self._chimera.audit(
                stage=stage,
                data=result_dict,
            )
            new_trust = audit_result.get("trust_score", trust_in)
            self._trust_chain.append({"stage": stage, "attempt": attempt, "trust": new_trust})

            # Gate 3: chimera_explore (multi-path consensus check on key fields)
            summary_candidates = [
                {"path": "A", "trust": new_trust, "score": h_score},
                {"path": "B", "trust": trust_in, "score": 0.0},
            ]
            explore_result = await self._chimera.explore(summary_candidates)
            consensus_ok = explore_result.get("agreement_score", 1.0) >= 0.5

            gate_passed = (
                not detect_sem.get("hallucination_detected", False)
                and h_score <= _HALLUCINATION_THRESHOLD
                and consensus_ok
            )

            if gate_passed:
                # Gate 4: chimera_confident for high-trust stages
                if new_trust >= 0.80:
                    conf_result = await self._chimera.confident(
                        new_trust, threshold=_CONFIDENCE_GATE_THRESHOLD
                    )
                    if not conf_result.get("passed", True):
                        log.info(
                            "[OrchestratorAgent] chimera_confident soft-fail on stage '%s' (trust=%.2f)",
                            stage, new_trust,
                        )

                # Write artifact
                atomic_write_json(artifact_file, result_dict)
                self._stage_results.append(StageResult(
                    stage=stage,
                    status="passed",
                    trust_score=new_trust,
                    hallucination_events=len(stage_events),
                    retry_count=attempt - 1,
                    notes=f"completed in {latency_ms:.0f}ms",
                ))
                return result, new_trust

            # Gate failed — record redirect
            event = _HallucinationEvent(
                stage=stage,
                attempt=attempt,
                score=h_score,
                flags=[{"flag": f, "detect": detect_sem} for f in (flags or ["unknown"])],
            )
            stage_events.append(event)
            self._hallucination_events.append(event)
            log.warning(
                "[OrchestratorAgent] Stage '%s' hallucination detected (score=%.3f) — redirect #%d",
                stage, h_score, attempt,
            )
            context["redirect_reason"] = f"Hallucination score {h_score:.3f} > {_HALLUCINATION_THRESHOLD}"
            context["attempt"] = attempt
            context["prior_flags"] = flags

        # All retries exhausted
        self._stage_results.append(StageResult(
            stage=stage,
            status="aborted",
            trust_score=new_trust,
            hallucination_events=len(stage_events),
            retry_count=_MAX_RETRIES,
            notes=f"Aborted after {_MAX_RETRIES} retries",
        ))
        raise StageAbortedError(stage, stage_events)

    # ------------------------------------------------------------------
    # Report finalization
    # ------------------------------------------------------------------

    def _finalize_report(
        self,
        run_id: str,
        timestamp_start: str,
        verdict: str,
        final_trust: float,
        run_dir: Path,
    ) -> OrchestrationReport:
        timestamp_end = datetime.now(timezone.utc).isoformat()
        report = OrchestrationReport(
            run_id=run_id,
            timestamp_start=timestamp_start,
            timestamp_end=timestamp_end,
            workspace=str(self._workspace),
            stages=self._stage_results,
            overall_verdict=verdict,
            chimera_summary={
                "trust_chain": self._trust_chain,
                "hallucination_events": [
                    asdict(e) for e in self._hallucination_events
                ],
                "final_trust": final_trust,
            },
            artifacts_dir=str(run_dir),
        )
        report_path = run_dir / "orchestration_report.json"
        atomic_write_json(report_path, report.model_dump())

        chain_path = run_dir / "chimera_audit_chain.json"
        atomic_write_json(chain_path, self._trust_chain)

        log.info("[OrchestratorAgent] Report written to %s", report_path)
        return report

    # ------------------------------------------------------------------
    # Sync wrapper for use as standalone script
    # ------------------------------------------------------------------

    @classmethod
    def run_sync(
        cls,
        workspace: str | Path,
        run_id: str | None = None,
        dry_run: bool = True,
        skip_execute: bool = False,
        skip_tests: bool = False,
    ) -> OrchestrationReport:
        import asyncio
        from datetime import datetime

        if run_id is None:
            run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

        agent = cls(
            workspace=workspace,
            dry_run=dry_run,
            skip_execute=skip_execute,
            skip_tests=skip_tests,
        )
        return asyncio.run(agent.run(run_id))
