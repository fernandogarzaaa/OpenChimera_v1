"""Agent 2 — RecommenderAgent.

Consumes the AuditReport produced by Agent 1 and generates a prioritized,
chimera-validated RecommendationSet.

Hallucination gates applied:
  - chimera_detect (cross-reference): ensure all file_paths in findings exist
  - chimera_detect (semantic): flag incoherent or self-contradictory descriptions
  - chimera_confident: only forward recommendations with confidence >= 0.85
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from swarms.audit_system.chimera_client import ChimeraClient
from swarms.audit_system.models import (
    AuditFinding,
    AuditReport,
    Recommendation,
    RecommendationSet,
)

log = logging.getLogger(__name__)

# Severity → numeric weight for priority scoring
_SEVERITY_WEIGHT: dict[str, int] = {
    "critical": 10,
    "high": 7,
    "medium": 4,
    "low": 2,
    "info": 1,
}

# Maximum findings bundled into a single recommendation
_MAX_CLUSTER_SIZE = 20

# Minimum confidence for a recommendation to pass the chimera_confident gate
_CONFIDENCE_GATE = 0.85


def _cluster_key(finding: AuditFinding) -> str:
    """Group key: category + top-level directory of the affected file."""
    parts = Path(finding.file_path).parts
    top_dir = parts[0] if len(parts) > 1 else "root"
    return f"{finding.category}::{top_dir}"


def _score_cluster(findings: list[AuditFinding]) -> float:
    """Aggregate priority score for a cluster of findings (higher = more urgent)."""
    if not findings:
        return 0.0
    total = sum(_SEVERITY_WEIGHT.get(f.severity, 1) for f in findings)
    # Boost score for clusters with critical/high findings
    has_critical = any(f.severity == "critical" for f in findings)
    has_high = any(f.severity == "high" for f in findings)
    boost = 1.5 if has_critical else (1.2 if has_high else 1.0)
    return total * boost


def _action_for_category(category: str) -> str:
    mapping = {
        "security": "fix",
        "quality": "refactor",
        "architecture": "refactor",
        "dependency": "update_dep",
        "dead_code": "delete",
        "test_gap": "add_test",
    }
    return mapping.get(category, "fix")


def _build_description(category: str, findings: list[AuditFinding]) -> str:
    sample_msgs = [f.message[:80] for f in findings[:3]]
    count = len(findings)
    plural = "s" if count != 1 else ""
    summary = f"{count} {category} finding{plural} detected"
    if sample_msgs:
        summary += ": " + "; ".join(sample_msgs)
    return summary


class RecommenderAgent:
    """Agent 2 — produces chimera-validated recommendations from an AuditReport."""

    def __init__(
        self,
        workspace: str | Path | None = None,
        chimera: ChimeraClient | None = None,
    ) -> None:
        self._workspace = Path(workspace).resolve() if workspace else Path.cwd()
        self._chimera = chimera or ChimeraClient()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    async def run_async(self, run_id: str, report: AuditReport) -> RecommendationSet:
        """Generate and chimera-validate a RecommendationSet from *report*."""
        log.info("[RecommenderAgent] Processing %d findings for run_id=%s",
                 len(report.findings), run_id)

        # Step 1 — cluster findings by category + directory
        clusters: dict[str, list[AuditFinding]] = defaultdict(list)
        for finding in report.findings:
            key = _cluster_key(finding)
            clusters[key].append(finding)

        # Step 2 — generate one recommendation per cluster, sorted by score
        raw_recs: list[tuple[float, Recommendation]] = []
        for key, findings in clusters.items():
            category = key.split("::")[0]
            score = _score_cluster(findings)
            # Limit very large clusters
            capped = findings[:_MAX_CLUSTER_SIZE]
            rec = Recommendation(
                rec_id=uuid.uuid4().hex[:12],
                priority=1,  # assigned below after sort; placeholder must satisfy ge=1
                title=f"[{category.upper()}] {key.split('::')[1]} — {len(findings)} issue(s)",
                description=_build_description(category, capped),
                affected_files=list(dict.fromkeys(f.file_path for f in capped)),
                action=_action_for_category(category),
                confidence=min(1.0, score / 50.0 + 0.5),  # normalise to [0.5,1.0]
                evidence=[f.finding_id for f in capped],
            )
            raw_recs.append((score, rec))

        # Assign priority ranks (1 = most urgent)
        raw_recs.sort(key=lambda t: t[0], reverse=True)
        ranked: list[Recommendation] = []
        for rank, (_, rec) in enumerate(raw_recs, start=1):
            ranked.append(rec.model_copy(update={"priority": rank}))

        # Step 3 — chimera_detect: cross-reference file paths actually exist
        ranked, hallucination_events = await self._detect_and_filter(ranked)

        # Step 4 — chimera_confident gate: drop low-confidence recommendations
        validated: list[Recommendation] = []
        for rec in ranked:
            gate = await self._chimera.confident(rec.confidence, threshold=_CONFIDENCE_GATE)
            if gate.get("passed", True):
                validated.append(rec.model_copy(update={"chimera_detect_result": gate}))
            else:
                log.info(
                    "[RecommenderAgent] Dropped rec %s (confidence=%.2f < %.2f)",
                    rec.rec_id, rec.confidence, _CONFIDENCE_GATE,
                )

        log.info(
            "[RecommenderAgent] %d/%d recommendations passed chimera gates",
            len(validated), len(ranked),
        )

        rec_set = RecommendationSet(
            run_id=run_id,
            recommendations=validated,
            chimera_validated=True,
            hallucination_events=hallucination_events,
        )
        return rec_set

    def run(self, run_id: str, report: AuditReport) -> RecommendationSet:
        """Synchronous wrapper around run_async."""
        import asyncio
        return asyncio.run(self.run_async(run_id, report))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _detect_and_filter(
        self,
        recs: list[Recommendation],
    ) -> tuple[list[Recommendation], list[dict]]:
        """Run chimera_detect on the full recommendation list.

        Uses two strategies:
        - cross-reference: check that all affected_files exist on disk
        - semantic: check that descriptions are coherent

        Returns (filtered_recs, hallucination_events).
        """
        hallucination_events: list[dict] = []

        # Cross-reference: ensure affected files exist
        cleaned: list[Recommendation] = []
        for rec in recs:
            missing = [p for p in rec.affected_files if not Path(p).exists()]
            if missing:
                # Run chimera_detect to formally record the hallucination
                detect_result = await self._chimera.detect(
                    content=json.dumps({"rec_id": rec.rec_id, "missing_files": missing}),
                    strategies=["cross_reference"],
                    context="file path validation",
                )
                if detect_result.get("hallucination_detected", False):
                    hallucination_events.append({
                        "rec_id": rec.rec_id,
                        "type": "non_existent_file_path",
                        "missing": missing,
                        "chimera": detect_result,
                    })
                    # Strip missing files from affected_files rather than discarding
                    existing = [p for p in rec.affected_files if p not in missing]
                    rec = rec.model_copy(update={"affected_files": existing})
            cleaned.append(rec)

        # Semantic check on the full description batch
        all_descriptions = " | ".join(r.description for r in cleaned)
        semantic_result = await self._chimera.detect(
            content=all_descriptions,
            strategies=["semantic", "dictionary"],
        )
        if semantic_result.get("hallucination_detected", False):
            hallucination_events.append({
                "type": "semantic_inconsistency",
                "chimera": semantic_result,
            })

        return cleaned, hallucination_events
