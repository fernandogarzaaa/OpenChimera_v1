#!/usr/bin/env python3
"""run_audit.py — Entry point for the OpenChimera 5-agent audit pipeline.

The pipeline runs 5 agents in sequence, governed at every boundary by
chimeralang-mcp (hallucination detection, confidence gating, trust propagation):

  Agent 1: AuditAgent       — full codebase scan
  Agent 2: RecommenderAgent — prioritised recommendations
  Agent 3: ExecutorAgent    — code changes  (dry-run by default)
  Agent 4: TesterAgent      — pytest + smoke tests
  Agent 5: OrchestratorAgent (admin) — coordinates 1-4, applies all chimera gates

Usage
-----
  python run_audit.py                        # dry-run (no file writes)
  python run_audit.py --apply                # apply code changes
  python run_audit.py --skip-execute         # audit + recommend only
  python run_audit.py --skip-tests           # skip test runner
  python run_audit.py --run-id custom_id     # use a specific run ID

Artifacts are written to:
  artifacts/audit_runs/<run_id>/
    audit_report.json
    recommendations.json
    execution_log.json
    test_report.json
    orchestration_report.json
    chimera_audit_chain.json

Exit codes
----------
  0  pipeline passed
  1  pipeline failed / aborted
  2  pipeline completed with partial results
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure workspace root is on sys.path
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="run_audit",
        description="OpenChimera 5-agent audit pipeline with chimeralang-mcp governance",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help="Apply code changes (Agent 3). Default is dry-run (describe only).",
    )
    p.add_argument(
        "--skip-execute",
        action="store_true",
        default=False,
        help="Skip Agent 3 (executor). Implies no code changes.",
    )
    p.add_argument(
        "--skip-tests",
        action="store_true",
        default=False,
        help="Skip Agent 4 (tester). Useful for quick audit+recommend cycles.",
    )
    p.add_argument(
        "--run-id",
        metavar="ID",
        default=None,
        help="Custom run ID (default: timestamp-based).",
    )
    p.add_argument(
        "--workspace",
        metavar="PATH",
        default=str(_ROOT),
        help=f"Workspace root to audit (default: {_ROOT})",
    )
    p.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="Enable DEBUG logging.",
    )
    p.add_argument(
        "--json",
        action="store_true",
        default=False,
        dest="json_output",
        help="Print final report as JSON to stdout.",
    )
    return p


async def _run(args: argparse.Namespace) -> int:
    from swarms.audit_system.agent5_orchestrator import OrchestratorAgent

    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dry_run = not args.apply

    print(f"\n{'='*60}")
    print(f"  OpenChimera Audit Pipeline")
    print(f"  run_id   : {run_id}")
    print(f"  workspace: {args.workspace}")
    print(f"  mode     : {'DRY-RUN' if dry_run else 'APPLY'}")
    print(f"  execute  : {'SKIP' if args.skip_execute else 'YES'}")
    print(f"  tests    : {'SKIP' if args.skip_tests else 'YES'}")
    print(f"{'='*60}\n")

    orchestrator = OrchestratorAgent(
        workspace=args.workspace,
        dry_run=dry_run,
        skip_execute=args.skip_execute,
        skip_tests=args.skip_tests,
    )

    report = await orchestrator.run(run_id)

    # Print summary
    print(f"\n{'='*60}")
    print(f"  PIPELINE COMPLETE")
    print(f"  Verdict  : {report.overall_verdict.upper()}")
    print(f"  Stages   : {len(report.stages)}")
    for stage in report.stages:
        status_icon = "✓" if stage.status == "passed" else ("↻" if stage.status == "redirected" else "✗")
        print(f"    {status_icon} {stage.stage:<12} trust={stage.trust_score:.3f}  retries={stage.retry_count}")
    chimera = report.chimera_summary
    print(f"  Hallucination events: {len(chimera.get('hallucination_events', []))}")
    print(f"  Final trust score   : {chimera.get('final_trust', 1.0):.3f}")
    print(f"  Artifacts           : {report.artifacts_dir}")
    print(f"{'='*60}\n")

    if args.json_output:
        print(json.dumps(report.model_dump(), indent=2))

    # Map verdict to exit code
    verdict_map = {"success": 0, "partial": 2, "failed": 1, "aborted": 1}
    return verdict_map.get(report.overall_verdict, 1)


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    _configure_logging(args.verbose)
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
