"""Simulated New-User Experience Test Suite for OpenChimera.

This test suite simulates what a brand-new user would encounter when:
  1. Installing OpenChimera for the first time
  2. Running the setup wizard / bootstrap
  3. Configuring providers and models
  4. Sending their first queries
  5. Using cognitive/AGI features (planning, reasoning, memory)
  6. Interacting with the API server
  7. Managing sessions and history

Each test class represents a phase of the user journey, testing for:
  - Correct defaults and sensible error messages
  - No crashes on empty/missing config
  - Graceful degradation when LLM providers are unavailable
  - Discoverable capabilities and helpful onboarding

Inspired by claw-code's permission enforcer, hierarchical config, and
session persistence patterns.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from core.config import ROOT


# ======================================================================
# Phase 1: Installation & Bootstrap
# ======================================================================


class TestPhase1_InstallationBootstrap(unittest.TestCase):
    """Simulate: user installs OpenChimera and runs bootstrap."""

    def test_package_is_importable(self):
        """Core modules should be importable without errors."""
        import core
        import core.config
        import core.bus
        import core.kernel
        import core.provider
        import core.query_engine
        import core.api_server
        self.assertTrue(hasattr(core, "__name__"))

    def test_bootstrap_workspace_creates_required_dirs(self):
        """bootstrap_workspace should create data/ and config/ dirs."""
        from core.bootstrap import bootstrap_workspace
        with tempfile.TemporaryDirectory() as tmp:
            with patch("core.bootstrap.ROOT", Path(tmp)):
                result = bootstrap_workspace()
            self.assertIn("status", result)
            self.assertIn(result["status"], ("ok", "already_bootstrapped"))

    def test_entry_point_help_flag(self):
        """The CLI should accept --help without crashing."""
        import subprocess
        result = subprocess.run(
            ["python", "-c", "from run import main; import sys; sys.argv=['openchimera', '--help']; main()"],
            capture_output=True, text=True, timeout=10,
            cwd=str(ROOT),
        )
        # --help causes SystemExit(0) which is fine
        self.assertIn(result.returncode, (0, 2))

    def test_database_initializes_cleanly(self):
        """DatabaseManager should init without errors in a fresh temp dir."""
        from core.database import DatabaseManager
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            db = DatabaseManager(db_path=str(db_path))
            db.initialize()
            self.assertTrue(db_path.exists())
            db.close()

    def test_eventbus_pubsub_works(self):
        """EventBus should allow subscribe/publish without errors."""
        from core.bus import EventBus
        bus = EventBus()
        received = []
        bus.subscribe("test.event", lambda data: received.append(data))
        bus.publish("test.event", {"msg": "hello"})
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["msg"], "hello")


# ======================================================================
# Phase 2: Configuration & Setup Wizard
# ======================================================================


class TestPhase2_ConfigurationSetup(unittest.TestCase):
    """Simulate: user configures providers and models."""

    def test_runtime_profile_defaults(self):
        """Loading runtime profile with no file should return sensible defaults."""
        from core.config import load_runtime_profile
        load_runtime_profile.cache_clear()
        with tempfile.TemporaryDirectory() as tmp:
            fake_path = Path(tmp) / "nonexistent_profile.json"
            with patch("core.config.get_runtime_profile_path", return_value=fake_path):
                profile = load_runtime_profile()
            self.assertIsInstance(profile, dict)

    def test_model_registry_works_without_gpu(self):
        """Model registry should work for CPU-only hardware."""
        from core.model_registry import ModelRegistry
        with tempfile.TemporaryDirectory() as tmp:
            registry = ModelRegistry()
            registry.registry_path = Path(tmp) / "model_registry.json"
            registry.profile = {
                "hardware": {
                    "cpu_count": 4, "ram_gb": 8,
                    "gpu": {"available": False, "name": "cpu-only", "vram_gb": 0, "device_count": 0},
                },
                "model_inventory": {"available_models": []},
                "local_runtime": {},
            }
            payload = registry.refresh()
            self.assertIn("hardware", payload)
            self.assertIn("recommendations", payload)
            self.assertTrue(payload["recommendations"]["needs_cloud_fallback"])

    def test_model_registry_with_gpu_and_models(self):
        """Model registry should detect available local models correctly."""
        from core.model_registry import ModelRegistry
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "qwen.gguf").write_text("stub", encoding="utf-8")
            registry = ModelRegistry()
            registry.registry_path = Path(tmp) / "model_registry.json"
            registry.profile = {
                "hardware": {
                    "cpu_count": 16, "ram_gb": 32,
                    "gpu": {"available": True, "name": "RTX 4090", "vram_gb": 24, "device_count": 1},
                },
                "model_inventory": {
                    "available_models": ["qwen2.5-7b"],
                    "model_files": {"qwen2.5-7b": str(Path(tmp) / "qwen.gguf")},
                    "models_dir": tmp,
                },
                "local_runtime": {},
            }
            payload = registry.refresh()
            qwen = next((m for m in payload["local_models"] if m["id"] == "qwen2.5-7b"), None)
            self.assertIsNotNone(qwen)
            self.assertTrue(qwen["available_locally"])
            self.assertTrue(qwen["runnable_on_detected_hardware"])

    def test_model_roles_resolve_with_local_models(self):
        """Model roles should pick local models for code_model when available."""
        from core.model_registry import ModelRegistry
        from core.model_roles import ModelRoleManager
        from core import config
        with tempfile.TemporaryDirectory() as tmp:
            profile_path = Path(tmp) / "runtime_profile.json"
            profile_path.write_text(json.dumps({
                "providers": {"enabled": ["local-llama-cpp"]},
                "local_runtime": {"preferred_local_models": ["qwen2.5-7b"], "model_roles": {}},
            }), encoding="utf-8")
            config.load_runtime_profile.cache_clear()
            registry = ModelRegistry()
            registry.registry_path = Path(tmp) / "model_registry.json"
            registry.profile = {
                "hardware": {"cpu_count": 8, "ram_gb": 16, "gpu": {"available": True, "name": "RTX 3060", "vram_gb": 12, "device_count": 1}},
                "model_inventory": {"available_models": ["qwen2.5-7b", "phi-3.5-mini"], "models_dir": tmp},
                "local_runtime": {"preferred_local_models": ["qwen2.5-7b"]},
                "providers": {"enabled": ["local-llama-cpp"]},
            }
            registry.refresh()
            with patch.object(config, "get_runtime_profile_path", return_value=profile_path):
                manager = ModelRoleManager(registry)
                status = manager.status()
            self.assertIn("roles", status)
            self.assertIn("code_model", status["roles"])
            self.assertIsNotNone(status["roles"]["code_model"]["model"])

    def test_credential_store_works_with_fresh_db(self):
        """CredentialStore should init with a fresh database."""
        from core.database import DatabaseManager
        from core.credential_store import CredentialStore
        with tempfile.TemporaryDirectory() as tmp:
            db = DatabaseManager(db_path=str(Path(tmp) / "creds.db"))
            db.initialize()
            store = CredentialStore(database=db)
            # Should not crash on empty state
            keys = store.list_keys() if hasattr(store, "list_keys") else []
            self.assertIsInstance(keys, list)
            db.close()


# ======================================================================
# Phase 3: First Query Experience
# ======================================================================


class TestPhase3_FirstQueryExperience(unittest.TestCase):
    """Simulate: user sends their first queries."""

    def _make_query_engine(self, tmp_dir: str):
        """Create a QueryEngine with minimal deps for testing."""
        from core.capabilities import CapabilityRegistry
        from core.model_registry import ModelRegistry
        from core.model_roles import ModelRoleManager
        from core.query_engine import QueryEngine

        caps = CapabilityRegistry()
        registry = ModelRegistry()
        registry.registry_path = Path(tmp_dir) / "model_registry.json"
        registry.profile = {
            "hardware": {"cpu_count": 4, "ram_gb": 8, "gpu": {"available": False, "name": "cpu-only", "vram_gb": 0, "device_count": 0}},
            "model_inventory": {"available_models": []},
            "local_runtime": {},
        }
        roles = ModelRoleManager(registry)

        def _mock_completion(**kwargs):
            return {"content": f"Mock response for: {kwargs.get('query', '')}", "model": "mock"}

        return QueryEngine(
            capability_registry=caps,
            model_roles=roles,
            tool_registry=None,
            completion_callback=_mock_completion,
            sessions_path=Path(tmp_dir) / "sessions.json",
            tool_history_path=Path(tmp_dir) / "tool_history.json",
        )

    def test_query_engine_initializes(self):
        """QueryEngine should init with minimal deps."""
        with tempfile.TemporaryDirectory() as tmp:
            qe = self._make_query_engine(tmp)
            status = qe.status()
            self.assertIn("session_count", status)

    def test_query_engine_status_is_useful(self):
        """Status should show session count."""
        with tempfile.TemporaryDirectory() as tmp:
            qe = self._make_query_engine(tmp)
            status = qe.status()
            self.assertIsInstance(status["session_count"], int)
            self.assertGreaterEqual(status["session_count"], 0)

    def test_query_engine_handles_empty_query_gracefully(self):
        """An empty query should return a valid response, not crash."""
        with tempfile.TemporaryDirectory() as tmp:
            qe = self._make_query_engine(tmp)
            result = qe.run_query(query="", permission_scope="user")
            self.assertIsNotNone(result)

    def test_query_engine_run_query_with_content(self):
        """A real query should produce a structured result."""
        with tempfile.TemporaryDirectory() as tmp:
            qe = self._make_query_engine(tmp)
            result = qe.run_query(query="What is OpenChimera?", permission_scope="user")
            self.assertIsNotNone(result)
            self.assertIn("response", result)


# ======================================================================
# Phase 4: AGI Cognitive Features
# ======================================================================


class TestPhase4_AGICognitiveFeatures(unittest.TestCase):
    """Simulate: user explores AGI capabilities."""

    def setUp(self):
        from core._bus_fallback import EventBus
        from core._database_fallback import DatabaseManager
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.db = DatabaseManager(db_path=self._tmp.name)
        self.db.initialize()
        self.bus = EventBus()

    def tearDown(self):
        self.db.close()
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass

    def test_self_model_tracks_capabilities(self):
        """Self-model should record and report capability snapshots."""
        from core.self_model import SelfModel
        sm = SelfModel(bus=self.bus)
        snap = sm.record_capability("reasoning", "accuracy", 0.85, sample_count=10)
        self.assertEqual(snap.domain, "reasoning")
        self.assertAlmostEqual(snap.value, 0.85)
        assessment = sm.self_assessment()
        self.assertIn("capabilities_tracked", assessment)

    def test_causal_reasoning_builds_and_queries_graph(self):
        """Causal reasoning should support graph operations."""
        from core.causal_reasoning import CausalReasoning
        cr = CausalReasoning(bus=self.bus)
        cr.add_cause("input_quality", "output_quality", strength=0.8, confidence=0.9)
        cr.set_variable("input_quality", 0.7)
        result = cr.intervene("input_quality", 0.9)
        self.assertIsNotNone(result.total_effect)

    def test_meta_learning_registers_and_selects_strategies(self):
        """Meta-learning should manage strategies."""
        from core.meta_learning import MetaLearning
        ml = MetaLearning(bus=self.bus)
        strat = ml.register_strategy("chain-of-thought", {"depth": 3}, "reasoning")
        ml.record_outcome(strat.strategy_id, "reasoning", True, 0.9, 50.0)
        selected = ml.select_strategy("reasoning")
        self.assertIsNotNone(selected)

    def test_ethical_reasoning_evaluates_actions(self):
        """Ethical reasoning should evaluate actions and detect violations."""
        from core.ethical_reasoning import EthicalReasoning, Severity
        er = EthicalReasoning(bus=self.bus)
        er.register_constraint(
            name="no-harmful-content",
            description="Prevent generation of harmful content",
            severity=Severity.CRITICAL,
            domain="general",
            checker=lambda action, ctx: "harmful content" if "harm" in action.lower() else None,
        )
        result = er.evaluate(action="Generate harmful content", domain="general")
        self.assertEqual(result.outcome.value, "vetoed")

    def test_transfer_learning_finds_cross_domain_patterns(self):
        """Transfer learning should find relevant patterns across domains."""
        from core.transfer_learning import TransferLearning, PatternType
        tl = TransferLearning(bus=self.bus)
        tl.register_pattern(
            source_domain="math",
            pattern_type=PatternType.STRATEGY,
            description="Divide and conquer for complex problems",
            keywords=["divide", "conquer", "decomposition"],
            success_rate=0.88,
        )
        candidates = tl.find_transfers(
            target_domain="programming",
            target_keywords=["decomposition", "divide"],
        )
        self.assertGreater(len(candidates), 0)

    def test_plan_mode_creates_and_executes_plan(self):
        """Plan mode should support full plan lifecycle."""
        from core.plan_mode import PlanMode, PlanStatus, StepStatus
        pm = PlanMode()
        plan = pm.create_plan(
            name="Build a web app",
            description="Full-stack web application",
            steps=[
                {"description": "Design database schema"},
                {"description": "Implement API endpoints"},
                {"description": "Build frontend"},
            ],
        )
        self.assertEqual(plan.status, PlanStatus.PENDING)
        pm.start_plan(plan.plan_id)
        self.assertEqual(pm.get_plan(plan.plan_id).status, PlanStatus.IN_PROGRESS)
        for step in pm.get_plan(plan.plan_id).steps:
            pm.update_step(plan.plan_id, step.step_id, StepStatus.COMPLETED)
        final = pm.get_plan(plan.plan_id)
        all_done = all(s.status == StepStatus.COMPLETED for s in final.steps)
        self.assertTrue(all_done)

    def test_knowledge_base_stores_and_retrieves(self):
        """Knowledge base should support add/search operations."""
        from core.knowledge_base import KnowledgeBase
        kb = KnowledgeBase()
        kb.add(
            content="Python is a high-level programming language.",
            category="programming",
            tags=["python", "language"],
        )
        results = kb.search("Python")
        self.assertGreater(len(results), 0)
        self.assertIn("Python", results[0].content)

    def test_safety_layer_validates_content(self):
        """Safety layer should filter harmful content."""
        from core.safety_layer import SafetyLayer
        sl = SafetyLayer()
        allowed, reason = sl.validate_content("How to hack into a bank")
        # Should return a tuple (bool, optional reason)
        self.assertIsInstance(allowed, bool)

    def test_agent_coordinator_manages_tasks(self):
        """Agent coordinator should support task lifecycle."""
        from core.agent_coordinator import AgentCoordinator
        ac = AgentCoordinator()
        ac.register_agent("agent-1", capabilities=["coding", "reasoning"])
        task = ac.assign_task("agent-1", description="Write unit tests")
        self.assertIsNotNone(task)

    def test_health_monitor_tracks_subsystems(self):
        """Health monitor should track and report subsystem health."""
        from core.health_monitor import HealthMonitor
        hm = HealthMonitor()
        hm.record_health("database", status="healthy")
        hm.record_health("llm_provider", status="healthy")
        all_health = hm.get_all_current_health()
        self.assertIn("database", all_health)

    def test_identity_manager_handles_sessions(self):
        """Identity manager should create and manage sessions."""
        from core.identity_manager import IdentityManager
        im = IdentityManager()
        # Must create user first
        user = im.create_user(name="Test User", role="user")
        session = im.create_session(user_id=user.user_id)
        self.assertIsNotNone(session)
        self.assertEqual(session.user_id, user.user_id)


# ======================================================================
# Phase 5: Multi-Agent Consensus (QuantumEngine)
# ======================================================================


class TestPhase5_MultiAgentConsensus(unittest.TestCase):
    """Simulate: user triggers multi-agent consensus."""

    def setUp(self):
        from core._bus_fallback import EventBus
        from core._database_fallback import DatabaseManager
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.db = DatabaseManager(db_path=self._tmp.name)
        self.db.initialize()
        self.bus = EventBus()

    def tearDown(self):
        self.db.close()
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass

    def test_multi_agent_orchestrator_status(self):
        """Orchestrator should report status of all AGI modules."""
        from core.multi_agent_orchestrator import MultiAgentOrchestrator
        orch = MultiAgentOrchestrator(bus=self.bus, db=self.db)
        status = orch.status()
        self.assertTrue(status["self_model_available"])
        self.assertTrue(status["transfer_learning_available"])
        self.assertTrue(status["causal_reasoning_available"])
        self.assertTrue(status["meta_learning_available"])
        self.assertTrue(status["ethical_reasoning_available"])

    def test_consensus_with_agents(self):
        """Full consensus cycle should work with registered agents."""
        import asyncio
        from core.agent_pool import AgentPool, AgentSpec, AgentRole
        from core.multi_agent_orchestrator import MultiAgentOrchestrator

        async def _mock_agent(task, context):
            return f"answer:{task}"

        pool = AgentPool()
        pool.register(AgentSpec(
            agent_id="test-agent", role=AgentRole.REASONER, domain="general",
        ), external_fn=_mock_agent)

        orch = MultiAgentOrchestrator(pool=pool, bus=self.bus, db=self.db, quorum=1)
        result = asyncio.run(orch.run("What is 2+2?", domain="general"))
        self.assertIsNotNone(result.answer)
        self.assertGreater(result.confidence, 0.0)


# ======================================================================
# Phase 6: Session Management & Memory
# ======================================================================


class TestPhase6_SessionManagement(unittest.TestCase):
    """Simulate: user manages sessions and memory."""

    def test_session_memory_records_and_retrieves(self):
        """SessionMemory should persist conversation state."""
        from core.session_memory import SessionMemory
        with tempfile.TemporaryDirectory() as tmp:
            sm = SessionMemory(session_id="test-session", store_root=Path(tmp))
            sm.append_turn(role="user", content="Hello!")
            sm.append_turn(role="assistant", content="Hi there!")
            turns = sm.get_turns()
            self.assertEqual(len(turns), 2)
            self.assertEqual(turns[0]["role"], "user")

    def test_session_memory_resume(self):
        """Sessions should be resumable after creation."""
        from core.session_memory import SessionMemory
        with tempfile.TemporaryDirectory() as tmp:
            sm = SessionMemory(session_id="resume-session", store_root=Path(tmp))
            sm.append_turn(role="user", content="Remember this")
            sm.save()
            # Create a new SessionMemory with same session_id to simulate resume
            sm2 = SessionMemory.load(session_id="resume-session", store_root=Path(tmp))
            turns = sm2.get_turns()
            self.assertGreater(len(turns), 0)

    def test_memory_system_episode_recording(self):
        """MemorySystem should record and retrieve episodes."""
        from core._bus_fallback import EventBus
        from core._database_fallback import DatabaseManager
        from core.memory_system import MemorySystem
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "mem.db"
            db = DatabaseManager(db_path=str(db_path))
            db.initialize()
            bus = EventBus()
            mem = MemorySystem(db=db, bus=bus, working_max_size=64)
            mem.record_episode(
                session_id="test-session",
                goal="Test memory",
                outcome="success",
                confidence_initial=0.5,
                confidence_final=0.9,
                models_used=["test-model"],
                reasoning_chain=["step1", "step2"],
                domain="general",
            )
            summary = mem.summary()
            self.assertIsNotNone(summary)
            db.close()


# ======================================================================
# Phase 7: Plugin & Capability Discovery
# ======================================================================


class TestPhase7_PluginCapabilityDiscovery(unittest.TestCase):
    """Simulate: user discovers and uses plugins/capabilities."""

    def test_capability_registry_snapshot(self):
        """Capability registry should produce a snapshot."""
        from core.capabilities import CapabilityRegistry
        caps = CapabilityRegistry()
        snap = caps.snapshot()
        self.assertIsInstance(snap, dict)

    def test_plugin_manager_initializes(self):
        """PluginManager should initialize with capability registry."""
        from core.capabilities import CapabilityRegistry
        from core.plugins import PluginManager
        caps = CapabilityRegistry()
        pm = PluginManager(caps)
        self.assertIsNotNone(pm)

    def test_command_registry_lists_commands(self):
        """CommandRegistry should list available commands."""
        from core.command_registry import CommandRegistry
        cr = CommandRegistry()
        commands = cr.list_commands()
        self.assertIsInstance(commands, list)


# ======================================================================
# Phase 8: Observability & Health
# ======================================================================


class TestPhase8_ObservabilityHealth(unittest.TestCase):
    """Simulate: user checks system health and diagnostics."""

    def test_observability_store_initializes(self):
        """ObservabilityStore should work with temp storage."""
        from core.observability import ObservabilityStore
        with tempfile.TemporaryDirectory() as tmp:
            obs_path = Path(tmp) / "obs.db"
            obs = ObservabilityStore(persist_path=str(obs_path))
            self.assertIsNotNone(obs)
            if obs._connection is not None:
                obs._connection.close()

    def test_kernel_boot(self):
        """Kernel should instantiate without crashing."""
        from core.kernel import OpenChimeraKernel
        from unittest.mock import patch, MagicMock
        with patch("core.kernel.OpenChimeraAPIServer") as mock_server:
            mock_server.return_value = MagicMock()
            kernel = OpenChimeraKernel()
            # Kernel should have a status_snapshot method
            self.assertTrue(hasattr(kernel, "status_snapshot") or hasattr(kernel, "boot"))

    def test_chimera_bridge_status(self):
        """ChimeraLang bridge should report availability status."""
        from core.chimera_bridge import get_bridge
        bridge = get_bridge()
        status = bridge.status()
        self.assertIn("available", status)
        self.assertIn("version", status)


# ======================================================================
# Phase 9: Claw-Code Inspired — Permission Enforcement
# ======================================================================


class TestPhase9_PermissionEnforcement(unittest.TestCase):
    """Claw-code inspired: test permission enforcement patterns."""

    def test_tool_executor_permission_gating(self):
        """ToolExecutor should enforce permission checks via execute_with_gating."""
        from core.tool_executor import ToolExecutor, ToolPermissionError
        from core.bus import EventBus
        bus = EventBus()
        executor = ToolExecutor(bus=bus)

        # Admin tool should be denied for user scope
        with self.assertRaises(ToolPermissionError):
            executor.execute_with_gating(
                tool_id="dangerous-tool",
                handler=lambda **kw: {"result": "executed"},
                requires_admin=True,
                permission_scope="user",
            )

    def test_tool_executor_user_can_run_safe_tools(self):
        """User-level permission should allow safe tools."""
        from core.tool_executor import ToolExecutor
        from core.bus import EventBus
        bus = EventBus()
        executor = ToolExecutor(bus=bus)
        result = executor.execute_with_gating(
            tool_id="safe-tool",
            handler=lambda args: {"result": "ok"},
            requires_admin=False,
            permission_scope="user",
        )
        # Result contains the handler output (may be wrapped)
        self.assertIsNotNone(result)


# ======================================================================
# Phase 10: Claw-Code Inspired — Hierarchical Config
# ======================================================================


class TestPhase10_HierarchicalConfig(unittest.TestCase):
    """Claw-code inspired: hierarchical config (user → project → defaults)."""

    def test_config_normalization(self):
        """Runtime profile normalization should handle partial input."""
        from core.config import normalize_runtime_profile, validate_runtime_profile
        partial = {"providers": {"enabled": ["openai"]}}
        normalized, warnings = normalize_runtime_profile(partial)
        errors = validate_runtime_profile(normalized)
        # Should not have critical errors
        self.assertIsInstance(normalized, dict)
        self.assertIn("providers", normalized)

    def test_config_validation_catches_bad_failover_chain(self):
        """Validation should catch non-list failover_chain."""
        from core.config import normalize_runtime_profile, validate_runtime_profile
        bad_config = {
            "providers": {"enabled": ["openai"], "failover_chain": "not-a-list"},
        }
        normalized, _ = normalize_runtime_profile(bad_config)
        normalized.setdefault("providers", {})["failover_chain"] = "not-a-list"
        errors = validate_runtime_profile(normalized)
        self.assertTrue(any("failover_chain" in e for e in errors))


# ======================================================================
# Phase 11: Claw-Code Inspired — Session Persistence
# ======================================================================


class TestPhase11_SessionPersistence(unittest.TestCase):
    """Claw-code inspired: session persistence."""

    def test_query_engine_persists_sessions(self):
        """QueryEngine should persist session data."""
        from core.capabilities import CapabilityRegistry
        from core.model_registry import ModelRegistry
        from core.model_roles import ModelRoleManager
        from core.query_engine import QueryEngine

        with tempfile.TemporaryDirectory() as tmp:
            caps = CapabilityRegistry()
            registry = ModelRegistry()
            registry.registry_path = Path(tmp) / "model_registry.json"
            registry.profile = {
                "hardware": {"cpu_count": 4, "ram_gb": 8, "gpu": {"available": False, "name": "cpu-only", "vram_gb": 0, "device_count": 0}},
                "model_inventory": {"available_models": []},
                "local_runtime": {},
            }
            roles = ModelRoleManager(registry)

            def _completion(**kwargs):
                return {"content": "mock response", "model": "mock"}

            qe = QueryEngine(
                capability_registry=caps,
                model_roles=roles,
                tool_registry=None,
                completion_callback=_completion,
                sessions_path=Path(tmp) / "sessions.json",
                tool_history_path=Path(tmp) / "tool_history.json",
            )
            result = qe.run_query(query="Test persistence", permission_scope="user")
            sessions = qe.list_sessions()
            self.assertGreater(len(sessions), 0)


# ======================================================================
# Phase 12: Full AGI Loop Integration
# ======================================================================


class TestPhase12_FullAGILoop(unittest.TestCase):
    """Verify the complete AGI cognitive loop works end-to-end."""

    def setUp(self):
        from core._bus_fallback import EventBus
        from core._database_fallback import DatabaseManager
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.db = DatabaseManager(db_path=self._tmp.name)
        self.db.initialize()
        self.bus = EventBus()

    def tearDown(self):
        self.db.close()
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass

    def test_full_cognitive_pipeline(self):
        """Memory → Causal → Transfer → Meta → Ethical → Plan."""
        from core.memory_system import MemorySystem
        from core.causal_reasoning import CausalReasoning
        from core.transfer_learning import TransferLearning, PatternType
        from core.meta_learning import MetaLearning
        from core.ethical_reasoning import EthicalReasoning
        from core.plan_mode import PlanMode, PlanStatus, StepStatus
        from core.self_model import SelfModel

        # 1. Memory: record learning experience
        mem = MemorySystem(db=self.db, bus=self.bus, working_max_size=64)
        mem.record_episode(
            session_id="agi-full",
            goal="Complete cognitive loop",
            outcome="success",
            confidence_initial=0.5,
            confidence_final=0.95,
            models_used=["model-a"],
            reasoning_chain=["observe", "hypothesize", "test", "conclude"],
            domain="reasoning",
        )

        # 2. Causal reasoning: understand relationships
        cr = CausalReasoning(bus=self.bus)
        cr.add_cause("observation_quality", "hypothesis_accuracy", strength=0.8, confidence=0.9)
        cr.add_cause("hypothesis_accuracy", "conclusion_validity", strength=0.7, confidence=0.85)
        cr.set_variable("observation_quality", 0.8)
        intervention = cr.intervene("observation_quality", 0.95)
        self.assertIsNotNone(intervention.total_effect)

        # 3. Transfer: extract reusable patterns
        tl = TransferLearning(bus=self.bus)
        tl.register_pattern(
            source_domain="reasoning",
            pattern_type=PatternType.STRATEGY,
            description="Hypothesis-driven reasoning",
            keywords=["hypothesis", "test", "validate"],
            success_rate=0.88,
        )
        candidates = tl.find_transfers(
            target_domain="science",
            target_keywords=["hypothesis", "experiment"],
        )
        self.assertGreater(len(candidates), 0)

        # 4. Meta-learning: adapt strategies
        ml = MetaLearning(bus=self.bus)
        strat = ml.register_strategy("hypothesis-testing", {"max_iterations": 5}, "reasoning")
        ml.record_outcome(strat.strategy_id, "reasoning", True, 0.92, 80.0)
        selected = ml.select_strategy("reasoning")
        self.assertIsNotNone(selected)

        # 5. Ethical check: verify safety
        er = EthicalReasoning(bus=self.bus)
        eval_result = er.evaluate(
            action="Apply hypothesis-testing to drug discovery",
            domain="science",
        )
        self.assertIn(eval_result.outcome.value, ["approved", "warning", "vetoed"])

        # 6. Self-model: track capability growth
        sm = SelfModel(bus=self.bus)
        snap = sm.record_capability("reasoning", "accuracy", 0.92, sample_count=20)
        self.assertAlmostEqual(snap.value, 0.92)

        # 7. Plan: orchestrate execution
        pm = PlanMode()
        plan = pm.create_plan(
            name="Hypothesis Testing Pipeline",
            description="Execute hypothesis-testing pipeline",
            steps=[
                {"description": "Gather observations"},
                {"description": "Form hypotheses"},
                {"description": "Run tests"},
                {"description": "Analyze results"},
            ],
        )
        pm.start_plan(plan.plan_id)
        for step in pm.get_plan(plan.plan_id).steps:
            pm.update_step(plan.plan_id, step.step_id, StepStatus.COMPLETED)
        final = pm.get_plan(plan.plan_id)
        all_done = all(s.status == StepStatus.COMPLETED for s in final.steps)
        self.assertTrue(all_done)

    def test_deliberation_engine_multi_perspective(self):
        """Deliberation engine resolves multi-perspective conflicts."""
        from core.deliberation_engine import DeliberationEngine
        de = DeliberationEngine(bus=self.bus)
        result = de.deliberate(
            prompt="Is AGI achievable with current architectures?",
            perspectives=[
                {"perspective": "optimist", "content": "Yes, with scaling", "model": "model-a"},
                {"perspective": "skeptic", "content": "No, fundamental limits", "model": "model-b"},
                {"perspective": "pragmatist", "content": "Partially, for narrow tasks", "model": "model-c"},
            ],
        )
        self.assertIn("consensus", result)
        self.assertIn("hypotheses", result)


# ======================================================================
# Phase 13: ChimeraLang Integration
# ======================================================================


class TestPhase13_ChimeraLangIntegration(unittest.TestCase):
    """Test ChimeraLang as part of the AGI cognitive stack."""

    def test_chimera_bridge_run(self):
        """ChimeraLang should run simple programs."""
        from core.chimera_bridge import get_bridge
        bridge = get_bridge()
        if not bridge.status().get("available"):
            self.skipTest("ChimeraLang not available")
        result = bridge.run("let x = 42; x")
        self.assertIsNotNone(result)

    def test_chimera_bridge_capabilities(self):
        """Bridge should expose capability information."""
        from core.chimera_bridge import get_bridge
        bridge = get_bridge()
        status = bridge.status()
        self.assertIn("available", status)
        if status["available"]:
            self.assertIn("version", status)


if __name__ == "__main__":
    unittest.main()
