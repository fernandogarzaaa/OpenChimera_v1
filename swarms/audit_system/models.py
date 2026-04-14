"""Pydantic data models for the 5-agent audit pipeline.

Each model represents the structured output of one pipeline stage and
serves as the typed interface between agents.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Agent 1 output — AuditReport
# ---------------------------------------------------------------------------


class AuditFinding(BaseModel):
    """A single finding produced by the AuditAgent."""

    finding_id: str
    file_path: str
    line: int | None = None
    severity: Literal["critical", "high", "medium", "low", "info"]
    category: Literal[
        "security", "quality", "architecture", "dependency", "dead_code", "test_gap"
    ]
    message: str
    rule_id: str


class AuditReport(BaseModel):
    """Full output of Agent 1 (AuditAgent)."""

    run_id: str
    timestamp: str
    workspace: str
    total_files_scanned: int
    findings: list[AuditFinding] = Field(default_factory=list)
    # Attached by Agent 5 via chimera_audit after Agent 1 completes
    trust_score: float = 1.0
    chimera_audit_result: dict = Field(default_factory=dict)

    def findings_by_severity(self) -> dict[str, list[AuditFinding]]:
        result: dict[str, list[AuditFinding]] = {
            "critical": [], "high": [], "medium": [], "low": [], "info": []
        }
        for f in self.findings:
            result[f.severity].append(f)
        return result

    def summary_stats(self) -> dict:
        counts = {sev: 0 for sev in ("critical", "high", "medium", "low", "info")}
        for f in self.findings:
            counts[f.severity] += 1
        return {
            "total": len(self.findings),
            "by_severity": counts,
            "files_scanned": self.total_files_scanned,
            "trust_score": self.trust_score,
        }


# ---------------------------------------------------------------------------
# Agent 2 output — RecommendationSet
# ---------------------------------------------------------------------------


class Recommendation(BaseModel):
    """A single actionable recommendation produced by the RecommenderAgent."""

    rec_id: str
    priority: int = Field(ge=1, le=5, description="1=critical, 5=low")
    title: str
    description: str
    affected_files: list[str] = Field(default_factory=list)
    action: Literal["fix", "refactor", "delete", "add_test", "update_dep"]
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list, description="finding_id refs")
    chimera_detect_result: dict = Field(default_factory=dict)


class RecommendationSet(BaseModel):
    """Full output of Agent 2 (RecommenderAgent)."""

    run_id: str
    recommendations: list[Recommendation] = Field(default_factory=list)
    chimera_validated: bool = False
    hallucination_events: list[dict] = Field(default_factory=list)
    retry_count: int = 0

    def by_priority(self) -> list[Recommendation]:
        return sorted(self.recommendations, key=lambda r: r.priority)


# ---------------------------------------------------------------------------
# Agent 3 output — ExecutionLog
# ---------------------------------------------------------------------------


class ExecutionRecord(BaseModel):
    """Result of applying a single recommendation."""

    recommendation_id: str
    status: Literal["applied", "skipped", "failed"]
    files_changed: list[str] = Field(default_factory=list)
    diff_summary: str = ""
    integrity_proof: str | None = None
    chimera_prove_result: dict = Field(default_factory=dict)
    chimera_constrain_result: dict = Field(default_factory=dict)
    skip_reason: str | None = None


class ExecutionLog(BaseModel):
    """Full output of Agent 3 (ExecutorAgent)."""

    run_id: str
    records: list[ExecutionRecord] = Field(default_factory=list)

    def applied(self) -> list[ExecutionRecord]:
        return [r for r in self.records if r.status == "applied"]

    def skipped(self) -> list[ExecutionRecord]:
        return [r for r in self.records if r.status == "skipped"]

    def failed(self) -> list[ExecutionRecord]:
        return [r for r in self.records if r.status == "failed"]

    def all_changed_files(self) -> list[str]:
        files: list[str] = []
        for rec in self.records:
            files.extend(rec.files_changed)
        return list(dict.fromkeys(files))  # deduplicate, preserve order


# ---------------------------------------------------------------------------
# Agent 4 output — TestReport
# ---------------------------------------------------------------------------


class TestResult(BaseModel):
    """Result of a single test suite run."""

    suite: str
    passed: int
    failed: int
    skipped: int = 0
    errors: list[str] = Field(default_factory=list)
    gate_passed: bool = False
    chimera_gate_result: dict = Field(default_factory=dict)


class TestReport(BaseModel):
    """Full output of Agent 4 (TesterAgent)."""

    run_id: str
    overall_pass: bool
    results: list[TestResult] = Field(default_factory=list)
    regressions: list[str] = Field(default_factory=list)
    api_simulation_notes: list[str] = Field(default_factory=list)
    baseline_delta: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Agent 5 output — OrchestrationReport
# ---------------------------------------------------------------------------


class StageResult(BaseModel):
    """Per-stage summary from Agent 5."""

    stage: str
    status: Literal["passed", "failed", "aborted", "skipped"]
    trust_score: float = 1.0
    hallucination_events: int = 0
    retry_count: int = 0
    notes: str = ""


class OrchestrationReport(BaseModel):
    """Final report produced by Agent 5 (OrchestratorAgent)."""

    run_id: str
    timestamp_start: str
    timestamp_end: str
    workspace: str
    stages: list[StageResult] = Field(default_factory=list)
    overall_verdict: Literal["success", "partial", "failed", "aborted"]
    chimera_summary: dict = Field(default_factory=dict)
    artifacts_dir: str = ""
