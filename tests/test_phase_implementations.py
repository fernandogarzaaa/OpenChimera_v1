"""Tests for all 5 AGI implementation phases.

Validates Phase 1-5 implementations are structurally complete and
functionally correct without requiring external services.
"""
from __future__ import annotations

import json
import time
import unittest
from dataclasses import fields
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Phase 1: ToolRuntime + CapabilityPlane
# ---------------------------------------------------------------------------

class TestToolRuntime(unittest.TestCase):
    """Phase 1 — core/tool_runtime.py"""

    def _make_bus(self):
        bus = MagicMock()
        bus.publish_nowait = MagicMock()
        return bus

    def test_tool_metadata_fields(self):
        from core.tool_runtime import ToolMetadata
        tool = ToolMetadata(name="test.tool", description="A test tool", tags=["test"])
        self.assertEqual(tool.name, "test.tool")
        self.assertEqual(tool.description, "A test tool")
        self.assertIn("test", tool.tags)

    def test_tool_metadata_to_dict(self):
        from core.tool_runtime import ToolMetadata
        tool = ToolMetadata(name="my.tool", description="desc", tags=["a", "b"])
        d = tool.to_dict()
        self.assertEqual(d["name"], "my.tool")
        self.assertTrue(d["executable"] is False)  # no handler

    def test_tool_result_fields(self):
        from core.tool_runtime import ToolResult
        result = ToolResult(tool_name="my.tool", success=True, output={"x": 1}, latency_ms=5.5)
        self.assertTrue(result.success)
        self.assertEqual(result.output, {"x": 1})
        self.assertAlmostEqual(result.latency_ms, 5.5)

    def test_tool_result_to_dict(self):
        from core.tool_runtime import ToolResult
        result = ToolResult(tool_name="t", success=False, output=None, error="boom")
        d = result.to_dict()
        self.assertEqual(d["error"], "boom")
        self.assertFalse(d["success"])

    def test_tool_registry_register_and_list(self):
        from core.tool_runtime import ToolMetadata, ToolRegistry
        reg = ToolRegistry()
        tool = ToolMetadata(name="alpha", description="Alpha tool")
        reg.register(tool)
        tools = reg.list_tools()
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["name"], "alpha")

    def test_tool_registry_unregister(self):
        from core.tool_runtime import ToolMetadata, ToolRegistry
        reg = ToolRegistry()
        reg.register(ToolMetadata(name="beta", description="Beta"))
        removed = reg.unregister("beta")
        self.assertTrue(removed)
        self.assertEqual(len(reg.list_tools()), 0)

    def test_tool_registry_describe_unknown_raises(self):
        from core.tool_runtime import ToolRegistry
        reg = ToolRegistry()
        with self.assertRaises(ValueError):
            reg.describe("nonexistent")

    def test_tool_registry_execute_with_handler(self):
        from core.tool_runtime import ToolMetadata, ToolRegistry
        reg = ToolRegistry()
        handler = lambda args: {"echo": args.get("msg", "hi")}
        reg.register(ToolMetadata(name="echo", description="Echo", handler=handler))
        result = reg.execute("echo", {"msg": "hello"})
        self.assertTrue(result.success)
        self.assertEqual(result.output["echo"], "hello")
        self.assertGreater(result.latency_ms, 0)

    def test_tool_registry_execute_no_handler(self):
        from core.tool_runtime import ToolMetadata, ToolRegistry
        reg = ToolRegistry()
        reg.register(ToolMetadata(name="stub", description="Stub"))
        result = reg.execute("stub")
        self.assertFalse(result.success)
        self.assertIn("no handler", result.error)

    def test_tool_registry_execute_unknown_tool(self):
        from core.tool_runtime import ToolRegistry
        reg = ToolRegistry()
        result = reg.execute("unknown")
        self.assertFalse(result.success)
        self.assertIn("Unknown tool", result.error)

    def test_tool_registry_execute_emits_event(self):
        from core.tool_runtime import ToolMetadata, ToolRegistry
        bus = self._make_bus()
        reg = ToolRegistry(bus=bus)
        reg.register(ToolMetadata(name="ev", description="ev", handler=lambda _: "ok"))
        reg.execute("ev")
        bus.publish_nowait.assert_called()
        args = bus.publish_nowait.call_args[0]
        self.assertEqual(args[0], "system/tools")
        self.assertEqual(args[1]["action"], "execute")

    def test_tool_registry_handler_exception_returns_error_result(self):
        from core.tool_runtime import ToolMetadata, ToolRegistry
        def bad_handler(args):
            raise RuntimeError("intentional failure")
        reg = ToolRegistry()
        reg.register(ToolMetadata(name="bad", description="bad", handler=bad_handler))
        result = reg.execute("bad")
        self.assertFalse(result.success)
        self.assertIn("intentional failure", result.error)

    def test_tool_registry_register_emits_event(self):
        from core.tool_runtime import ToolMetadata, ToolRegistry
        bus = self._make_bus()
        reg = ToolRegistry(bus=bus)
        reg.register(ToolMetadata(name="reg-ev", description="x"))
        bus.publish_nowait.assert_called()


