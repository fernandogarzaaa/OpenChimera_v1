"""Tests for new core components: PlanMode, AgentCoordinator, KnowledgeBase, SafetyLayer."""
import pytest

from core.plan_mode import PlanMode, PlanStatus, StepStatus
from core.agent_coordinator import AgentCoordinator
from core.knowledge_base import KnowledgeBase
from core.safety_layer import SafetyLayer


class TestPlanMode:
    @pytest.fixture
    def plan_mode(self):
        return PlanMode()
    
    def test_create_plan(self, plan_mode):
        plan = plan_mode.create_plan(
            name="Test Plan",
            description="A test plan",
            steps=[
                {"description": "Step 1", "action": "test_action_1"},
                {"description": "Step 2", "action": "test_action_2", "dependencies": []},
            ],
        )
        assert plan.name == "Test Plan"
        assert len(plan.steps) == 2
        assert plan.status == PlanStatus.PENDING
    
    def test_plan_execution(self, plan_mode):
        plan = plan_mode.create_plan(
            name="Sequential Plan",
            description="Test sequential execution",
            steps=[
                {"description": "First", "action": "action1"},
                {"description": "Second", "action": "action2"},
            ],
        )
        
        assert plan_mode.start_plan(plan.plan_id)
        assert plan.status == PlanStatus.IN_PROGRESS
        
        # Get first step
        step1 = plan_mode.get_next_step(plan.plan_id)
        assert step1 is not None
        assert step1.description == "First"
        
        # Complete first step
        plan_mode.update_step(plan.plan_id, step1.step_id, StepStatus.COMPLETED, result="done")
        
        # Get second step
        step2 = plan_mode.get_next_step(plan.plan_id)
        assert step2 is not None
        assert step2.description == "Second"
        
        # Complete second step
        plan_mode.update_step(plan.plan_id, step2.step_id, StepStatus.COMPLETED)
        
        # Plan should be complete
        updated_plan = plan_mode.get_plan(plan.plan_id)
        assert updated_plan.status == PlanStatus.COMPLETED
    
    def test_plan_dependencies(self, plan_mode):
        # Create plan with dependencies
        plan = plan_mode.create_plan(
            name="Dependent Plan",
            description="Test with dependencies",
            steps=[
                {"description": "Step A", "action": "a"},
                {"description": "Step B", "action": "b"},
            ],
        )
        
        plan_mode.start_plan(plan.plan_id)
        
        # Should be able to get next step
        next_step = plan_mode.get_next_step(plan.plan_id)
        assert next_step is not None
    
    def test_pause_resume(self, plan_mode):
        plan = plan_mode.create_plan("Pausable", "Test pause/resume", [{"description": "Step", "action": "test"}])
        plan_mode.start_plan(plan.plan_id)
        
        assert plan_mode.pause_plan(plan.plan_id)
        updated = plan_mode.get_plan(plan.plan_id)
        assert updated.status == PlanStatus.PAUSED
        
        assert plan_mode.resume_plan(plan.plan_id)
        updated = plan_mode.get_plan(plan.plan_id)
        assert updated.status == PlanStatus.IN_PROGRESS


class TestAgentCoordinator:
    @pytest.fixture
    def coordinator(self):
        return AgentCoordinator()
    
    def test_register_agent(self, coordinator):
        coordinator.register_agent("agent1", ["capability1", "capability2"])
        status = coordinator.status()
        assert status["total_agents"] == 1
        assert status["active_agents"] == 1
    
    def test_assign_task(self, coordinator):
        coordinator.register_agent("agent1", ["test"])
        task = coordinator.assign_task("agent1", "Test task", {"param": "value"})
        assert task.agent_id == "agent1"
        assert task.status == "pending"
    
    def test_find_agent_for_capability(self, coordinator):
        coordinator.register_agent("agent1", ["math"])
        coordinator.register_agent("agent2", ["text", "math"])
        
        agent_id = coordinator.find_agent_for_capability("math")
        assert agent_id in ("agent1", "agent2")
    
    def test_task_lifecycle(self, coordinator):
        coordinator.register_agent("agent1", ["test"])
        task = coordinator.assign_task("agent1", "Test")
        
        coordinator.update_task(task.task_id, "running")
        updated = coordinator.get_task(task.task_id)
        assert updated.status == "running"
        assert updated.started_at is not None
        
        coordinator.update_task(task.task_id, "completed", result="success")
        updated = coordinator.get_task(task.task_id)
        assert updated.status == "completed"
        assert updated.result == "success"


class TestKnowledgeBase:
    @pytest.fixture
    def kb(self, tmp_path):
        return KnowledgeBase(storage_path=tmp_path / "test_kb.json")
    
    def test_add_entry(self, kb):
        entry = kb.add("Test knowledge", category="test", tags=["tag1"])
        assert entry.content == "Test knowledge"
        assert entry.category == "test"
        assert "tag1" in entry.tags
    
    def test_search_by_content(self, kb):
        kb.add("Python is a programming language", category="tech")
        kb.add("Java is also a programming language", category="tech")
        kb.add("The sky is blue", category="nature")
        
        results = kb.search(query="programming")
        assert len(results) == 2
    
    def test_search_by_category(self, kb):
        kb.add("Content 1", category="cat1")
        kb.add("Content 2", category="cat2")
        kb.add("Content 3", category="cat1")
        
        results = kb.search(category="cat1")
        assert len(results) == 2
    
    def test_search_by_tags(self, kb):
        kb.add("Entry 1", tags=["tag1", "tag2"])
        kb.add("Entry 2", tags=["tag1"])
        kb.add("Entry 3", tags=["tag2", "tag3"])
        
        results = kb.search(tags=["tag1"])
        assert len(results) == 2
    
    def test_delete_entry(self, kb):
        entry = kb.add("To be deleted")
        assert kb.delete(entry.entry_id)
        assert kb.get(entry.entry_id) is None


class TestSafetyLayer:
    @pytest.fixture
    def safety(self):
        return SafetyLayer()
    
    def test_validate_safe_content(self, safety):
        is_safe, reason = safety.validate_content("This is safe content")
        assert is_safe
        assert reason is None
    
    def test_validate_harmful_content(self, safety):
        is_safe, reason = safety.validate_content("How to hack the system")
        assert not is_safe
        assert reason is not None
    
    def test_validate_safe_action(self, safety):
        is_safe, reason = safety.validate_action(
            "read_file",
            {"path": "relative/path.txt"},
        )
        assert is_safe
    
    def test_validate_dangerous_action_without_admin(self, safety):
        is_safe, reason = safety.validate_action(
            "file_delete",
            {"path": "file.txt"},
            context={"user_role": "user"},
        )
        assert not is_safe
        assert "admin" in reason.lower()
    
    def test_validate_dangerous_action_with_admin(self, safety):
        is_safe, reason = safety.validate_action(
            "file_delete",
            {"path": "file.txt"},
            context={"user_role": "admin"},
        )
        assert is_safe
    
    def test_hardcoded_path_rejection(self, safety):
        is_safe, reason = safety.validate_action(
            "read_file",
            {"path": "/home/user/file.txt"},
        )
        assert not is_safe
        assert "absolute" in reason.lower()
    
    def test_enable_disable(self, safety):
        safety.disable()
        is_safe, _ = safety.validate_content("hack the system")
        assert is_safe  # Safety disabled
        
        safety.enable()
        is_safe, _ = safety.validate_content("hack the system")
        assert not is_safe  # Safety re-enabled
