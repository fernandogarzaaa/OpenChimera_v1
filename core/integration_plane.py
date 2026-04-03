from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from core.config import (
    get_aegis_mobile_root,
    get_aether_root,
    get_appforge_root,
    get_legacy_workspace_root,
)


class IntegrationPlane:
    def __init__(
        self,
        *,
        integration_audit: Any,
        mcp_status_getter: Callable[[], dict[str, Any]],
        aegis_status_getter: Callable[[], dict[str, Any]],
        ascension_status_getter: Callable[[], dict[str, Any]],
    ) -> None:
        self.integration_audit = integration_audit
        self.mcp_status_getter = mcp_status_getter
        self.aegis_status_getter = aegis_status_getter
        self.ascension_status_getter = ascension_status_getter

    def build_integration_status(self) -> dict[str, Any]:
        report = self.integration_audit.build_report()
        engines = report.get("engines", {})
        if "aegis_swarm" in engines:
            engines["aegis_swarm"]["integrated_runtime"] = bool(self.aegis_status_getter().get("available"))
            engines["aegis_swarm"]["bridge_status"] = self.aegis_status_getter()
        if "ascension_engine" in engines:
            engines["ascension_engine"]["integrated_runtime"] = True
            engines["ascension_engine"]["bridge_status"] = self.ascension_status_getter()
        if "context_hub" in engines:
            context_hub = self.context_hub_status()
            engines["context_hub"]["detected"] = bool(context_hub.get("available"))
            engines["context_hub"]["integrated_runtime"] = bool(context_hub.get("available"))
            engines["context_hub"]["bridge_status"] = context_hub
        if "deepagents_stack" in engines:
            deepagents_stack = self.deepagents_stack_status()
            engines["deepagents_stack"]["detected"] = bool(deepagents_stack.get("available"))
            engines["deepagents_stack"]["integrated_runtime"] = bool(deepagents_stack.get("available"))
            engines["deepagents_stack"]["bridge_status"] = deepagents_stack
        if "aether_operator_stack" in engines:
            aether_operator_stack = self.aether_operator_stack_status()
            engines["aether_operator_stack"]["detected"] = bool(aether_operator_stack.get("available"))
            engines["aether_operator_stack"]["integrated_runtime"] = bool(aether_operator_stack.get("available"))
            engines["aether_operator_stack"]["bridge_status"] = aether_operator_stack
        return report

    def qwen_agent_status(self) -> dict[str, Any]:
        appforge_root = get_appforge_root()
        legacy_workspace_root = get_legacy_workspace_root()
        qwen_agent_root = appforge_root / "Qwen-Agent"
        api_bridge = legacy_workspace_root / "qwen_agent_api.py"
        enhanced_bridge = legacy_workspace_root / "chimera_qwen_enhanced.py"
        bridge = legacy_workspace_root / "chimera_qwen.py"
        available = qwen_agent_root.exists() or api_bridge.exists() or enhanced_bridge.exists() or bridge.exists()
        return {
            "name": "qwen_agent",
            "available": available,
            "running": False,
            "root": str(qwen_agent_root),
            "api_bridge": str(api_bridge),
            "enhanced_bridge": str(enhanced_bridge),
            "compat_bridge": str(bridge),
            "workspace_available": qwen_agent_root.exists(),
            "api_bridge_available": api_bridge.exists(),
            "enhanced_bridge_available": enhanced_bridge.exists(),
            "compat_bridge_available": bridge.exists(),
            "capabilities": [
                "agent-framework",
                "chat-bridge",
                "tool-calling",
            ],
        }

    def context_hub_status(self) -> dict[str, Any]:
        legacy_workspace_root = get_legacy_workspace_root()
        context_root = legacy_workspace_root / "integrations" / "context-hub"
        hub_service = legacy_workspace_root / "memory" / "hub_service.py"
        mcp_snapshot = self.mcp_status_getter()
        mcp_servers = mcp_snapshot.get("servers", []) if isinstance(mcp_snapshot, dict) else []
        registry_servers = mcp_snapshot.get("registry", {}).get("servers", []) if isinstance(mcp_snapshot, dict) else []
        context_entry = next((item for item in mcp_servers if str(item.get("id")) == "context_hub"), {})
        gateway_entry = next((item for item in registry_servers if str(item.get("id")) == "context_gateway_remote"), {})
        status = str(context_entry.get("status") or gateway_entry.get("status") or "missing").lower()
        available = bool(context_root.exists() or hub_service.exists() or context_entry or gateway_entry)
        return {
            "name": "context_hub",
            "available": available,
            "running": status in {"healthy", "discovered"},
            "root": str(context_root),
            "hub_service": str(hub_service),
            "mcp_server_id": str(context_entry.get("id") or "context_hub"),
            "mcp_status": status,
            "gateway_connector_id": str(gateway_entry.get("id") or ""),
            "gateway_status": str(gateway_entry.get("status") or "unknown"),
            "workspace_available": context_root.exists(),
            "hub_service_available": hub_service.exists(),
            "capabilities": [
                "mcp-context-server",
                "memory-bridge",
                "session-hydration",
            ],
        }

    def deepagents_stack_status(self) -> dict[str, Any]:
        legacy_workspace_root = get_legacy_workspace_root()
        integrations_root = legacy_workspace_root / "integrations"
        deepagents_root = integrations_root / "deepagents"
        bettafish_root = integrations_root / "BettaFish"
        everything_claude_code_root = integrations_root / "everything-claude-code"
        deepagents_manifest = deepagents_root / ".mcp.json"
        deepagents_agents_doc = deepagents_root / "AGENTS.md"
        bettafish_app = bettafish_root / "app.py"
        available = any(
            path.exists()
            for path in [deepagents_root, bettafish_root, everything_claude_code_root, deepagents_manifest, deepagents_agents_doc, bettafish_app]
        )
        return {
            "name": "deepagents_stack",
            "available": available,
            "running": False,
            "root": str(integrations_root),
            "deepagents_root": str(deepagents_root),
            "bettafish_root": str(bettafish_root),
            "everything_claude_code_root": str(everything_claude_code_root),
            "deepagents_available": deepagents_root.exists(),
            "bettafish_available": bettafish_root.exists(),
            "everything_claude_code_available": everything_claude_code_root.exists(),
            "mcp_manifest_available": deepagents_manifest.exists(),
            "agents_doc_available": deepagents_agents_doc.exists(),
            "bettafish_app_available": bettafish_app.exists(),
            "capabilities": [
                "agent-orchestration",
                "mcp-manifest",
                "reporting-stack",
            ],
        }

    def aether_operator_stack_status(self) -> dict[str, Any]:
        aether_root = get_aether_root()
        core_root = aether_root / "core"
        router_path = core_root / "aether_router.py"
        event_bus_path = core_root / "event_bus.py"
        consensus_path = core_root / "consensus_engine.py"
        kernel_path = core_root / "kernel.py"
        readme_path = aether_root / "README.md"
        available = any(path.exists() for path in [router_path, event_bus_path, consensus_path, kernel_path, readme_path])
        return {
            "name": "aether_operator_stack",
            "available": available,
            "running": False,
            "root": str(aether_root),
            "core_root": str(core_root),
            "router_entrypoint": str(router_path),
            "event_bus": str(event_bus_path),
            "consensus_engine": str(consensus_path),
            "kernel": str(kernel_path),
            "readme": str(readme_path),
            "workspace_available": aether_root.exists(),
            "router_available": router_path.exists(),
            "event_bus_available": event_bus_path.exists(),
            "consensus_engine_available": consensus_path.exists(),
            "kernel_available": kernel_path.exists(),
            "readme_available": readme_path.exists(),
            "capabilities": [
                "operator-routing",
                "event-bus",
                "consensus-engine",
            ],
        }

    def clawd_hybrid_rtx_status(self) -> dict[str, Any]:
        clawd_root = get_appforge_root() / "infrastructure" / "clawd-hybrid-rtx"
        api_server = clawd_root / "src" / "api_server.py"
        consensus = clawd_root / "src" / "quantum_consensus.py"
        requirements = clawd_root / "requirements.txt"
        available = clawd_root.exists() or api_server.exists() or consensus.exists()
        return {
            "name": "clawd_hybrid_rtx",
            "available": available,
            "running": False,
            "root": str(clawd_root),
            "api_server": str(api_server),
            "quantum_consensus": str(consensus),
            "requirements": str(requirements),
            "api_server_available": api_server.exists(),
            "quantum_consensus_available": consensus.exists(),
            "requirements_available": requirements.exists(),
            "capabilities": [
                "openai-compatible-api",
                "quantum-consensus",
                "hybrid-rtx-inference",
            ],
        }

    def aegis_mobile_gateway_status(self) -> dict[str, Any]:
        mobile_root = get_aegis_mobile_root()
        app_manifest = mobile_root / "app.json"
        gateway_path = Path(r"D:\AegisSwarm\gateway\gateway.py")
        available = mobile_root.exists() or gateway_path.exists() or app_manifest.exists()
        return {
            "name": "aegis_mobile_gateway",
            "available": available,
            "running": False,
            "root": str(mobile_root),
            "app_manifest": str(app_manifest),
            "gateway_entrypoint": str(gateway_path),
            "mobile_app_available": mobile_root.exists() and app_manifest.exists(),
            "gateway_available": gateway_path.exists(),
            "capabilities": [
                "mobile-operator-client",
                "gateway-bridge",
                "websocket-control",
            ],
        }