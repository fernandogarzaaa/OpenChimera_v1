"""swarms.audit_system — 5-agent audit pipeline for OpenChimera.

Pipeline flow
-------------
Agent 1 (AuditAgent)          → full codebase scan + AuditReport
    ↓  [chimera_audit gate]
Agent 2 (RecommenderAgent)    → prioritised RecommendationSet
    ↓  [chimera_detect + chimera_confident gate]
Agent 3 (ExecutorAgent)       → code changes + ExecutionLog
    ↓  [chimera_prove + chimera_constrain gate]
Agent 4 (TesterAgent)         → pytest + smoke tests + TestReport
    ↓  [chimera_gate verdict]
Agent 5 (OrchestratorAgent)   → coordinates all of the above, manages
                                 hallucination detection & trust propagation,
                                 writes OrchestrationReport

Entry point
-----------
    python run_audit.py [--dry-run] [--skip-execute] [--skip-tests]

Or programmatically:
    from swarms.audit_system import run_audit
    report = run_audit(workspace="/path/to/project")
"""
from __future__ import annotations

from swarms.audit_system.agent1_auditor import AuditAgent
from swarms.audit_system.agent2_recommender import RecommenderAgent
from swarms.audit_system.agent3_executor import ExecutorAgent
from swarms.audit_system.agent4_tester import TesterAgent
from swarms.audit_system.agent5_orchestrator import OrchestratorAgent
from swarms.audit_system.chimera_client import ChimeraClient
from swarms.audit_system.models import (
    AuditReport,
    ExecutionLog,
    OrchestrationReport,
    RecommendationSet,
    TestReport,
)


def run_audit(
    workspace: str = ".",
    dry_run: bool = True,
    skip_execute: bool = False,
    skip_tests: bool = False,
    run_id: str | None = None,
) -> OrchestrationReport:
    """Convenience function: run the full 5-agent pipeline synchronously."""
    return OrchestratorAgent.run_sync(
        workspace=workspace,
        run_id=run_id,
        dry_run=dry_run,
        skip_execute=skip_execute,
        skip_tests=skip_tests,
    )


__all__ = [
    "run_audit",
    "AuditAgent",
    "RecommenderAgent",
    "ExecutorAgent",
    "TesterAgent",
    "OrchestratorAgent",
    "ChimeraClient",
    "AuditReport",
    "RecommendationSet",
    "ExecutionLog",
    "TestReport",
    "OrchestrationReport",
]
