from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable

from pydantic import BaseModel, ValidationError


class ToolPermissionError(PermissionError):
    pass


class ToolExecutionError(RuntimeError):
    pass


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