class TestCapabilityPlane(unittest.TestCase):
    """Phase 1 — core/capability_plane.py"""

    def _make_plane(self):
        from core.capability_plane import CapabilityPlane

        class StubCaps:
            def status(self): return {}
            def list_kind(self, k): return []
            def refresh(self): pass

        class StubPlugins:
            def status(self): return {"plugins": []}
            def install(self, _id): return {"installed": True, "id": _id}
            def uninstall(self, _id): return {"uninstalled": True, "id": _id}

        bus = MagicMock()
        bus.publish_nowait = MagicMock()
        return CapabilityPlane(capabilities=StubCaps(), plugins=StubPlugins(), bus=bus)

    def test_register_and_list_tools(self):
        from core.tool_runtime import ToolMetadata
        plane = self._make_plane()
        plane.register_tool(ToolMetadata(name="cap.tool", description="A cap tool"))
        tools = plane.list_tools()
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["name"], "cap.tool")

    def test_unregister_tool(self):
        from core.tool_runtime import ToolMetadata
        plane = self._make_plane()
        plane.register_tool(ToolMetadata(name="removable", description="x"))
        self.assertTrue(plane.unregister_tool("removable"))
        self.assertEqual(len(plane.list_tools()), 0)

    def test_register_and_list_skills(self):
        plane = self._make_plane()
        plane.register_skill("my-skill", {"description": "My skill", "version": "1.0"})
        skills = plane.list_skills()
        self.assertEqual(len(skills), 1)
        self.assertEqual(skills[0]["name"], "my-skill")

    def test_describe_skill_unknown_raises(self):
        plane = self._make_plane()
        with self.assertRaises(ValueError):
            plane.describe_skill("ghost")

    def test_load_plugin_from_json(self, tmp_path=None):
        import tempfile, os
        plane = self._make_plane()
        manifest = {
            "id": "test-plugin",
            "name": "Test Plugin",
            "version": "0.1.0",
            "tools": ["test.tool1", "test.tool2"],
            "skills": ["test-skill"],
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(manifest, f)
            tmp = f.name
        try:
            result = plane.load_plugin(tmp)
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["plugin_id"], "test-plugin")
            # Tools should be registered
            tools = plane.list_tools()
            tool_names = [t["name"] for t in tools]
            self.assertIn("test.tool1", tool_names)
        finally:
            os.unlink(tmp)

    def test_list_plugins(self):
        import tempfile, os
        plane = self._make_plane()
        manifest = {"id": "p1", "name": "Plugin 1", "tools": [], "skills": []}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(manifest, f)
            tmp = f.name
        try:
            plane.load_plugin(tmp)
            plugins = plane.list_plugins()
            self.assertEqual(len(plugins), 1)
            self.assertEqual(plugins[0]["plugin_id"], "p1")
        finally:
            os.unlink(tmp)

    def test_find_capability_tool(self):
        from core.tool_runtime import ToolMetadata
        plane = self._make_plane()
        plane.register_tool(ToolMetadata(name="findme", description="find this"))
        found = plane.find_capability("findme")
        self.assertIsNotNone(found)
        self.assertEqual(found["kind"], "tool")

    def test_find_capability_skill(self):
        plane = self._make_plane()
        plane.register_skill("my-cap-skill", {"description": "skill"})
        found = plane.find_capability("my-cap-skill")
        self.assertIsNotNone(found)
        self.assertEqual(found["kind"], "skill")

    def test_find_capability_none(self):
        plane = self._make_plane()
        found = plane.find_capability("does-not-exist")
        self.assertIsNone(found)


