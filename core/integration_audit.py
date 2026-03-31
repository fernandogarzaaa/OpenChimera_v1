from __future__ import annotations

from pathlib import Path
from typing import Any

from core.config import ROOT, get_aether_root, get_evo_root, get_openclaw_root, get_wraith_root


class IntegrationAudit:
    def build_report(self) -> dict[str, Any]:
        openclaw_root = get_openclaw_root()
        project_evo_root = get_evo_root()
        aegis_root = openclaw_root / "aegis_swarm"
        quantum_skill = ROOT / "skills" / "quantumskill" / "quantum_tool.py"
        hyper_skill = ROOT / "skills" / "hyper_intelligence" / "hyper_tool.py"
        ascension_reference = aegis_root / "core" / "orchestrator.py"
        report = {
            "aether": self._entry("aether", get_aether_root(), True, [get_aether_root() / "README.md"]),
            "wraith": self._entry("wraith", get_wraith_root(), True, [get_wraith_root() / "README.md"]),
            "project_evo_swarm": self._entry(
                "project_evo_swarm",
                project_evo_root,
                (ROOT / "core" / "evo_service.py").exists(),
                [project_evo_root / "swarm_bot.py"],
            ),
            "quantum_engine": self._entry(
                "quantum_engine",
                ROOT / "skills" / "quantumskill",
                quantum_skill.exists(),
                [quantum_skill, hyper_skill],
            ),
            "ascension_engine": self._entry(
                "ascension_engine",
                ascension_reference,
                False,
                [ascension_reference],
            ),
            "aegis_swarm": self._entry(
                "aegis_swarm",
                aegis_root,
                False,
                [aegis_root / "core" / "orchestrator.py", aegis_root / "core" / "ide" / "mcp_server.py"],
            ),
        }
        remediation = []
        for name, entry in report.items():
            if entry["detected"] and not entry["integrated_runtime"]:
                remediation.append(f"{name} is detected on disk but does not yet have a first-class OpenChimera runtime bridge.")
        return {"engines": report, "remediation": remediation}

    def _entry(self, name: str, root: Path, integrated_runtime: bool, evidence: list[Path]) -> dict[str, Any]:
        existing_evidence = [str(path) for path in evidence if path.exists()]
        return {
            "name": name,
            "detected": root.exists() or bool(existing_evidence),
            "integrated_runtime": integrated_runtime,
            "root": str(root),
            "evidence": existing_evidence,
        }