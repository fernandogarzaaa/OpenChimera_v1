"""Shared ToolExecutor helper — DRY extraction for tool execution patterns.

Consolidates permission gating, timing, exception handling, and bus event emission
from tool_registry.py and tool_runtime.py into a single reusable helper.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable

log = logging.getLogger(__name__)


class ToolPermissionError(PermissionError):
    """Raised when tool permission requirements are not met."""


class ToolExecutionError(RuntimeError):
    """Raised when tool execution fails."""


class ToolExecutor:
    """Shared helper for executing tools with permission gating, timing, and events.
    
    Parameters
    ----------
    bus:
        Optional event bus for publishing execution events.
    """
    
    def __init__(self, bus: Any | None = None) -> None:
        self._bus = bus
    
    def execute_with_gating(
        self,
        tool_id: str,
        handler: Callable[[dict[str, Any]], Any],
        arguments: dict[str, Any] | None = None,
        *,
        requires_admin: bool = False,
        permission_scope: str = "user",
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Execute a tool handler with permission gating, timing, and event emission.
        
        Parameters
        ----------
        tool_id:
            Tool identifier for logging and events.
        handler:
            Callable that executes the tool logic.
        arguments:
            Arguments to pass to the handler.
        requires_admin:
            Whether the tool requires admin permissions.
        permission_scope:
            Current permission scope ("user" or "admin").
        tags:
            Optional tags for metadata.
        
        Returns
        -------
        dict with keys: tool_id, status, permission_scope, arguments, result, error, latency_ms
        
        Raises
        ------
        ToolPermissionError:
            If permission requirements are not met.
        """
        # Permission check
        scope = str(permission_scope or "user").strip().lower() or "user"
        if requires_admin and scope != "admin":
            raise ToolPermissionError(
                f"Tool '{tool_id}' requires admin permission scope"
            )
        
        # Execute with timing
        args = dict(arguments or {})
        started = time.perf_counter()
        error = None
        result = None
        status = "ok"
        
        try:
            result = handler(args)
        except Exception as exc:
            error = str(exc)
            status = "error"
            log.warning("[ToolExecutor] %s execution failed: %s", tool_id, exc)
        
        latency_ms = (time.perf_counter() - started) * 1000.0
        
        # Emit event
        self._publish_event("system/tools", {
            "action": "execute",
            "tool_id": tool_id,
            "status": status,
            "latency_ms": round(latency_ms, 3),
            "tags": tags or [],
        })
        
        return {
            "tool_id": tool_id,
            "status": status,
            "permission_scope": scope,
            "arguments": args,
            "result": result,
            "error": error,
            "latency_ms": round(latency_ms, 3),
        }
    
    def _publish_event(self, topic: str, payload: dict[str, Any]) -> None:
        """Publish event to bus if available."""
        if self._bus is None:
            return
        try:
            self._bus.publish_nowait(topic, payload)
        except Exception:
            pass
