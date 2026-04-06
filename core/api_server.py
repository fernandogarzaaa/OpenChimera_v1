from __future__ import annotations

import concurrent.futures
import json
import logging
import ssl
import threading
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from pydantic import ValidationError

from core.api_docs import build_docs_html, build_openapi_document
from core.auth import RequestAuthorizer
from core.config import (
    build_runtime_configuration_status,
    get_provider_host,
    get_provider_max_workers,
    get_provider_port,
    get_provider_tls_certfile,
    get_provider_tls_key_password,
    get_provider_tls_keyfile,
    is_insecure_bind_allowed,
    is_loopback_host,
    is_provider_tls_enabled,
)
from core.mcp_server import OpenChimeraMCPServer
from core.logging_utils import clear_request_context, set_request_context
from core.observability import ObservabilityStore
from core.provider import OpenChimeraProvider
from core.rate_limiter import RateLimiter
from core.schemas import GET_QUERY_SCHEMAS, POST_BODY_SCHEMAS, HealthResponse, ReadinessResponse


LOGGER = logging.getLogger(__name__)
MAX_JSON_BODY_BYTES = 10 * 1024 * 1024


class RequestValidationFailure(Exception):
    def __init__(self, message: str, *, status: HTTPStatus, details: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.details = details or []


class _ProviderHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def __init__(
        self,
        server_address: tuple[str, int],
        provider: OpenChimeraProvider,
        system_status_provider: callable | None = None,
        rate_limiter: RateLimiter | None = None,
    ):
        super().__init__(server_address, _ProviderRequestHandler)
        self.provider = provider
        self.system_status_provider = system_status_provider
        self.authorizer = RequestAuthorizer(bus=getattr(provider, "bus", None))
        self.observability = getattr(provider, "observability", ObservabilityStore())
        self.mcp = OpenChimeraMCPServer(provider)
        self.rate_limiter = rate_limiter or RateLimiter()
        self.transport_scheme = "http"
        max_workers = get_provider_max_workers()
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="oc-request",
        )

    def process_request(self, request: Any, client_address: Any) -> None:
        self._executor.submit(self.process_request_thread, request, client_address)

    def server_close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
        super().server_close()


