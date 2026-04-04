from __future__ import annotations

import html
import json
from typing import Any


ROUTE_CATALOG: dict[str, dict[str, dict[str, Any]]] = {
    "/health": {"get": {"summary": "Runtime health", "tag": "system", "public": True}},
    "/v1/system/readiness": {"get": {"summary": "Readiness probe", "tag": "system", "public": True}},
    "/v1/system/status": {"get": {"summary": "System status snapshot", "tag": "system", "public": False}},
    "/v1/system/metrics": {"get": {"summary": "Observability metrics", "tag": "system", "public": False}},
    "/v1/control-plane/status": {"get": {"summary": "Operator control-plane snapshot", "tag": "control-plane", "public": False}},
    "/v1/config/status": {"get": {"summary": "Safe configuration snapshot", "tag": "configuration", "public": False}},
    "/v1/auth/status": {"get": {"summary": "Authentication state", "tag": "security", "public": False}},
    "/v1/credentials/status": {"get": {"summary": "Credential status", "tag": "security", "public": False}},
    "/v1/providers/status": {"get": {"summary": "Provider activation status", "tag": "providers", "public": False}},
    "/v1/tools/status": {"get": {"summary": "Runtime tool status", "tag": "tools", "public": False}},
    "/v1/model-registry/status": {"get": {"summary": "Model registry status", "tag": "providers", "public": False}},
    "/v1/model-registry/refresh": {"post": {"summary": "Refresh model registry", "tag": "providers", "public": False}},
    "/v1/runtime/status": {"get": {"summary": "Local runtime status", "tag": "runtime", "public": False}},
    "/v1/runtime/start": {"post": {"summary": "Start local models", "tag": "runtime", "public": False}},
    "/v1/runtime/stop": {"post": {"summary": "Stop local models", "tag": "runtime", "public": False}},
    "/v1/query/status": {"get": {"summary": "Query engine status", "tag": "query", "public": False}},
    "/v1/query/sessions": {"get": {"summary": "List query sessions", "tag": "query", "public": False}},
    "/v1/query/memory": {"get": {"summary": "Inspect query memory", "tag": "query", "public": False}},
    "/v1/query/run": {"post": {"summary": "Run query", "tag": "query", "public": False}},
    "/v1/query/session/get": {"post": {"summary": "Get query session", "tag": "query", "public": False}},
    "/v1/tools/execute": {"post": {"summary": "Execute runtime tool", "tag": "tools", "public": False}},
    "/v1/channels/status": {"get": {"summary": "Channel status", "tag": "channels", "public": False}},
    "/v1/channels/history": {"get": {"summary": "Channel delivery history", "tag": "channels", "public": False}},
    "/v1/channels/subscriptions/set": {"post": {"summary": "Create or update subscription", "tag": "channels", "public": False}},
    "/v1/channels/subscriptions/delete": {"post": {"summary": "Delete subscription", "tag": "channels", "public": False}},
    "/v1/channels/validate": {"post": {"summary": "Validate subscription", "tag": "channels", "public": False}},
    "/v1/channels/dispatch": {"post": {"summary": "Dispatch topic payload", "tag": "channels", "public": False}},
    "/v1/channels/dispatch/daily-briefing": {"post": {"summary": "Dispatch daily briefing", "tag": "channels", "public": False}},
    "/v1/jobs/status": {"get": {"summary": "Job queue status", "tag": "jobs", "public": False}},
    "/v1/jobs/get": {"get": {"summary": "Get one job", "tag": "jobs", "public": False}},
    "/v1/jobs/create": {"post": {"summary": "Create operator job", "tag": "jobs", "public": False}},
    "/v1/jobs/cancel": {"post": {"summary": "Cancel operator job", "tag": "jobs", "public": False}},
    "/v1/jobs/replay": {"post": {"summary": "Replay operator job", "tag": "jobs", "public": False}},
    "/v1/browser/status": {"get": {"summary": "Browser subsystem status", "tag": "browser", "public": False}},
    "/v1/browser/fetch": {"post": {"summary": "Fetch URL with browser service", "tag": "browser", "public": False}},
    "/v1/browser/submit-form": {"post": {"summary": "Submit form with browser service", "tag": "browser", "public": False}},
    "/v1/media/status": {"get": {"summary": "Media subsystem status", "tag": "media", "public": False}},
    "/v1/media/transcribe": {"post": {"summary": "Transcribe media", "tag": "media", "public": False}},
    "/v1/media/synthesize": {"post": {"summary": "Synthesize speech", "tag": "media", "public": False}},
    "/v1/media/understand-image": {"post": {"summary": "Understand image", "tag": "media", "public": False}},
    "/v1/media/generate-image": {"post": {"summary": "Generate image", "tag": "media", "public": False}},
    "/v1/autonomy/status": {"get": {"summary": "Autonomy runtime status", "tag": "autonomy", "public": False}},
    "/v1/autonomy/diagnostics": {"get": {"summary": "Autonomy diagnostics", "tag": "autonomy", "public": False}},
    "/v1/autonomy/artifacts/history": {"get": {"summary": "Autonomy artifact history", "tag": "autonomy", "public": False}},
    "/v1/autonomy/artifacts/get": {"get": {"summary": "Get one autonomy artifact", "tag": "autonomy", "public": False}},
    "/v1/autonomy/operator-digest": {"get": {"summary": "Get operator digest", "tag": "autonomy", "public": False}},
    "/v1/autonomy/start": {"post": {"summary": "Start autonomy", "tag": "autonomy", "public": False}},
    "/v1/autonomy/stop": {"post": {"summary": "Stop autonomy", "tag": "autonomy", "public": False}},
    "/v1/autonomy/run": {"post": {"summary": "Run one autonomy job", "tag": "autonomy", "public": False}},
    "/v1/autonomy/preview-repair": {"post": {"summary": "Generate preview repair plan", "tag": "autonomy", "public": False}},
    "/v1/autonomy/operator-digest/dispatch": {"post": {"summary": "Dispatch operator digest", "tag": "autonomy", "public": False}},
    "/v1/onboarding/status": {"get": {"summary": "Onboarding status", "tag": "onboarding", "public": False}},
    "/v1/onboarding/apply": {"post": {"summary": "Apply onboarding payload", "tag": "onboarding", "public": False}},
    "/v1/onboarding/reset": {"post": {"summary": "Reset onboarding state", "tag": "onboarding", "public": False}},
    "/v1/subsystems/status": {"get": {"summary": "Managed subsystem status", "tag": "subsystems", "public": False}},
    "/v1/subsystems/invoke": {"post": {"summary": "Invoke managed subsystem", "tag": "subsystems", "public": False}},
    "/v1/plugins/status": {"get": {"summary": "Plugin status", "tag": "plugins", "public": False}},
    "/v1/plugins/install": {"post": {"summary": "Install plugin", "tag": "plugins", "public": False}},
    "/v1/plugins/uninstall": {"post": {"summary": "Uninstall plugin", "tag": "plugins", "public": False}},
    "/v1/mcp/status": {"get": {"summary": "MCP status", "tag": "mcp", "public": False}},
    "/v1/mcp/registry": {"get": {"summary": "MCP registry status", "tag": "mcp", "public": False}},
    "/v1/mcp/registry/set": {"post": {"summary": "Register MCP connector", "tag": "mcp", "public": False}},
    "/v1/mcp/registry/delete": {"post": {"summary": "Delete MCP connector", "tag": "mcp", "public": False}},
    "/v1/mcp/probe": {"post": {"summary": "Probe MCP connectors", "tag": "mcp", "public": False}},
    "/mcp": {
        "get": {"summary": "HTTP MCP descriptor", "tag": "mcp", "public": False},
        "post": {"summary": "HTTP MCP request handler", "tag": "mcp", "public": False},
    },
    "/v1/models": {"get": {"summary": "List models", "tag": "models", "public": False}},
    "/v1/chat/completions": {"post": {"summary": "OpenAI-compatible chat completions", "tag": "models", "public": False}},
    "/v1/embeddings": {"post": {"summary": "Generate embeddings", "tag": "models", "public": False}},
    "/openapi.json": {"get": {"summary": "OpenAPI-style API document", "tag": "documentation", "public": True}},
    "/docs": {"get": {"summary": "Human-readable API documentation", "tag": "documentation", "public": True}},
}


