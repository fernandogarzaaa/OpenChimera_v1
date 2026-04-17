#!/usr/bin/env python3
"""Run the 6-agent AGI evolution pipeline.

Usage:
    python run_evolution.py                          # dry-run, all 6 agents
    python run_evolution.py --apply                  # apply fixes + integrations
    python run_evolution.py --skip 4,5               # skip AGI research + integration
    python run_evolution.py --only 1,2               # scan + audit only
    python run_evolution.py --run-id custom_id       # custom run ID
    python run_evolution.py --verbose                # enable debug logging

Agents:
    1 = RepoScanner      — full codebase scan
    2 = GapAuditor       — gaps and bugs audit
    3 = FixExecutor      — apply priority-1/2 fixes
    4 = AGIResearcher    — discover AGI-enhancing OSS repos
    5 = CapabilityIntegrator — integrate selected capabilities
    6 = RefactorDocumenter   — refactor + update README

Chimera token-saving tools active in all sessions:
    chimera_compress, chimera_optimize, chimera_fracture
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys


def _parse_int_list(s: str) -> list[int]:
    return [int(x.strip()) for x in s.split(",") if x.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="OpenChimera 6-agent AGI evolution pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--apply", action="store_true", help="Apply fixes and integrations (default: dry-run)")
    parser.add_argument("--skip", type=_parse_int_list, default=[], metavar="N,N", help="Agent numbers to skip (e.g. --skip 4,5)")
    parser.add_argument("--only", type=_parse_int_list, default=None, metavar="N,N", help="Run only these agent numbers (e.g. --only 1,2)")
    parser.add_argument("--run-id", default=None, metavar="ID", help="Custom run ID (default: timestamp)")
    parser.add_argument("--workspace", default="/home/user/OpenChimera_v1", help="Path to OpenChimera workspace")
    parser.add_argument("--verbose", action="store_true", help="Enable DEBUG logging")
    parser.add_argument("--json", action="store_true", help="Print final EvolutionReport as JSON")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    from swarms.evolution_system.orchestrator import EvolutionOrchestrator

    orchestrator = EvolutionOrchestrator(
        workspace=args.workspace,
        dry_run=not args.apply,
        skip_agents=args.skip or None,
        only_agents=args.only,
    )

    report = asyncio.run(orchestrator.run(run_id=args.run_id))

    if args.json:
        print(report.model_dump_json(indent=2))

    exit_codes = {"success": 0, "partial": 2, "failed": 1, "aborted": 1}
    sys.exit(exit_codes.get(report.overall_verdict, 1))


if __name__ == "__main__":
    main()
