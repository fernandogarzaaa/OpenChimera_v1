"""
UnifiedToolRegistry
===================
Unified facade over ToolRegistry (ToolMetadata-based) and
RuntimeToolRegistry (RuntimeToolSpec-based).

Provides a single ``list_tools()``, ``describe()``, and ``execute()``
surface that merges both registries with consistent permission gating
and bus event emission.
"""
from __future__ import annotations

from typing import Any

from core.tool_runtime import (
    ToolMetadata,
    ToolRegistry,
    ToolResult,
    RuntimeToolRegistry,
)


class UnifiedToolRegistry:
    """Unified facade over ``ToolRegistry`` and ``RuntimeToolRegistry``.

    Parameters
    ----------
    tool_registry:
        A ``ToolRegistry`` (ToolMetadata-based).  Created automatically if
        not provided.
    runtime_registry:
        An optional ``RuntimeToolRegistry`` (RuntimeToolSpec-based) to
        merge into the unified surface.
    bus:
        Optional event bus passed to an auto-created ``ToolRegistry``.
    """

    def __init__(
        self,
        tool_registry: ToolRegistry | None = None,
        runtime_registry: RuntimeToolRegistry | None = None,
        bus: Any | None = None,
    ) -> None:
        self._tool_registry = tool_registry if tool_registry is not None else ToolRegistry(bus=bus)
        self._runtime_registry = runtime_registry
        self._bus = bus

    # ------------------------------------------------------------------
    # ToolMetadata-based tool CRUD (delegates to _tool_registry)
    # ------------------------------------------------------------------

    def register(self, tool: ToolMetadata) -> ToolMetadata:
        """Register a ToolMetadata-based tool."""
        return self._tool_registry.register(tool)

    def unregister(self, name: str) -> bool:
        """Unregister a ToolMetadata-based tool by name."""
        return self._tool_registry.unregister(name)

    # ------------------------------------------------------------------
    # Unified discovery
    # ------------------------------------------------------------------

    def list_tools(self) -> list[dict[str, Any]]:
        """Return all tools from both registries, deduplicated by name/id.

        ToolMetadata-based tools are listed first; RuntimeToolRegistry entries
        are appended unless their id already appears in the metadata set.
        The combined list is sorted alphabetically by name/id.
        """
        metadata_tools = self._tool_registry.list_tools()
        seen = {t["name"] for t in metadata_tools}

        runtime_tools: list[dict[str, Any]] = []
        if self._runtime_registry is not None:
            for t in self._runtime_registry.list_tools():
                tool_id = str(t.get("id") or t.get("name") or "")
                if tool_id and tool_id not in seen:
                    seen.add(tool_id)
                    runtime_tools.append(t)

        combined = metadata_tools + runtime_tools
        return sorted(combined, key=lambda t: str(t.get("name") or t.get("id") or ""))

    def describe(self, name_or_id: str) -> dict[str, Any]:
        """Return a descriptor for a tool from either registry.

        Resolution order: ToolMetadata registry → RuntimeToolRegistry.
        Raises ``ValueError`` if not found in either.
        """
        try:
            return self._tool_registry.describe(name_or_id).to_dict()
        except ValueError:
            pass

        if self._runtime_registry is not None:
            try:
                return self._runtime_registry.get_tool(name_or_id)
            except (ValueError, StopIteration):
                pass

        raise ValueError(f"Unknown tool: {name_or_id!r}")

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute(
        self,
        name_or_id: str,
        arguments: dict[str, Any] | None = None,
        *,
        permission_scope: str = "user",
    ) -> dict[str, Any]:
        """Execute a tool from either registry.

        RuntimeToolRegistry specs are tried first (they carry structured
        permission gating).  ToolMetadata-based tools are used as the
        fallback.  Always returns a normalized result dict.

        Raises ``ValueError`` if the tool is not found in either registry.
        """
        # Try RuntimeToolRegistry first via its public API.
        if self._runtime_registry is not None:
            try:
                return self._runtime_registry.execute(
                    name_or_id, arguments, permission_scope=permission_scope
                )
            except ValueError:
                pass

        # Verify the tool exists in the metadata registry before executing
        # (ToolRegistry.execute returns a failed ToolResult rather than raising)
        try:
            self._tool_registry.describe(name_or_id)
        except ValueError:
            raise ValueError(f"Unknown tool: {name_or_id!r}")

        result: ToolResult = self._tool_registry.execute(name_or_id, arguments)
        return {
            "tool_id": name_or_id,
            "status": "ok" if result.success else "error",
            "permission_scope": permission_scope,
            "arguments": dict(arguments or {}),
            "result": result.output,
            "error": result.error,
            "latency_ms": result.latency_ms,
        }

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        metadata_count = len(self._tool_registry.list_tools())
        runtime_count = (
            len(self._runtime_registry.list_tools()) if self._runtime_registry is not None else 0
        )
        return {
            "counts": {
                "metadata_tools": metadata_count,
                "runtime_tools": runtime_count,
                "total": len(self.list_tools()),
            }
        }
