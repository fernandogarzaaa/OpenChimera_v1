from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.capabilities import CapabilityRegistry
from core.integration_audit import IntegrationAudit
from core.plugins import PluginManager
from core.subsystems import ManagedSubsystemRegistry


class PluginAndSubsystemTests(unittest.TestCase):
    def test_plugin_installation_state_and_subsystem_invocation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plugins_dir = root / "plugins"
            plugins_dir.mkdir(parents=True)
            (plugins_dir / "openchimera-core.json").write_text(
                '{"id": "openchimera-core", "name": "OpenChimera Core", "version": "1.0.0", "description": "Core runtime bundle."}',
                encoding="utf-8",
            )
            capabilities = CapabilityRegistry(root=root)
            plugin_manager = PluginManager(capability_registry=capabilities, state_path=root / "plugins_state.json")
            installed = plugin_manager.install("openchimera-core")
            self.assertEqual(installed["status"], "installed")
            self.assertEqual(plugin_manager.status()["counts"]["installed"], 1)

            registry = ManagedSubsystemRegistry(
                IntegrationAudit(),
                providers={"ascension_engine": lambda: {"available": True, "running": True}},
                invokers={"ascension_engine": lambda subsystem_id, payload: {"status": "ok", "subsystem_id": subsystem_id, "payload": payload}},
                audit_path=root / "subsystem_audit.json",
            )
            result = registry.invoke("ascension_engine", "deliberate", {"prompt": "next"})
            self.assertEqual(result["status"], "ok")
            self.assertEqual(registry.status()["counts"]["invokable"], 1)

    def test_subsystem_snapshot_includes_memory_recovered_integrations(self) -> None:
        registry = ManagedSubsystemRegistry(
            IntegrationAudit(),
            providers={
                "clawd_hybrid_rtx": lambda: {"available": True, "running": False, "api_server_available": True},
                "qwen_agent": lambda: {"available": True, "running": False, "api_bridge_available": True},
                "context_hub": lambda: {"available": True, "running": True, "mcp_status": "healthy"},
                "deepagents_stack": lambda: {"available": True, "running": False, "deepagents_available": True, "bettafish_available": True},
                "aether_operator_stack": lambda: {"available": True, "running": False, "router_available": True},
                "aegis_mobile_gateway": lambda: {"available": True, "running": False, "gateway_available": True},
            },
            invokers={
                "clawd_hybrid_rtx": lambda subsystem_id, payload: {"status": "ok", "subsystem_id": subsystem_id, "payload": payload},
                "qwen_agent": lambda subsystem_id, payload: {"status": "ok", "subsystem_id": subsystem_id, "payload": payload},
                "context_hub": lambda subsystem_id, payload: {"status": "ok", "subsystem_id": subsystem_id, "payload": payload},
                "deepagents_stack": lambda subsystem_id, payload: {"status": "ok", "subsystem_id": subsystem_id, "payload": payload},
                "aether_operator_stack": lambda subsystem_id, payload: {"status": "ok", "subsystem_id": subsystem_id, "payload": payload},
                "aegis_mobile_gateway": lambda subsystem_id, payload: {"status": "ok", "subsystem_id": subsystem_id, "payload": payload},
            },
        )

        snapshot = registry.snapshot()
        subsystems = {item["id"]: item for item in snapshot["subsystems"]}

        self.assertIn("qwen_agent", subsystems)
        self.assertIn("tri_core_architecture", subsystems)
        self.assertIn("aether_operator_stack", subsystems)
        self.assertIn("aegis_core_control_plane", subsystems)
        self.assertNotIn("abo_cluster", subsystems)
        self.assertNotIn("vision_daemon", subsystems)
        self.assertTrue(subsystems["aegis_swarm"]["integrated_runtime"])
        self.assertTrue(subsystems["ascension_engine"]["integrated_runtime"])
        self.assertTrue(subsystems["clawd_hybrid_rtx"]["integrated_runtime"])
        self.assertTrue(subsystems["clawd_hybrid_rtx"]["invokable"])
        self.assertTrue(subsystems["qwen_agent"]["declared_in_memory"])
        self.assertTrue(subsystems["qwen_agent"]["integrated_runtime"])
        self.assertTrue(subsystems["qwen_agent"]["invokable"])
        self.assertTrue(subsystems["context_hub"]["integrated_runtime"])
        self.assertTrue(subsystems["context_hub"]["invokable"])
        self.assertTrue(subsystems["deepagents_stack"]["integrated_runtime"])
        self.assertTrue(subsystems["deepagents_stack"]["invokable"])
        self.assertTrue(subsystems["aether_operator_stack"]["integrated_runtime"])
        self.assertTrue(subsystems["aether_operator_stack"]["invokable"])
        self.assertTrue(subsystems["aegis_mobile_gateway"]["integrated_runtime"])
        self.assertTrue(subsystems["aegis_mobile_gateway"]["invokable"])
        self.assertIn("2026-03-17-snapshot.md", subsystems["tri_core_architecture"]["source_memory"])
        self.assertIn("2026-03-18.md", subsystems["aether_operator_stack"]["source_memory"])
        self.assertIn("2026-03-29.md", subsystems["aegis_core_control_plane"]["source_memory"])


if __name__ == "__main__":
    unittest.main()
