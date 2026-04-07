"""Tests for RBAC enforcement in CommandRegistry."""
import pytest
from core.command_registry import CommandEntry, CommandRegistry
from core.bus import EventBus


def test_admin_command_requires_admin():
    """Test that commands marked requires_admin raise PermissionError for non-admin users."""
    bus = EventBus()
    registry = CommandRegistry(bus=bus)
    
    def admin_handler():
        return "admin action executed"
    
    cmd = CommandEntry(
        id="admin.delete_all",
        name="Delete All",
        description="Deletes all data",
        requires_admin=True,
        handler=admin_handler,
    )
    registry.register(cmd)
    
    # Should raise PermissionError for non-admin
    with pytest.raises(PermissionError, match="requires admin privileges"):
        registry.execute("admin.delete_all", is_admin=False)
    
    # Should work for admin
    result = registry.execute("admin.delete_all", is_admin=True)
    assert result == "admin action executed"


def test_regular_command_works_for_all():
    """Test that regular commands work for both admin and non-admin users."""
    registry = CommandRegistry()
    
    def regular_handler():
        return "regular action executed"
    
    cmd = CommandEntry(
        id="regular.action",
        name="Regular Action",
        description="A regular action",
        requires_admin=False,
        handler=regular_handler,
    )
    registry.register(cmd)
    
    # Should work for non-admin
    result = registry.execute("regular.action", is_admin=False)
    assert result == "regular action executed"
    
    # Should also work for admin
    result = registry.execute("regular.action", is_admin=True)
    assert result == "regular action executed"


def test_security_event_emitted_on_unauthorized_access():
    """Test that security.unauthorized_access event is emitted when access is denied."""
    bus = EventBus()
    events = []
    
    def event_handler(payload):
        events.append(("security.unauthorized_access", payload))
    
    bus.subscribe("security.unauthorized_access", event_handler)
    
    registry = CommandRegistry(bus=bus)
    
    def admin_handler():
        return "admin action"
    
    cmd = CommandEntry(
        id="admin.config",
        name="Config Admin",
        description="Admin config",
        requires_admin=True,
        handler=admin_handler,
    )
    registry.register(cmd)
    
    # Try to execute as non-admin
    with pytest.raises(PermissionError):
        registry.execute("admin.config", is_admin=False, permission_scope="user")
    
    # Check that security event was emitted
    security_events = [e for e in events if e[0] == "security.unauthorized_access"]
    assert len(security_events) == 1
    topic, payload = security_events[0]
    assert payload["command_id"] == "admin.config"
    assert payload["requires_admin"] is True
    assert payload["permission_scope"] == "user"


def test_permission_scope_defaults_to_user():
    """Test that permission_scope defaults to 'user' when not provided."""
    bus = EventBus()
    events = []
    
    def event_handler(payload):
        events.append(("security.unauthorized_access", payload))
    
    bus.subscribe("security.unauthorized_access", event_handler)
    
    registry = CommandRegistry(bus=bus)
    
    cmd = CommandEntry(
        id="admin.reset",
        name="Reset",
        description="Reset system",
        requires_admin=True,
        handler=lambda: "reset",
    )
    registry.register(cmd)
    
    # Try to execute without permission_scope
    with pytest.raises(PermissionError):
        registry.execute("admin.reset", is_admin=False)
    
    # Check that default permission_scope is "user"
    security_events = [e for e in events if e[0] == "security.unauthorized_access"]
    assert len(security_events) == 1
    assert security_events[0][1]["permission_scope"] == "user"


def test_unknown_command_raises_value_error():
    """Test that executing unknown command raises ValueError."""
    registry = CommandRegistry()
    
    with pytest.raises(ValueError, match="Unknown command"):
        registry.execute("nonexistent.command")


def test_command_without_handler_raises_not_implemented():
    """Test that commands without handlers raise NotImplementedError."""
    registry = CommandRegistry()
    
    cmd = CommandEntry(
        id="no.handler",
        name="No Handler",
        description="Command without handler",
        handler=None,
    )
    registry.register(cmd)
    
    with pytest.raises(NotImplementedError, match="no executable handler"):
        registry.execute("no.handler")
