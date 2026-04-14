from __future__ import annotations

import glob
import time
from pathlib import Path
from typing import Any

from core.config import ROOT, get_aegis_root
from core.integration import import_module_from_file


class AegisService:
    def __init__(self):
        self.root = get_aegis_root()
        self.entrypoint = self.root / "main.py"
        self.orchestrator_path = self.root / "core" / "orchestrator.py"
        self.available = self.entrypoint.exists() and self.orchestrator_path.exists()
        self.last_run: dict[str, Any] | None = None
        self.running = False
        self.last_error: str | None = None
        self.aegis_swarm = None
        self.orchestrator_cls = None

        if self.available:
            try:
                main_module = import_module_from_file("openchimera_aegis_main", self.entrypoint, repo_root=self.root)
                orchestrator_module = import_module_from_file(
                    "openchimera_aegis_orchestrator",
                    self.orchestrator_path,
                    repo_root=self.root,
                )
                self.aegis_swarm = getattr(main_module, "AegisSwarm", None)
                self.orchestrator_cls = getattr(orchestrator_module, "SwarmOrchestrator", None)
            except Exception as exc:
                self.available = False
                self.last_error = str(exc)

    def status(self) -> dict[str, Any]:
        from core.config import load_runtime_profile
        profile = load_runtime_profile()
        if profile.get("simulate_cloud"):
            return {
                "name": "aegis",
                "available": True,
                "running": True,
                "root": str(self.root),
                "entrypoint": str(self.entrypoint),
                "orchestrator": str(self.orchestrator_path),
                "last_run": self.last_run,
                "last_error": self.last_error,
                "capabilities": ["workflow-preview", "debt-scan", "remediation-bridge"],
            }
        return {
            "name": "aegis",
            "available": self.available,
            "running": self.running,
            "root": str(self.root),
            "entrypoint": str(self.entrypoint),
            "orchestrator": str(self.orchestrator_path),
            "last_run": self.last_run,
            "last_error": self.last_error,
            "capabilities": ["workflow-preview", "debt-scan", "remediation-bridge"],
        }

    def start(self) -> dict[str, Any]:
        """Start the aegis service. Returns running state based on availability."""
        if self.available:
            self.running = True
        return {"running": self.running}

    def stop(self) -> dict[str, Any]:
        """Stop the aegis service."""
        self.running = False
        return {"running": False}

    def run_workflow(
        self,
        target_project: str | None = None,
        preview: bool = True,
        preview_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run the aegis workflow or a preview scan.

        In preview mode, scans the target project for debt targets and
        returns recommended actions without mutating any files.

        In live mode, instantiates the AegisSwarm and runs the full workflow.
        """
        if not self.available:
            result: dict[str, Any] = {
                "status": "error",
                "error": "AegisService is unavailable; entrypoint or orchestrator not found.",
            }
            self.last_run = result
            return result

        target = Path(target_project) if target_project else self.root
        ctx = preview_context or {}

        if preview:
            debt_targets = self._scan_debt_targets(target)
            focus_areas = [str(item) for item in ctx.get("focus_areas", []) if str(item).strip()]
            recommended_actions = self._preview_recommendations(ctx, debt_targets)
            result = {
                "status": "preview",
                "mode": "preview",
                "target_project": str(target),
                "debt_count": len(debt_targets),
                "debt_targets": debt_targets,
                "focus_areas": focus_areas,
                "recommended_actions": recommended_actions,
            }
            self.last_run = result
            return result

        # Live mode
        if self.aegis_swarm is None:
            result = {
                "status": "error",
                "error": "AegisSwarm is unavailable; cannot run live workflow.",
            }
            self.last_run = result
            return result

        try:
            swarm_instance = self.aegis_swarm(target_project=str(target))
            swarm_instance.run_workflow()
            result = {
                "status": "ok",
                "mode": "workflow",
                "target_project": str(target),
            }
        except Exception as exc:
            self.last_error = str(exc)
            result = {
                "status": "error",
                "error": str(exc),
            }

        self.last_run = result
        return result

    def _scan_debt_targets(self, target: Path) -> list[str]:
        patterns = [
            "test_*.py",
            "test_*.js",
            "test_*.mjs",
            "demo_*.py",
            "*audit*.py",
            "*report*.txt",
            "*report*.md",
            "*report*.json",
        ]
        debt_targets: list[str] = []
        for pattern in patterns:
            debt_targets.extend(glob.glob(str(target / pattern)))
        debt_targets = [path for path in debt_targets if not path.endswith("README.md")]
        return sorted(set(debt_targets))

    def _preview_recommendations(self, preview_context: dict[str, Any], debt_targets: list[str]) -> list[str]:
        recommendations: list[str] = []
        focus_areas = [str(item) for item in preview_context.get("focus_areas", []) if str(item).strip()]
        if focus_areas:
            recommendations.append("Inspect the highest-priority autonomy focus areas first: " + ", ".join(focus_areas[:4]))
        context_recommendations = [str(item) for item in preview_context.get("recommendations", []) if str(item).strip()]
        recommendations.extend(context_recommendations[:4])
        if debt_targets:
            recommendations.append("Review the detected debt targets before attempting any repair workflow mutations.")
        if not recommendations:
            recommendations.append("No concrete repair actions were inferred; keep the workflow in preview mode.")
        return recommendations[:6]
