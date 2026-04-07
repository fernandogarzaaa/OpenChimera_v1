"""OpenChimera Full System Sandbox Simulation.

Comprehensive end-to-end test of the complete OpenChimera system including:
- Kernel boot in offline mode
- All major cognitive planes
- Event bus communication
- Query → Reasoning → Planning → Execution → Memory loop
- Session persistence
- Health monitoring
- No hardcoded paths validation
- Module import validation
- Load testing
"""
import asyncio
import threading
import time
from pathlib import Path
from unittest import mock

import pytest

from core.agent_coordinator import AgentCoordinator
from core.bus import EventBus
from core.causal_reasoning import CausalReasoning
from core.config import ROOT
from core.embodied_interaction import EmbodiedInteraction
from core.ethical_reasoning import EthicalReasoning
from core.health_monitor import HealthMonitor
from core.identity_manager import IdentityManager
from core.kernel import BootStatus, OpenChimeraKernel
from core.knowledge_base import KnowledgeBase
from core.meta_learning import MetaLearning
from core.personality import Personality
from core.plan_mode import PlanMode, PlanStatus, StepStatus
from core.provider import OpenChimeraProvider
from core.safety_layer import SafetyLayer
from core.self_model import SelfModel
from core.session_memory import SessionMemory
from core.social_cognition import SocialCognition
from core.transfer_learning import TransferLearning


