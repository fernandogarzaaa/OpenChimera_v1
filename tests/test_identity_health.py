"""Tests for IdentityManager and HealthMonitor."""
import time

import pytest

from core.identity_manager import IdentityManager
from core.health_monitor import HealthMonitor


class TestIdentityManager:
    @pytest.fixture
    def identity_mgr(self):
        return IdentityManager()
    
    def test_system_identity_created(self, identity_mgr):
        system_user = identity_mgr.get_user("system")
        assert system_user is not None
        assert system_user.role == "system"
    
    def test_create_user(self, identity_mgr):
        user = identity_mgr.create_user("Test User", role="operator")
        assert user.name == "Test User"
        assert user.role == "operator"
    
    def test_update_user(self, identity_mgr):
        user = identity_mgr.create_user("Original Name")
        assert identity_mgr.update_user(user.user_id, name="New Name", role="admin")
        
        updated = identity_mgr.get_user(user.user_id)
        assert updated.name == "New Name"
        assert updated.role == "admin"
    
    def test_create_session(self, identity_mgr):
        user = identity_mgr.create_user("User")
        session = identity_mgr.create_session(user.user_id, context={"key": "value"})
        
        assert session.user_id == user.user_id
        assert session.active
        assert session.context["key"] == "value"
    
    def test_session_context_update(self, identity_mgr):
        user = identity_mgr.create_user("User")
        session = identity_mgr.create_session(user.user_id)
        
        assert identity_mgr.update_session_context(session.session_id, {"new_key": "new_value"})
        
        updated = identity_mgr.get_session(session.session_id)
        assert updated.context["new_key"] == "new_value"
    
    def test_end_session(self, identity_mgr):
        user = identity_mgr.create_user("User")
        session = identity_mgr.create_session(user.user_id)
        
        assert identity_mgr.end_session(session.session_id)
        
        ended = identity_mgr.get_session(session.session_id)
        assert not ended.active
    
    def test_get_active_sessions(self, identity_mgr):
        user1 = identity_mgr.create_user("User1")
        user2 = identity_mgr.create_user("User2")
        
        session1 = identity_mgr.create_session(user1.user_id)
        session2 = identity_mgr.create_session(user2.user_id)
        identity_mgr.create_session(user1.user_id)  # Another for user1
        
        all_active = identity_mgr.get_active_sessions()
        assert len(all_active) == 3
        
        user1_sessions = identity_mgr.get_active_sessions(user1.user_id)
        assert len(user1_sessions) == 2
    
    def test_cleanup_inactive_sessions(self, identity_mgr):
        user = identity_mgr.create_user("User")
        session = identity_mgr.create_session(user.user_id)
        
        # Manually set old last_activity
        session.last_activity = time.time() - 7200  # 2 hours ago
        
        cleaned = identity_mgr.cleanup_inactive_sessions(timeout_seconds=3600)  # 1 hour timeout
        assert cleaned == 1


class TestHealthMonitor:
    @pytest.fixture
    def monitor(self):
        return HealthMonitor()
    
    def test_record_health(self, monitor):
        monitor.record_health("subsystem1", "healthy", details={"uptime": 100})
        
        current = monitor.get_current_health("subsystem1")
        assert current.status == "healthy"
        assert current.details["uptime"] == 100
    
    def test_health_history(self, monitor):
        monitor.record_health("subsystem1", "healthy")
        time.sleep(0.01)
        monitor.record_health("subsystem1", "degraded")
        time.sleep(0.01)
        monitor.record_health("subsystem1", "healthy")
        
        history = monitor.get_health_history("subsystem1")
        assert len(history) == 3
        assert history[0].status == "healthy"  # Most recent
        assert history[1].status == "degraded"
    
    def test_aggregate_status(self, monitor):
        monitor.record_health("sub1", "healthy")
        monitor.record_health("sub2", "healthy")
        assert monitor.get_aggregate_status() == "healthy"
        
        monitor.record_health("sub3", "degraded")
        assert monitor.get_aggregate_status() == "degraded"
        
        monitor.record_health("sub4", "failed")
        assert monitor.get_aggregate_status() == "failed"
    
    def test_get_subsystems_by_status(self, monitor):
        monitor.record_health("sub1", "healthy")
        monitor.record_health("sub2", "healthy")
        monitor.record_health("sub3", "failed")
        
        healthy = monitor.get_subsystems_by_status("healthy")
        assert len(healthy) == 2
        assert "sub1" in healthy
        
        failed = monitor.get_subsystems_by_status("failed")
        assert len(failed) == 1
        assert "sub3" in failed
    
    def test_check_degradation(self, monitor):
        # Record 5 checks with 4 failures
        monitor.record_health("sub1", "healthy")
        monitor.record_health("sub1", "failed")
        monitor.record_health("sub1", "failed")
        monitor.record_health("sub1", "degraded")
        monitor.record_health("sub1", "failed")
        
        # With threshold 0.6, 4/5 = 0.8 should trigger
        assert monitor.check_degradation("sub1", window_size=5, threshold=0.6)
        
        # With threshold 0.9, 4/5 = 0.8 should not trigger
        assert not monitor.check_degradation("sub1", window_size=5, threshold=0.9)
    
    def test_status(self, monitor):
        monitor.record_health("sub1", "healthy")
        monitor.record_health("sub2", "degraded")
        monitor.record_health("sub3", "failed")
        
        status = monitor.status()
        assert status["tracked_subsystems"] == 3
        assert status["healthy"] == 1
        assert status["degraded"] == 1
        assert status["failed"] == 1
        assert status["aggregate_status"] == "failed"
