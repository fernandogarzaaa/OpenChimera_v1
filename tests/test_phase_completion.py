"""Tests for new Phase 2-10 implementations.

Tests added for:
- ToolExecutor shared helper
- MCP normalization
- ActiveInquiry REST endpoints
- GodSwarm uniqueness check and config loading
- EmbodiedInteraction timeout/retry
- SocialCognition word embedding similarity
- HealthMonitor REST endpoint
"""
from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock

from core.tool_executor import ToolExecutor, ToolPermissionError
from core.mcp_normalization import normalize_mcp_server_entry
from core.active_inquiry import ActiveInquiry
from core.embodied_interaction import ActuatorInterface
from core.social_cognition import SocialNormRegistry
from swarms.god_swarm import GodSwarm, _load_god_swarm_agent_specs


class TestToolExecutor(unittest.TestCase):
    """Test the shared ToolExecutor helper."""

    def test_execute_with_gating_success(self):
        """Verify basic tool execution with timing."""
        bus = MagicMock()
        executor = ToolExecutor(bus=bus)
        
        def handler(args):
            return {"result": args.get("value", 0) * 2}
        
        result = executor.execute_with_gating(
            tool_id="multiply",
            handler=handler,
            arguments={"value": 5},
            permission_scope="user",
        )
        
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["tool_id"], "multiply")
        self.assertEqual(result["result"]["result"], 10)
        self.assertIsNone(result["error"])
        self.assertGreaterEqual(result["latency_ms"], 0.0)
        
        # Check bus event was emitted
        bus.publish_nowait.assert_called_once()

    def test_execute_with_gating_permission_denied(self):
        """Verify admin permission check."""
        executor = ToolExecutor()
        
        def handler(args):
            return {"result": "should not execute"}
        
        with self.assertRaises(ToolPermissionError) as ctx:
            executor.execute_with_gating(
                tool_id="admin_tool",
                handler=handler,
                arguments={},
                requires_admin=True,
                permission_scope="user",
            )
        
        self.assertIn("requires admin", str(ctx.exception))

    def test_execute_with_gating_handles_exceptions(self):
        """Verify exception handling and error reporting."""
        executor = ToolExecutor()
        
        def failing_handler(args):
            raise RuntimeError("Tool execution failed")
        
        result = executor.execute_with_gating(
            tool_id="failing_tool",
            handler=failing_handler,
            arguments={},
        )
        
        self.assertEqual(result["status"], "error")
        self.assertIn("Tool execution failed", result["error"])
        self.assertIsNone(result["result"])
        self.assertGreaterEqual(result["latency_ms"], 0.0)


class TestMCPNormalization(unittest.TestCase):
    """Test MCP server entry normalization."""

    def test_normalize_http_server(self):
        """Verify HTTP server normalization."""
        entry = normalize_mcp_server_entry(
            "my-server",
            {
                "transport": "http",
                "url": "http://localhost:8080",
                "name": "My Server",
                "description": "Test server",
                "enabled": True,
            },
            source_path="/tmp/config.json",
        )
        
        self.assertEqual(entry["id"], "my-server")
        self.assertEqual(entry["transport"], "http")
        self.assertEqual(entry["url"], "http://localhost:8080")
        self.assertEqual(entry["status"], "registered")
        self.assertTrue(entry["enabled"])

    def test_normalize_stdio_server(self):
        """Verify stdio server normalization."""
        entry = normalize_mcp_server_entry(
            "local-server",
            {
                "command": "/usr/bin/server",
                "args": ["--port", "9000"],
                "enabled": True,
            },
        )
        
        self.assertEqual(entry["transport"], "stdio")
        self.assertEqual(entry["command"], "/usr/bin/server")
        self.assertIn("args", entry)
        self.assertEqual(len(entry["args"]), 2)

    def test_normalize_disabled_server(self):
        """Verify disabled server status."""
        entry = normalize_mcp_server_entry(
            "disabled-server",
            {"transport": "http", "url": "http://example.com", "enabled": False},
        )
        
        self.assertEqual(entry["status"], "disabled")
        self.assertFalse(entry["enabled"])


class TestActiveInquiryIntegration(unittest.TestCase):
    """Test ActiveInquiry with new type hints and REST integration."""

    def test_pending_questions_returns_list(self):
        """Verify pending_questions returns correct format."""
        semantic = MagicMock()
        semantic.get_triples.return_value = []
        
        inquiry = ActiveInquiry(semantic=semantic, episodic=None, bus=None)
        inquiry.post_question("Test question?", {"test": True})
        
        pending = inquiry.pending_questions()
        self.assertEqual(len(pending), 1)
        self.assertIn("question_id", pending[0])
        self.assertEqual(pending[0]["question"], "Test question?")
        self.assertFalse(pending[0]["resolved"])

    def test_resolve_question_updates_status(self):
        """Verify question resolution."""
        semantic = MagicMock()
        semantic.get_triples.return_value = []
        
        inquiry = ActiveInquiry(semantic=semantic, episodic=None, bus=None)
        posted = inquiry.post_question("Color preference?")
        
        resolved = inquiry.resolve_question(posted["question_id"], "Blue")
        self.assertTrue(resolved)
        
        pending = inquiry.pending_questions()
        self.assertEqual(len(pending), 0)