class _ProviderRequestHandler(BaseHTTPRequestHandler):
    server: _ProviderHTTPServer

    def _base_security_headers(self, *, content_type: str, status: HTTPStatus) -> dict[str, str]:
        headers = {
            "Content-Type": content_type,
            "X-Request-Id": self._request_id,
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer",
            "Permissions-Policy": "accelerometer=(), camera=(), geolocation=(), gyroscope=(), microphone=(), payment=(), usb=()",
            "Cache-Control": "no-store",
        }
        if content_type.startswith("text/html"):
            headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
        if getattr(self.server, "transport_scheme", "http") == "https":
            headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return headers

    def _parse_request_target(self) -> tuple[str, dict[str, list[str]]]:
        parsed = urlparse(self.path)
        return parsed.path, parse_qs(parsed.query)

    def _begin_request(self) -> None:
        self._request_started_at = time.perf_counter()
        self._request_id = self.headers.get("X-Request-Id", "").strip() or f"req-{uuid.uuid4().hex[:12]}"
        self._response_recorded = False
        self._request_context_token = set_request_context(self._request_id)

    def _record_response(self, status: HTTPStatus) -> None:
        if getattr(self, "_response_recorded", False):
            return
        started_at = getattr(self, "_request_started_at", None)
        duration_ms = 0.0
        if started_at is not None:
            duration_ms = (time.perf_counter() - started_at) * 1000.0
        self.server.observability.record_http_request(
            method=self.command,
            path=self.path,
            status_code=int(status),
            duration_ms=duration_ms,
            request_id=getattr(self, "_request_id", "unknown"),
        )
        LOGGER.info(
            "http request complete",
            extra={
                "event": "http_request",
                "request_id": getattr(self, "_request_id", "unknown"),
                "method": self.command,
                "path": self.path,
                "status_code": int(status),
                "duration_ms": round(duration_ms, 2),
                "client_ip": str(self.client_address[0]) if self.client_address else "unknown",
            },
        )
        self._response_recorded = True
        clear_request_context(getattr(self, "_request_context_token", None))
        self._request_context_token = None

    def _authorize_request(self) -> bool:
        decision = self.server.authorizer.authorize(self.command, self.path, self.headers)
        if decision.allowed:
            return True
        self._write_json(
            {
                "error": decision.error,
                "required_permission": decision.required_permission,
                "auth_required": decision.auth_required,
            },
            status=decision.status,
            www_authenticate=decision.status == HTTPStatus.UNAUTHORIZED,
        )
        return False

    def _extract_auth_token(self) -> str | None:
        raw = self.headers.get(self.server.authorizer.auth_header, "")
        if raw.startswith("Bearer "):
            raw = raw[7:]
        token = raw.strip()
        return token or None

    def _apply_rate_limit(self) -> bool:
        path, _ = self._parse_request_target()
        decision = self.server.rate_limiter.check(
            path=path,
            client_ip=str(self.client_address[0]),
            auth_token=self._extract_auth_token(),
        )
        if decision.allowed:
            return True
        self._write_json(
            {
                "error": "Too Many Requests",
                "details": [
                    {
                        "scope": decision.scope,
                        "limit": decision.limit,
                        "retry_after_seconds": decision.retry_after_seconds,
                    }
                ],
            },
            status=HTTPStatus.TOO_MANY_REQUESTS,
            extra_headers={"Retry-After": str(decision.retry_after_seconds)},
        )
        return False

    def _build_readiness_payload(self) -> tuple[dict[str, Any], HTTPStatus]:
        try:
            system_status = self.server.system_status_provider() if self.server.system_status_provider is not None else {}
            payload = self.server.provider.control_plane_readiness(
                system_status=system_status,
                auth_required=self.server.authorizer.auth_enabled,
            )
        except Exception as exc:
            LOGGER.warning("Readiness requested before provider startup completed: %s", exc)
            return (
                {
                    "status": "degraded",
                    "ready": False,
                    "checks": {
                        "provider_online": False,
                        "generation_path": False,
                        "auth": False,
                        "channels": False,
                    },
                    "issues": ["provider_startup_incomplete"],
                    "auth_required": self.server.authorizer.auth_enabled,
                },
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
        validated = ReadinessResponse.model_validate(payload).model_dump()
        return validated, HTTPStatus.OK if validated.get("ready") else HTTPStatus.SERVICE_UNAVAILABLE

    def _validation_error_payload(self, exc: ValidationError | RequestValidationFailure) -> dict[str, Any]:
        if isinstance(exc, ValidationError):
            details: list[dict[str, Any]] = []
            for item in exc.errors():
                normalized = dict(item)
                ctx = normalized.get("ctx")
                if isinstance(ctx, dict):
                    normalized["ctx"] = {key: str(value) for key, value in ctx.items()}
                details.append(normalized)
            return {"error": "Validation failed", "details": details}
        return {"error": exc.message, "details": exc.details}

    def _normalize_query(self, path: str, query: dict[str, list[str]]) -> dict[str, Any]:
        flattened: dict[str, Any] = {}
        for key, values in query.items():
            flattened[key] = values[0] if len(values) == 1 else values
        schema = GET_QUERY_SCHEMAS.get(path)
        if schema is None:
            return flattened
        return schema.model_validate(flattened).model_dump(exclude_none=True)

    def _normalize_payload(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        schema = POST_BODY_SCHEMAS.get(path)
        if schema is None:
            return payload
        return schema.model_validate(payload).model_dump(exclude_none=True)

    def do_GET(self) -> None:
        self._begin_request()
        if not self._apply_rate_limit():
            return
        if not self._authorize_request():
            return
        path, query = self._parse_request_target()
        try:
            query_data = self._normalize_query(path, query)
            if path == "/health":
                try:
                    payload = self.server.provider.health()
                    payload["auth_required"] = self.server.authorizer.auth_enabled
                    self._write_json(HealthResponse.model_validate(payload).model_dump())
                except Exception as exc:
                    LOGGER.warning("Health requested before provider startup completed: %s", exc)
                    self._write_json(
                        {
                            "status": "starting",
                            "name": "openchimera",
                            "base_url": self.server.provider.base_url,
                            "components": {"provider": False},
                            "healthy_models": 0,
                            "known_models": 0,
                            "documents": 0,
                            "auth_required": self.server.authorizer.auth_enabled,
                        }
                    )
                return
            if path == "/openapi.json":
                self._write_json(
                    build_openapi_document(
                        base_url=f"{self.server.transport_scheme}://{self.headers.get('Host', '')}".rstrip(":"),
                        auth_header=self.server.authorizer.auth_header,
                        auth_enabled=self.server.authorizer.auth_enabled,
                    )
                )
                return
            if path == "/docs":
                spec = build_openapi_document(
                    base_url=f"{self.server.transport_scheme}://{self.headers.get('Host', '')}".rstrip(":"),
                    auth_header=self.server.authorizer.auth_header,
                    auth_enabled=self.server.authorizer.auth_enabled,
                )
                self._write_html(build_docs_html(spec=spec, auth_header=self.server.authorizer.auth_header, auth_enabled=self.server.authorizer.auth_enabled))
                return
            if path == "/v1/system/readiness":
                payload, status = self._build_readiness_payload()
                self._write_json(payload, status=status)
                return
            if path == "/v1/control-plane/status":
                self._write_json(self.server.provider.control_plane_status(system_status=self.server.system_status_provider() if self.server.system_status_provider is not None else {}))
                return
            if path == "/v1/auth/status":
                self._write_json(self.server.provider.auth_status())
                return
            if path == "/v1/config/status":
                self._write_json(build_runtime_configuration_status())
                return
            if path == "/v1/credentials/status":
                self._write_json(self.server.provider.credential_status())
                return
            if path == "/v1/channels/status":
                self._write_json(self.server.provider.channel_status())
                return
            if path == "/v1/channels/history":
                self._write_json(
                    self.server.provider.channel_delivery_history(
                        topic=query_data.get("topic") or None,
                        status=query_data.get("status") or None,
                        limit=int(query_data.get("limit", 20)),
                    )
                )
                return
            if path == "/v1/browser/status":
                self._write_json(self.server.provider.browser_status())
                return
            if path == "/v1/media/status":
                self._write_json(self.server.provider.media_status())
                return
            if path == "/v1/jobs/status":
                self._write_json(
                    self.server.provider.job_queue_status(
                        status_filter=query_data.get("status") or None,
                        job_type=query_data.get("job_type") or None,
                        limit=int(query_data.get("limit")) if query_data.get("limit") is not None else None,
                    )
                )
                return
            if path == "/v1/jobs/get":
                self._write_json(self.server.provider.get_operator_job(str(query_data.get("job_id", "")).strip()))
                return
            if path == "/v1/providers/status":
                self._write_json(self.server.provider.provider_activation_status())
                return
            if path == "/v1/tools/status":
                self._write_json(self.server.provider.tool_status())
                return
            if self.path == "/v1/model-roles/status":
                self._write_json(self.server.provider.model_role_status())
                return
            if self.path == "/v1/capabilities/status":
                self._write_json(self.server.provider.capability_status())
                return
            if self.path == "/v1/capabilities/commands":
                self._write_json({"data": self.server.provider.list_capabilities("commands")})
                return
            if self.path == "/v1/capabilities/tools":
                self._write_json({"data": self.server.provider.list_capabilities("tools")})
                return
            if self.path == "/v1/capabilities/skills":
                self._write_json({"data": self.server.provider.list_capabilities("skills")})
                return
            if self.path == "/v1/capabilities/plugins":
                self._write_json({"data": self.server.provider.list_capabilities("plugins")})
                return
            if self.path == "/v1/capabilities/mcp":
                self._write_json({"data": self.server.provider.list_capabilities("mcp")})
                return
            if self.path == "/v1/mcp/status":
                self._write_json(self.server.provider.mcp_status())
                return
            if self.path == "/v1/mcp/registry":
                self._write_json(self.server.provider.mcp_registry_status())
                return
            if self.path == "/mcp":
                self._write_json(
                    {
                        "name": "openchimera-local",
                        "transport": "http",
                        "status": "ready",
                        "capabilities": {
                            "tools": len(self.server.mcp.tool_descriptors()),
                            "resources": len(self.server.mcp.resource_descriptors()),
                            "prompts": len(self.server.mcp.prompt_descriptors()),
                        },
                    }
                )
                return
            if self.path == "/v1/system/metrics":
                self._write_json(self.server.provider.observability_status())
                return
            if self.path == "/v1/query/status":
                self._write_json(self.server.provider.query_status())
                return
            if self.path == "/v1/query/sessions":
                self._write_json({"data": self.server.provider.list_query_sessions(limit=int(query_data.get("limit", 20)))})
                return
            if self.path == "/v1/query/memory":
                self._write_json(self.server.provider.inspect_memory())
                return
            if self.path == "/v1/memory/show":
                self._write_json(self.server.provider.inspect_memory())
                return
            if self.path == "/v1/plugins/status":
                self._write_json(self.server.provider.plugin_status())
                return
            if self.path == "/v1/subsystems/status":
                self._write_json(self.server.provider.subsystem_status())
                return
            if self.path == "/v1/models":
                self._write_json(self.server.provider.list_models())
                return
            if self.path == "/v1/runtime/status":
                self._write_json(self.server.provider.local_runtime_status())
                return
            if self.path == "/v1/router/status":
                self._write_json(self.server.provider.router.status())
                return
            if self.path == "/v1/harness/status":
                self._write_json(self.server.provider.harness_port_status())
                return
            if self.path == "/v1/minimind/status":
                self._write_json(self.server.provider.minimind_status())
                return
            if path == "/v1/autonomy/status":
                self._write_json(self.server.provider.autonomy_status())
                return
            if path == "/v1/autonomy/diagnostics":
                self._write_json(self.server.provider.autonomy_diagnostics())
                return
            if path == "/v1/autonomy/artifacts/history":
                self._write_json(
                    self.server.provider.autonomy_artifact_history(
                        artifact_name=query_data.get("artifact") or None,
                        limit=int(query_data.get("limit", 20)),
                    )
                )
                return
            if path == "/v1/autonomy/artifacts/get":
                self._write_json(self.server.provider.autonomy_artifact(str(query_data.get("artifact", "")).strip()))
                return
            if path == "/v1/autonomy/operator-digest":
                self._write_json(self.server.provider.operator_digest())
                return
            if self.path == "/v1/model-registry/status":
                self._write_json(self.server.provider.model_registry_status())
                return
            if self.path == "/v1/onboarding/status":
                self._write_json(self.server.provider.onboarding_status())
                return
            if self.path == "/v1/integrations/status":
                self._write_json(self.server.provider.integration_status())
                return
            if self.path == "/v1/aegis/status":
                self._write_json(self.server.provider.aegis_status())
                return
            if self.path == "/v1/ascension/status":
                self._write_json(self.server.provider.ascension_status())
                return
            if path == "/v1/briefings/daily":
                self._write_json(self.server.provider.daily_briefing())
                return
            if path == "/v1/system/status":
                if self.server.system_status_provider is None:
                    self._write_json({"error": "System status unavailable"}, status=HTTPStatus.SERVICE_UNAVAILABLE)
                    return
                self._write_json(self.server.system_status_provider())
                return
            self._write_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)
        except ValidationError as exc:
            self._write_json(self._validation_error_payload(exc), status=HTTPStatus.UNPROCESSABLE_ENTITY)
        except RequestValidationFailure as exc:
            self._write_json(self._validation_error_payload(exc), status=exc.status)
        except ValueError as exc:
            self._write_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except NotImplementedError as exc:
            self._write_json({"error": str(exc)}, status=HTTPStatus.SERVICE_UNAVAILABLE)
        except RuntimeError as exc:
            self._write_json({"error": str(exc)}, status=HTTPStatus.BAD_GATEWAY)
        except Exception as exc:
            LOGGER.exception("Unhandled GET request failure for %s", path)
            self._write_json({"error": str(exc)}, status=HTTPStatus.SERVICE_UNAVAILABLE)

    def do_POST(self) -> None:
        self._begin_request()
        if not self._apply_rate_limit():
            return
        if not self._authorize_request():
            return
        try:
            payload = self._normalize_payload(self.path, self._read_json_body())
            if self.path == "/mcp":
                response = self.server.mcp.handle_request(payload)
                if response is None:
                    self._write_json({"status": "accepted"}, status=HTTPStatus.ACCEPTED)
                    return
                self._write_json(response)
                return
            if self.path == "/v1/chat/completions":
                response = self.server.provider.chat_completion(
                    messages=payload.get("messages", []),
                    model=payload.get("model", "openchimera-local"),
                    temperature=float(payload.get("temperature", 0.7)),
                    max_tokens=int(payload.get("max_tokens") or payload.get("max_completion_tokens") or 1024),
                    stream=bool(payload.get("stream", False)),
                )
                if payload.get("stream"):
                    self._write_stream(response)
                    return
                self._write_json(response)
                return
            if self.path == "/v1/embeddings":
                input_text = payload.get("input", "")
                if isinstance(input_text, list):
                    input_text = "\n".join(str(item) for item in input_text)
                self._write_json(self.server.provider.embeddings(str(input_text), model=payload.get("model", "openchimera-local")))
                return

            if self.path == "/v1/runtime/start":
                models = payload.get("models")
                requested_models = [str(item) for item in models] if isinstance(models, list) else None
                self._write_json(self.server.provider.start_local_models(requested_models))
                return

            if self.path == "/v1/runtime/stop":
                models = payload.get("models")
                requested_models = [str(item) for item in models] if isinstance(models, list) else None
                self._write_json(self.server.provider.stop_local_models(requested_models))
                return

            if self.path == "/v1/model-registry/refresh":
                self._write_json(self.server.provider.refresh_model_registry())
                return

            if self.path == "/v1/mcp/registry/set":
                raw_args = payload.get("args")
                args = [str(item) for item in raw_args] if isinstance(raw_args, list) else None
                self._write_json(
                    self.server.provider.register_mcp_connector(
                        str(payload.get("id", "")).strip(),
                        transport=str(payload.get("transport", "")).strip(),
                        name=str(payload.get("name", "")).strip() or None,
                        description=str(payload.get("description", "")).strip() or None,
                        url=str(payload.get("url", "")).strip() or None,
                        command=str(payload.get("command", "")).strip() or None,
                        args=args,
                        enabled=not bool(payload.get("disabled", False)),
                    )
                )
                return

            if self.path == "/v1/mcp/registry/delete":
                self._write_json(self.server.provider.unregister_mcp_connector(str(payload.get("id", "")).strip()))
                return

            if self.path == "/v1/mcp/probe":
                self._write_json(
                    self.server.provider.probe_mcp_connectors(
                        server_id=str(payload.get("id", "")).strip() or None,
                        timeout_seconds=float(payload.get("timeout_seconds", 3.0)),
                    )
                )
                return

            if self.path == "/v1/providers/configure":
                raw_enabled = payload.get("enabled_provider_ids")
                enabled = [str(item) for item in raw_enabled] if isinstance(raw_enabled, list) else None
                preferred_cloud_provider = payload.get("preferred_cloud_provider")
                preferred = str(preferred_cloud_provider).strip() if preferred_cloud_provider is not None else None
                prefer_free_models = payload.get("prefer_free_models") if "prefer_free_models" in payload else None
                self._write_json(self.server.provider.configure_provider_activation(enabled, preferred, prefer_free_models))
                return

            if self.path == "/v1/model-roles/configure":
                overrides = payload.get("overrides", payload if isinstance(payload, dict) else {})
                self._write_json(self.server.provider.configure_model_roles(overrides if isinstance(overrides, dict) else {}))
                return

            if self.path == "/v1/query/run":
                raw_messages = payload.get("messages")
                messages = raw_messages if isinstance(raw_messages, list) else None
                raw_tool_requests = payload.get("tool_requests")
                tool_requests = raw_tool_requests if isinstance(raw_tool_requests, list) else None
                spawn_job = payload.get("spawn_job") if isinstance(payload.get("spawn_job"), dict) else None
                self._write_json(
                    self.server.provider.run_query(
                        query=str(payload.get("query", "")),
                        messages=messages,
                        session_id=str(payload.get("session_id", "")).strip() or None,
                        permission_scope=str(payload.get("permission_scope", "user")),
                        max_tokens=int(payload.get("max_tokens", 512)),
                        allow_tool_planning=bool(payload.get("allow_tool_planning", True)),
                        execute_tools=bool(payload.get("execute_tools", False)),
                        tool_requests=tool_requests,
                        allow_agent_spawn=bool(payload.get("allow_agent_spawn", False)),
                        spawn_job=spawn_job,
                    )
                )
                return

            if self.path == "/v1/tools/execute":
                self._write_json(
                    self.server.provider.execute_tool(
                        str(payload.get("tool_id", "")).strip(),
                        dict(payload.get("arguments", {})),
                        permission_scope=str(payload.get("permission_scope", "user")),
                    )
                )
                return

            if self.path == "/v1/query/session/get":
                self._write_json(self.server.provider.get_query_session(str(payload.get("session_id", "")).strip()))
                return

            if self.path == "/v1/sessions/resume":
                self._write_json(
                    self.server.provider.resume_session(
                        session_id=str(payload.get("session_id", "")).strip(),
                        query=str(payload.get("query", "")).strip(),
                        permission_scope=str(payload.get("permission_scope", "user")),
                        max_tokens=int(payload.get("max_tokens", 512)),
                    )
                )
                return

            if self.path == "/v1/memory/clear":
                scope = payload.get("scope")
                scope = str(scope).strip() if scope is not None else None
                self._write_json(self.server.provider.clear_memory(scope=scope))
                return

            if self.path == "/v1/onboarding/apply":
                self._write_json(self.server.provider.apply_onboarding(payload))
                return

            if self.path == "/v1/onboarding/reset":
                self._write_json(self.server.provider.reset_onboarding())
                return

            if self.path == "/v1/aegis/run":
                self._write_json(
                    self.server.provider.run_aegis_workflow(
                        target_project=str(payload.get("target_project") or "") or None,
                        preview=bool(payload.get("preview", True)),
                    )
                )
                return

            if self.path == "/v1/ascension/deliberate":
                raw_perspectives = payload.get("perspectives")
                perspectives = [str(item) for item in raw_perspectives] if isinstance(raw_perspectives, list) else None
                self._write_json(
                    self.server.provider.deliberate(
                        prompt=str(payload.get("prompt", "")),
                        perspectives=perspectives,
                        max_tokens=int(payload.get("max_tokens", 256)),
                    )
                )
                return

            if self.path == "/v1/autonomy/start":
                self._write_json(self.server.provider.start_autonomy())
                return

            if self.path == "/v1/autonomy/stop":
                self._write_json(self.server.provider.stop_autonomy())
                return

            if self.path == "/v1/autonomy/run":
                job_name = str(payload.get("job", "")).strip()
                job_payload = dict(payload) if isinstance(payload, dict) else {}
                job_payload.pop("job", None)
                self._write_json(self.server.provider.run_autonomy_job(job_name, payload=job_payload))
                return

            if self.path == "/v1/autonomy/preview-repair":
                self._write_json(
                    self.server.provider.preview_self_repair(
                        target_project=str(payload.get("target_project") or "").strip() or None,
                        enqueue=bool(payload.get("enqueue", False)),
                        max_attempts=int(payload.get("max_attempts", 3)),
                    )
                )
                return

            if self.path == "/v1/autonomy/operator-digest/dispatch":
                self._write_json(
                    self.server.provider.dispatch_operator_digest(
                        enqueue=bool(payload.get("enqueue", False)),
                        max_attempts=int(payload.get("max_attempts", 3)),
                        history_limit=int(payload.get("history_limit", 0)) or None,
                        dispatch_topic=str(payload.get("dispatch_topic", "")).strip() or None,
                    )
                )
                return

            if self.path == "/v1/minimind/dataset/build":
                self._write_json(self.server.provider.build_minimind_dataset(force=bool(payload.get("force", True))))
                return

            if self.path == "/v1/minimind/server/start":
                self._write_json(self.server.provider.start_minimind_server())
                return

            if self.path == "/v1/minimind/server/stop":
                self._write_json(self.server.provider.stop_minimind_server())
                return

            if self.path == "/v1/minimind/training/start":
                self._write_json(
                    self.server.provider.start_minimind_training(
                        mode=str(payload.get("mode", "reason_sft")),
                        force_dataset=bool(payload.get("force_dataset", False)),
                    )
                )
                return

            if self.path == "/v1/minimind/training/stop":
                self._write_json(self.server.provider.stop_minimind_training(str(payload.get("job_id", ""))))
                return

            if self.path == "/v1/credentials/providers/set":
                self._write_json(
                    self.server.provider.set_provider_credential(
                        provider_id=str(payload.get("provider_id", "")).strip(),
                        key=str(payload.get("key", "")).strip(),
                        value=str(payload.get("value", "")),
                    )
                )
                return

            if self.path == "/v1/credentials/providers/delete":
                self._write_json(
                    self.server.provider.delete_provider_credential(
                        provider_id=str(payload.get("provider_id", "")).strip(),
                        key=str(payload.get("key", "")).strip(),
                    )
                )
                return

            if self.path == "/v1/channels/subscriptions/set":
                self._write_json(self.server.provider.upsert_channel_subscription(payload))
                return

            if self.path == "/v1/channels/subscriptions/delete":
                self._write_json(self.server.provider.delete_channel_subscription(str(payload.get("subscription_id", "")).strip()))
                return

            if self.path == "/v1/channels/validate":
                self._write_json(
                    self.server.provider.validate_channel_subscription(
                        subscription_id=str(payload.get("subscription_id", "")).strip(),
                        subscription=payload.get("subscription", {}) if isinstance(payload.get("subscription", {}), dict) else None,
                    )
                )
                return

            if self.path == "/v1/channels/dispatch/daily-briefing":
                self._write_json(self.server.provider.dispatch_daily_briefing())
                return

            if self.path == "/v1/channels/dispatch":
                self._write_json(
                    self.server.provider.dispatch_channel(
                        topic=str(payload.get("topic", "")).strip(),
                        payload=payload.get("payload", {}) if isinstance(payload.get("payload", {}), dict) else {},
                    )
                )
                return

            if self.path == "/v1/browser/fetch":
                self._write_json(
                    self.server.provider.browser_fetch(
                        url=str(payload.get("url", "")).strip(),
                        max_chars=int(payload.get("max_chars", 4000)),
                    )
                )
                return

            if self.path == "/v1/browser/submit-form":
                form_data = payload.get("form_data", {}) if isinstance(payload.get("form_data", {}), dict) else {}
                self._write_json(
                    self.server.provider.browser_submit_form(
                        url=str(payload.get("url", "")).strip(),
                        form_data=form_data,
                        method=str(payload.get("method", "POST")),
                        max_chars=int(payload.get("max_chars", 4000)),
                    )
                )
                return

            if self.path == "/v1/media/transcribe":
                self._write_json(
                    self.server.provider.media_transcribe(
                        audio_text=str(payload.get("audio_text", "")),
                        audio_base64=str(payload.get("audio_base64", "")),
                        language=str(payload.get("language", "en")),
                    )
                )
                return

            if self.path == "/v1/media/synthesize":
                self._write_json(
                    self.server.provider.media_synthesize(
                        text=str(payload.get("text", "")),
                        voice=str(payload.get("voice", "openchimera-default")),
                        audio_format=str(payload.get("audio_format", "wav")),
                        sample_rate_hz=int(payload.get("sample_rate_hz", 16000)),
                    )
                )
                return

            if self.path == "/v1/media/understand-image":
                raw_image_path = str(payload.get("image_path", ""))
                if ".." in raw_image_path.replace("\\", "/"):
                    raise RequestValidationFailure(
                        "Validation failed",
                        status=HTTPStatus.UNPROCESSABLE_ENTITY,
                        details=[{"field": "image_path", "msg": "path traversal detected"}],
                    )
                self._write_json(
                    self.server.provider.media_understand_image(
                        prompt=str(payload.get("prompt", "")),
                        image_path=raw_image_path,
                        image_base64=str(payload.get("image_base64", "")),
                    )
                )
                return

            if self.path == "/v1/media/generate-image":
                self._write_json(
                    self.server.provider.media_generate_image(
                        prompt=str(payload.get("prompt", "")),
                        width=int(payload.get("width", 1024)),
                        height=int(payload.get("height", 1024)),
                        style=str(payload.get("style", "schematic")),
                    )
                )
                return

            if self.path == "/v1/jobs/create":
                self._write_json(
                    self.server.provider.create_operator_job(
                        job_type=str(payload.get("job_type", "autonomy")).strip(),
                        payload=payload.get("payload", {}) if isinstance(payload.get("payload", {}), dict) else {},
                        max_attempts=int(payload.get("max_attempts", 3)),
                    )
                )
                return

            if self.path == "/v1/jobs/cancel":
                self._write_json(self.server.provider.cancel_operator_job(str(payload.get("job_id", "")).strip()))
                return

            if self.path == "/v1/jobs/replay":
                self._write_json(self.server.provider.replay_operator_job(str(payload.get("job_id", "")).strip()))
                return

            if self.path == "/v1/plugins/install":
                self._write_json(self.server.provider.install_plugin(str(payload.get("plugin_id", "")).strip()))
                return

            if self.path == "/v1/plugins/uninstall":
                self._write_json(self.server.provider.uninstall_plugin(str(payload.get("plugin_id", "")).strip()))
                return

            if self.path == "/v1/subsystems/invoke":
                subsystem_id = str(payload.get("subsystem_id", "")).strip()
                action = str(payload.get("action", "status")).strip()
                invoke_payload = payload.get("payload", {}) if isinstance(payload.get("payload", {}), dict) else {}
                invoke_payload.setdefault("action", action)
                self._write_json(self.server.provider.invoke_subsystem(subsystem_id, action, invoke_payload))
                return

            self._write_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)
        except ValidationError as exc:
            self._write_json(self._validation_error_payload(exc), status=HTTPStatus.UNPROCESSABLE_ENTITY)
        except RequestValidationFailure as exc:
            self._write_json(self._validation_error_payload(exc), status=exc.status)
        except ValueError as exc:
            self._write_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
        except NotImplementedError as exc:
            self._write_json({"error": str(exc)}, status=HTTPStatus.SERVICE_UNAVAILABLE)
        except RuntimeError as exc:
            self._write_json({"error": str(exc)}, status=HTTPStatus.BAD_GATEWAY)
        except Exception as exc:
            LOGGER.exception("Unhandled POST request failure for %s", self.path)
            self._write_json({"error": str(exc)}, status=HTTPStatus.SERVICE_UNAVAILABLE)

    def log_message(self, format: str, *args: Any) -> None:
        LOGGER.debug("OpenChimera API: " + format, *args)

    def _read_json_body(self) -> dict[str, Any]:
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise RequestValidationFailure("Invalid Content-Length header", status=HTTPStatus.BAD_REQUEST)

        if content_length > MAX_JSON_BODY_BYTES:
            if content_length > 0:
                self.rfile.read(content_length)
            raise RequestValidationFailure(
                "JSON payload exceeds the 10MB limit",
                status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
            )

        raw = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            raise RequestValidationFailure("Invalid JSON body", status=HTTPStatus.BAD_REQUEST)
        if not isinstance(payload, dict):
            raise RequestValidationFailure("JSON body must be an object", status=HTTPStatus.UNPROCESSABLE_ENTITY)
        return payload

    def _write_json(
        self,
        payload: dict[str, Any],
        status: HTTPStatus = HTTPStatus.OK,
        www_authenticate: bool = False,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        if not hasattr(self, "_request_id"):
            self._begin_request()
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        for key, value in self._base_security_headers(content_type="application/json", status=status).items():
            self.send_header(key, value)
        if www_authenticate:
            self.send_header("WWW-Authenticate", 'Bearer realm="OpenChimera"')
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        self._record_response(status)

    def _write_html(self, body: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        if not hasattr(self, "_request_id"):
            self._begin_request()
        encoded = body.encode("utf-8")
        self.send_response(status)
        for key, value in self._base_security_headers(content_type="text/html; charset=utf-8", status=status).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)
        self._record_response(status)

    def _write_stream(self, response: dict[str, Any]) -> None:
        content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
        words = content.split()
        self.send_response(HTTPStatus.OK)
        for key, value in self._base_security_headers(content_type="text/event-stream", status=HTTPStatus.OK).items():
            self.send_header(key, value)
        self.send_header("Cache-Control", "no-cache, no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        for index, word in enumerate(words):
            chunk = {
                "id": response.get("id"),
                "object": "chat.completion.chunk",
                "created": response.get("created"),
                "model": response.get("model"),
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": word + (" " if index < len(words) - 1 else "")},
                        "finish_reason": None,
                    }
                ],
            }
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode("utf-8"))
            self.wfile.flush()
            time.sleep(0.01)

        done_chunk = {
            "id": response.get("id"),
            "object": "chat.completion.chunk",
            "created": response.get("created"),
            "model": response.get("model"),
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        self.wfile.write(f"data: {json.dumps(done_chunk)}\n\n".encode("utf-8"))
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()
        self._record_response(HTTPStatus.OK)


class OpenChimeraAPIServer:
    def __init__(
        self,
        provider: OpenChimeraProvider,
        host: str | None = None,
        port: int | None = None,
        system_status_provider: callable | None = None,
        rate_limiter: RateLimiter | None = None,
    ):
        self.provider = provider
        self.host = host if host is not None else get_provider_host()
        self.port = port if port is not None else get_provider_port()
        self.system_status_provider = system_status_provider
        self.rate_limiter = rate_limiter
        self.tls_enabled = is_provider_tls_enabled()
        self.tls_certfile = get_provider_tls_certfile()
        self.tls_keyfile = get_provider_tls_keyfile()
        self.tls_key_password = get_provider_tls_key_password()
        self.server: _ProviderHTTPServer | None = None
        self.thread: threading.Thread | None = None

    def _build_tls_context(self) -> ssl.SSLContext:
        if not self.tls_enabled:
            raise RuntimeError("TLS is not enabled")
        if self.tls_certfile is None or self.tls_keyfile is None:
            raise ValueError("TLS requires both certfile and keyfile")
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(
            certfile=str(self.tls_certfile),
            keyfile=str(self.tls_keyfile),
            password=self.tls_key_password,
        )
        return context

    def start(self) -> bool:
        if self.thread is not None:
            return True

        authorizer = RequestAuthorizer()
        if not is_loopback_host(self.host) and not authorizer.auth_enabled and not is_insecure_bind_allowed():
            LOGGER.error(
                "Refusing to start OpenChimera API on non-loopback host %s without API auth. Set OPENCHIMERA_API_TOKEN and OPENCHIMERA_ADMIN_TOKEN, or explicitly set OPENCHIMERA_ALLOW_INSECURE_BIND=1 for isolated lab use.",
                self.host,
            )
            return False

        try:
            self.server = _ProviderHTTPServer(
                (self.host, self.port),
                self.provider,
                system_status_provider=self.system_status_provider,
                rate_limiter=self.rate_limiter,
            )
        except OSError as exc:
            LOGGER.exception("Failed to bind OpenChimera API server.")
            return False

        if self.tls_enabled:
            try:
                context = self._build_tls_context()
                assert self.server is not None
                self.server.socket = context.wrap_socket(self.server.socket, server_side=True)
                self.server.transport_scheme = "https"
            except Exception:
                LOGGER.exception("Failed to configure OpenChimera API TLS.")
                assert self.server is not None
                self.server.server_close()
                self.server = None
                return False

        server = self.server
        self.thread = threading.Thread(
            target=lambda: server.serve_forever(poll_interval=0.1),
            daemon=True,
            name="OpenChimera-API",
        )
        self.thread.start()
        scheme = "https" if self.tls_enabled else "http"
        LOGGER.info("OpenChimera API available at %s://%s:%s", scheme, self.host, self.port)
        return True

    def stop(self) -> None:
        server = self.server
        thread = self.thread
        self.server = None
        self.thread = None

        if server is None:
            return

        shutdown_complete = threading.Event()

        def _shutdown_server() -> None:
            try:
                server.shutdown()
            finally:
                shutdown_complete.set()

        shutdown_thread = threading.Thread(
            target=_shutdown_server,
            daemon=True,
            name="OpenChimera-API-Shutdown",
        )
        shutdown_thread.start()
        shutdown_complete.wait(timeout=2.0)
        server.server_close()

        if thread is not None:
            thread.join(timeout=2.0)
            if thread.is_alive():
                LOGGER.warning("OpenChimera API thread did not terminate cleanly before timeout.")