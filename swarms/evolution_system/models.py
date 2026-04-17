"""Pydantic models shared across the 6-agent evolution pipeline."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# Re-export audit models used in Agents 1-3
from swarms.audit_system.models import (
    AuditReport,
    ExecutionLog,
    RecommendationSet,
    StageResult,
    TestReport,
)

__all__ = [
    "AuditReport",
    "ExecutionLog",
    "RecommendationSet",
    "StageResult",
    "TestReport",
    "ResearchCandidate",
    "ResearchReport",
    "CapabilityRecord",
    "CapabilityLog",
    "RefactorRecord",
    "RefactorLog",
    "EvolutionReport",
]


class ResearchCandidate(BaseModel):
    repo_url: str
    name: str
    license: str = "unknown"
    stars: int = 0
    last_commit: str = ""
    capability_gap: str
    integration_complexity: Literal["low", "medium", "high"] = "medium"
    recommendation: Literal["adopt", "extract_pattern", "skip"] = "skip"
    rationale: str = ""


class ResearchReport(BaseModel):
    run_id: str
    candidates: list[ResearchCandidate] = Field(default_factory=list)
    chimera_explore_result: dict = Field(default_factory=dict)
    total_found: int = 0
    adopted: int = 0
    skipped: int = 0


class CapabilityRecord(BaseModel):
    candidate_name: str
    action_taken: Literal["added_dep", "extracted_pattern", "skipped_complexity", "skipped_license", "skipped_test_fail"]
    files_changed: list[str] = Field(default_factory=list)
    integrity_proof: str = ""
    tests_passed: bool = True
    notes: str = ""


class CapabilityLog(BaseModel):
    run_id: str
    records: list[CapabilityRecord] = Field(default_factory=list)


class RefactorRecord(BaseModel):
    file_path: str
    action: Literal["split", "type_hints", "readme_update", "docstring"]
    lines_before: int = 0
    lines_after: int = 0
    notes: str = ""


class RefactorLog(BaseModel):
    run_id: str
    records: list[RefactorRecord] = Field(default_factory=list)


class EvolutionReport(BaseModel):
    run_id: str
    timestamp_start: str = ""
    timestamp_end: str = ""
    workspace: str = ""
    stages: list[StageResult] = Field(default_factory=list)
    overall_verdict: Literal["success", "partial", "failed", "aborted"] = "failed"
    capabilities_added: list[str] = Field(default_factory=list)
    test_count_before: int = 0
    test_count_after: int = 0
    final_trust: float = 0.0
    artifacts_dir: str = ""