# ---------------------------------------------------------------------------
# Phase 2: QueryEngine checkpointing
# ---------------------------------------------------------------------------

class TestQueryEngineCheckpoints(unittest.TestCase):
    """Phase 2 — core/query_engine.py"""

    def test_session_checkpoint_fields(self):
        from core.query_engine import SessionCheckpoint
        ckpt = SessionCheckpoint(
            session_id="sess-1",
            turn_id="turn-1",
            state={"turns": [], "permission_scope": "user"},
        )
        self.assertEqual(ckpt.session_id, "sess-1")
        self.assertEqual(ckpt.turn_id, "turn-1")
        self.assertIsInstance(ckpt.timestamp, float)

    def test_session_checkpoint_to_dict(self):
        from core.query_engine import SessionCheckpoint
        ckpt = SessionCheckpoint(session_id="s", turn_id="t", state={"x": 1})
        d = ckpt.to_dict()
        self.assertIn("session_id", d)
        self.assertIn("state", d)
        self.assertEqual(d["state"]["x"], 1)

    def test_query_result_fields(self):
        from core.query_engine import QueryResult
        qr = QueryResult(
            response={"choices": []},
            model_used="test-model",
            confidence=0.85,
            latency_ms=42.0,
        )
        self.assertEqual(qr.model_used, "test-model")
        self.assertAlmostEqual(qr.confidence, 0.85)

    def test_query_result_to_dict(self):
        from core.query_engine import QueryResult
        qr = QueryResult(response={"x": 1}, latency_ms=10.0)
        d = qr.to_dict()
        self.assertIn("response", d)
        self.assertIn("latency_ms", d)

    def test_query_engine_has_checkpoint_methods(self):
        from core.query_engine import QueryEngine
        self.assertTrue(hasattr(QueryEngine, "save_checkpoint"))
        self.assertTrue(hasattr(QueryEngine, "branch_from_checkpoint"))
        self.assertTrue(hasattr(QueryEngine, "replay_session"))


# ---------------------------------------------------------------------------
# Phase 3: ModelRole / RoleRegistry
# ---------------------------------------------------------------------------

class TestModelRoleExpansion(unittest.TestCase):
    """Phase 3 — core/router.py"""

    def test_model_role_enum_values(self):
        from core.router import ModelRole
        self.assertIn(ModelRole.MAIN, list(ModelRole))
        self.assertIn(ModelRole.FAST, list(ModelRole))
        self.assertIn(ModelRole.CODE, list(ModelRole))
        self.assertIn(ModelRole.REASONING, list(ModelRole))
        self.assertIn(ModelRole.ADVISOR, list(ModelRole))
        self.assertIn(ModelRole.CONSENSUS, list(ModelRole))
        self.assertIn(ModelRole.FALLBACK, list(ModelRole))

    def test_model_role_to_query_type(self):
        from core.router import ModelRole
        self.assertEqual(ModelRole.CODE.to_query_type(), "code")
        self.assertEqual(ModelRole.FAST.to_query_type(), "fast")
        self.assertEqual(ModelRole.REASONING.to_query_type(), "reasoning")

    def test_model_role_assignment_fields(self):
        from core.router import ModelRole, ModelRoleAssignment
        assignment = ModelRoleAssignment(role=ModelRole.MAIN, model="gpt-4")
        self.assertEqual(assignment.role, ModelRole.MAIN)
        self.assertEqual(assignment.model, "gpt-4")

    def test_model_role_assignment_to_dict(self):
        from core.router import ModelRole, ModelRoleAssignment
        assignment = ModelRoleAssignment(role=ModelRole.CODE, model="codex", reason="test")
        d = assignment.to_dict()
        self.assertEqual(d["role"], "code")
        self.assertEqual(d["model"], "codex")
        self.assertEqual(d["reason"], "test")

    def test_role_registry_assign_and_get(self, tmp_path=None):
        import tempfile
        from core.router import ModelRole, RoleRegistry
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = Path(tmpdir) / "roles.json"
            reg = RoleRegistry(config_path=cfg)
            assignment = reg.assign_role(ModelRole.FAST, "llama-fast")
            self.assertEqual(assignment.model, "llama-fast")
            retrieved = reg.get_role(ModelRole.FAST)
            self.assertIsNotNone(retrieved)
            self.assertEqual(retrieved.model, "llama-fast")

    def test_role_registry_list_roles(self):
        import tempfile
        from core.router import ModelRole, RoleRegistry
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = Path(tmpdir) / "roles.json"
            reg = RoleRegistry(config_path=cfg)
            roles = reg.list_roles()
            # Should list all ModelRole values
            self.assertEqual(len(roles), len(list(ModelRole)))

    def test_role_registry_reset(self):
        import tempfile
        from core.router import ModelRole, RoleRegistry
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = Path(tmpdir) / "roles.json"
            reg = RoleRegistry(config_path=cfg)
            reg.assign_role(ModelRole.CODE, "code-model")
            reg.reset_roles()
            self.assertIsNone(reg.get_role(ModelRole.CODE))

    def test_role_registry_persistence(self):
        import tempfile
        from core.router import ModelRole, RoleRegistry
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = Path(tmpdir) / "roles.json"
            reg = RoleRegistry(config_path=cfg)
            reg.assign_role(ModelRole.REASONING, "mistral-7b")
            # Load fresh instance from same config
            reg2 = RoleRegistry(config_path=cfg)
            retrieved = reg2.get_role(ModelRole.REASONING)
            self.assertIsNotNone(retrieved)
            self.assertEqual(retrieved.model, "mistral-7b")

    def test_role_registry_route_by_role(self):
        import tempfile
        from core.router import ModelRole, RoleRegistry
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = Path(tmpdir) / "roles.json"
            reg = RoleRegistry(config_path=cfg)
            reg.assign_role(ModelRole.ADVISOR, "advisor-model")
            model = reg.route_by_role(ModelRole.ADVISOR)
            self.assertEqual(model, "advisor-model")
            self.assertIsNone(reg.route_by_role(ModelRole.MAIN))

    def test_role_registry_invalid_model_raises(self):
        import tempfile
        from core.router import ModelRole, RoleRegistry
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = Path(tmpdir) / "roles.json"
            reg = RoleRegistry(config_path=cfg)
            with self.assertRaises(ValueError):
                reg.assign_role(ModelRole.MAIN, "")


