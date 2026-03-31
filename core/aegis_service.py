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

    def start(self) -> dict[str, Any]:
        self.running = self.available
        return self.status()

    def stop(self) -> dict[str, Any]:
        self.running = False
        return self.status()

    def run_workflow(self, target_project: str | None = None, preview: bool = True) -> dict[str, Any]:
        target = Path(target_project or ROOT).resolve()
        if not self.available:
            result = {"status": "error", "error": "Aegis workspace unavailable", "target": str(target)}
            self.last_run = result
            return result

        if preview:
            debt_targets = self._scan_debt_targets(target)
            result = {
                "status": "preview",
                "target": str(target),
                "mode": "safe-preview",
                "debt_count": len(debt_targets),
                "debt_targets": debt_targets[:50],
                "workflow_steps": [
                    "analysis-scan",
                    "audit-review",
                    "devops-sandbox-plan",
                    "quantum-verification-check",
                    "report-generation",
                ],
                "generated_at": time.time(),
            }
            self.last_run = result
            return result

        if self.aegis_swarm is None:
            result = {"status": "error", "error": "Aegis runtime entrypoint unavailable", "target": str(target)}
            self.last_run = result
            return result

        swarm = self.aegis_swarm()
        swarm.run_workflow(str(target))
        result = {
            "status": "ok",
            "target": str(target),
            "mode": "workflow",
            "generated_at": time.time(),
        }
        self.last_run = result
        return result

    def status(self) -> dict[str, Any]:
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