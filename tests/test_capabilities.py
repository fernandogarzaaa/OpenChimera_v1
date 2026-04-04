from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from core.capabilities import CapabilityRegistry


ROOT = Path(__file__).resolve().parents[1]


class CapabilityRegistryTests(unittest.TestCase):
    def test_registry_discovers_skills_plugins_and_mcp_servers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".mcp.json").write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "openchimera-local": {
                                "command": "python",
                                "args": ["${workspaceFolder}/run.py", "mcp", "--serve"],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            skill_dir = root / "skills" / "demo-skill"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "---\nname: \"demo-skill\"\ndescription: Demo capability skill.\n---\n\n# Demo Skill\n",
                encoding="utf-8",
            )
            appforge_dir = root / "skills" / "appforge-mcp"
            appforge_dir.mkdir(parents=True)
            (appforge_dir / "SKILL.md").write_text(
                "# AppForge MCP Semantic Layer\n\n## Description\nUse this skill to talk to the local AppForge MCP server.\n",
                encoding="utf-8",
            )
            plugins_dir = root / "plugins"
            plugins_dir.mkdir(parents=True)
            (plugins_dir / "openchimera-core.json").write_text(
                json.dumps(
                    {
                        "id": "openchimera-core",
                        "name": "OpenChimera Core",
                        "version": "1.0.0",
                        "description": "Core runtime bundle.",
                        "skills": ["demo-skill"],
                        "mcp_servers": ["context_hub"],
                    }
                ),
                encoding="utf-8",
            )
            data_dir = root / "data"
            data_dir.mkdir(parents=True)
            (data_dir / "mcp_health_state.json").write_text(
                json.dumps({"servers": {"context_hub": {"status": "healthy", "checked_at": 123}}}),
                encoding="utf-8",
            )
            (data_dir / "mcp_registry.json").write_text(
                json.dumps(
                    {
                        "servers": {
                            "context_gateway_remote": {
                                "transport": "http",
                                "url": "http://localhost:9100/mcp",
                                "enabled": True,
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )

            registry = CapabilityRegistry(root=root)
            snapshot = registry.snapshot()

            self.assertEqual(snapshot["counts"]["plugins"], 1)
            self.assertEqual(snapshot["skills"][0]["id"], "demo-skill")
            self.assertEqual(snapshot["plugins"][0]["id"], "openchimera-core")
            mcp_ids = {item["id"] for item in snapshot["mcp_servers"]}
            self.assertIn("context_hub", mcp_ids)
            self.assertIn("context_gateway_remote", mcp_ids)
            self.assertIn("appforge-local", mcp_ids)
            self.assertIn("openchimera-local", mcp_ids)

            openchimera_mcp = next(item for item in snapshot["mcp_servers"] if item["id"] == "openchimera-local")
            self.assertEqual(openchimera_mcp["transport"], "stdio")

            registry_mcp = next(item for item in snapshot["mcp_servers"] if item["id"] == "context_gateway_remote")
            self.assertEqual(registry_mcp["transport"], "http")

    def test_registry_exposes_builtin_commands_and_tools(self) -> None:
        registry = CapabilityRegistry(root=ROOT)
        commands = registry.list_kind("commands")
        tools = registry.list_kind("tools")

        self.assertTrue(any(item["id"] == "capabilities" for item in commands))
        self.assertTrue(any(item["id"] == "browser.fetch" for item in tools))
        self.assertTrue(any(item["id"] == "autonomy.run_job" for item in tools))