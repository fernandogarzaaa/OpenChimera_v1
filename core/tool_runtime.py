from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, List

from pydantic import BaseModel, ValidationError


class ToolPermissionError(PermissionError):
    pass


class ToolExecutionError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# ToolMetadata / ToolResult — structured capability descriptors
# ---------------------------------------------------------------------------

@dataclass
class ToolMetadata:
    """Describes a registered tool's identity and interface."""
    name: str
    description: str
    schema: dict[str, Any] | None = None
    handler: Callable[..., Any] | None = None
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "schema": self.schema or {"type": "object", "additionalProperties": True},
            "tags": list(self.tags),
            "executable": self.handler is not None,
        }


@dataclass
class ToolResult:
    """Structured result returned from ToolRegistry.execute()."""
    tool_name: str
    success: bool
    output: Any
    error: str | None = None
    latency_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "latency_ms": round(self.latency_ms, 3),
            "metadata": dict(self.metadata),
        }


# ---------------------------------------------------------------------------
# ToolRegistry — lightweight registry for ToolMetadata-based tools
# ---------------------------------------------------------------------------

class ToolRegistry:
    """Lightweight tool registry backed by ToolMetadata descriptors.

    Provides register/unregister/list/describe/execute with timing and
    event bus integration.  Designed to be wired into the CapabilityPlane.
    """

    def __init__(self, bus: Any | None = None) -> None:
        self._tools: dict[str, ToolMetadata] = {}
        self._bus = bus

    # --- CRUD ---

    def register(self, tool: ToolMetadata) -> ToolMetadata:
        """Register or replace a tool by name."""
        if not tool.name or not tool.name.strip():
            raise ValueError("Tool name must be non-empty")
        self._tools[tool.name] = tool
        if self._bus is not None:
            try:
                self._bus.publish_nowait(
                    "system/tools",
                    {"action": "register", "tool_name": tool.name, "tags": tool.tags},
                )
            except Exception:
                pass
        return tool

    def unregister(self, name: str) -> bool:
        """Remove a tool by name.  Returns True if found and removed."""
        removed = self._tools.pop(name, None) is not None
        if removed and self._bus is not None:
            try:
                self._bus.publish_nowait(
                    "system/tools",
                    {"action": "unregister", "tool_name": name},
                )
            except Exception:
                pass
        return removed

    def list_tools(self) -> list[dict[str, Any]]:
        """Return a list of all registered tool descriptors."""
        return [meta.to_dict() for meta in sorted(self._tools.values(), key=lambda m: m.name)]

    def describe(self, name: str) -> ToolMetadata:
        """Return the ToolMetadata for a specific tool."""
        tool = self._tools.get(name)
        if tool is None:
            raise ValueError(f"Unknown tool: {name!r}")
        return tool

    def execute(self, name: str, arguments: dict[str, Any] | None = None) -> ToolResult:
        """Execute a registered tool and return a ToolResult.

        Times execution and emits an event on the bus if available.
        """
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(
                tool_name=name,
                success=False,
                output=None,
                error=f"Unknown tool: {name!r}",
            )

        if tool.handler is None:
            return ToolResult(
                tool_name=name,
                success=False,
                output=None,
                error=f"Tool {name!r} has no handler registered",
            )

        args = dict(arguments or {})
        started = time.perf_counter()
        try:
            output = tool.handler(args)
            latency_ms = (time.perf_counter() - started) * 1000.0
            result = ToolResult(
                tool_name=name,
                success=True,
                output=output,
                latency_ms=latency_ms,
                metadata={"tags": tool.tags},
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - started) * 1000.0
            result = ToolResult(
                tool_name=name,
                success=False,
                output=None,
                error=str(exc),
                latency_ms=latency_ms,
                metadata={"tags": tool.tags},
            )

        if self._bus is not None:
            try:
                self._bus.publish_nowait(
                    "system/tools",
                    {
                        "action": "execute",
                        "tool_name": name,
                        "success": result.success,
                        "latency_ms": result.latency_ms,
                    },
                )
            except Exception:
                pass

        return result


@dataclass(frozen=True)
class RuntimeToolSpec:
    tool_id: str
    name: str
    description: str
    schema: type[BaseModel] | None
    executor: Callable[[dict[str, Any]], Any]
    requires_admin: bool = False
    category: str = "runtime"


class RuntimeToolRegistry:
    def __init__(self, *, capability_registry: Any, bus: Any, specs: list[RuntimeToolSpec] | None = None) -> None:
        self.capability_registry = capability_registry
        self.bus = bus
        self._specs = {spec.tool_id: spec for spec in (specs or [])}

    def list_tools(self) -> list[dict[str, Any]]:
        metadata = {
            str(item.get("id")): dict(item)
            for item in self.capability_registry.list_kind("tools")
        }
        tools: list[dict[str, Any]] = []
        for tool_id in sorted(self._specs):
            spec = self._specs[tool_id]
            item = metadata.get(tool_id, {"id": tool_id, "name": spec.name, "description": spec.description, "kind": "tool"})
            rendered = dict(item)
            rendered["name"] = spec.name
            rendered["description"] = spec.description
            rendered["category"] = spec.category or str(item.get("category") or "runtime")
            rendered["requires_admin"] = spec.requires_admin
            rendered["executable"] = True
            rendered["input_schema"] = spec.schema.model_json_schema() if spec.schema is not None else {"type": "object", "additionalProperties": True}
            tools.append(rendered)
        return tools

    def get_tool(self, tool_id: str) -> dict[str, Any]:
        normalized = str(tool_id or "").strip()
        spec = self._specs.get(normalized)
        if spec is None:
            raise ValueError(f"Unknown tool: {tool_id}")
        return next(item for item in self.list_tools() if str(item.get("id")) == normalized)

    def execute(self, tool_id: str, arguments: dict[str, Any] | None = None, *, permission_scope: str = "user") -> dict[str, Any]:
        normalized = str(tool_id or "").strip()
        spec = self._specs.get(normalized)
        if spec is None:
            raise ValueError(f"Unknown tool: {tool_id}")

        scope = str(permission_scope or "user").strip().lower() or "user"
        if spec.requires_admin and scope != "admin":
            raise ToolPermissionError(f"Tool '{normalized}' requires admin permission scope")

        payload = dict(arguments or {})
        try:
            if spec.schema is not None:
                payload = spec.schema.model_validate(payload).model_dump(exclude_none=True)
        except ValidationError as exc:
            raise ToolExecutionError(json.dumps(exc.errors(), default=str)) from exc

        started_at = time.time()
        result = spec.executor(payload)
        envelope = {
            "tool_id": normalized,
            "status": "ok",
            "permission_scope": scope,
            "arguments": payload,
            "result": result,
            "executed_at": int(started_at),
        }
        self.bus.publish_nowait("system/tools", {"action": "execute", "tool": normalized, "result": envelope})
        return envelope