def build_openapi_document(*, base_url: str, auth_header: str, auth_enabled: bool) -> dict[str, Any]:
    paths: dict[str, Any] = {}
    for path, operations in ROUTE_CATALOG.items():
        rendered_ops: dict[str, Any] = {}
        for method, metadata in operations.items():
            operation: dict[str, Any] = {
                "summary": metadata["summary"],
                "tags": [metadata["tag"]],
                "responses": {
                    "200": {"description": "Successful response"},
                    "401": {"description": "Unauthorized"},
                    "403": {"description": "Forbidden"},
                    "422": {"description": "Validation failed"},
                },
            }
            if method == "post":
                operation["requestBody"] = {
                    "required": False,
                    "content": {
                        "application/json": {
                            "schema": {"type": "object"},
                        }
                    },
                }
            if not metadata.get("public", False):
                operation["security"] = [{"bearerAuth": []}]
            rendered_ops[method] = operation
        paths[path] = rendered_ops

    return {
        "openapi": "3.1.0",
        "info": {
            "title": "OpenChimera API",
            "version": "local",
            "description": "Local-first control-plane, operator, and runtime API for OpenChimera.",
        },
        "servers": [{"url": base_url}],
        "tags": [{"name": name} for name in sorted({metadata["tag"] for ops in ROUTE_CATALOG.values() for metadata in ops.values()})],
        "components": {
            "securitySchemes": {
                "bearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "description": f"Use the {auth_header} header with a configured OpenChimera token. auth_enabled={str(auth_enabled).lower()}",
                }
            }
        },
        "paths": paths,
    }


