from __future__ import annotations

from pathlib import Path
from typing import Any

from core.config import (
    ROOT,
    get_abo_root,
    get_aegis_mobile_root,
    get_aether_root,
    get_appforge_root,
    get_evo_root,
    get_legacy_workspace_root,
    get_wraith_root,
)


class IntegrationAudit:
    def build_report(self) -> dict[str, Any]:
        legacy_workspace_root = get_legacy_workspace_root()
        project_evo_root = get_evo_root()
        appforge_root = get_appforge_root()
        abo_root = get_abo_root()
        aegis_mobile_root = get_aegis_mobile_root()
        aegis_root = legacy_workspace_root / "aegis_swarm"
        quantum_skill = ROOT / "skills" / "quantumskill" / "quantum_tool.py"
        hyper_skill = ROOT / "skills" / "hyper_intelligence" / "hyper_tool.py"
        ascension_reference = aegis_root / "core" / "orchestrator.py"
        qwen_agent_root = appforge_root / "Qwen-Agent"
        clawd_root = appforge_root / "infrastructure" / "clawd-hybrid-rtx"
        context_hub_root = legacy_workspace_root / "integrations" / "context-hub"
        deepagents_root = legacy_workspace_root / "integrations" / "deepagents"
        bettafish_root = legacy_workspace_root / "integrations" / "BettaFish"
        everything_claude_code_root = legacy_workspace_root / "integrations" / "everything-claude-code"
        prometheus_root = get_aether_root() / "Prometheus"
        aether_operator_root = get_aether_root()
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
                True,
                [ascension_reference],
            ),
            "aegis_swarm": self._entry(
                "aegis_swarm",
                aegis_root,
                True,
                [aegis_root / "core" / "orchestrator.py", aegis_root / "core" / "ide" / "mcp_server.py"],
            ),
            "clawd_hybrid_rtx": self._memory_entry(
                "clawd_hybrid_rtx",
                clawd_root,
                True,
                [clawd_root / "src" / "api_server.py", clawd_root / "src" / "quantum_consensus.py"],
                ["2026-02-24-1200.md", "2026-02-24-2000.md"],
                category="legacy-runtime",
            ),
            "qwen_agent": self._memory_entry(
                "qwen_agent",
                qwen_agent_root,
                True,
                [legacy_workspace_root / "chimera_qwen.py", legacy_workspace_root / "chimera_qwen_enhanced.py", legacy_workspace_root / "qwen_agent_api.py"],
                ["2026-03-06.md", "2026-03-07.md", "system_architecture_audit.md"],
                category="agent-framework",
            ),
            "abo_cluster": self._memory_entry(
                "abo_cluster",
                abo_root,
                False,
                [abo_root / "start_abo_cluster.bat", abo_root / "fuel_gauge.json"],
                ["2026-03-17-snapshot.md", "2026-03-17.md", "2026-03-18.md"],
                category="private-archived",
                public_focus=False,
                remediation_exempt=True,
            ),
            "project_seraph": self._memory_entry(
                "project_seraph",
                legacy_workspace_root,
                False,
                [legacy_workspace_root / "project_seraph.py", legacy_workspace_root / "aether_web_bridge.html"],
                ["2026-03-20.md", "2026-03-21.md"],
                category="operator-interface",
                detect_from_root=False,
            ),
            "aether_operator_stack": self._memory_entry(
                "aether_operator_stack",
                aether_operator_root,
                True,
                [
                    aether_operator_root / "core" / "aether_router.py",
                    legacy_workspace_root / "senses" / "screenpipe_bridge.py",
                    legacy_workspace_root / "uia_controller.py",
                    legacy_workspace_root / "server.py",
                ],
                ["2026-03-18.md", "2026-03-20.md", "2026-03-21.md"],
                category="operator-interface",
                detect_from_root=False,
            ),
            "aegis_mobile_gateway": self._memory_entry(
                "aegis_mobile_gateway",
                aegis_mobile_root,
                True,
                [aegis_mobile_root / "app.json", Path(r"D:\AegisSwarm\gateway\gateway.py")],
                ["2026-03-21.md"],
                category="operator-interface",
            ),
            "aegis_core_control_plane": self._memory_entry(
                "aegis_core_control_plane",
                legacy_workspace_root,
                False,
                [
                    legacy_workspace_root / "chimera_gateway_api.py",
                    legacy_workspace_root / "aegis_dashboard.html",
                    legacy_workspace_root / "aegis_runtime.py",
                ],
                ["2026-03-29.md", "2026-03-30.md"],
                category="control-plane",
                detect_from_root=False,
            ),
            "context_hub": self._memory_entry(
                "context_hub",
                context_hub_root,
                True,
                [context_hub_root, legacy_workspace_root / "memory" / "hub_service.py"],
                ["2026-03-24.md", "hub_service.py"],
                category="integration-framework",
            ),
            "deepagents_stack": self._memory_entry(
                "deepagents_stack",
                legacy_workspace_root / "integrations",
                True,
                [deepagents_root, bettafish_root, everything_claude_code_root],
                ["2026-03-24.md"],
                category="integration-framework",
                detect_from_root=False,
            ),
            "vision_daemon": self._memory_entry(
                "vision_daemon",
                legacy_workspace_root,
                False,
                [legacy_workspace_root / "imouapi", legacy_workspace_root / "senses" / "screenpipe_bridge.py"],
                ["2026-03-17-snapshot.md", "2026-03-18.md", "2026-03-20.md"],
                category="private-archived",
                detect_from_root=False,
                public_focus=False,
                remediation_exempt=True,
            ),
            "tri_core_architecture": self._memory_entry(
                "tri_core_architecture",
                get_aether_root(),
                False,
                [
                    get_aether_root() / "core" / "ruview.py",
                    get_aether_root() / "core" / "ruvector.py",
                    get_aether_root() / "core" / "ruflo.py",
                ],
                ["2026-03-17-snapshot.md"],
                category="architecture",
                detect_from_root=False,
            ),
            "hitchhiker_protocol": self._memory_entry(
                "hitchhiker_protocol",
                legacy_workspace_root,
                False,
                [legacy_workspace_root / "Arbiter_Feedback_Loop.py", legacy_workspace_root / "reasoning_shim_server.py"],
                ["hitchhiker_status.md"],
                category="reasoning-observability",
                detect_from_root=False,
            ),
            "prometheus_research": self._memory_entry(
                "prometheus_research",
                prometheus_root,
                False,
                [prometheus_root],
                ["2026-03-18.md", "2026-03-19.md", "project_prometheus_update_20260319_0330.txt", "project_prometheus_update_20260319_1700.txt"],
                category="research-stack",
            ),
        }
        remediation = []
        lineage_only = []
        for name, entry in report.items():
            if entry.get("remediation_exempt"):
                continue
            if entry.get("operator_actionable") and entry["detected"] and not entry["integrated_runtime"]:
                remediation.append(f"{name} is detected on disk but does not yet have a first-class OpenChimera runtime bridge.")
            elif entry.get("declared_in_memory") and not entry["detected"] and not entry["integrated_runtime"]:
                lineage_only.append(name)
        return {"engines": report, "remediation": remediation, "lineage_only": lineage_only}

    def _entry(self, name: str, root: Path, integrated_runtime: bool, evidence: list[Path], *, detect_from_root: bool = True) -> dict[str, Any]:
        existing_evidence = [str(path) for path in evidence if path.exists()]
        return {
            "name": name,
            "detected": (root.exists() if detect_from_root else False) or bool(existing_evidence),
            "integrated_runtime": integrated_runtime,
            "root": str(root),
            "evidence": existing_evidence,
        }

    def _memory_entry(
        self,
        name: str,
        root: Path,
        integrated_runtime: bool,
        evidence: list[Path],
        source_memory: list[str],
        *,
        category: str,
        detect_from_root: bool = True,
        public_focus: bool = True,
        remediation_exempt: bool = False,
    ) -> dict[str, Any]:
        entry = self._entry(name, root, integrated_runtime, evidence, detect_from_root=detect_from_root)
        entry["declared_in_memory"] = True
        entry["source_memory"] = source_memory
        entry["category"] = category
        entry["public_focus"] = public_focus
        entry["remediation_exempt"] = remediation_exempt
        if integrated_runtime:
            recovery_state = "runtime-bridge"
        elif entry["detected"]:
            recovery_state = "recovered-on-disk"
        elif remediation_exempt or not public_focus:
            recovery_state = "archived-lineage"
        else:
            recovery_state = "memory-lineage"
        entry["recovery_state"] = recovery_state
        entry["operator_actionable"] = recovery_state == "recovered-on-disk"
        return entry