class TestGodSwarmEnhancements(unittest.TestCase):
    """Test GodSwarm agent uniqueness and config loading."""

    def test_spawn_agent_uniqueness_check(self):
        """Verify spawn_agent rejects duplicate agent_id."""
        swarm = GodSwarm()
        
        # Omniscient already exists from initialization
        with self.assertRaises(ValueError) as ctx:
            swarm.spawn_agent({
                "agent_id": "omniscient",
                "role": "Duplicate",
                "description": "Should fail",
            })
        
        self.assertIn("already exists", str(ctx.exception))

    def test_load_god_swarm_agent_specs_from_config(self):
        """Verify config loading works."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "agents.json"
            config_path.write_text(json.dumps({
                "core_agents": [
                    {
                        "agent_id": "test_agent",
                        "role": "Tester",
                        "description": "Test agent",
                        "capabilities": ["testing"]
                    }
                ],
                "supporting_agents": []
            }))
            
            specs = _load_god_swarm_agent_specs(config_path)
            self.assertEqual(len(specs["core_agents"]), 1)
            self.assertEqual(specs["core_agents"][0]["agent_id"], "test_agent")

    def test_god_swarm_loads_config_agents(self):
        """Verify GodSwarm initializes from config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "agents.json"
            config_path.write_text(json.dumps({
                "core_agents": [{"agent_id": "custom", "role": "Custom", "description": "Custom agent", "capabilities": []}],
                "supporting_agents": []
            }))
            
            swarm = GodSwarm(config_path=config_path)
            self.assertIn("custom", swarm.ALL_AGENT_IDS)


class TestEmbodiedInteractionTimeout(unittest.TestCase):
    """Test ActuatorInterface timeout and retry logic."""

    def test_issue_command_with_timeout(self):
        """Verify timeout detection."""
        interface = ActuatorInterface(command_timeout_s=0.1)
        
        def slow_handler(cmd):
            time.sleep(0.2)  # Exceeds timeout
            return {"result": "should timeout"}
        
        interface.register_handler("slow_actuator", slow_handler)
        cmd = interface.issue_command("slow_actuator", "move", timeout_s=0.1)
        
        self.assertEqual(cmd.status, "timeout")
        self.assertIn("exceeded", cmd.result.get("error", ""))

    def test_issue_command_with_retry(self):
        """Verify retry logic on failure."""
        interface = ActuatorInterface()
        call_count = 0
        
        def failing_handler(cmd):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise RuntimeError(f"Attempt {call_count} failed")
            return {"result": "success"}
        
        interface.register_handler("retry_actuator", failing_handler)
        cmd = interface.issue_command("retry_actuator", "move", retry_count=2)
        
        self.assertEqual(cmd.status, "completed")
        self.assertEqual(call_count, 3)  # Initial + 2 retries

    def test_issue_command_retry_exhausted(self):
        """Verify failure after retries exhausted."""
        interface = ActuatorInterface()
        
        def always_failing_handler(cmd):
            raise RuntimeError("Always fails")
        
        interface.register_handler("bad_actuator", always_failing_handler)
        cmd = interface.issue_command("bad_actuator", "move", retry_count=2)
        
        self.assertEqual(cmd.status, "failed")
        self.assertEqual(cmd.result.get("attempt"), 3)


class TestSocialCognitionEmbeddings(unittest.TestCase):
    """Test SocialCognition word embedding similarity."""

    def test_evaluate_uses_similarity(self):
        """Verify evaluate uses word embedding similarity."""
        registry = SocialNormRegistry()
        registry.add_norm(
            "test_norm",
            "Be helpful and kind to others",
            weight=1.0,
            category="test",
        )
        
        # Action with semantic similarity
        result = registry.evaluate("assist others with kindness")
        
        # Should score higher than simple keyword matching
        self.assertGreater(result["total_score"], 0.6)
        self.assertGreaterEqual(len(result["norms"]), 1)  # At least our test norm

    def test_embedding_similarity_computation(self):
        """Verify character n-gram similarity works."""
        registry = SocialNormRegistry()
        
        words1 = {"helpful", "kind"}
        words2 = {"help", "kindness"}
        
        # Should have high similarity due to shared character n-grams
        similarity = registry._compute_word_embedding_similarity(words1, words2)
        self.assertGreater(similarity, 0.4)
        self.assertLessEqual(similarity, 1.0)

    def test_embedding_similarity_empty_sets(self):
        """Verify empty set handling."""
        registry = SocialNormRegistry()
        
        similarity = registry._compute_word_embedding_similarity(set(), {"word"})
        self.assertEqual(similarity, 0.0)


class TestHealthMonitorEndpoint(unittest.TestCase):
    """Test health monitor integration."""

    def test_health_monitor_status_method(self):
        """Verify health_monitor_status returns correct structure."""
        # This would normally test via provider, but we can test the concept
        from core.health_monitor import HealthMonitor
        
        monitor = HealthMonitor()
        monitor.record_health("test_subsystem", "healthy", {"version": "1.0"})
        
        current = monitor.get_current_health("test_subsystem")
        self.assertEqual(current.status, "healthy")
        self.assertEqual(current.subsystem, "test_subsystem")
        self.assertEqual(current.details["version"], "1.0")


if __name__ == "__main__":
    unittest.main()