# ---------------------------------------------------------------------------
# Phase 4: GodSwarm, EvolutionEngine, QuantumServiceContract
# ---------------------------------------------------------------------------

class TestGodSwarmPhase4(unittest.TestCase):
    """Phase 4 — swarms/god_swarm.py"""

    def _make_swarm(self):
        from swarms.god_swarm import GodSwarm
        bus = MagicMock()
        bus.publish_nowait = MagicMock()
        return GodSwarm(bus=bus)

    def test_spawn_agent_creates_record(self):
        swarm = self._make_swarm()
        record = swarm.spawn_agent({
            "role": "Tester",
            "description": "Test agent",
            "capabilities": ["test"],
        })
        self.assertIn("agent_id", record)
        self.assertEqual(record["role"], "Tester")
        self.assertIn("spawned_at", record)

    def test_spawn_agent_emits_event(self):
        swarm = self._make_swarm()
        swarm.spawn_agent({"role": "Emitter", "description": "X"})
        swarm._bus.publish_nowait.assert_called()
        args = swarm._bus.publish_nowait.call_args[0]
        self.assertIn("god_swarm.agent.spawned", args[0])

    def test_spawn_agent_uses_provided_id(self):
        swarm = self._make_swarm()
        record = swarm.spawn_agent({"agent_id": "my-agent", "role": "Custom"})
        self.assertEqual(record["agent_id"], "my-agent")

    def test_spawn_agent_auto_id(self):
        swarm = self._make_swarm()
        record = swarm.spawn_agent({"role": "Auto"})
        self.assertTrue(record["agent_id"].startswith("dyn-"))

    def test_wire_to_kernel_stores_reference(self):
        swarm = self._make_swarm()
        kernel = MagicMock()
        swarm.wire_to_kernel(kernel)
        self.assertIs(swarm._kernel, kernel)

    def test_wire_to_kernel_emits_event(self):
        swarm = self._make_swarm()
        kernel = MagicMock()
        swarm.wire_to_kernel(kernel)
        swarm._bus.publish_nowait.assert_called()

    def test_wire_to_kernel_adopts_bus_from_kernel(self):
        from swarms.god_swarm import GodSwarm
        swarm = GodSwarm(bus=None)  # No bus initially
        kernel = MagicMock()
        kernel.bus = MagicMock()
        kernel.bus.publish_nowait = MagicMock()
        swarm.wire_to_kernel(kernel)
        self.assertIs(swarm._bus, kernel.bus)

    def test_status_includes_dynamic_agents(self):
        swarm = self._make_swarm()
        swarm.spawn_agent({"role": "Dynamic"})
        status = swarm.status()
        self.assertIn("dynamic_agents", status)
        self.assertEqual(len(status["dynamic_agents"]), 1)

    def test_status_kernel_wired(self):
        swarm = self._make_swarm()
        self.assertFalse(swarm.status()["kernel_wired"])
        swarm.wire_to_kernel(MagicMock())
        self.assertTrue(swarm.status()["kernel_wired"])