def build_docs_html(*, spec: dict[str, Any], auth_header: str, auth_enabled: bool) -> str:
    rows: list[str] = []
    for path, operations in sorted(spec.get("paths", {}).items()):
        for method, metadata in sorted(operations.items()):
            security = "public" if not metadata.get("security") else "authenticated"
            rows.append(
                "<tr>"
                f"<td>{html.escape(method.upper())}</td>"
                f"<td>{html.escape(path)}</td>"
                f"<td>{html.escape(str(metadata.get('summary', '')))}</td>"
                f"<td>{html.escape(security)}</td>"
                "</tr>"
            )

    return (
        "<!doctype html>"
        "<html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>OpenChimera API Docs</title>"
        "<style>body{font-family:Consolas,Menlo,monospace;background:#f5f1e8;color:#1f1a14;margin:0;padding:32px;}"
        "main{max-width:1120px;margin:0 auto;}h1,h2{margin:0 0 16px;}p{line-height:1.5;}table{width:100%;border-collapse:collapse;margin-top:20px;background:#fffdf8;}"
        "th,td{padding:10px 12px;border:1px solid #d7cbb6;text-align:left;vertical-align:top;}th{background:#efe4d0;}"
        "code,a{color:#6f2e00;} .meta{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin:20px 0;}"
        ".card{background:#fffdf8;border:1px solid #d7cbb6;padding:14px;} .small{font-size:12px;color:#5d5449;}</style></head><body><main>"
        "<h1>OpenChimera API</h1>"
        "<p>Operator-facing API documentation generated from the local runtime contract. Download the machine-readable specification at <a href=\"/openapi.json\">/openapi.json</a>.</p>"
        f"<div class=\"meta\"><div class=\"card\"><strong>Server</strong><div class=\"small\">{html.escape(str(spec.get('servers', [{}])[0].get('url', '')))}</div></div>"
        f"<div class=\"card\"><strong>Auth header</strong><div class=\"small\">{html.escape(auth_header)}</div></div>"
        f"<div class=\"card\"><strong>Auth enabled</strong><div class=\"small\">{html.escape(str(auth_enabled).lower())}</div></div></div>"
        "<table><thead><tr><th>Method</th><th>Path</th><th>Summary</th><th>Access</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
        "<h2 style=\"margin-top:24px;\">Notes</h2>"
        "<p>Public routes are limited to health, readiness, and documentation surfaces. Mutating and operator-sensitive routes require bearer authentication when API auth is enabled.</p>"
        f"<script type=\"application/json\" id=\"openapi-source\">{html.escape(json.dumps(spec))}</script>"
        "</main></body></html>"
    )