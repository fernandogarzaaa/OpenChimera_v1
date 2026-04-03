from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from core.config import ROOT
from core.integration_audit import IntegrationAudit
from core.transactions import atomic_write_json


class ManagedSubsystemRegistry:
    def __init__(
        self,
        integration_audit: IntegrationAudit,
        providers: dict[str, Callable[[], dict[str, Any]]],
        invokers: dict[str, Callable[[str, dict[str, Any]], dict[str, Any]]],
        audit_path: Path | None = None,
    ):
        self.integration_audit = integration_audit
        self.providers = providers
        self.invokers = invokers
        self.audit_path = audit_path or (ROOT / "data" / "subsystem_audit.json")

    def status(self) -> dict[str, Any]:
        snapshot = self.snapshot()
        subsystems = snapshot.get("subsystems", [])
        return {
            "counts": {
                "total": len(subsystems),
                "available": sum(1 for item in subsystems if item.get("available")),
                "invokable": sum(1 for item in subsystems if item.get("invokable")),
            },
            "subsystems": subsystems,
        }

    def snapshot(self) -> dict[str, Any]:
        audit = self.integration_audit.build_report().get("engines", {})
        subsystems = [
            self._build_subsystem_entry("aether", audit.get("aether", {}), "Managed runtime kernel bridge."),
            self._build_subsystem_entry("wraith", audit.get("wraith", {}), "Background orchestration and evolution loop."),
            self._build_subsystem_entry("project_evo_swarm", audit.get("project_evo_swarm", {}), "Autonomous swarm execution and healing bridge."),
            self._build_subsystem_entry("quantum_engine", audit.get("quantum_engine", {}), "Quantum engine evidence and capability bridge."),
            self._build_subsystem_entry("aegis_swarm", audit.get("aegis_swarm", {}), "Aegis workflow and remediation subsystem."),
            self._build_subsystem_entry("ascension_engine", audit.get("ascension_engine", {}), "Ascension deliberation and consensus subsystem."),
            self._build_subsystem_entry("clawd_hybrid_rtx", audit.get("clawd_hybrid_rtx", {}), "Legacy CHIMERA Quantum and hybrid RTX inference surface."),
            self._build_subsystem_entry("qwen_agent", audit.get("qwen_agent", {}), "Historical Qwen-Agent bridge and agent framework integration."),
            self._build_subsystem_entry("project_seraph", audit.get("project_seraph", {}), "Personal swarm, voice bridge, and desktop telemetry interface."),
            self._build_subsystem_entry("aether_operator_stack", audit.get("aether_operator_stack", {}), "Recovered AETHER operator stack covering router, context sensing, and voice-actuation lineage."),
            self._build_subsystem_entry("aegis_mobile_gateway", audit.get("aegis_mobile_gateway", {}), "Mobile operator client and gateway bridge."),
            self._build_subsystem_entry("aegis_core_control_plane", audit.get("aegis_core_control_plane", {}), "Recovered Aegis Core gateway, dashboard, and Python runtime replacement control plane."),
            self._build_subsystem_entry("context_hub", audit.get("context_hub", {}), "Context-Hub integration and MCP-adjacent memory bridge."),
            self._build_subsystem_entry("deepagents_stack", audit.get("deepagents_stack", {}), "Recovered deepagents, BettaFish, and everything-claude-code integration set."),
            self._build_subsystem_entry("tri_core_architecture", audit.get("tri_core_architecture", {}), "RuView, RuVector, and RuFlo tri-core architecture recovered from memory."),
            self._build_subsystem_entry("hitchhiker_protocol", audit.get("hitchhiker_protocol", {}), "Model drift, reasoning shim, and arbiter feedback loop."),
            self._build_subsystem_entry("prometheus_research", audit.get("prometheus_research", {}), "Prometheus swarm research and Q-ANC experimentation surface."),
            self._build_subsystem_entry("minimind", {"name": "minimind", "detected": True, "integrated_runtime": True, "root": str(ROOT / "data" / "minimind"), "evidence": []}, "MiniMind reasoning and training subsystem."),
        ]
        return {
            "generated_at": int(time.time()),
            "subsystems": subsystems,
            "recent_audit": self._load_audit().get("events", [])[-10:],
        }

    def invoke(self, subsystem_id: str, action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        subsystem_key = str(subsystem_id).strip()
        action_name = str(action).strip()
        if subsystem_key not in self.invokers:
            raise ValueError(f"Subsystem does not expose invokable actions: {subsystem_key}")
        invoke_payload = dict(payload or {})
        invoke_payload.setdefault("action", action_name)
        result = self.invokers[subsystem_key](subsystem_key, invoke_payload)
        audit = self._load_audit()
        events = audit.get("events", [])
        events.append(
            {
                "subsystem_id": subsystem_key,
                "action": action_name,
                "recorded_at": int(time.time()),
                "result": result,
            }
        )
        self._save_audit({"events": events[-100:]})
        return result

    def _build_subsystem_entry(self, subsystem_id: str, audit_entry: dict[str, Any], description: str) -> dict[str, Any]:
        provider = self.providers.get(subsystem_id)
        runtime_status = provider() if provider is not None else {}
        available = bool(runtime_status.get("available", audit_entry.get("detected", False)))
        invokable = subsystem_id in self.invokers
        return {
            "id": subsystem_id,
            "name": audit_entry.get("name", subsystem_id),
            "description": description,
            "category": audit_entry.get("category", "runtime"),
            "declared_in_memory": bool(audit_entry.get("declared_in_memory", False)),
            "available": available,
            "integrated_runtime": bool(audit_entry.get("integrated_runtime", runtime_status.get("running", False))),
            "invokable": invokable,
            "health": self._health_from_status(runtime_status, audit_entry),
            "permissions": self._permission_boundary(subsystem_id),
            "actions": self._actions_for_subsystem(subsystem_id),
            "root": audit_entry.get("root", runtime_status.get("root")),
            "evidence": audit_entry.get("evidence", []),
            "source_memory": audit_entry.get("source_memory", []),
            "state_snapshot": runtime_status,
        }

    def _health_from_status(self, runtime_status: dict[str, Any], audit_entry: dict[str, Any]) -> str:
        if runtime_status.get("running"):
            return "running"
        if runtime_status.get("available", audit_entry.get("detected", False)):
            return "available"
        return "missing"

    def _permission_boundary(self, subsystem_id: str) -> dict[str, Any]:
        if subsystem_id in {"aegis_swarm", "project_evo_swarm", "minimind"}:
            return {"required_permission": "admin", "writes_state": True}
        if subsystem_id in {"ascension_engine", "quantum_engine"}:
            return {"required_permission": "admin", "writes_state": False}
        return {"required_permission": "user", "writes_state": False}

    def _actions_for_subsystem(self, subsystem_id: str) -> list[str]:
        mapping = {
            "aegis_swarm": ["run_workflow"],
            "ascension_engine": ["deliberate"],
            "aether_operator_stack": ["status"],
            "clawd_hybrid_rtx": ["status"],
            "qwen_agent": ["status"],
            "context_hub": ["status"],
            "deepagents_stack": ["status"],
            "aegis_mobile_gateway": ["status"],
            "minimind": ["build_dataset", "start_server", "stop_server", "start_training", "stop_training"],
        }
        return mapping.get(subsystem_id, ["status"])

    def _load_audit(self) -> dict[str, Any]:
        if not self.audit_path.exists():
            return {"events": []}
        try:
            raw = json.loads(self.audit_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"events": []}
        if not isinstance(raw, dict):
            return {"events": []}
        events = raw.get("events", [])
        if not isinstance(events, list):
            events = []
        return {"events": events}

    def _save_audit(self, payload: dict[str, Any]) -> None:
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.audit_path, payload)