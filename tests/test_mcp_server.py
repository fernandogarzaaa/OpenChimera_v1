from __future__ import annotations

import json
import unittest

from core.mcp_server import OpenChimeraMCPServer


class _FakeProvider:
    def provider_activation_status(self) -> dict[str, object]:
        return {"providers": [{"id": "openai", "healthy": True}], "preferred_cloud_provider": "openai"}

    def mcp_status(self) -> dict[str, object]:
        return {
            "counts": {"total": 2, "healthy": 1, "registered": 1},
            "servers": [{"id": "openchimera-local", "status": "healthy"}],
            "registry": {"counts": {"total": 1, "healthy": 1, "enabled": 1}, "servers": [{"id": "context_gateway_remote", "status": "healthy"}]},
        }

    def mcp_registry_status(self) -> dict[str, object]:
        return {"counts": {"total": 1, "healthy": 1, "enabled": 1}, "servers": [{"id": "context_gateway_remote", "status": "healthy"}]}

    def probe_mcp_connectors(self, server_id: str | None = None, timeout_seconds: float = 3.0) -> dict[str, object]:
        item = {"id": server_id or "context_gateway_remote", "status": "healthy", "timeout_seconds": timeout_seconds}
        return {"counts": {"total": 1, "healthy": 1}, "servers": [item]}

    def daily_briefing(self) -> dict[str, object]:
        return {"summary": "OpenChimera daily briefing"}

    def autonomy_diagnostics(self) -> dict[str, object]:
        return {"status": "ok", "artifacts": {"self_audit": {"status": "warning"}}}

    def operator_digest(self) -> dict[str, object]:
        return {"artifact_name": "operator_digest", "summary": {"failed_job_count": 1}}

    def dispatch_operator_digest(
        self,
        enqueue: bool = False,
        max_attempts: int = 3,
        history_limit: int | None = None,
        dispatch_topic: str | None = None,
    ) -> dict[str, object]:
        return {
            "status": "ok",
            "enqueue": enqueue,
            "max_attempts": max_attempts,
            "history_limit": history_limit,
            "dispatch_topic": dispatch_topic or "system/briefing/daily",
        }

    def channel_status(self) -> dict[str, object]:
        return {"counts": {"total": 1, "enabled": 1}}

    def channel_delivery_history(self, topic: str | None = None, status: str | None = None, limit: int = 20) -> dict[str, object]:
        return {"topic": topic or "", "status": status or "", "count": 1, "history": [{"topic": topic or "system/autonomy/alert", "delivery_count": 1}], "limit": limit}

    def upsert_channel_subscription(self, subscription: dict[str, object]) -> dict[str, object]:
        return {"id": subscription.get("id", "sub-1"), "topics": subscription.get("topics", [])}

    def delete_channel_subscription(self, subscription_id: str) -> dict[str, object]:
        return {"subscription_id": subscription_id, "deleted": True}

    def dispatch_channel(self, topic: str, payload: dict[str, object] | None = None) -> dict[str, object]:
        return {"topic": topic, "payload": payload or {}, "delivery": {"status": "sent"}}

    def job_queue_status(self, status_filter: str | None = None, job_type: str | None = None, limit: int | None = None) -> dict[str, object]:
        return {"counts": {"total": 1}, "jobs": [{"job_id": "job-1", "status": status_filter or "queued", "job_type": job_type or "demo"}], "limit": limit or 20}

    def get_operator_job(self, job_id: str) -> dict[str, object]:
        return {"job_id": job_id, "status": "queued"}

    def onboarding_status(self) -> dict[str, object]:
        return {"completed": False, "next_actions": ["Configure provider credentials"]}

    def integration_status(self) -> dict[str, object]:
        return {"engines": {"aegis_swarm": {"integrated_runtime": True}}}

    def subsystem_status(self) -> dict[str, object]:
        return {"subsystems": [{"id": "aegis", "health": "healthy"}]}


class OpenChimeraMCPServerTests(unittest.TestCase):
    def test_initialize_and_list_tools(self) -> None:
        server = OpenChimeraMCPServer(provider=_FakeProvider())

        initialized = server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}})
        listed = server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})

        self.assertEqual(initialized["result"]["serverInfo"]["name"], "openchimera-local")
        self.assertIn("resources", initialized["result"]["capabilities"])
        self.assertIn("prompts", initialized["result"]["capabilities"])
        tool_names = {item["name"] for item in listed["result"]["tools"]}
        self.assertIn("openchimera.operator_digest", tool_names)
        self.assertIn("openchimera.dispatch_operator_digest", tool_names)
        self.assertIn("openchimera.job_queue", tool_names)
        self.assertIn("openchimera.mcp_registry", tool_names)
        self.assertIn("openchimera.mcp_probe", tool_names)

    def test_tools_call_returns_structured_content(self) -> None:
        server = OpenChimeraMCPServer(provider=_FakeProvider())

        response = server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "openchimera.dispatch_operator_digest",
                    "arguments": {"history_limit": 4, "dispatch_topic": "system/briefing/daily", "enqueue": True},
                },
            }
        )

        self.assertFalse(response["result"]["isError"])
        self.assertEqual(response["result"]["structuredContent"]["history_limit"], 4)
        rendered = json.loads(response["result"]["content"][0]["text"])
        self.assertTrue(rendered["enqueue"])

    def test_server_lists_and_reads_resources(self) -> None:
        server = OpenChimeraMCPServer(provider=_FakeProvider())

        listed = server.handle_request({"jsonrpc": "2.0", "id": 5, "method": "resources/list", "params": {}})
        resource_uris = {item["uri"] for item in listed["result"]["resources"]}
        self.assertIn("openchimera://status/mcp", resource_uris)
        self.assertIn("openchimera://status/mcp-registry", resource_uris)

        read = server.handle_request(
            {"jsonrpc": "2.0", "id": 6, "method": "resources/read", "params": {"uri": "openchimera://status/mcp"}}
        )
        payload = json.loads(read["result"]["contents"][0]["text"])
        self.assertEqual(payload["counts"]["total"], 2)

    def test_server_lists_and_gets_prompts(self) -> None:
        server = OpenChimeraMCPServer(provider=_FakeProvider())

        listed = server.handle_request({"jsonrpc": "2.0", "id": 7, "method": "prompts/list", "params": {}})
        prompt_names = {item["name"] for item in listed["result"]["prompts"]}
        self.assertIn("openchimera.operator_triage", prompt_names)

        prompt = server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 8,
                "method": "prompts/get",
                "params": {"name": "openchimera.operator_triage", "arguments": {"topic": "system/autonomy/alert", "limit": 3}},
            }
        )
        self.assertIn("system/autonomy/alert", prompt["result"]["messages"][0]["content"]["text"])

    def test_server_can_probe_registry_connectors(self) -> None:
        server = OpenChimeraMCPServer(provider=_FakeProvider())

        response = server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 9,
                "method": "tools/call",
                "params": {"name": "openchimera.mcp_probe", "arguments": {"id": "context_gateway_remote", "timeout_seconds": 1.5}},
            }
        )

        self.assertFalse(response["result"]["isError"])
        self.assertEqual(response["result"]["structuredContent"]["servers"][0]["id"], "context_gateway_remote")

    def test_unknown_tool_returns_error_result(self) -> None:
        server = OpenChimeraMCPServer(provider=_FakeProvider())

        response = server.handle_request(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "openchimera.unknown", "arguments": {}},
            }
        )

        self.assertEqual(response["error"]["code"], -32602)