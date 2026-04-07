"""OpenChimera SafetyLayer — Content filtering and action validation.

Provides safety checks for content and actions before execution.
"""
from __future__ import annotations

import logging
import re
import threading
from typing import Any

log = logging.getLogger(__name__)


class SafetyLayer:
    """Content filtering and action validation.
    
    Features:
    - Content filtering (harmful/inappropriate content)
    - Action validation (dangerous operations)
    - Configurable safety rules
    - Thread-safe operations
    """
    
    # Patterns for harmful content detection
    _HARMFUL_PATTERNS = [
        r"\b(hack|exploit|attack|ddos|malware|virus)\b",
        r"\b(password|credential|api[_-]?key|secret|token)\s*[:=]",
        r"\b(sudo|rm\s+-rf|chmod\s+777)\b",
    ]
    
    # Dangerous actions that require extra validation
    _DANGEROUS_ACTIONS = {
        "file_delete",
        "system_execute",
        "network_send",
        "database_drop",
        "user_impersonate",
    }
    
    def __init__(self, bus: Any | None = None) -> None:
        self._bus = bus
        self._enabled = True
        self._lock = threading.RLock()
        self._blocked_count = 0
        self._allowed_count = 0
        log.info("SafetyLayer initialized")
    
    def validate_content(self, content: str) -> tuple[bool, str | None]:
        """Validate content for safety.
        
        Args:
            content: Content to validate
            
        Returns:
            (is_safe, reason) tuple. reason is None if safe.
        """
        with self._lock:
            if not self._enabled:
                self._allowed_count += 1
                return True, None
            
            content_lower = content.lower()
            
            # Check harmful patterns
            for pattern in self._HARMFUL_PATTERNS:
                if re.search(pattern, content_lower):
                    self._blocked_count += 1
                    if self._bus:
                        self._bus.publish_nowait("safety/content_blocked", {
                            "pattern": pattern,
                            "content_preview": content[:100],
                        })
                    return False, f"Potentially harmful content detected (pattern: {pattern})"
            
            self._allowed_count += 1
            return True, None
    
    def validate_action(
        self,
        action: str,
        parameters: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> tuple[bool, str | None]:
        """Validate an action for safety.
        
        Args:
            action: Action name
            parameters: Action parameters
            context: Optional context (user, session, etc.)
            
        Returns:
            (is_safe, reason) tuple. reason is None if safe.
        """
        with self._lock:
            if not self._enabled:
                self._allowed_count += 1
                return True, None
            
            # Check if action is dangerous
            if action in self._DANGEROUS_ACTIONS:
                # Require admin context for dangerous actions
                ctx = context or {}
                user_role = ctx.get("user_role", "user")
                if user_role != "admin":
                    self._blocked_count += 1
                    if self._bus:
                        self._bus.publish_nowait("safety/action_blocked", {
                            "action": action,
                            "user_role": user_role,
                        })
                    return False, f"Action '{action}' requires admin privileges"
            
            # Validate file paths (no absolute paths outside project)
            if "path" in parameters:
                path = str(parameters["path"])
                if path.startswith("/home/") or path.startswith("/Users/") or path.startswith("C:\\"):
                    self._blocked_count += 1
                    return False, "Hardcoded absolute paths are not allowed"
            
            self._allowed_count += 1
            return True, None
    
    def add_harmful_pattern(self, pattern: str) -> None:
        """Add a custom harmful content pattern."""
        with self._lock:
            if pattern not in self._HARMFUL_PATTERNS:
                self._HARMFUL_PATTERNS.append(pattern)
                log.info("Added harmful pattern: %s", pattern)
    
    def add_dangerous_action(self, action: str) -> None:
        """Add a custom dangerous action."""
        with self._lock:
            self._DANGEROUS_ACTIONS.add(action)
            log.info("Added dangerous action: %s", action)
    
    def enable(self) -> None:
        """Enable safety checks."""
        with self._lock:
            self._enabled = True
            log.info("SafetyLayer enabled")
    
    def disable(self) -> None:
        """Disable safety checks (for testing only)."""
        with self._lock:
            self._enabled = False
            log.warning("SafetyLayer disabled - use only for testing!")
    
    def status(self) -> dict[str, Any]:
        """Get safety layer status."""
        with self._lock:
            return {
                "enabled": self._enabled,
                "total_checks": self._allowed_count + self._blocked_count,
                "allowed": self._allowed_count,
                "blocked": self._blocked_count,
                "block_rate": (
                    self._blocked_count / (self._allowed_count + self._blocked_count)
                    if (self._allowed_count + self._blocked_count) > 0
                    else 0.0
                ),
                "harmful_patterns": len(self._HARMFUL_PATTERNS),
                "dangerous_actions": len(self._DANGEROUS_ACTIONS),
            }
