from __future__ import annotations

import json
import os
import ssl
import unittest
from unittest import mock
from urllib import error
from urllib import request

from core.api_server import OpenChimeraAPIServer
from core.rate_limiter import RateLimiter


class _FakeRouter:
    def status(self) -> dict[str, object]:
        return {"available_models": ["qwen2.5-7b"], "healthy_models": 1, "known_models": 1}


class _FakeProvider:
    def __init__(self) -> None:
        self.router = _FakeRouter()
        self._credentials = {}
        self._subscriptions = []
        self._delivery_history = []
        self._jobs = []
        self._browser_history = []
        self._query_sessions = []
        self._installed_plugins = set()
        self._tool_executions = []
        self._onboarding = {"steps": [], "completed": False, "recommendations": {"suggested_local_models": [{"id": "phi-3.5-mini"}]}, "validation": {"missing_required_roots": []}}
        self._providers = [{"id": "local-llama-cpp", "enabled": True, "activation_state": {"enabled": True, "preferred_cloud_provider": False, "prefer_free_models": False}}, {"id": "openai", "enabled": False, "activation_state": {"enabled": False, "preferred_cloud_provider": False, "prefer_free_models": False}}]
        self._preferred_cloud_provider = ""
        self._prefer_free_models = False
        self._autonomy_runs = []
        self._capability_status = {"counts": {"commands": 6, "tools": 8, "skills": 4, "plugins": 1, "mcp_servers": 2}}
        self._model_roles = {
            "main_loop_model": {"model": "qwen2.5-7b", "source": "local-catalog"},
            "fast_model": {"model": "phi-3.5-mini", "source": "local-catalog"},
            "code_model": {"model": "qwen2.5-7b", "source": "local-catalog"},
            "reasoning_model": {"model": "llama-3.2-3b", "source": "local-catalog"},
            "advisor_model": {"model": "gpt-4.1-mini", "source": "cloud-catalog"},
            "fallback_model": {"model": "gpt-4.1-mini", "source": "cloud-catalog"},
            "consensus_ensemble": {"models": ["qwen2.5-7b", "llama-3.2-3b"], "source": "resolved"},
        }

    def health(self) -> dict[str, object]:
        return {"status": "online", "name": "openchimera"}

    def control_plane_readiness(self, system_status: dict[str, object] | None = None, auth_required: bool = False) -> dict[str, object]:
        return {
            "status": "ready",
            "ready": True,
            "checks": {"provider_online": True, "rag": True, "router": True, "generation_path": True},
            "healthy_models": 1,
            "minimind_available": True,
            "auth_required": auth_required,
        }

    def control_plane_status(self, system_status: dict[str, object] | None = None) -> dict[str, object]:
        return {
            "generated_at": 0,
            "health": self.health(),
            "readiness": self.control_plane_readiness(system_status=system_status),
            "deployment": {
                "mode": "local",
                "containerized": False,
                "transport": {"tls_enabled": False},
                "logging": {"structured_enabled": True},
            },
            "provider_activation": self.provider_activation_status(),
            "onboarding": self.onboarding_status(),
            "integrations": self.integration_status(),
            "subsystems": self.subsystem_status(),
            "channels": {"status": self.channel_status(), "failed_deliveries": self.channel_delivery_history(status="error", limit=5)},
            "jobs": self.job_queue_status(limit=20),
            "issues": [],
        }

    def list_models(self) -> dict[str, object]:
        return {"object": "list", "data": []}

    def auth_status(self) -> dict[str, object]:
        return {
            "enabled": bool(os.environ.get("OPENCHIMERA_API_TOKEN")),
            "header": "Authorization",
            "user_token_configured": bool(os.environ.get("OPENCHIMERA_API_TOKEN")),
            "admin_token_configured": bool(os.environ.get("OPENCHIMERA_ADMIN_TOKEN") or os.environ.get("OPENCHIMERA_API_TOKEN")),
            "admin_separate_from_user": bool(os.environ.get("OPENCHIMERA_ADMIN_TOKEN")),
            "protected_mutations": True,
        }

    def credential_status(self) -> dict[str, object]:
        return {"providers": self._credentials}

    def channel_status(self) -> dict[str, object]:
        return {
            "subscriptions": list(self._subscriptions),
            "supported_channels": ["discord", "filesystem", "slack", "telegram", "webhook"],
            "counts": {
                "total": len(self._subscriptions),
                "enabled": len(self._subscriptions),
                "validated": len([item for item in self._subscriptions if item.get("last_validation")]),
                "healthy": len([item for item in self._subscriptions if item.get("last_validation", {}).get("status") == "delivered"]),
                "errors": len([item for item in self._subscriptions if item.get("last_validation", {}).get("status") == "error"]),
            },
            "last_delivery": {},
            "delivery_history_count": len(self._delivery_history),
        }

    def channel_delivery_history(self, topic: str | None = None, status: str | None = None, limit: int = 20) -> dict[str, object]:
        entries = list(self._delivery_history)
        if topic:
            entries = [item for item in entries if item.get("topic") == topic]
        if status:
            entries = [item for item in entries if any(result.get("status") == status for result in item.get("results", []))]
        return {"topic": topic or "", "status": status or "", "count": min(len(entries), limit), "history": entries[:limit]}

    def browser_status(self) -> dict[str, object]:
        return {
            "enabled": True,
            "artifact_root": "fake/openchimera/sandbox/artifacts/browser",
            "history_path": "fake/openchimera/data/browser_sessions.json",
            "recent_sessions": list(self._browser_history),
            "supported_actions": ["fetch", "submit_form"],
        }

    def query_status(self) -> dict[str, object]:
        return {
            "session_count": len(self._query_sessions),
            "active_session_ids": [item["session_id"] for item in self._query_sessions],
            "tool_history_events": 1,
            "memory": self.inspect_memory(),
            "model_roles": self._model_roles,
        }

    def list_query_sessions(self, limit: int = 20) -> list[dict[str, object]]:
        return list(self._query_sessions)[:limit]

    def get_query_session(self, session_id: str) -> dict[str, object]:
        for session in self._query_sessions:
            if session["session_id"] == session_id:
                return session
        raise ValueError(f"Unknown session: {session_id}")

    def inspect_memory(self) -> dict[str, object]:
        return {
            "scopes": {
                "user_memory": {"history_count": 1, "last_entries": [{"task": "bootstrap", "status": "success"}]},
                "repo_memory": {"synced_file_count": 2},
                "session_memory": {"session_count": len(self._query_sessions), "alias_count": 1},
            },
            "summaries": ["user_memory:bootstrap=success", f"session_memory:sessions={len(self._query_sessions)} aliases=1"],
        }

    def run_query(
        self,
        query: str = "",
        messages: list[dict[str, object]] | None = None,
        session_id: str | None = None,
        permission_scope: str = "user",
        max_tokens: int = 512,
        allow_tool_planning: bool = True,
        execute_tools: bool = False,
        tool_requests: list[dict[str, object]] | None = None,
        allow_agent_spawn: bool = False,
        spawn_job: dict[str, object] | None = None,
    ) -> dict[str, object]:
        session = {
            "session_id": session_id or f"qs-{len(self._query_sessions) + 1}",
            "title": (query or "query")[:40],
            "turns": [{"role": "user", "content": query}, {"role": "assistant", "content": "ok"}],
        }
        self._query_sessions = [item for item in self._query_sessions if item.get("session_id") != session["session_id"]]
        self._query_sessions.append(session)
        return {
            "session_id": session["session_id"],
            "query_type": "general",
            "permission_context": {"scope": permission_scope, "requires_admin": False},
            "memory_hydration": self.inspect_memory(),
            "role_selection": {"role": "main_loop_model", "model": "qwen2.5-7b", "source": "local-catalog"},
            "suggested_tools": [{"id": "browser.fetch", "requires_admin": True}] if allow_tool_planning else [],
            "executed_tools": [
                self.execute_tool(str(item.get("tool_id", "")), dict(item.get("arguments", {})), permission_scope=permission_scope)
                for item in (tool_requests or [])
            ] if execute_tools else [],
            "spawned_job": None,
            "response": self.chat_completion(),
        }

    def tool_status(self) -> dict[str, object]:
        return {
            "counts": {"total": 2, "admin_required": 1},
            "tools": [
                {
                    "id": "browser.fetch",
                    "description": "Fetch a web page.",
                    "category": "browser",
                    "requires_admin": True,
                    "executable": True,
                },
                {
                    "id": "ascension.deliberate",
                    "description": "Run a structured deliberation.",
                    "category": "reasoning",
                    "requires_admin": False,
                    "executable": True,
                },
            ],
        }

    def get_tool(self, tool_id: str) -> dict[str, object]:
        for item in self.tool_status()["tools"]:
            if item["id"] == tool_id:
                return item
        raise ValueError(f"Unknown tool: {tool_id}")

    def execute_tool(self, tool_id: str, arguments: dict[str, object] | None = None, permission_scope: str = "user") -> dict[str, object]:
        payload = {
            "tool_id": tool_id,
            "status": "ok",
            "permission_scope": permission_scope,
            "arguments": arguments or {},
            "result": {"echo": arguments or {}},
        }
        self._tool_executions.append(payload)
        return payload

    def plugin_status(self) -> dict[str, object]:
        return {
            "counts": {"total": 1, "installed": len(self._installed_plugins)},
            "plugins": [{"id": "openchimera-core", "installed": "openchimera-core" in self._installed_plugins}],
        }

    def install_plugin(self, plugin_id: str) -> dict[str, object]:
        self._installed_plugins.add(plugin_id)
        return {"status": "installed", "plugin": {"id": plugin_id}}

    def uninstall_plugin(self, plugin_id: str) -> dict[str, object]:
        self._installed_plugins.discard(plugin_id)
        return {"status": "uninstalled", "plugin": {"id": plugin_id}}

    def subsystem_status(self) -> dict[str, object]:
        return {
            "counts": {"total": 9, "available": 9, "invokable": 9},
            "subsystems": [
                {"id": "aegis_swarm", "health": "running", "description": "Aegis workflow and remediation subsystem."},
                {"id": "ascension_engine", "health": "running", "description": "Ascension deliberation and consensus subsystem."},
                {"id": "clawd_hybrid_rtx", "health": "available", "description": "Legacy CHIMERA Quantum and hybrid RTX inference surface."},
                {"id": "qwen_agent", "health": "available", "description": "Historical Qwen-Agent bridge and agent framework integration."},
                {"id": "context_hub", "health": "running", "description": "Context-Hub integration and MCP-adjacent memory bridge."},
                {"id": "deepagents_stack", "health": "available", "description": "Recovered deepagents, BettaFish, and everything-claude-code integration set."},
                {"id": "aether_operator_stack", "health": "available", "description": "Recovered AETHER operator stack covering router, context sensing, and voice-actuation lineage."},
                {"id": "aegis_mobile_gateway", "health": "available", "description": "Mobile operator client and gateway bridge."},
                {"id": "minimind", "health": "available", "description": "MiniMind reasoning and training subsystem."},
            ],
        }

    def invoke_subsystem(self, subsystem_id: str, action: str, payload: dict[str, object] | None = None) -> dict[str, object]:
        if subsystem_id == "ascension_engine":
            return {"status": "ok", "prompt": str((payload or {}).get("prompt", ""))}
        if subsystem_id == "aegis_swarm":
            return {"status": "preview", "target": str((payload or {}).get("target_project", "fake/openchimera"))}
        return {"status": "ok", "action": action}

    def browser_fetch(self, url: str, max_chars: int = 4000) -> dict[str, object]:
        record = {
            "action": "fetch",
            "url": url,
            "content_type": "text/html",
            "text_preview": "Example page",
            "artifact": {"path": "fake/openchimera/sandbox/artifacts/browser/fetch.json"},
            "recorded_at": 0,
        }
        self._browser_history.append(record)
        return record

    def browser_submit_form(self, url: str, form_data: dict[str, object], method: str = "POST", max_chars: int = 4000) -> dict[str, object]:
        record = {
            "action": "submit_form",
            "url": url,
            "method": method.upper(),
            "content_type": "text/html",
            "text_preview": "Submitted",
            "artifact": {"path": "fake/openchimera/sandbox/artifacts/browser/form.json"},
            "recorded_at": 0,
        }
        self._browser_history.append(record)
        return record

    def upsert_channel_subscription(self, subscription: dict[str, object]) -> dict[str, object]:
        normalized = dict(subscription)
        normalized.setdefault("id", f"sub-{len(self._subscriptions) + 1}")
        self._subscriptions = [item for item in self._subscriptions if item.get("id") != normalized["id"]]
        self._subscriptions.append(normalized)
        return normalized

    def delete_channel_subscription(self, subscription_id: str) -> dict[str, object]:
        before = len(self._subscriptions)
        self._subscriptions = [item for item in self._subscriptions if item.get("id") != subscription_id]
        return {"deleted": len(self._subscriptions) != before, "subscription_id": subscription_id}

    def validate_channel_subscription(self, subscription_id: str = "", subscription: dict[str, object] | None = None) -> dict[str, object]:
        if subscription_id:
            for item in self._subscriptions:
                if item.get("id") == subscription_id:
                    item["last_validation"] = {"status": "delivered", "subscription_id": subscription_id, "status_code": 200}
                    return dict(item["last_validation"])
        return {"status": "delivered", "subscription_id": subscription_id or "inline", "status_code": 200}

    def dispatch_daily_briefing(self) -> dict[str, object]:
        delivery = {"topic": "system/briefing/daily", "delivery_count": len(self._subscriptions), "results": []}
        self._delivery_history.append({"topic": "system/briefing/daily", "delivery_count": len(self._subscriptions), "delivered_count": len(self._subscriptions), "error_count": 0, "results": []})
        return {"briefing": self.daily_briefing(), "delivery": delivery}

    def dispatch_channel(self, topic: str, payload: dict[str, object] | None = None) -> dict[str, object]:
        self._delivery_history.append({"topic": topic, "delivery_count": len(self._subscriptions), "delivered_count": len(self._subscriptions), "error_count": 0, "results": [{"status": "delivered"}]})
        return {
            "topic": topic,
            "payload": payload or {},
            "delivery": {"topic": topic, "delivery_count": len(self._subscriptions), "results": []},
        }

    def job_queue_status(self, status_filter: str | None = None, job_type: str | None = None, limit: int | None = None) -> dict[str, object]:
        jobs = list(self._jobs)
        if status_filter:
            jobs = [item for item in jobs if item.get("status") == status_filter]
        if job_type:
            jobs = [item for item in jobs if item.get("job_type") == job_type or item.get("job_class") == job_type]
        if limit is not None:
            jobs = jobs[:limit]
        return {
            "running": True,
            "store_path": "fake/openchimera/data/job_queue.json",
            "jobs": jobs,
            "counts": {
                "total": len(jobs),
                "queued": sum(1 for item in jobs if item.get("status") == "queued"),
                "running": 0,
                "completed": sum(1 for item in jobs if item.get("status") == "completed"),
                "failed": 0,
                "cancelled": sum(1 for item in jobs if item.get("status") == "cancelled"),
            },
            "filters": {"status": status_filter or "", "job_type": job_type or "", "limit": limit or 0},
            "total_counts": {
                "total": len(self._jobs),
                "queued": sum(1 for item in self._jobs if item.get("status") == "queued"),
                "running": 0,
                "completed": sum(1 for item in self._jobs if item.get("status") == "completed"),
                "failed": 0,
                "cancelled": sum(1 for item in self._jobs if item.get("status") == "cancelled"),
            },
        }

    def create_operator_job(self, job_type: str, payload: dict[str, object], max_attempts: int = 3) -> dict[str, object]:
        record = {
            "job_id": f"job-{len(self._jobs) + 1}",
            "job_type": "autonomy.preview_repair" if payload.get("job") == "preview_self_repair" else job_type,
            "job_class": "autonomy.preview_repair" if payload.get("job") == "preview_self_repair" else job_type,
            "label": "Preview self repair" if payload.get("job") == "preview_self_repair" else job_type,
            "payload": payload,
            "status": "queued",
            "max_attempts": max_attempts,
        }
        self._jobs.append(record)
        return record

    def get_operator_job(self, job_id: str) -> dict[str, object]:
        for job in self._jobs:
            if job["job_id"] == job_id:
                return job
        return {"status": "missing", "job_id": job_id}

    def cancel_operator_job(self, job_id: str) -> dict[str, object]:
        for job in self._jobs:
            if job["job_id"] == job_id:
                job["status"] = "cancelled"
                return {"status": "cancelled", "job_id": job_id}
        return {"status": "missing", "job_id": job_id}

    def replay_operator_job(self, job_id: str) -> dict[str, object]:
        return self.create_operator_job("autonomy", {"job": "sync_scouted_models"}, 3)

    def observability_status(self) -> dict[str, object]:
        return {
            "http": {"total_requests": 2, "status_codes": {"200": 2}, "routes": {"GET /health": 1}, "average_duration_ms": 1.0, "recent_requests": []},
            "llm": {"total_completions": 1, "fallback_completions": 0, "models": {"openchimera-local": 1}, "query_types": {"general": 1}, "recent_completions": []},
        }

    def set_provider_credential(self, provider_id: str, key: str, value: str) -> dict[str, object]:
        masked = value[:2] + ("*" * max(0, len(value) - 4)) + value[-2:] if len(value) > 4 else ("*" * len(value))
        self._credentials[provider_id] = {
            "configured": True,
            "keys": [key],
            "masked": {key: masked},
        }
        return self._credentials[provider_id]

    def delete_provider_credential(self, provider_id: str, key: str) -> dict[str, object]:
        self._credentials.pop(provider_id, None)
        return {"configured": False, "keys": [], "masked": {}}

    def local_runtime_status(self) -> dict[str, object]:
        return {"enabled": True}

    def harness_port_status(self) -> dict[str, object]:
        return {"available": True}

    def minimind_status(self) -> dict[str, object]:
        return {"available": True, "runtime": {"server": {"running": False}}}

    def autonomy_status(self) -> dict[str, object]:
        return {"running": False, "jobs": {"run_self_audit": {"enabled": True, "last_status": "never"}}}

    def autonomy_diagnostics(self) -> dict[str, object]:
        return {
            "status": "ok",
            "scheduler": {"artifacts": {"self_audit": "fake/openchimera/data/autonomy/self_audit.json"}},
            "provider_activation": {"prefer_free_models": self._prefer_free_models},
            "job_queue": self.job_queue_status(),
            "artifacts": {
                "self_audit": {"status": "warning", "findings": [{"id": "autonomy-job-drift"}]},
                "degradation_chains": {"status": "degraded", "chains": [{"id": "generation-path-offline"}]},
            },
            "artifact_history": {"history": [{"artifact_name": "self_audit", "summary": "1 self-audit finding", "status": "warning"}]},
        }

    def autonomy_artifact_history(self, artifact_name: str | None = None, limit: int = 20) -> dict[str, object]:
        return {
            "status": "ok",
            "artifact_name": artifact_name or "",
            "count": 1,
            "history": [{"artifact_name": artifact_name or "self_audit", "summary": "1 self-audit finding", "status": "warning"}],
        }

    def autonomy_artifact(self, artifact_name: str) -> dict[str, object]:
        if artifact_name == "operator_digest":
            return {
                "artifact_name": "operator_digest",
                "status": "ok",
                "summary": {"recent_alert_count": 1, "failed_job_count": 1, "failed_channel_delivery_count": 1},
                "dispatch": {"topic": "system/briefing/daily"},
            }
        return {"artifact_name": artifact_name, "status": "warning", "findings": [{"id": "autonomy-job-drift"}]}

    def operator_digest(self) -> dict[str, object]:
        return self.autonomy_artifact("operator_digest")

    def model_registry_status(self) -> dict[str, object]:
        return {
            "providers": [{"id": "local-llama-cpp"}],
            "discovery": {"scouted_models_available": True, "discovered_models_available": True},
            "recommendations": {"needs_cloud_fallback": False, "prefer_free_models": self._prefer_free_models, "suggested_free_models": [{"id": "openrouter/qwen-free"}]},
        }

    def provider_activation_status(self) -> dict[str, object]:
        return {
            "providers": self._providers,
            "preferred_cloud_provider": self._preferred_cloud_provider,
            "prefer_free_models": self._prefer_free_models,
            "discovery": {"scouted_models_available": True, "discovered_models_available": True},
            "model_roles": self._model_roles,
        }

    def model_role_status(self) -> dict[str, object]:
        return {"roles": self._model_roles, "overrides": {}}

    def configure_model_roles(self, overrides: dict[str, object]) -> dict[str, object]:
        for key, value in overrides.items():
            if key == "consensus_ensemble" and isinstance(value, list):
                self._model_roles[key] = {"models": [str(item) for item in value], "source": "override"}
            else:
                self._model_roles[str(key)] = {"model": str(value), "source": "override"}
        return self.model_role_status()

    def capability_status(self) -> dict[str, object]:
        return dict(self._capability_status)

    def mcp_status(self) -> dict[str, object]:
        servers = self.list_capabilities("mcp")
        return {
            "counts": {
                "total": len(servers),
                "healthy": sum(1 for item in servers if str(item.get("status", "")).lower() in {"healthy", "discovered"}),
                "registered": 1,
            },
            "servers": servers,
            "registry": {
                "counts": {"total": 1, "healthy": 1, "enabled": 1},
                "servers": [{"id": "context_gateway_remote", "transport": "http", "status": "healthy"}],
            },
        }

    def mcp_registry_status(self) -> dict[str, object]:
        return {
            "counts": {"total": 1, "healthy": 1, "enabled": 1},
            "servers": [{"id": "context_gateway_remote", "transport": "http", "status": "healthy"}],
        }

    def register_mcp_connector(
        self,
        server_id: str,
        *,
        transport: str,
        name: str | None = None,
        description: str | None = None,
        url: str | None = None,
        command: str | None = None,
        args: list[str] | None = None,
        enabled: bool = True,
    ) -> dict[str, object]:
        return {
            "id": server_id,
            "transport": transport,
            "name": name or server_id,
            "description": description or "",
            "url": url,
            "command": command,
            "args": args or [],
            "enabled": enabled,
            "status": "registered" if enabled else "disabled",
        }

    def unregister_mcp_connector(self, server_id: str) -> dict[str, object]:
        return {"id": server_id, "deleted": True}

    def probe_mcp_connectors(self, server_id: str | None = None, timeout_seconds: float = 3.0) -> dict[str, object]:
        return {
            "counts": {"total": 1, "healthy": 1},
            "servers": [{"id": server_id or "context_gateway_remote", "status": "healthy", "timeout_seconds": timeout_seconds}],
        }

    def list_capabilities(self, kind: str) -> list[dict[str, object]]:
        fixtures = {
            "commands": [{"id": "bootstrap", "description": "Create missing local state."}],
            "tools": [{"id": "browser.fetch", "description": "Fetch a web page."}],
            "skills": [{"id": "appforge-mcp", "description": "AppForge MCP bridge."}],
            "plugins": [{"id": "openchimera-core", "description": "Core runtime bundle."}],
            "mcp": [{"id": "context_hub", "status": "healthy"}],
        }
        return fixtures[kind]

    def refresh_model_registry(self) -> dict[str, object]:
        return {
            "generated_at": "2026-01-01T00:00:00+00:00",
            "providers": [{"id": "local-llama-cpp"}],
            "discovery": {"scouted_models_available": True, "discovered_models_available": True},
            "recommendations": {"prefer_free_models": self._prefer_free_models, "suggested_free_models": [{"id": "openrouter/qwen-free"}]},
        }

    def configure_provider_activation(
        self,
        enabled_provider_ids: list[str] | None = None,
        preferred_cloud_provider: str | None = None,
        prefer_free_models: bool | None = None,
    ) -> dict[str, object]:
        enabled_provider_ids = enabled_provider_ids or []
        self._preferred_cloud_provider = preferred_cloud_provider or ""
        if prefer_free_models is not None:
            self._prefer_free_models = bool(prefer_free_models)
        updated = []
        for provider in self._providers:
            enabled = provider["id"] in enabled_provider_ids
            updated.append(
                {
                    "id": provider["id"],
                    "enabled": enabled,
                    "activation_state": {
                        "enabled": enabled,
                        "preferred_cloud_provider": bool(self._preferred_cloud_provider and self._preferred_cloud_provider == provider["id"]),
                        "prefer_free_models": self._prefer_free_models,
                    },
                }
            )
        self._providers = updated
        return {
            "status": "ok",
            "providers": self._providers,
            "preferred_cloud_provider": self._preferred_cloud_provider,
            "prefer_free_models": self._prefer_free_models,
            "discovery": {"scouted_models_available": True, "discovered_models_available": True},
        }

    def onboarding_status(self) -> dict[str, object]:
        return self._onboarding

    def apply_onboarding(self, payload: dict[str, object]) -> dict[str, object]:
        preferred_local = payload.get("preferred_local_model") or payload.get("local_model_asset_id") or "phi-3.5-mini"
        self._onboarding = {
            "steps": [
                {"id": "local-model", "completed": bool(payload.get("preferred_local_model") or payload.get("local_model_asset_path")), "detail": preferred_local},
                {"id": "provider-credentials", "completed": bool(payload.get("provider_credentials")), "detail": list((payload.get("provider_credentials") or {}).keys())},
                {"id": "channels", "completed": bool(payload.get("channel_subscription")), "detail": 1 if payload.get("channel_subscription") else 0},
                {"id": "runtime-roots", "completed": True, "detail": {"missing_required_roots": []}},
            ],
            "completed": True,
            "recommendations": {"suggested_local_models": [{"id": preferred_local}]},
            "validation": {"missing_required_roots": []},
        }
        return self._onboarding

    def reset_onboarding(self) -> dict[str, object]:
        self._onboarding = {"steps": [], "completed": False, "recommendations": {"suggested_local_models": [{"id": "phi-3.5-mini"}]}, "validation": {"missing_required_roots": []}}
        return self._onboarding

    def integration_status(self) -> dict[str, object]:
        return {
            "engines": {
                "project_evo_swarm": {"detected": True, "integrated_runtime": True},
                "qwen_agent": {"detected": True, "integrated_runtime": True, "declared_in_memory": True, "source_memory": ["2026-03-06.md"], "recovery_state": "runtime-bridge", "operator_actionable": False},
                "context_hub": {"detected": True, "integrated_runtime": True, "declared_in_memory": True, "source_memory": ["2026-03-24.md", "hub_service.py"], "recovery_state": "runtime-bridge", "operator_actionable": False},
                "deepagents_stack": {"detected": True, "integrated_runtime": True, "declared_in_memory": True, "source_memory": ["2026-03-24.md"], "recovery_state": "runtime-bridge", "operator_actionable": False},
                "aether_operator_stack": {"detected": True, "integrated_runtime": True, "declared_in_memory": True, "source_memory": ["2026-03-18.md", "2026-03-20.md", "2026-03-21.md"], "recovery_state": "runtime-bridge", "operator_actionable": False},
                "clawd_hybrid_rtx": {"detected": True, "integrated_runtime": True, "declared_in_memory": True, "source_memory": ["2026-02-24-1200.md"], "recovery_state": "runtime-bridge", "operator_actionable": False},
                "aegis_mobile_gateway": {"detected": True, "integrated_runtime": True, "declared_in_memory": True, "source_memory": ["2026-03-21.md"], "recovery_state": "runtime-bridge", "operator_actionable": False},
                "abo_cluster": {"detected": False, "integrated_runtime": False, "declared_in_memory": True, "source_memory": ["2026-03-17.md"], "public_focus": False, "remediation_exempt": True, "recovery_state": "archived-lineage", "operator_actionable": False},
                "tri_core_architecture": {"detected": False, "integrated_runtime": False, "declared_in_memory": True, "source_memory": ["2026-03-17-snapshot.md"], "recovery_state": "memory-lineage", "operator_actionable": False},
            },
            "remediation": [],
            "lineage_only": ["tri_core_architecture"],
        }

    def aegis_status(self) -> dict[str, object]:
        return {"available": True, "running": True}

    def run_aegis_workflow(self, target_project: str | None = None, preview: bool = True) -> dict[str, object]:
        return {"status": "preview" if preview else "ok", "target": target_project or "fake/openchimera"}

    def preview_self_repair(self, target_project: str | None = None, enqueue: bool = False, max_attempts: int = 3) -> dict[str, object]:
        if enqueue:
            return self.create_operator_job("autonomy", {"job": "preview_self_repair", "target_project": target_project or "fake/openchimera"}, max_attempts)
        return {
            "status": "preview",
            "target": "fake/openchimera/data/autonomy/preview_self_repair.json",
            "focus_area_count": 2,
            "recommendation_count": 3,
        }

    def ascension_status(self) -> dict[str, object]:
        return {"available": True, "running": True}

    def deliberate(self, prompt: str, perspectives: list[str] | None = None, max_tokens: int = 256) -> dict[str, object]:
        return {"status": "ok", "prompt": prompt, "perspectives": [{"perspective": "architect", "content": "answer"}]}

    def daily_briefing(self) -> dict[str, object]:
        return {"summary": "OpenChimera daily briefing", "priorities": []}

    def chat_completion(self, **_: object) -> dict[str, object]:
        return {
            "id": "test",
            "object": "chat.completion",
            "created": 0,
            "model": "openchimera-local",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
            "openchimera": {
                "query_type": "general",
                "prompt_strategy": "chat_guided",
                "prompt_strategies_tried": ["chat_guided"],
            },
        }

    def embeddings(self, *_: object, **__: object) -> dict[str, object]:
        return {"object": "list", "data": []}

    def start_local_models(self, _: object = None) -> dict[str, object]:
        return {"started": []}

    def stop_local_models(self, _: object = None) -> dict[str, object]:
        return {"stopped": []}

    def start_autonomy(self) -> dict[str, object]:
        return {"status": "online"}

    def stop_autonomy(self) -> dict[str, object]:
        return {"status": "offline"}

    def run_autonomy_job(self, job: str, payload: dict[str, object] | None = None) -> dict[str, object]:
        self._autonomy_runs.append({"job": job, "payload": payload or {}})
        return {"job": job, "status": "ok", "payload": payload or {}}

    def dispatch_operator_digest(
        self,
        enqueue: bool = False,
        max_attempts: int = 3,
        history_limit: int | None = None,
        dispatch_topic: str | None = None,
    ) -> dict[str, object]:
        if enqueue:
            return self.create_operator_job(
                "autonomy",
                {
                    "job": "dispatch_operator_digest",
                    **({"history_limit": history_limit} if history_limit is not None else {}),
                    **({"dispatch_topic": dispatch_topic} if dispatch_topic else {}),
                },
                max_attempts,
            )
        return {
            "status": "ok",
            "dispatch_topic": dispatch_topic or "system/briefing/daily",
            "target": "fake/openchimera/data/autonomy/operator_digest.json",
            "recent_alert_count": history_limit or 1,
        }

    def build_minimind_dataset(self, force: bool = True) -> dict[str, object]:
        return {"built": True, "force": force}

    def start_minimind_server(self) -> dict[str, object]:
        return {"status": "started"}

    def stop_minimind_server(self) -> dict[str, object]:
        return {"status": "stopped"}

    def start_minimind_training(self, mode: str = "reason_sft", force_dataset: bool = False) -> dict[str, object]:
        return {"status": "running", "mode": mode, "force_dataset": force_dataset}

    def stop_minimind_training(self, job_id: str) -> dict[str, object]:
        return {"status": "stopped", "job_id": job_id}


class ApiContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self._original_api_token = os.environ.get("OPENCHIMERA_API_TOKEN")
        self._original_admin_token = os.environ.get("OPENCHIMERA_ADMIN_TOKEN")
        os.environ.pop("OPENCHIMERA_API_TOKEN", None)
        os.environ.pop("OPENCHIMERA_ADMIN_TOKEN", None)
        self.provider = _FakeProvider()
        self.server = OpenChimeraAPIServer(
            self.provider,
            host="127.0.0.1",
            port=0,
            system_status_provider=lambda: {
                "provider_online": True,
                "supervision": {"running": True},
                "deployment": {"mode": "local", "containerized": False},
            },
        )
        started = self.server.start()
        self.assertTrue(started)
        assert self.server.server is not None
        self.base_url = f"http://127.0.0.1:{self.server.server.server_port}"

    def tearDown(self) -> None:
        self.server.stop()
        if self._original_api_token is None:
            os.environ.pop("OPENCHIMERA_API_TOKEN", None)
        else:
            os.environ["OPENCHIMERA_API_TOKEN"] = self._original_api_token
        if self._original_admin_token is None:
            os.environ.pop("OPENCHIMERA_ADMIN_TOKEN", None)
        else:
            os.environ["OPENCHIMERA_ADMIN_TOKEN"] = self._original_admin_token
        for name in [
            "OPENCHIMERA_TLS_ENABLED",
            "OPENCHIMERA_TLS_CERTFILE",
            "OPENCHIMERA_TLS_KEYFILE",
            "OPENCHIMERA_TLS_KEY_PASSWORD",
        ]:
            os.environ.pop(name, None)

    def _get(self, path: str) -> dict[str, object]:
        with request.urlopen(f"{self.base_url}{path}", timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    def _post(self, path: str, payload: dict[str, object], headers: dict[str, str] | None = None) -> dict[str, object]:
        body = json.dumps(payload).encode("utf-8")
        merged_headers = {"Content-Type": "application/json"}
        if headers:
            merged_headers.update(headers)
        req = request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers=merged_headers,
            method="POST",
        )
        with request.urlopen(req, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    def _post_raw(self, path: str, body: bytes, headers: dict[str, str] | None = None) -> tuple[int, dict[str, object]]:
        merged_headers = {"Content-Type": "application/json", "Content-Length": str(len(body))}
        if headers:
            merged_headers.update(headers)
        last_os_exc: OSError | None = None
        for _attempt in range(2):
            req = request.Request(
                f"{self.base_url}{path}",
                data=body,
                headers=merged_headers,
                method="POST",
            )
            try:
                with request.urlopen(req, timeout=10) as response:
                    return response.status, json.loads(response.read().decode("utf-8"))
            except error.HTTPError as exc:
                raw = exc.read().decode("utf-8")
                exc.close()
                return exc.code, json.loads(raw)
            except OSError as exc:
                # Windows (WinError 10053/10054) can abort the connection when the
                # server sends a 429 and immediately closes the socket.  Retry once.
                last_os_exc = exc
                import time as _t; _t.sleep(0.05)
        raise last_os_exc  # type: ignore[misc]

    def _post_raw_with_headers(
        self,
        path: str,
        body: bytes,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, object], dict[str, str]]:
        merged_headers = {"Content-Type": "application/json", "Content-Length": str(len(body))}
        if headers:
            merged_headers.update(headers)
        req = request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers=merged_headers,
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=10) as response:
                return response.status, json.loads(response.read().decode("utf-8")), dict(response.headers.items())
        except error.HTTPError as exc:
            response_body = exc.read().decode("utf-8")
            response_headers = dict(exc.headers.items())
            exc.close()
            return exc.code, json.loads(response_body), response_headers

    def _get_error(self, path: str) -> tuple[int, dict[str, object]]:
        req = request.Request(f"{self.base_url}{path}", method="GET")
        try:
            with request.urlopen(req, timeout=10) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8")
            exc.close()
            return exc.code, json.loads(body)

    def _get_error_with_headers(self, path: str, headers: dict[str, str] | None = None) -> tuple[int, dict[str, object], dict[str, str]]:
        req = request.Request(f"{self.base_url}{path}", headers=headers or {}, method="GET")
        try:
            with request.urlopen(req, timeout=10) as response:
                return response.status, json.loads(response.read().decode("utf-8")), dict(response.headers.items())
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8")
            response_headers = dict(exc.headers.items())
            exc.close()
            return exc.code, json.loads(body), response_headers

    def _restart_server(self) -> None:
        self.server.stop()
        self.server = OpenChimeraAPIServer(
            self.provider,
            host="127.0.0.1",
            port=0,
            system_status_provider=lambda: {
                "provider_online": True,
                "supervision": {"running": True},
                "deployment": {"mode": "local", "containerized": False},
            },
        )
        started = self.server.start()
        self.assertTrue(started)
        assert self.server.server is not None
        self.base_url = f"http://127.0.0.1:{self.server.server.server_port}"

    def test_system_status_endpoint_returns_provider_snapshot(self) -> None:
        payload = self._get("/v1/system/status")
        self.assertTrue(payload["provider_online"])
        self.assertTrue(payload["supervision"]["running"])
        self.assertEqual(payload["deployment"]["mode"], "local")

    def test_readiness_endpoint_returns_ready_state(self) -> None:
        payload = self._get("/v1/system/readiness")
        self.assertTrue(payload["ready"])
        self.assertEqual(payload["status"], "ready")
        self.assertFalse(payload["auth_required"])

    def test_control_plane_status_endpoint_returns_operator_snapshot(self) -> None:
        payload = self._get("/v1/control-plane/status")
        self.assertTrue(payload["readiness"]["ready"])
        self.assertIn("deployment", payload)
        self.assertIn("provider_activation", payload)
        self.assertIn("channels", payload)
        self.assertIn("jobs", payload)

    def test_health_endpoint_reports_auth_requirement(self) -> None:
        payload = self._get("/health")
        self.assertFalse(payload["auth_required"])

    def test_documentation_endpoints_are_public_and_hardened(self) -> None:
        with request.urlopen(f"{self.base_url}/openapi.json", timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")
            self.assertEqual(response.headers.get("X-Frame-Options"), "DENY")
            self.assertEqual(response.headers.get("Cache-Control"), "no-store")
        self.assertEqual(payload["openapi"], "3.1.0")
        self.assertIn("/v1/system/status", payload["paths"])

        req = request.Request(f"{self.base_url}/docs", method="GET")
        with request.urlopen(req, timeout=10) as response:
            body = response.read().decode("utf-8")
            self.assertIn("text/html", response.headers.get("Content-Type", ""))
            self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")
            self.assertIn("OpenChimera API", body)

    def test_config_status_endpoint_returns_sanitized_configuration(self) -> None:
        payload = self._get("/v1/config/status")
        self.assertIn("auth", payload)
        self.assertIn("deployment", payload)
        self.assertIn("profile_sources", payload)
        self.assertNotIn("user_token", payload["auth"])

    def test_auth_and_credential_status_endpoints(self) -> None:
        auth_status = self._get("/v1/auth/status")
        self.assertFalse(auth_status["enabled"])
        credentials = self._get("/v1/credentials/status")
        self.assertEqual(credentials["providers"], {})

    def test_metrics_endpoint_and_request_id_header(self) -> None:
        req = request.Request(f"{self.base_url}/health", method="GET")
        with request.urlopen(req, timeout=10) as response:
            request_id = response.headers.get("X-Request-Id")
            payload = json.loads(response.read().decode("utf-8"))
        self.assertEqual(payload["status"], "online")
        self.assertTrue(request_id)

    def test_request_id_header_is_propagated_when_supplied(self) -> None:
        req = request.Request(f"{self.base_url}/health", headers={"X-Request-Id": "operator-trace-123"}, method="GET")
        with request.urlopen(req, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
            request_id = response.headers.get("X-Request-Id")

        self.assertEqual(payload["status"], "online")
        self.assertEqual(request_id, "operator-trace-123")

    def test_query_run_rejects_invalid_permission_scope_with_422(self) -> None:
        status, payload = self._post_raw(
            "/v1/query/run",
            json.dumps({"query": "Summarize runtime state", "permission_scope": "root"}).encode("utf-8"),
        )

        self.assertEqual(status, 422)
        self.assertEqual(payload["error"], "Validation failed")
        self.assertTrue(payload["details"])

    def test_jobs_status_rejects_invalid_limit_query_with_422(self) -> None:
        status, payload = self._get_error("/v1/jobs/status?limit=zero")

        self.assertEqual(status, 422)
        self.assertEqual(payload["error"], "Validation failed")

    def test_json_payload_limit_returns_413(self) -> None:
        oversized_body = json.dumps({"query": "x" * (10 * 1024 * 1024)}).encode("utf-8")

        status, payload = self._post_raw("/v1/query/run", oversized_body)

        self.assertEqual(status, 413)
        self.assertIn("10MB", payload["error"])

    def test_media_understand_image_rejects_path_traversal_with_422(self) -> None:
        status, payload = self._post_raw(
            "/v1/media/understand-image",
            json.dumps({"prompt": "describe", "image_path": "..\\..\\Windows\\win.ini"}).encode("utf-8"),
        )

        self.assertEqual(status, 422)
        self.assertEqual(payload["error"], "Validation failed")

    def test_public_endpoint_rate_limit_returns_429(self) -> None:
        self.server.stop()
        self.server = OpenChimeraAPIServer(
            self.provider,
            host="127.0.0.1",
            port=0,
            system_status_provider=lambda: {"provider_online": True, "supervision": {"running": True}},
            rate_limiter=RateLimiter(global_rate_per_minute=1000, public_ip_rate_per_minute=1, expensive_ip_rate_per_minute=10),
        )
        started = self.server.start()
        self.assertTrue(started)
        assert self.server.server is not None
        self.base_url = f"http://127.0.0.1:{self.server.server.server_port}"

        first = self._get("/health")
        status, payload = self._get_error("/health")

        self.assertEqual(first["status"], "online")
        self.assertEqual(status, 429)
        self.assertEqual(payload["error"], "Too Many Requests")

    def test_rate_limit_response_includes_retry_after_and_request_id(self) -> None:
        self.server.stop()
        self.server = OpenChimeraAPIServer(
            self.provider,
            host="127.0.0.1",
            port=0,
            system_status_provider=lambda: {"provider_online": True, "supervision": {"running": True}},
            rate_limiter=RateLimiter(global_rate_per_minute=1000, public_ip_rate_per_minute=1, expensive_ip_rate_per_minute=10),
        )
        started = self.server.start()
        self.assertTrue(started)
        assert self.server.server is not None
        self.base_url = f"http://127.0.0.1:{self.server.server.server_port}"

        self._get("/health")
        status, payload, headers = self._get_error_with_headers("/health", {"X-Request-Id": "rate-limit-check"})

        self.assertEqual(status, 429)
        self.assertEqual(payload["error"], "Too Many Requests")
        self.assertEqual(headers.get("Retry-After"), str(payload["details"][0]["retry_after_seconds"]))
        self.assertEqual(headers.get("X-Request-Id"), "rate-limit-check")
        self.assertEqual(headers.get("Cache-Control"), "no-store")

    def test_expensive_endpoint_rate_limit_returns_429(self) -> None:
        self.server.stop()
        self.server = OpenChimeraAPIServer(
            self.provider,
            host="127.0.0.1",
            port=0,
            system_status_provider=lambda: {"provider_online": True, "supervision": {"running": True}},
            rate_limiter=RateLimiter(global_rate_per_minute=1000, public_ip_rate_per_minute=60, expensive_ip_rate_per_minute=1),
        )
        started = self.server.start()
        self.assertTrue(started)
        assert self.server.server is not None
        self.base_url = f"http://127.0.0.1:{self.server.server.server_port}"

        first = self._post("/v1/browser/fetch", {"url": "https://example.invalid", "max_chars": 500})
        status, payload = self._post_raw(
            "/v1/browser/fetch",
            json.dumps({"url": "https://example.invalid", "max_chars": 500}).encode("utf-8"),
        )

        self.assertEqual(first["action"], "fetch")
        self.assertEqual(status, 429)
        self.assertEqual(payload["error"], "Too Many Requests")

    def test_capabilities_endpoints(self) -> None:
        status = self._get("/v1/capabilities/status")
        self.assertEqual(status["counts"]["commands"], 6)

        commands = self._get("/v1/capabilities/commands")
        self.assertEqual(commands["data"][0]["id"], "bootstrap")

        mcp = self._get("/v1/capabilities/mcp")
        self.assertEqual(mcp["data"][0]["id"], "context_hub")

    def test_http_mcp_endpoint_supports_initialize_and_tool_calls(self) -> None:
        descriptor = self._get("/mcp")
        self.assertEqual(descriptor["name"], "openchimera-local")
        self.assertEqual(descriptor["capabilities"]["resources"], 8)
        self.assertEqual(descriptor["capabilities"]["prompts"], 2)

        initialized = self._post(
            "/mcp",
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
        )
        self.assertEqual(initialized["result"]["serverInfo"]["name"], "openchimera-local")

        listed = self._post("/mcp", {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tool_names = {item["name"] for item in listed["result"]["tools"]}
        self.assertIn("openchimera.operator_digest", tool_names)

        called = self._post(
            "/mcp",
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "openchimera.operator_digest", "arguments": {}},
            },
        )
        self.assertEqual(called["result"]["structuredContent"]["artifact_name"], "operator_digest")

    def test_mcp_registry_and_probe_endpoints(self) -> None:
        registry = self._get("/v1/mcp/registry")
        self.assertEqual(registry["counts"]["total"], 1)
        self.assertEqual(registry["servers"][0]["id"], "context_gateway_remote")

        stored = self._post(
            "/v1/mcp/registry/set",
            {"id": "context_gateway_remote", "transport": "http", "url": "http://localhost:9100/mcp", "name": "Context Gateway"},
        )
        self.assertEqual(stored["id"], "context_gateway_remote")
        self.assertEqual(stored["transport"], "http")

        probed = self._post("/v1/mcp/probe", {"id": "context_gateway_remote", "timeout_seconds": 1.25})
        self.assertEqual(probed["counts"]["healthy"], 1)
        self.assertEqual(probed["servers"][0]["id"], "context_gateway_remote")

        deleted = self._post("/v1/mcp/registry/delete", {"id": "context_gateway_remote"})
        self.assertTrue(deleted["deleted"])

    def test_channel_subscription_and_dispatch_endpoints(self) -> None:
        status = self._get("/v1/channels/status")
        self.assertEqual(status["counts"]["total"], 0)

        stored = self._post(
            "/v1/channels/subscriptions/set",
            {"id": "ops-webhook", "channel": "webhook", "endpoint": "http://example.invalid/webhook", "topics": ["system/briefing/daily"]},
        )
        self.assertEqual(stored["id"], "ops-webhook")

        status = self._get("/v1/channels/status")
        self.assertEqual(status["counts"]["total"], 1)
        self.assertEqual(status["delivery_history_count"], 0)

        dispatched = self._post("/v1/channels/dispatch/daily-briefing", {})
        self.assertEqual(dispatched["delivery"]["topic"], "system/briefing/daily")

        dispatched_topic = self._post(
            "/v1/channels/dispatch",
            {"topic": "system/autonomy/alert", "payload": {"message": "operator attention required"}},
        )
        self.assertEqual(dispatched_topic["topic"], "system/autonomy/alert")
        self.assertEqual(dispatched_topic["payload"]["message"], "operator attention required")

        history = self._get("/v1/channels/history?topic=system/autonomy/alert&status=delivered&limit=5")
        self.assertEqual(history["count"], 1)
        self.assertEqual(history["history"][0]["topic"], "system/autonomy/alert")

        validated = self._post("/v1/channels/validate", {"subscription_id": "ops-webhook"})
        self.assertEqual(validated["subscription_id"], "ops-webhook")
        self.assertEqual(validated["status"], "delivered")

        deleted = self._post("/v1/channels/subscriptions/delete", {"subscription_id": "ops-webhook"})
        self.assertTrue(deleted["deleted"])

    def test_browser_endpoints(self) -> None:
        status = self._get("/v1/browser/status")
        self.assertTrue(status["enabled"])

        fetched = self._post("/v1/browser/fetch", {"url": "https://example.invalid", "max_chars": 500})
        self.assertEqual(fetched["action"], "fetch")

        submitted = self._post(
            "/v1/browser/submit-form",
            {"url": "https://example.invalid/form", "method": "POST", "form_data": {"q": "openchimera"}},
        )
        self.assertEqual(submitted["action"], "submit_form")

    def test_job_queue_endpoints(self) -> None:
        status = self._get("/v1/jobs/status")
        self.assertEqual(status["counts"]["total"], 0)

        created = self._post(
            "/v1/jobs/create",
            {"job_type": "autonomy", "payload": {"job": "sync_scouted_models"}, "max_attempts": 2},
        )
        self.assertEqual(created["job_type"], "autonomy")

        status = self._get("/v1/jobs/status")
        self.assertEqual(status["counts"]["total"], 1)

        cancelled = self._post("/v1/jobs/cancel", {"job_id": created["job_id"]})
        self.assertEqual(cancelled["status"], "cancelled")

        replayed = self._post("/v1/jobs/replay", {"job_id": created["job_id"]})
        self.assertTrue(replayed["job_type"].startswith("autonomy"))

        repair_job = self._post(
            "/v1/jobs/create",
            {"job_type": "autonomy", "payload": {"job": "preview_self_repair", "target_project": "fake/openchimera"}, "max_attempts": 2},
        )

        filtered = self._get("/v1/jobs/status?job_type=autonomy.preview_repair")
        self.assertEqual(filtered["jobs"][0]["job_id"], repair_job["job_id"])
        self.assertEqual(filtered["jobs"][0]["job_class"], "autonomy.preview_repair")

        fetched = self._get(f"/v1/jobs/get?job_id={created['job_id']}")
        self.assertEqual(fetched["job_id"], created["job_id"])

    def test_provider_activation_endpoints(self) -> None:
        status = self._get("/v1/providers/status")
        self.assertEqual(status["providers"][0]["id"], "local-llama-cpp")
        self.assertFalse(status["prefer_free_models"])
        self.assertTrue(status["discovery"]["scouted_models_available"])

        configured = self._post(
            "/v1/providers/configure",
            {"enabled_provider_ids": ["local-llama-cpp", "openai"], "preferred_cloud_provider": "openai", "prefer_free_models": True},
        )
        self.assertEqual(configured["preferred_cloud_provider"], "openai")
        self.assertTrue(configured["prefer_free_models"])
        self.assertTrue(any(item["id"] == "openai" and item["enabled"] for item in configured["providers"]))
        self.assertTrue(any(item["id"] == "openai" and item["activation_state"]["prefer_free_models"] for item in configured["providers"]))

    def test_autonomy_diagnostics_and_preview_repair_endpoints(self) -> None:
        diagnostics = self._get("/v1/autonomy/diagnostics")
        self.assertEqual(diagnostics["artifacts"]["self_audit"]["status"], "warning")
        self.assertEqual(diagnostics["artifacts"]["degradation_chains"]["chains"][0]["id"], "generation-path-offline")
        self.assertEqual(diagnostics["artifact_history"]["history"][0]["artifact_name"], "self_audit")

        history = self._get("/v1/autonomy/artifacts/history?artifact=self_audit&limit=5")
        self.assertEqual(history["artifact_name"], "self_audit")

        artifact = self._get("/v1/autonomy/artifacts/get?artifact=self_audit")
        self.assertEqual(artifact["artifact_name"], "self_audit")

        preview = self._post("/v1/autonomy/preview-repair", {"target_project": "fake/openchimera"})
        self.assertEqual(preview["status"], "preview")

        queued = self._post("/v1/autonomy/preview-repair", {"target_project": "fake/openchimera", "enqueue": True, "max_attempts": 2})
        self.assertEqual(queued["job_class"], "autonomy.preview_repair")

        operator_digest = self._get("/v1/autonomy/operator-digest")
        self.assertEqual(operator_digest["artifact_name"], "operator_digest")

        dispatched_digest = self._post(
            "/v1/autonomy/operator-digest/dispatch",
            {"history_limit": 3, "dispatch_topic": "system/briefing/daily"},
        )
        self.assertEqual(dispatched_digest["dispatch_topic"], "system/briefing/daily")
        self.assertEqual(dispatched_digest["recent_alert_count"], 3)

        queued_digest = self._post(
            "/v1/autonomy/operator-digest/dispatch",
            {"enqueue": True, "max_attempts": 2, "history_limit": 4},
        )
        self.assertEqual(queued_digest["job_type"], "autonomy")

    def test_autonomy_run_endpoint_forwards_payload(self) -> None:
        result = self._post("/v1/autonomy/run", {"job": "preview_self_repair", "target_project": "fake/openchimera"})
        self.assertEqual(result["job"], "preview_self_repair")
        self.assertEqual(result["payload"]["target_project"], "fake/openchimera")

    def test_query_model_roles_plugin_and_subsystem_endpoints(self) -> None:
        model_roles = self._get("/v1/model-roles/status")
        self.assertEqual(model_roles["roles"]["main_loop_model"]["model"], "qwen2.5-7b")

        tools = self._get("/v1/tools/status")
        self.assertEqual(tools["counts"]["total"], 2)
        self.assertTrue(any(item["id"] == "browser.fetch" for item in tools["tools"]))

        configured_roles = self._post("/v1/model-roles/configure", {"overrides": {"fast_model": "llama-3.2-3b"}})
        self.assertEqual(configured_roles["roles"]["fast_model"]["model"], "llama-3.2-3b")

        query = self._post("/v1/query/run", {"query": "Summarize runtime state", "permission_scope": "user"})
        self.assertTrue(query["session_id"])

        query_with_tools = self._post(
            "/v1/query/run",
            {
                "query": "Fetch runtime docs and summarize them",
                "permission_scope": "admin",
                "execute_tools": True,
                "tool_requests": [{"tool_id": "browser.fetch", "arguments": {"url": "https://example.com", "max_chars": 512}}],
            },
        )
        self.assertEqual(query_with_tools["executed_tools"][0]["tool_id"], "browser.fetch")

        sessions = self._get("/v1/query/sessions")
        self.assertEqual(len(sessions["data"]), 2)

        session = self._post("/v1/query/session/get", {"session_id": query["session_id"]})
        self.assertEqual(session["session_id"], query["session_id"])

        memory = self._get("/v1/query/memory")
        self.assertIn("scopes", memory)

        plugins_before = self._get("/v1/plugins/status")
        self.assertEqual(plugins_before["counts"]["installed"], 0)

        installed = self._post("/v1/plugins/install", {"plugin_id": "openchimera-core"})
        self.assertEqual(installed["status"], "installed")

        plugins_after = self._get("/v1/plugins/status")
        self.assertEqual(plugins_after["counts"]["installed"], 1)

        subsystems = self._get("/v1/subsystems/status")
        self.assertEqual(subsystems["counts"]["invokable"], 9)
        subsystem_ids = {item["id"] for item in subsystems["subsystems"]}
        self.assertIn("qwen_agent", subsystem_ids)
        self.assertIn("context_hub", subsystem_ids)
        self.assertIn("deepagents_stack", subsystem_ids)
        self.assertIn("aether_operator_stack", subsystem_ids)
        self.assertIn("clawd_hybrid_rtx", subsystem_ids)
        self.assertIn("aegis_mobile_gateway", subsystem_ids)

        invoked = self._post("/v1/subsystems/invoke", {"subsystem_id": "ascension_engine", "action": "deliberate", "payload": {"prompt": "next step"}})
        self.assertEqual(invoked["status"], "ok")

        tool_execution = self._post(
            "/v1/tools/execute",
            {"tool_id": "ascension.deliberate", "permission_scope": "user", "arguments": {"prompt": "derive next step", "max_tokens": 128}},
        )
        self.assertEqual(tool_execution["tool_id"], "ascension.deliberate")
        self.assertEqual(tool_execution["status"], "ok")

    def test_minimind_endpoints_round_trip(self) -> None:
        self.assertTrue(self._get("/v1/minimind/status")["available"])
        self.assertEqual(self._post("/v1/minimind/dataset/build", {"force": True})["built"], True)
        self.assertEqual(self._post("/v1/minimind/server/start", {})["status"], "started")
        self.assertEqual(self._post("/v1/minimind/training/start", {"mode": "reason_sft", "force_dataset": True})["status"], "running")
        self.assertEqual(self._post("/v1/minimind/training/stop", {"job_id": "job-1"})["job_id"], "job-1")
        self.assertEqual(self._post("/v1/minimind/server/stop", {})["status"], "stopped")

    def test_chat_completion_exposes_prompt_metadata(self) -> None:
        payload = self._post("/v1/chat/completions", {"messages": [{"role": "user", "content": "Hello"}]})
        self.assertEqual(payload["openchimera"]["query_type"], "general")
        self.assertEqual(payload["openchimera"]["prompt_strategy"], "chat_guided")
        self.assertEqual(payload["openchimera"]["prompt_strategies_tried"], ["chat_guided"])

    def test_model_registry_and_onboarding_endpoints(self) -> None:
        registry = self._get("/v1/model-registry/status")
        self.assertEqual(registry["providers"][0]["id"], "local-llama-cpp")
        self.assertTrue(registry["discovery"]["discovered_models_available"])
        refreshed = self._post("/v1/model-registry/refresh", {})
        self.assertIn("generated_at", refreshed)
        self.assertIn("suggested_free_models", refreshed["recommendations"])
        onboarding = self._get("/v1/onboarding/status")
        self.assertEqual(onboarding["recommendations"]["suggested_local_models"][0]["id"], "phi-3.5-mini")

    def test_onboarding_apply_and_reset_endpoints(self) -> None:
        applied = self._post(
            "/v1/onboarding/apply",
            {
                "preferred_local_model": "qwen2.5-7b",
                "provider_credentials": {"openai": {"OPENAI_API_KEY": "sk-test-123456"}},
                "channel_subscription": {"id": "ops-webhook", "channel": "webhook", "endpoint": "http://example.invalid", "topics": ["system/briefing/daily"]},
            },
        )
        self.assertTrue(applied["completed"])
        self.assertEqual(applied["recommendations"]["suggested_local_models"][0]["id"], "qwen2.5-7b")

        registered = self._post(
            "/v1/onboarding/apply",
            {
                "local_model_asset_path": "D:/models/qwen2.5-7b-instruct-q4_k_m.gguf",
                "local_model_asset_id": "qwen2.5-7b",
            },
        )
        self.assertEqual(registered["recommendations"]["suggested_local_models"][0]["id"], "qwen2.5-7b")

        reset = self._post("/v1/onboarding/reset", {})
        self.assertFalse(reset["completed"])

    def test_integrations_status_endpoint(self) -> None:
        integrations = self._get("/v1/integrations/status")
        self.assertTrue(integrations["engines"]["project_evo_swarm"]["detected"])
        self.assertTrue(integrations["engines"]["qwen_agent"]["declared_in_memory"])
        self.assertTrue(integrations["engines"]["qwen_agent"]["integrated_runtime"])
        self.assertTrue(integrations["engines"]["context_hub"]["integrated_runtime"])
        self.assertTrue(integrations["engines"]["deepagents_stack"]["integrated_runtime"])
        self.assertTrue(integrations["engines"]["aether_operator_stack"]["integrated_runtime"])
        self.assertTrue(integrations["engines"]["clawd_hybrid_rtx"]["integrated_runtime"])
        self.assertTrue(integrations["engines"]["aegis_mobile_gateway"]["integrated_runtime"])
        self.assertEqual(integrations["engines"]["abo_cluster"]["source_memory"][0], "2026-03-17.md")
        self.assertFalse(integrations["engines"]["abo_cluster"]["public_focus"])
        self.assertEqual(integrations["engines"]["tri_core_architecture"]["source_memory"][0], "2026-03-17-snapshot.md")
        self.assertEqual(integrations["engines"]["tri_core_architecture"]["recovery_state"], "memory-lineage")
        self.assertIn("tri_core_architecture", integrations["lineage_only"])

    def test_advanced_capability_endpoints(self) -> None:
        self.assertTrue(self._get("/v1/aegis/status")["available"])
        self.assertTrue(self._get("/v1/ascension/status")["running"])
        self.assertEqual(self._get("/v1/briefings/daily")["summary"], "OpenChimera daily briefing")
        aegis_run = self._post("/v1/aegis/run", {"preview": True, "target_project": "fake/openchimera"})
        self.assertEqual(aegis_run["status"], "preview")
        ascension = self._post("/v1/ascension/deliberate", {"prompt": "What should we improve next?"})
        self.assertEqual(ascension["status"], "ok")

    def test_api_token_protects_non_public_routes(self) -> None:
        os.environ["OPENCHIMERA_API_TOKEN"] = "sandbox-token"
        self._restart_server()

        health = self._get("/health")
        self.assertTrue(health["auth_required"])
        readiness = self._get("/v1/system/readiness")
        self.assertTrue(readiness["auth_required"])

        docs = self._get("/openapi.json")
        self.assertEqual(docs["openapi"], "3.1.0")

        with self.assertRaises(error.HTTPError) as unauthorized:
            self._get("/v1/system/status")
        self.assertEqual(unauthorized.exception.code, 401)
        unauthorized.exception.close()

        with self.assertRaises(error.HTTPError) as unauthorized_config:
            self._get("/v1/config/status")
        self.assertEqual(unauthorized_config.exception.code, 401)
        unauthorized_config.exception.close()

        req = request.Request(
            f"{self.base_url}/v1/system/status",
            headers={"Authorization": "Bearer sandbox-token"},
            method="GET",
        )
        with request.urlopen(req, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.assertTrue(payload["provider_online"])

        config_req = request.Request(
            f"{self.base_url}/v1/config/status",
            headers={"Authorization": "Bearer sandbox-token"},
            method="GET",
        )
        with request.urlopen(config_req, timeout=10) as response:
            config_payload = json.loads(response.read().decode("utf-8"))
        self.assertIn("deployment", config_payload)

    def test_unauthorized_response_includes_bearer_challenge_and_request_id(self) -> None:
        os.environ["OPENCHIMERA_API_TOKEN"] = "sandbox-token"
        self._restart_server()

        status, payload, headers = self._get_error_with_headers(
            "/v1/system/status",
            {"X-Request-Id": "auth-check-123"},
        )

        self.assertEqual(status, 401)
        self.assertEqual(payload["error"], "Unauthorized")
        self.assertEqual(headers.get("WWW-Authenticate"), 'Bearer realm="OpenChimera"')
        self.assertEqual(headers.get("X-Request-Id"), "auth-check-123")
        self.assertEqual(headers.get("Cache-Control"), "no-store")
    def test_admin_token_required_for_mutating_routes(self) -> None:
        os.environ["OPENCHIMERA_API_TOKEN"] = "user-token"
        os.environ["OPENCHIMERA_ADMIN_TOKEN"] = "admin-token"
        self._restart_server()

        req = request.Request(
            f"{self.base_url}/v1/auth/status",
            headers={"Authorization": "Bearer user-token"},
            method="GET",
        )
        with request.urlopen(req, timeout=10) as response:
            auth_status = json.loads(response.read().decode("utf-8"))
        self.assertTrue(auth_status["admin_separate_from_user"])

        with self.assertRaises(error.HTTPError) as forbidden:
            self._post(
                "/v1/model-registry/refresh",
                {},
                headers={"Authorization": "Bearer user-token"},
            )
        self.assertEqual(forbidden.exception.code, 403)
        forbidden.exception.close()

        refreshed = self._post(
            "/v1/model-registry/refresh",
            {},
            headers={"Authorization": "Bearer admin-token"},
        )
        self.assertIn("generated_at", refreshed)

    def test_provider_credentials_can_be_persisted_via_api(self) -> None:
        os.environ["OPENCHIMERA_API_TOKEN"] = "user-token"
        os.environ["OPENCHIMERA_ADMIN_TOKEN"] = "admin-token"
        self._restart_server()

        stored = self._post(
            "/v1/credentials/providers/set",
            {"provider_id": "openai", "key": "OPENAI_API_KEY", "value": "sk-test-123456"},
            headers={"Authorization": "Bearer admin-token"},
        )
        self.assertTrue(stored["configured"])

        req = request.Request(
            f"{self.base_url}/v1/credentials/status",
            headers={"Authorization": "Bearer user-token"},
            method="GET",
        )
        with request.urlopen(req, timeout=10) as response:
            credentials = json.loads(response.read().decode("utf-8"))
        self.assertTrue(credentials["providers"]["openai"]["configured"])

        deleted = self._post(
            "/v1/credentials/providers/delete",
            {"provider_id": "openai", "key": "OPENAI_API_KEY"},
            headers={"Authorization": "Bearer admin-token"},
        )
        self.assertFalse(deleted["configured"])


class ApiTlsContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = _FakeProvider()
        self._env = {name: os.environ.get(name) for name in [
            "OPENCHIMERA_TLS_ENABLED",
            "OPENCHIMERA_TLS_CERTFILE",
            "OPENCHIMERA_TLS_KEYFILE",
            "OPENCHIMERA_TLS_KEY_PASSWORD",
            "OPENCHIMERA_API_TOKEN",
            "OPENCHIMERA_ADMIN_TOKEN",
            "OPENCHIMERA_ALLOW_INSECURE_BIND",
        ]}

    def tearDown(self) -> None:
        for name, value in self._env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def test_tls_enabled_wraps_socket_and_updates_transport_scheme(self) -> None:
        os.environ["OPENCHIMERA_TLS_ENABLED"] = "1"
        os.environ["OPENCHIMERA_TLS_CERTFILE"] = "tls/server.crt"
        os.environ["OPENCHIMERA_TLS_KEYFILE"] = "tls/server.key"

        server = OpenChimeraAPIServer(self.provider, host="127.0.0.1", port=0)
        with (
            mock.patch.object(ssl.SSLContext, "load_cert_chain") as load_cert_chain,
            mock.patch.object(ssl.SSLContext, "wrap_socket", side_effect=lambda sock, server_side=True: sock) as wrap_socket,
        ):
            started = server.start()

        try:
            self.assertTrue(started)
            self.assertIsNotNone(server.server)
            assert server.server is not None
            self.assertEqual(server.server.transport_scheme, "https")
            self.assertEqual(
                load_cert_chain.call_args.kwargs,
                {
                    "certfile": os.path.join("tls", "server.crt"),
                    "keyfile": os.path.join("tls", "server.key"),
                    "password": None,
                },
            )
            wrap_socket.assert_called_once()
        finally:
            server.stop()

    def test_tls_start_fails_fast_when_cert_configuration_is_invalid(self) -> None:
        os.environ["OPENCHIMERA_TLS_ENABLED"] = "1"
        os.environ["OPENCHIMERA_TLS_CERTFILE"] = "tls/server.crt"
        os.environ["OPENCHIMERA_TLS_KEYFILE"] = "tls/server.key"

        server = OpenChimeraAPIServer(self.provider, host="127.0.0.1", port=0)
        with (
            mock.patch.object(ssl.SSLContext, "load_cert_chain", side_effect=FileNotFoundError("missing cert")),
            mock.patch("core.api_server.LOGGER.exception"),
        ):
            started = server.start()

        self.assertFalse(started)
        self.assertIsNone(server.server)

    def test_non_loopback_bind_requires_auth_by_default(self) -> None:
        os.environ.pop("OPENCHIMERA_API_TOKEN", None)
        os.environ.pop("OPENCHIMERA_ADMIN_TOKEN", None)
        os.environ.pop("OPENCHIMERA_ALLOW_INSECURE_BIND", None)

        server = OpenChimeraAPIServer(self.provider, host="0.0.0.0", port=0)
        with mock.patch("core.api_server.LOGGER.error") as logger_error:
            started = server.start()

        self.assertFalse(started)
        self.assertIsNone(server.server)
        logger_error.assert_called_once()

    def test_non_loopback_bind_starts_when_auth_is_configured(self) -> None:
        os.environ["OPENCHIMERA_API_TOKEN"] = "user-token"
        os.environ["OPENCHIMERA_ADMIN_TOKEN"] = "admin-token"

        server = OpenChimeraAPIServer(self.provider, host="0.0.0.0", port=0)
        started = server.start()
        try:
            self.assertTrue(started)
            self.assertIsNotNone(server.server)
        finally:
            server.stop()

    def test_non_loopback_bind_can_be_explicitly_overridden_for_lab_use(self) -> None:
        os.environ["OPENCHIMERA_ALLOW_INSECURE_BIND"] = "1"
        os.environ.pop("OPENCHIMERA_API_TOKEN", None)
        os.environ.pop("OPENCHIMERA_ADMIN_TOKEN", None)

        server = OpenChimeraAPIServer(self.provider, host="0.0.0.0", port=0)
        started = server.start()
        try:
            self.assertTrue(started)
            self.assertIsNotNone(server.server)
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()