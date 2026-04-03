from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any, BinaryIO

from core.bus import EventBus
from core.personality import Personality
from core.provider import OpenChimeraProvider


@dataclass
class _ToolDef:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class _ResourceDef:
    uri: str
    name: str
    description: str
    mime_type: str


@dataclass
class _PromptDef:
    name: str
    description: str
    arguments: list[dict[str, Any]]


class OpenChimeraMCPServer:
    def __init__(self, provider: OpenChimeraProvider | None = None):
        self.provider = provider or OpenChimeraProvider(EventBus(), Personality())
        self._tools: dict[str, tuple[_ToolDef, Any]] = {
            "openchimera.provider_activation": (
                _ToolDef(
                    name="openchimera.provider_activation",
                    description="Return provider activation, discovery, and role routing state.",
                    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
                ),
                lambda arguments: self.provider.provider_activation_status(),
            ),
            "openchimera.mcp_status": (
                _ToolDef(
                    name="openchimera.mcp_status",
                    description="Return the discovered MCP inventory and current health summary.",
                    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
                ),
                lambda arguments: self.provider.mcp_status(),
            ),
            "openchimera.mcp_registry": (
                _ToolDef(
                    name="openchimera.mcp_registry",
                    description="Return OpenChimera-managed MCP registry entries and probe state.",
                    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
                ),
                lambda arguments: self.provider.mcp_registry_status(),
            ),
            "openchimera.mcp_probe": (
                _ToolDef(
                    name="openchimera.mcp_probe",
                    description="Probe one or all OpenChimera-managed MCP connectors and persist health state.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "timeout_seconds": {"type": "number", "minimum": 0.1},
                        },
                        "additionalProperties": False,
                    },
                ),
                lambda arguments: self.provider.probe_mcp_connectors(
                    server_id=str(arguments.get("id", "")).strip() or None,
                    timeout_seconds=float(arguments.get("timeout_seconds", 3.0)),
                ),
            ),
            "openchimera.daily_briefing": (
                _ToolDef(
                    name="openchimera.daily_briefing",
                    description="Return the current OpenChimera operator daily briefing.",
                    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
                ),
                lambda arguments: self.provider.daily_briefing(),
            ),
            "openchimera.autonomy_diagnostics": (
                _ToolDef(
                    name="openchimera.autonomy_diagnostics",
                    description="Return the current autonomy diagnostics snapshot and latest artifacts.",
                    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
                ),
                lambda arguments: self.provider.autonomy_diagnostics(),
            ),
            "openchimera.operator_digest": (
                _ToolDef(
                    name="openchimera.operator_digest",
                    description="Read the latest rolled-up operator digest artifact.",
                    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
                ),
                lambda arguments: self.provider.operator_digest(),
            ),
            "openchimera.dispatch_operator_digest": (
                _ToolDef(
                    name="openchimera.dispatch_operator_digest",
                    description="Generate or queue an operator digest dispatch.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "enqueue": {"type": "boolean"},
                            "max_attempts": {"type": "integer", "minimum": 1},
                            "history_limit": {"type": "integer", "minimum": 1},
                            "dispatch_topic": {"type": "string"},
                        },
                        "additionalProperties": False,
                    },
                ),
                lambda arguments: self.provider.dispatch_operator_digest(
                    enqueue=bool(arguments.get("enqueue", False)),
                    max_attempts=int(arguments.get("max_attempts", 3)),
                    history_limit=int(arguments.get("history_limit")) if arguments.get("history_limit") is not None else None,
                    dispatch_topic=str(arguments.get("dispatch_topic", "")).strip() or None,
                ),
            ),
            "openchimera.channel_status": (
                _ToolDef(
                    name="openchimera.channel_status",
                    description="Return configured channel subscriptions and delivery counters.",
                    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
                ),
                lambda arguments: self.provider.channel_status(),
            ),
            "openchimera.channel_history": (
                _ToolDef(
                    name="openchimera.channel_history",
                    description="Read recent channel delivery history filtered by topic or status.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "topic": {"type": "string"},
                            "status": {"type": "string"},
                            "limit": {"type": "integer", "minimum": 1},
                        },
                        "additionalProperties": False,
                    },
                ),
                lambda arguments: self.provider.channel_delivery_history(
                    topic=str(arguments.get("topic", "")).strip() or None,
                    status=str(arguments.get("status", "")).strip() or None,
                    limit=int(arguments.get("limit", 20)),
                ),
            ),
            "openchimera.channel_upsert": (
                _ToolDef(
                    name="openchimera.channel_upsert",
                    description="Create or update a channel subscription.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "subscription": {"type": "object"},
                        },
                        "required": ["subscription"],
                        "additionalProperties": False,
                    },
                ),
                lambda arguments: self.provider.upsert_channel_subscription(dict(arguments.get("subscription", {}))),
            ),
            "openchimera.channel_delete": (
                _ToolDef(
                    name="openchimera.channel_delete",
                    description="Delete a channel subscription by id.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "subscription_id": {"type": "string"},
                        },
                        "required": ["subscription_id"],
                        "additionalProperties": False,
                    },
                ),
                lambda arguments: self.provider.delete_channel_subscription(str(arguments.get("subscription_id", "")).strip()),
            ),
            "openchimera.channel_dispatch": (
                _ToolDef(
                    name="openchimera.channel_dispatch",
                    description="Dispatch a payload to a configured OpenChimera topic.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "topic": {"type": "string"},
                            "payload": {"type": "object"},
                        },
                        "required": ["topic"],
                        "additionalProperties": False,
                    },
                ),
                lambda arguments: self.provider.dispatch_channel(
                    topic=str(arguments.get("topic", "")).strip(),
                    payload=dict(arguments.get("payload", {})),
                ),
            ),
            "openchimera.job_queue": (
                _ToolDef(
                    name="openchimera.job_queue",
                    description="Inspect the operator job queue with optional filters.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "status": {"type": "string"},
                            "job_type": {"type": "string"},
                            "limit": {"type": "integer", "minimum": 1},
                        },
                        "additionalProperties": False,
                    },
                ),
                lambda arguments: self.provider.job_queue_status(
                    status_filter=str(arguments.get("status", "")).strip() or None,
                    job_type=str(arguments.get("job_type", "")).strip() or None,
                    limit=int(arguments.get("limit", 20)),
                ),
            ),
            "openchimera.get_job": (
                _ToolDef(
                    name="openchimera.get_job",
                    description="Read a single operator job by id.",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "job_id": {"type": "string"},
                        },
                        "required": ["job_id"],
                        "additionalProperties": False,
                    },
                ),
                lambda arguments: self.provider.get_operator_job(str(arguments.get("job_id", "")).strip()),
            ),
            "openchimera.onboarding_status": (
                _ToolDef(
                    name="openchimera.onboarding_status",
                    description="Return onboarding blockers and next actions.",
                    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
                ),
                lambda arguments: self.provider.onboarding_status(),
            ),
            "openchimera.integration_status": (
                _ToolDef(
                    name="openchimera.integration_status",
                    description="Return integration audit and bridge status details.",
                    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
                ),
                lambda arguments: self.provider.integration_status(),
            ),
            "openchimera.subsystem_status": (
                _ToolDef(
                    name="openchimera.subsystem_status",
                    description="Return subsystem health and availability.",
                    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
                ),
                lambda arguments: self.provider.subsystem_status(),
            ),
        }
        self._resources: dict[str, tuple[_ResourceDef, Any]] = {
            "openchimera://status/provider-activation": (
                _ResourceDef(
                    uri="openchimera://status/provider-activation",
                    name="Provider Activation",
                    description="Current provider discovery, preferences, and model role routing.",
                    mime_type="application/json",
                ),
                lambda: self.provider.provider_activation_status(),
            ),
            "openchimera://status/mcp": (
                _ResourceDef(
                    uri="openchimera://status/mcp",
                    name="MCP Status",
                    description="Discovered MCP servers and current health summary.",
                    mime_type="application/json",
                ),
                lambda: self.provider.mcp_status(),
            ),
            "openchimera://status/mcp-registry": (
                _ResourceDef(
                    uri="openchimera://status/mcp-registry",
                    name="MCP Registry",
                    description="OpenChimera-managed MCP registry entries and last-known probe state.",
                    mime_type="application/json",
                ),
                lambda: self.provider.mcp_registry_status(),
            ),
            "openchimera://status/channels": (
                _ResourceDef(
                    uri="openchimera://status/channels",
                    name="Channel Status",
                    description="Configured channel subscriptions and delivery counters.",
                    mime_type="application/json",
                ),
                lambda: self.provider.channel_status(),
            ),
            "openchimera://status/jobs": (
                _ResourceDef(
                    uri="openchimera://status/jobs",
                    name="Job Queue",
                    description="Current operator job queue snapshot.",
                    mime_type="application/json",
                ),
                lambda: self.provider.job_queue_status(limit=20),
            ),
            "openchimera://status/onboarding": (
                _ResourceDef(
                    uri="openchimera://status/onboarding",
                    name="Onboarding Status",
                    description="Current onboarding blockers and next actions.",
                    mime_type="application/json",
                ),
                lambda: self.provider.onboarding_status(),
            ),
            "openchimera://status/integrations": (
                _ResourceDef(
                    uri="openchimera://status/integrations",
                    name="Integration Status",
                    description="Current integration audit and bridge summaries.",
                    mime_type="application/json",
                ),
                lambda: self.provider.integration_status(),
            ),
            "openchimera://status/subsystems": (
                _ResourceDef(
                    uri="openchimera://status/subsystems",
                    name="Subsystem Status",
                    description="Current subsystem health and inventory.",
                    mime_type="application/json",
                ),
                lambda: self.provider.subsystem_status(),
            ),
        }
        self._prompts: dict[str, tuple[_PromptDef, Any]] = {
            "openchimera.system_overview": (
                _PromptDef(
                    name="openchimera.system_overview",
                    description="Generate a concise operator prompt for reviewing the current runtime.",
                    arguments=[],
                ),
                lambda arguments: self._build_system_overview_prompt(),
            ),
            "openchimera.operator_triage": (
                _PromptDef(
                    name="openchimera.operator_triage",
                    description="Generate a triage prompt using recent channel delivery history.",
                    arguments=[
                        {"name": "topic", "description": "Optional topic filter.", "required": False},
                        {"name": "status", "description": "Optional delivery status filter.", "required": False},
                        {"name": "limit", "description": "Number of records to inspect.", "required": False},
                    ],
                ),
                lambda arguments: self._build_operator_triage_prompt(arguments),
            ),
        }

    def tool_descriptors(self) -> list[dict[str, Any]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.input_schema,
            }
            for tool, _ in (item for item in self._tools.values())
        ]

    def resource_descriptors(self) -> list[dict[str, Any]]:
        return [
            {
                "uri": resource.uri,
                "name": resource.name,
                "description": resource.description,
                "mimeType": resource.mime_type,
            }
            for resource, _ in (item for item in self._resources.values())
        ]

    def prompt_descriptors(self) -> list[dict[str, Any]]:
        return [
            {
                "name": prompt.name,
                "description": prompt.description,
                "arguments": prompt.arguments,
            }
            for prompt, _ in (item for item in self._prompts.values())
        ]

    def handle_request(self, request: dict[str, Any]) -> dict[str, Any] | None:
        method = str(request.get("method", ""))
        request_id = request.get("id")
        params = request.get("params", {}) if isinstance(request.get("params", {}), dict) else {}

        if method == "notifications/initialized":
            return None
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": params.get("protocolVersion", "2024-11-05"),
                    "serverInfo": {"name": "openchimera-local", "version": "1.0.0"},
                    "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                },
            }
        if method == "ping":
            return {"jsonrpc": "2.0", "id": request_id, "result": {}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": self.tool_descriptors()}}
        if method == "resources/list":
            return {"jsonrpc": "2.0", "id": request_id, "result": {"resources": self.resource_descriptors()}}
        if method == "resources/read":
            resource_uri = str(params.get("uri", "")).strip()
            if resource_uri not in self._resources:
                return self._error_response(request_id, -32602, f"Unknown resource: {resource_uri}")
            resource_def, handler = self._resources[resource_uri]
            try:
                payload = handler()
            except Exception as exc:  # pragma: no cover - guarded by tests through happy path
                return self._error_result_response(request_id, exc)
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "contents": [
                        {
                            "uri": resource_def.uri,
                            "mimeType": resource_def.mime_type,
                            "text": json.dumps(payload, indent=2),
                        }
                    ]
                },
            }
        if method == "prompts/list":
            return {"jsonrpc": "2.0", "id": request_id, "result": {"prompts": self.prompt_descriptors()}}
        if method == "prompts/get":
            prompt_name = str(params.get("name", "")).strip()
            prompt_args = params.get("arguments", {}) if isinstance(params.get("arguments", {}), dict) else {}
            if prompt_name not in self._prompts:
                return self._error_response(request_id, -32602, f"Unknown prompt: {prompt_name}")
            prompt_def, handler = self._prompts[prompt_name]
            try:
                prompt_payload = handler(prompt_args)
            except Exception as exc:  # pragma: no cover - guarded by tests through happy path
                return self._error_result_response(request_id, exc)
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "description": prompt_def.description,
                    "messages": prompt_payload,
                },
            }
        if method == "tools/call":
            tool_name = str(params.get("name", "")).strip()
            tool_args = params.get("arguments", {}) if isinstance(params.get("arguments", {}), dict) else {}
            if tool_name not in self._tools:
                return self._error_response(request_id, -32602, f"Unknown tool: {tool_name}")
            _, handler = self._tools[tool_name]
            try:
                result = handler(tool_args)
            except Exception as exc:  # pragma: no cover - guarded by tests through happy path
                return self._error_result_response(request_id, exc)
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(result, indent=2)}],
                    "structuredContent": result,
                    "isError": False,
                },
            }
        return self._error_response(request_id, -32601, f"Unsupported method: {method}")

    def serve_stdio(self, input_stream: BinaryIO | None = None, output_stream: BinaryIO | None = None) -> int:
        source = input_stream or sys.stdin.buffer
        sink = output_stream or sys.stdout.buffer
        while True:
            message = self._read_message(source)
            if message is None:
                break
            response = self.handle_request(message)
            if response is not None:
                self._write_message(sink, response)
        return 0

    def _read_message(self, stream: BinaryIO) -> dict[str, Any] | None:
        headers: dict[str, str] = {}
        while True:
            line = stream.readline()
            if not line:
                return None
            if line in {b"\r\n", b"\n"}:
                break
            decoded = line.decode("utf-8").strip()
            if not decoded or ":" not in decoded:
                continue
            key, value = decoded.split(":", 1)
            headers[key.strip().lower()] = value.strip()
        content_length = int(headers.get("content-length", "0") or "0")
        if content_length <= 0:
            return None
        body = stream.read(content_length)
        if not body:
            return None
        return json.loads(body.decode("utf-8"))

    def _write_message(self, stream: BinaryIO, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8")
        stream.write(header)
        stream.write(body)
        stream.flush()

    def _error_response(self, request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}

    def _error_result_response(self, request_id: Any, exc: Exception) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [{"type": "text", "text": str(exc)}],
                "isError": True,
            },
        }

    def _build_system_overview_prompt(self) -> list[dict[str, Any]]:
        provider_activation = self.provider.provider_activation_status()
        mcp_status = self.provider.mcp_status()
        onboarding = self.provider.onboarding_status()
        prompt = {
            "provider_activation": provider_activation,
            "mcp": mcp_status,
            "onboarding": onboarding,
        }
        return [
            {
                "role": "user",
                "content": {
                    "type": "text",
                    "text": "Review this OpenChimera runtime snapshot and summarize the highest-value operator actions.\n\n" + json.dumps(prompt, indent=2),
                },
            }
        ]

    def _build_operator_triage_prompt(self, arguments: dict[str, Any]) -> list[dict[str, Any]]:
        topic = str(arguments.get("topic", "")).strip() or None
        status = str(arguments.get("status", "")).strip() or None
        limit = int(arguments.get("limit", 10))
        history = self.provider.channel_delivery_history(topic=topic, status=status, limit=limit)
        return [
            {
                "role": "user",
                "content": {
                    "type": "text",
                    "text": "Triage the recent OpenChimera channel delivery history, identify failures or hotspots, and propose the next operator checks.\n\n" + json.dumps(history, indent=2),
                },
            }
        ]


def main() -> int:
    server = OpenChimeraMCPServer()
    return server.serve_stdio()


if __name__ == "__main__":
    raise SystemExit(main())