class TestEvolutionEnginePhase4(unittest.TestCase):
    """Phase 4 — core/evolution.py"""

    def _make_engine(self):
        from core.evolution import EvolutionEngine
        from core._bus_fallback import EventBus
        from core._database_fallback import DatabaseManager
        db = MagicMock()
        db.list_episodes = MagicMock(return_value=[])
        bus = MagicMock()
        bus.publish = MagicMock()
        # Patch EpisodicMemory
        with patch("core.evolution.EpisodicMemory") as mock_mem:
            mock_mem.return_value.list_episodes.return_value = []
            mock_mem.return_value.mark_curated = MagicMock()
            engine = EvolutionEngine(db=db, bus=bus)
        return engine, bus

    def test_dpo_signal_fields(self):
        from core.evolution import DPOSignal
        sig = DPOSignal(prompt="p", chosen="c", rejected="r", reward_delta=0.5)
        self.assertEqual(sig.prompt, "p")
        self.assertEqual(sig.chosen, "c")
        self.assertAlmostEqual(sig.reward_delta, 0.5)
        self.assertIsNotNone(sig.signal_id)

    def test_dpo_signal_to_dict(self):
        from core.evolution import DPOSignal
        sig = DPOSignal(prompt="p", chosen="c", rejected="r")
        d = sig.to_dict()
        self.assertIn("signal_id", d)
        self.assertIn("reward_delta", d)

    def test_record_outcome_stores_record(self):
        engine, bus = self._make_engine()
        record = engine.record_outcome("sess-1", "My response", 0.9)
        self.assertEqual(record["session_id"], "sess-1")
        self.assertAlmostEqual(record["outcome_score"], 0.9)
        self.assertIn("record_id", record)

    def test_record_outcome_emits_event(self):
        engine, bus = self._make_engine()
        engine.record_outcome("sess-1", "response", 0.8)
        bus.publish.assert_called()

    def test_apply_dpo_signals_enhances_context(self):
        engine, bus = self._make_engine()
        # Record some outcomes first
        r1 = engine.record_outcome("s1", "good response", 0.9)
        r2 = engine.record_outcome("s1", "bad response", 0.2)
        # Track quality comparison to generate DPO signal
        engine.track_response_quality(r1["record_id"], r2["record_id"])
        # Apply to context
        ctx = {"query": "test query"}
        enhanced = engine.apply_dpo_signals(ctx)
        self.assertIn("dpo_preferences", enhanced)
        self.assertIn("dpo_signal_count", enhanced)
        self.assertEqual(enhanced["query"], "test query")  # Original key preserved

    def test_track_response_quality_creates_signal(self):
        engine, bus = self._make_engine()
        r1 = engine.record_outcome("s", "good", 0.9)
        r2 = engine.record_outcome("s", "bad", 0.1)
        signal = engine.track_response_quality(r1["record_id"], r2["record_id"])
        self.assertIsNotNone(signal)
        from core.evolution import DPOSignal
        self.assertIsInstance(signal, DPOSignal)
        self.assertGreater(signal.reward_delta, 0)  # good > bad

    def test_track_response_quality_missing_id_returns_none(self):
        engine, bus = self._make_engine()
        result = engine.track_response_quality("nonexistent", "also-nonexistent")
        self.assertIsNone(result)

    def test_summary_includes_inference_tracking_stats(self):
        engine, bus = self._make_engine()
        engine.record_outcome("s", "resp", 0.5)
        summary = engine.summary()
        self.assertIn("response_outcomes", summary)
        self.assertIn("dpo_signals_recorded", summary)