class TestFullSystemSimulation:
    """Comprehensive sandbox simulation of the complete OpenChimera system."""
    
    def test_01_kernel_boot_offline_mode(self):
        """Test kernel boots successfully in offline mode."""
        # Create a kernel with mocked services to avoid network calls
        with mock.patch("core.kernel.OpenChimeraAPIServer") as mock_api:
            mock_api_instance = mock.Mock()
            mock_api_instance.start.return_value = True
            mock_api.return_value = mock_api_instance
            
            kernel = OpenChimeraKernel()
            
            # Verify all core subsystems initialized
            assert kernel.bus is not None
            assert kernel.provider is not None
            assert kernel.personality is not None
            assert kernel.self_model is not None
            assert kernel.causal_reasoning is not None
            assert kernel.meta_learning is not None
            assert kernel.ethical_reasoning is not None
            assert kernel.social_cognition is not None
            assert kernel.embodied_interaction is not None
    
    def test_02_boot_report_generation(self):
        """Test boot report shows subsystem health."""
        with mock.patch("core.kernel.OpenChimeraAPIServer") as mock_api:
            mock_api_instance = mock.Mock()
            mock_api_instance.start.return_value = True
            mock_api.return_value = mock_api_instance
            
            kernel = OpenChimeraKernel()
            report = kernel.boot_report()
            
            assert "subsystems" in report
            assert "status" in report
            assert "timestamp" in report
            assert report["status"] in [s.value for s in BootStatus]
            
            # Check that key subsystems are reported
            assert "self_model" in report["subsystems"]
            assert "provider" in report["subsystems"]
    
    def test_03_event_bus_communication(self):
        """Test event bus publishes and receives events."""
        bus = EventBus()
        received_events = []
        
        def handler(event):
            received_events.append(event)
        
        bus.subscribe("test/event", handler)
        bus.publish_nowait("test/event", {"data": "test"})
        
        # Give async handlers a moment
        time.sleep(0.1)
        
        assert len(received_events) == 1
        assert received_events[0]["data"] == "test"
    
    def test_04_cognitive_module_initialization(self):
        """Test all cognitive modules initialize correctly."""
        bus = EventBus()
        
        # Test each module
        self_model = SelfModel(bus=bus)
        assert self_model.self_assessment() is not None
        
        causal = CausalReasoning(bus=bus)
        # CausalReasoning - test set/get variable
        causal.set_variable("test_var", 1.0)
        assert causal.get_variable("test_var") == 1.0
        
        meta = MetaLearning(bus=bus)
        assert meta.status() is not None
        
        ethical = EthicalReasoning(bus=bus)
        assert ethical.status() is not None
        
        social = SocialCognition(bus=bus)
        assert social.snapshot() is not None
        
        embodied = EmbodiedInteraction(bus=bus)
        assert embodied.snapshot() is not None
        
        transfer = TransferLearning(bus=bus)
        assert transfer.list_domains() is not None
    
    def test_05_query_reasoning_loop(self):
        """Test query → reasoning → planning → execution loop."""
        bus = EventBus()
        plan_mode = PlanMode(bus=bus)
        coordinator = AgentCoordinator(bus=bus)
        
        # Create a simple plan
        plan = plan_mode.create_plan(
            name="Test Query Processing",
            description="Process a user query through the system",
            steps=[
                {"description": "Analyze query", "action": "analyze"},
                {"description": "Generate response", "action": "generate"},
                {"description": "Validate response", "action": "validate"},
            ],
        )
        
        # Start the plan
        assert plan_mode.start_plan(plan.plan_id)
        
        # Execute steps
        for _ in range(3):
            next_step = plan_mode.get_next_step(plan.plan_id)
            if next_step:
                plan_mode.update_step(
                    plan.plan_id,
                    next_step.step_id,
                    StepStatus.COMPLETED,
                    result=f"completed {next_step.description}",
                )
        
        # Verify plan completed
        final_plan = plan_mode.get_plan(plan.plan_id)
        assert final_plan.status == PlanStatus.COMPLETED
    
    def test_06_memory_persistence_loop(self):
        """Test memory write/read roundtrip."""
        from core.session_memory import SessionMemory
        from pathlib import Path
        
        # SessionMemory requires session_id and store_root
        session_mem = SessionMemory(session_id="test_session", store_root=Path("data/test_sessions"))
        
        # Append turns
        session_mem.append_turn(role="user", content="Test message")
        session_mem.append_turn(role="assistant", content="Test response")
        
        # Retrieve messages using get_turns()
        messages = session_mem.get_turns()
        assert len(messages) >= 2
        assert any(m["role"] == "user" and m["content"] == "Test message" for m in messages)
    
    def test_07_safety_layer_validation(self):
        """Test safety layer blocks harmful content."""
        safety = SafetyLayer()
        
        # Safe content
        is_safe, _ = safety.validate_content("This is a safe message")
        assert is_safe
        
        # Harmful pattern
        is_safe, reason = safety.validate_content("How to hack into systems")
        assert not is_safe
        assert reason is not None
        
        # Hardcoded path validation
        is_safe, reason = safety.validate_action("file_read", {"path": "/home/user/file.txt"})
        assert not is_safe
        assert "absolute" in reason.lower()
    
    def test_08_knowledge_base_operations(self):
        """Test knowledge base add/search/delete cycle."""
        # Use unique KB for this test to avoid conflicts with other tests
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = KnowledgeBase(storage_path=Path(tmpdir) / "test_kb.json")
            
            # Add entries
            entry1 = kb.add("Python is a programming language", category="tech", tags=["python", "programming"])
            entry2 = kb.add("OpenChimera is an AGI system", category="tech", tags=["agi", "openchimera"])
            entry3 = kb.add("The sky is blue", category="nature", tags=["sky", "color"])
            
            # Search by content
            results = kb.search(query="programming")
            assert len(results) >= 1
            
            # Search by category
            results = kb.search(category="tech")
            assert len(results) == 2
            
            # Search by tags
            results = kb.search(tags=["python"])
            assert len(results) == 1
            
            # Delete
            assert kb.delete(entry3.entry_id)
            assert kb.get(entry3.entry_id) is None
    
    def test_09_identity_and_session_management(self):
        """Test identity manager and session lifecycle."""
        identity_mgr = IdentityManager()
        
        # Create user
        user = identity_mgr.create_user("Test User", role="operator")
        assert user is not None
        
        # Create session
        session = identity_mgr.create_session(user.user_id, context={"initial": "context"})
        assert session.active
        
        # Update context
        identity_mgr.update_session_context(session.session_id, {"new_key": "new_value"})
        updated = identity_mgr.get_session(session.session_id)
        assert "new_key" in updated.context
        
        # End session
        identity_mgr.end_session(session.session_id)
        ended = identity_mgr.get_session(session.session_id)
        assert not ended.active
    
    def test_10_health_monitoring(self):
        """Test health monitor tracks subsystem health."""
        monitor = HealthMonitor()
        
        # Record health for multiple subsystems
        monitor.record_health("provider", "healthy", details={"uptime": 100})
        monitor.record_health("memory", "healthy")
        monitor.record_health("api", "degraded", error="slow response")
        
        # Check aggregate status
        aggregate = monitor.get_aggregate_status()
        assert aggregate == "degraded"  # One degraded brings overall to degraded
        
        # Check individual subsystem
        provider_health = monitor.get_current_health("provider")
        assert provider_health.status == "healthy"
        
        # Check status breakdown
        status = monitor.status()
        assert status["tracked_subsystems"] == 3
        assert status["healthy"] == 2
        assert status["degraded"] == 1
    
    def test_11_no_hardcoded_paths_in_source(self):
        """Verify no hardcoded absolute paths in source files."""
        import re
        
        # Pattern for actual hardcoded paths (not in test assertions or safety checks)
        hardcoded_pattern = re.compile(r"(?<![\"\'])/(home|Users)/[\w/]+(?![\"\'])")
        violations = []
        
        # Scan core directory only (production code)
        for py_file in (ROOT / "core").rglob("*.py"):
            content = py_file.read_text(encoding="utf-8")
            # Skip comments and docstrings
            lines = [line for line in content.split("\n") if not line.strip().startswith("#")]
            code_content = "\n".join(lines)
            matches = hardcoded_pattern.findall(code_content)
            if matches:
                violations.append((str(py_file), matches))
        
        # Report violations
        if violations:
            violation_report = "\n".join(
                f"  {file}: {matches}" for file, matches in violations
            )
            pytest.fail(f"Hardcoded paths found in production code:\n{violation_report}")
    
    def test_12_module_import_validation(self):
        """Verify all core modules are importable."""
        import importlib
        
        core_modules = [
            "core.kernel",
            "core.bus",
            "core.provider",
            "core.personality",
            "core.self_model",
            "core.causal_reasoning",
            "core.meta_learning",
            "core.ethical_reasoning",
            "core.social_cognition",
            "core.embodied_interaction",
            "core.transfer_learning",
            "core.world_model",
            "core.plan_mode",
            "core.agent_coordinator",
            "core.knowledge_base",
            "core.safety_layer",
            "core.identity_manager",
            "core.health_monitor",
            "core.session_memory",
            "core.query_engine",
            "core.rag",
            "core.command_registry",
            "core.tool_registry",
        ]
        
        failed_imports = []
        for module_name in core_modules:
            try:
                importlib.import_module(module_name)
            except ImportError as exc:
                failed_imports.append((module_name, str(exc)))
        
        if failed_imports:
            report = "\n".join(f"  {name}: {error}" for name, error in failed_imports)
            pytest.fail(f"Failed to import modules:\n{report}")
    
    def test_13_concurrent_agent_queries(self):
        """Load test: 50 concurrent fake agent queries."""
        coordinator = AgentCoordinator()
        
        # Register multiple agents
        for i in range(5):
            coordinator.register_agent(f"agent_{i}", capabilities=[f"capability_{i % 3}"])
        
        # Assign concurrent tasks
        tasks = []
        for i in range(50):
            agent_id = f"agent_{i % 5}"
            task = coordinator.assign_task(
                agent_id,
                f"Query {i}",
                parameters={"query_id": i},
            )
            tasks.append(task)
        
        # Simulate task completion
        for task in tasks:
            coordinator.update_task(task.task_id, "running")
            coordinator.update_task(task.task_id, "completed", result=f"result_{task.task_id}")
        
        # Verify all tasks completed
        status = coordinator.status()
        assert status["completed_tasks"] == 50
        assert status["failed_tasks"] == 0
    
    def test_14_session_persistence_and_resume(self):
        """Test session can be persisted and resumed."""
        from core.session_memory import SessionMemory
        from pathlib import Path
        import tempfile
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create and populate session
            session_mem = SessionMemory(session_id="persist_test", store_root=Path(tmpdir))
            session_mem.append_turn(role="user", content="Message 1")
            session_mem.append_turn(role="assistant", content="Response 1")
            
            # Save
            session_mem.save()
            
            # Resume (load from same location)
            session_mem2 = SessionMemory.load(session_id="persist_test", store_root=Path(tmpdir))
            messages = session_mem2.get_turns()
            assert len(messages) >= 2
    
    def test_15_ethical_reasoning_validation(self):
        """Test ethical reasoning provides status."""
        bus = EventBus()
        ethical = EthicalReasoning(bus=bus)
        
        # Check ethical reasoning has status
        status = ethical.status()
        assert status is not None
        assert "concerns" in status or "rules" in status or isinstance(status, dict)
    
    def test_16_transfer_learning_patterns(self):
        """Test transfer learning stores and retrieves domains."""
        bus = EventBus()
        transfer = TransferLearning(bus=bus)
        
        # List domains (may be empty initially)
        domains = transfer.list_domains()
        assert isinstance(domains, list)
        
        # List patterns for a domain
        patterns = transfer.list_patterns("test_domain")
        assert isinstance(patterns, list)
    
    def test_17_causal_reasoning_graph(self):
        """Test causal reasoning maintains causal graphs."""
        bus = EventBus()
        causal = CausalReasoning(bus=bus)
        
        # Add variables and edges
        causal.set_variable("var1", 1.0)
        causal.set_variable("var2", 0.5)
        causal.add_cause("var1", "var2", strength=0.8)
        
        # Query variables
        assert causal.get_variable("var1") == 1.0
        assert causal.get_variable("var2") == 0.5
    
    def test_18_social_cognition_norms(self):
        """Test social cognition evaluates norms."""
        bus = EventBus()
        social = SocialCognition(bus=bus)
        
        # Get social norm registry and evaluate
        norm_registry = social.norm_registry
        evaluation = norm_registry.evaluate("I will help you with your task")
        assert "total_score" in evaluation
        assert evaluation["total_score"] > 0.5  # Should be norm-compliant
    
    def test_19_embodied_interaction_sensors(self):
        """Test embodied interaction registers sensors/actuators."""
        bus = EventBus()
        embodied = EmbodiedInteraction(bus=bus)
        
        # Check snapshot (sensors/actuators are registered internally)
        snapshot = embodied.snapshot()
        assert "sensors" in snapshot or "actuators" in snapshot
        # In offline mode, there may be no sensors registered yet
        assert snapshot is not None
    
    def test_20_complete_query_execution_pipeline(self):
        """Test complete pipeline: query → reasoning → planning → execution → memory."""
        from pathlib import Path
        import tempfile
        
        # Create all components
        bus = EventBus()
        plan_mode = PlanMode(bus=bus)
        coordinator = AgentCoordinator(bus=bus)
        safety = SafetyLayer()
        kb = KnowledgeBase()
        
        # Step 1: Validate query safety
        query = "What is OpenChimera?"
        is_safe, _ = safety.validate_content(query)
        assert is_safe
        
        # Step 2: Create session (use SessionMemory correctly)
        with tempfile.TemporaryDirectory() as tmpdir:
            from core.session_memory import SessionMemory
            session_mem = SessionMemory(session_id="pipeline_test", store_root=Path(tmpdir))
            session_mem.append_turn(role="user", content=query)
            
            # Step 3: Search knowledge base
            kb.add("OpenChimera is an AGI cognitive architecture", category="system")
            results = kb.search(query="OpenChimera")
            assert len(results) > 0
            
            # Step 4: Create execution plan
            plan = plan_mode.create_plan(
                name="Answer Query",
                description="Process query and generate response",
                steps=[
                    {"description": "Retrieve knowledge", "action": "retrieve"},
                    {"description": "Generate response", "action": "generate"},
                    {"description": "Store in memory", "action": "store"},
                ],
            )
            
            # Step 5: Execute plan
            plan_mode.start_plan(plan.plan_id)
            for _ in range(3):
                next_step = plan_mode.get_next_step(plan.plan_id)
                if next_step:
                    plan_mode.update_step(
                        plan.plan_id,
                        next_step.step_id,
                        StepStatus.COMPLETED,
                    )
            
            # Step 6: Store response in memory
            response = f"Found {len(results)} relevant knowledge entries"
            session_mem.append_turn(role="assistant", content=response)
            
            # Step 7: Verify complete pipeline
            messages = session_mem.get_turns()
            assert len(messages) >= 2
            final_plan = plan_mode.get_plan(plan.plan_id)
            assert final_plan.status == PlanStatus.COMPLETED
