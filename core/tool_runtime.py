from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, List

from pydantic import BaseModel, ValidationError

from core.tool_executor import ToolExecutor, ToolPermissionError, ToolExecutionError
from services.hook_pipeline import HookPipeline


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

    def __init__(self, bus: Any | None = None, hook_pipeline: HookPipeline | None = None) -> None:
        self._tools: dict[str, ToolMetadata] = {}
        self._bus = bus
        self.hook_pipeline = hook_pipeline if hook_pipeline is not None else HookPipeline()

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
        pre_hook = self.hook_pipeline.execute_pre(name, args)
        if pre_hook.action == "block":
            return ToolResult(
                tool_name=name,
                success=False,
                output=None,
                error=pre_hook.reason or f"Tool {name!r} was blocked by a pre-tool hook",
                metadata={"tags": tool.tags},
            )
        if pre_hook.action == "mutate" and pre_hook.mutated_input is not None:
            args = dict(pre_hook.mutated_input)
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

        result = self._apply_post_hooks(name, args, result)

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

    def _apply_post_hooks(self, name: str, arguments: dict[str, Any], result: ToolResult) -> ToolResult:
        payload = {
            "tool_name": result.tool_name,
            "success": result.success,
            "output": result.output,
            "error": result.error,
            "latency_ms": result.latency_ms,
            "metadata": dict(result.metadata),
        }
        post_hook = self.hook_pipeline.execute_post(name, arguments, payload)
        if post_hook.action != "mutate" or post_hook.mutated_input is None:
            return result

        mutated_payload = dict(payload)
        mutated_payload.update(post_hook.mutated_input)
        metadata = mutated_payload.get("metadata", result.metadata)
        return ToolResult(
            tool_name=str(mutated_payload.get("tool_name") or result.tool_name),
            success=bool(mutated_payload.get("success", result.success)),
            output=mutated_payload.get("output", result.output),
            error=None if mutated_payload.get("error", result.error) is None else str(mutated_payload.get("error", result.error)),
            latency_ms=float(mutated_payload.get("latency_ms", result.latency_ms)),
            metadata=dict(metadata) if isinstance(metadata, dict) else dict(result.metadata),
        )


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
    def __init__(
        self,
        *,
        capability_registry: Any,
        bus: Any,
        specs: list[RuntimeToolSpec] | None = None,
        hook_pipeline: HookPipeline | None = None,
    ) -> None:
        self.capability_registry = capability_registry
        self.bus = bus
        self._specs = {spec.tool_id: spec for spec in (specs or [])}
        self.hook_pipeline = hook_pipeline if hook_pipeline is not None else HookPipeline()
        self._executor = ToolExecutor(bus=bus)

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

        payload = dict(arguments or {})
        pre_hook = self.hook_pipeline.execute_pre(normalized, payload)
        if pre_hook.action == "block":
            return self._blocked_result(
                tool_id=normalized,
                arguments=payload,
                permission_scope=permission_scope,
                reason=pre_hook.reason or f"Tool {normalized!r} was blocked by a pre-tool hook",
            )
        if pre_hook.action == "mutate" and pre_hook.mutated_input is not None:
            payload = dict(pre_hook.mutated_input)

        try:
            if spec.schema is not None:
                payload = spec.schema.model_validate(payload).model_dump(exclude_none=True)
        except ValidationError as exc:
            raise ToolExecutionError(json.dumps(exc.errors(), default=str)) from exc

        # Use shared ToolExecutor for permission gating, timing, and event emission
        result = self._executor.execute_with_gating(
            tool_id=normalized,
            handler=spec.executor,
            arguments=payload,
            requires_admin=spec.requires_admin,
            permission_scope=permission_scope,
            tags=[spec.category],
        )
        return self._apply_post_hooks(normalized, payload, result)

    def _blocked_result(
        self,
        *,
        tool_id: str,
        arguments: dict[str, Any],
        permission_scope: str,
        reason: str,
    ) -> dict[str, Any]:
        return {
            "tool_id": tool_id,
            "status": "error",
            "permission_scope": str(permission_scope or "user").strip().lower() or "user",
            "arguments": dict(arguments),
            "result": None,
            "error": reason,
            "latency_ms": 0.0,
        }

    def _apply_post_hooks(
        self,
        tool_id: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        post_hook = self.hook_pipeline.execute_post(tool_id, arguments, result)
        if post_hook.action != "mutate" or post_hook.mutated_input is None:
            return result

        mutated_result = dict(result)
        mutated_result.update(post_hook.mutated_input)
        mutated_result["tool_id"] = str(mutated_result.get("tool_id") or tool_id)
        if not isinstance(mutated_result.get("arguments"), dict):
            mutated_result["arguments"] = dict(arguments)
        if "latency_ms" in mutated_result:
            mutated_result["latency_ms"] = float(mutated_result["latency_ms"])
        return mutated_result