class TestQuantumServiceContract(unittest.TestCase):
    """Phase 4 — core/quantum_engine.py"""

    def test_quantum_service_contract_imports(self):
        from core.quantum_engine import QuantumServiceContract
        self.assertTrue(callable(QuantumServiceContract))

    def test_start_and_stop(self):
        from core.quantum_engine import QuantumServiceContract
        svc = QuantumServiceContract()
        result = svc.start()
        self.assertEqual(result["status"], "started")
        self.assertTrue(svc._running)
        stop_result = svc.stop()
        self.assertEqual(stop_result["status"], "stopped")
        self.assertFalse(svc._running)

    def test_double_start_returns_already_running(self):
        from core.quantum_engine import QuantumServiceContract
        svc = QuantumServiceContract()
        svc.start()
        result = svc.start()
        self.assertEqual(result["status"], "already_running")
        svc.stop()

    def test_status_dict_structure(self):
        from core.quantum_engine import QuantumServiceContract
        svc = QuantumServiceContract()
        status = svc.status()
        self.assertIn("running", status)
        self.assertIn("quorum", status)
        self.assertIn("hard_timeout_ms", status)

    def test_health_check_returns_bool(self):
        from core.quantum_engine import QuantumServiceContract
        svc = QuantumServiceContract()
        result = svc.health_check()
        self.assertIsInstance(result, bool)
        self.assertTrue(result)

    def test_engine_property_accessible(self):
        from core.quantum_engine import QuantumServiceContract, QuantumEngine
        svc = QuantumServiceContract()
        self.assertIsInstance(svc.engine, QuantumEngine)

    def test_stop_not_running(self):
        from core.quantum_engine import QuantumServiceContract
        svc = QuantumServiceContract()
        result = svc.stop()
        self.assertEqual(result["status"], "not_running")

    def test_emits_start_event_on_bus(self):
        from core.quantum_engine import QuantumServiceContract
        bus = MagicMock()
        bus.publish_nowait = MagicMock()
        svc = QuantumServiceContract(bus=bus)
        svc.start()
        svc.stop()
        bus.publish_nowait.assert_called()
        topics = [call[0][0] for call in bus.publish_nowait.call_args_list]
        self.assertIn("quantum_engine.service.started", topics)


# ---------------------------------------------------------------------------
# Phase 5: Operator CLI (structural checks)
# ---------------------------------------------------------------------------

class TestOperatorCLI(unittest.TestCase):
    """Phase 5 — run.py operator commands"""

    def test_phases_command_imports(self):
        """_phases_command must be importable from run module."""
        import run
        self.assertTrue(hasattr(run, "_phases_command"))
        self.assertTrue(callable(run._phases_command))

    def test_roles_command_imports(self):
        import run
        self.assertTrue(hasattr(run, "_roles_command"))

    def test_skills_discover_command_imports(self):
        import run
        self.assertTrue(hasattr(run, "_skills_discover_command"))

    def test_plugins_command_has_load_param(self):
        import run, inspect
        sig = inspect.signature(run._plugins_command)
        params = list(sig.parameters.keys())
        self.assertIn("load_path", params)
        self.assertIn("list_loaded", params)

    def test_tools_command_has_new_params(self):
        import run, inspect
        sig = inspect.signature(run._tools_command)
        params = list(sig.parameters.keys())
        self.assertIn("list_tools", params)
        self.assertIn("register_args", params)
        self.assertIn("call_args", params)

    def test_sessions_command_has_branch_replay(self):
        import run, inspect
        sig = inspect.signature(run._sessions_command)
        params = list(sig.parameters.keys())
        self.assertIn("branch_checkpoint", params)
        self.assertIn("replay_checkpoint", params)

    def test_parser_includes_phases_command(self):
        import run
        parser = run._build_parser()
        # Phases command should be registered
        all_choices = parser._subparsers._group_actions[0].choices
        self.assertIn("phases", all_choices)

    def test_parser_includes_roles_command(self):
        import run
        parser = run._build_parser()
        all_choices = parser._subparsers._group_actions[0].choices
        self.assertIn("roles", all_choices)

    def test_parser_includes_skills_command(self):
        import run
        parser = run._build_parser()
        all_choices = parser._subparsers._group_actions[0].choices
        self.assertIn("skills", all_choices)


if __name__ == "__main__":
    unittest.main()
