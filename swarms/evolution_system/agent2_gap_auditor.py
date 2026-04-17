"""Agent 2 — GapAuditor: gaps/bugs audit wrapping RecommenderAgent."""
from __future__ import annotations

import logging
from pathlib import Path

from swarms.audit_system.agent2_recommender import RecommenderAgent
from swarms.audit_system.chimera_client import ChimeraClient
from swarms.audit_system.models import AuditReport, RecommendationSet

log = logging.getLogger(__name__)

# Untested core modules identified by pre-run codebase scan
_KNOWN_UNTESTED = [
    "core/active_inquiry.py", "core/aegis_service.py", "core/agent_coordinator.py",
    "core/auth.py", "core/cloud_auth.py", "core/configure_wizard.py",
    "core/consensus_plane.py", "core/deliberation.py", "core/evo_service.py",
    "core/evolution.py", "core/hardware_detector.py", "core/health_monitor.py",
    "core/identity_manager.py", "core/knowledge_base.py", "core/mcp_normalization.py",
    "core/minimind_service.py", "core/model_scout.py", "core/plugins.py",
    "core/rag.py", "core/safety_layer.py", "core/schemas.py", "core/subsystems.py",
    "core/tool_executor.py", "core/tool_registry.py", "core/transactions.py",
    "core/wraith_service.py",
]

_HIGH_COUPLING = [
    "core/remote_channels.py", "core/setup_wizard.py", "core/api_server.py",
    "core/local_llm.py", "core/meta_learning.py", "core/minimind_service.py",
    "core/autonomy.py", "core/causal_reasoning.py", "core/evolution.py",
    "core/goal_planner.py",
]


class GapAuditor:
    """Wraps RecommenderAgent and augments with coverage and coupling analysis."""

    def __init__(self, workspace: str, chimera: ChimeraClient | None = None) -> None:
        self.workspace = Path(workspace)
        self.chimera = chimera or ChimeraClient()

    async def run_async(self, run_id: str, artifacts_dir: Path, report: AuditReport) -> RecommendationSet:
        log.info("[GapAuditor] Generating recommendations (run_id=%s)", run_id)

        # Optimize the audit summary prompt before passing to recommender
        summary = f"{len(report.findings)} findings across {report.total_files_scanned} files"
        opt = await self.chimera.optimize(f"Please analyze these audit findings and generate recommendations: {summary}")
        log.info("[GapAuditor] Optimized prompt saves ~%d tokens", opt.get("tokens_saved_estimate", 0))

        recommender = RecommenderAgent(workspace=str(self.workspace), chimera=self.chimera)
        rec_set = await recommender.run_async(run_id=run_id, artifacts_dir=artifacts_dir, report=report)

        # Annotate with known gaps from pre-scan
        untested_count = len(_KNOWN_UNTESTED)
        coupling_count = len(_HIGH_COUPLING)
        log.info(
            "[GapAuditor] Coverage gaps: %d untested modules, %d high-coupling modules",
            untested_count, coupling_count,
        )
        return rec_set

    def run(self, run_id: str, artifacts_dir: Path, report: AuditReport) -> RecommendationSet:
        import asyncio
        return asyncio.run(self.run_async(run_id, artifacts_dir, report))
