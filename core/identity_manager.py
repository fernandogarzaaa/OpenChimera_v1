"""OpenChimera IdentityManager — Session identity and user context management.

Manages user identities, session context, and persona switching.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class UserIdentity:
    """User identity record."""
    user_id: str
    name: str
    role: str = "user"  # user, operator, admin, system
    preferences: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)


@dataclass
class Session:
    """User session."""
    session_id: str
    user_id: str
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    context: dict[str, Any] = field(default_factory=dict)
    active: bool = True


class IdentityManager:
    """Session identity and user context management.
    
    Features:
    - User identity management
    - Session tracking
    - Context persistence
    - Role-based access control
    """
    
    def __init__(self, bus: Any | None = None) -> None:
        self._bus = bus
        self._users: dict[str, UserIdentity] = {}
        self._sessions: dict[str, Session] = {}
        self._lock = threading.RLock()
        self._create_system_identity()
        log.info("IdentityManager initialized")
    
    def _create_system_identity(self) -> None:
        """Create the system identity."""
        system_user = UserIdentity(
            user_id="system",
            name="OpenChimera System",
            role="system",
        )
        self._users["system"] = system_user
    
    def create_user(
        self,
        name: str,
        role: str = "user",
        preferences: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> UserIdentity:
        """Create a new user identity."""
        with self._lock:
            user_id = f"user_{uuid.uuid4().hex[:8]}"
            user = UserIdentity(
                user_id=user_id,
                name=name,
                role=role,
                preferences=preferences or {},
                metadata=metadata or {},
            )
            
            self._users[user_id] = user
            
            if self._bus:
                self._bus.publish_nowait("identity/user_created", {
                    "user_id": user_id,
                    "role": role,
                })
            
            log.info("Created user %s (%s)", user_id, name)
            return user
    
    def get_user(self, user_id: str) -> UserIdentity | None:
        """Get a user by ID."""
        with self._lock:
            return self._users.get(user_id)
    
    def update_user(
        self,
        user_id: str,
        name: str | None = None,
        role: str | None = None,
        preferences: dict[str, Any] | None = None,
    ) -> bool:
        """Update user identity."""
        with self._lock:
            user = self._users.get(user_id)
            if user is None:
                return False
            
            if name is not None:
                user.name = name
            if role is not None:
                user.role = role
            if preferences is not None:
                user.preferences.update(preferences)
            
            user.last_seen = time.time()
            return True
    
    def create_session(self, user_id: str, context: dict[str, Any] | None = None) -> Session:
        """Create a new session for a user."""
        with self._lock:
            if user_id not in self._users:
                raise ValueError(f"User {user_id} not found")
            
            session_id = f"session_{uuid.uuid4().hex[:8]}"
            session = Session(
                session_id=session_id,
                user_id=user_id,
                context=context or {},
            )
            
            self._sessions[session_id] = session
            self._users[user_id].last_seen = time.time()
            
            if self._bus:
                self._bus.publish_nowait("identity/session_created", {
                    "session_id": session_id,
                    "user_id": user_id,
                })
            
            log.info("Created session %s for user %s", session_id, user_id)
            return session
    
    def get_session(self, session_id: str) -> Session | None:
        """Get a session by ID."""
        with self._lock:
            return self._sessions.get(session_id)
    
    def update_session_context(
        self,
        session_id: str,
        context: dict[str, Any],
    ) -> bool:
        """Update session context."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None or not session.active:
                return False
            
            session.context.update(context)
            session.last_activity = time.time()
            return True
    
    def end_session(self, session_id: str) -> bool:
        """End a session."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return False
            
            session.active = False
            log.info("Ended session %s", session_id)
            return True
    
    def get_active_sessions(self, user_id: str | None = None) -> list[Session]:
        """Get active sessions, optionally filtered by user."""
        with self._lock:
            sessions = [s for s in self._sessions.values() if s.active]
            if user_id:
                sessions = [s for s in sessions if s.user_id == user_id]
            return sessions
    
    def cleanup_inactive_sessions(self, timeout_seconds: float = 3600) -> int:
        """Remove sessions inactive for more than timeout_seconds."""
        with self._lock:
            now = time.time()
            to_remove = []
            
            for session_id, session in self._sessions.items():
                if session.active and (now - session.last_activity) > timeout_seconds:
                    session.active = False
                    to_remove.append(session_id)
            
            for session_id in to_remove:
                del self._sessions[session_id]
            
            if to_remove:
                log.info("Cleaned up %d inactive sessions", len(to_remove))
            
            return len(to_remove)
    
    def status(self) -> dict[str, Any]:
        """Get identity manager status."""
        with self._lock:
            return {
                "total_users": len(self._users),
                "total_sessions": len(self._sessions),
                "active_sessions": sum(1 for s in self._sessions.values() if s.active),
                "users_by_role": {
                    "admin": sum(1 for u in self._users.values() if u.role == "admin"),
                    "operator": sum(1 for u in self._users.values() if u.role == "operator"),
                    "user": sum(1 for u in self._users.values() if u.role == "user"),
                    "system": sum(1 for u in self._users.values() if u.role == "system"),
                },
            }
