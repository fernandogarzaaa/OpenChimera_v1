from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any
from urllib import error, request

from core.config import ROOT


def get_mcp_registry_path(root: Path | None = None) -> Path:
    return (root or ROOT) / "data" / "mcp_registry.json"


def get_mcp_health_state_path(root: Path | None = None) -> Path:
    return (root or ROOT) / "data" / "mcp_health_state.json"


def load_mcp_registry(root: Path | None = None) -> dict[str, Any]:
    path = get_mcp_registry_path(root)
    document = _read_registry_document(path)
    raw_servers = document.get("servers", {}) if isinstance(document, dict) else {}
    servers: dict[str, dict[str, Any]] = {}
    for server_id, details in raw_servers.items():
        if not isinstance(details, dict):
            continue
        normalized_id = str(server_id).strip()
        if not normalized_id:
            continue
        servers[normalized_id] = _normalize_registry_entry(normalized_id, details, path)
    return {"servers": servers, "source": str(path)}


def list_mcp_registry(root: Path | None = None) -> list[dict[str, Any]]:
    registry = load_mcp_registry(root)
    return sorted(registry.get("servers", {}).values(), key=lambda item: str(item.get("id", "")))


def load_mcp_health_state(root: Path | None = None) -> dict[str, Any]:
    path = get_mcp_health_state_path(root)
    if not path.exists():
        return {"version": 1, "servers": {}, "source": str(path)}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        payload = {"version": 1, "servers": {}}
    if not isinstance(payload, dict):
        payload = {"version": 1, "servers": {}}
    raw_servers = payload.get("servers", {})
    if not isinstance(raw_servers, dict):
        raw_servers = {}
    return {"version": int(payload.get("version", 1) or 1), "servers": raw_servers, "source": str(path)}


def list_mcp_registry_with_health(root: Path | None = None) -> list[dict[str, Any]]:
    registry_entries = list_mcp_registry(root)
    health_state = load_mcp_health_state(root).get("servers", {})
    merged: list[dict[str, Any]] = []
    for entry in registry_entries:
        item = dict(entry)
        health = health_state.get(str(item.get("id", "")), {})
        if isinstance(health, dict):
            for key in (
                "status",
                "checked_at",
                "failure_count",
                "last_error",
                "last_failure_code",
                "last_restored_at",
                "resolved_command",
                "probe_method",
                "probe_target",
            ):
                if key in health:
                    item[key] = health[key]
        merged.append(item)
    return merged


def upsert_mcp_registry_entry(
    server_id: str,
    *,
    transport: str,
    name: str | None = None,
    description: str | None = None,
    url: str | None = None,
    command: str | None = None,
    args: list[str] | None = None,
    enabled: bool = True,
    root: Path | None = None,
) -> dict[str, Any]:
    normalized_id = str(server_id).strip()
    if not normalized_id:
        raise ValueError("MCP registry entry requires a server id")

    normalized_transport = str(transport).strip().lower()
    if normalized_transport not in {"http", "stdio"}:
        raise ValueError("MCP registry transport must be http or stdio")
    if normalized_transport == "http" and not str(url or "").strip():
        raise ValueError("HTTP MCP registry entries require a URL")
    if normalized_transport == "stdio" and not str(command or "").strip():
        raise ValueError("stdio MCP registry entries require a command")

    path = get_mcp_registry_path(root)
    document = _read_registry_document(path)
    raw_servers = document.setdefault("servers", {})
    if not isinstance(raw_servers, dict):
        raw_servers = {}
        document["servers"] = raw_servers

    stored_entry: dict[str, Any] = {
        "name": str(name or normalized_id.replace("_", " ").replace("-", " ").title()),
        "transport": normalized_transport,
        "enabled": bool(enabled),
    }
    if description:
        stored_entry["description"] = str(description).strip()
    if normalized_transport == "http":
        stored_entry["url"] = str(url).strip()
    else:
        stored_entry["command"] = str(command).strip()
        stored_entry["args"] = [str(item) for item in (args or [])]

    raw_servers[normalized_id] = stored_entry
    _write_registry_document(path, document)
    return _normalize_registry_entry(normalized_id, stored_entry, path)


def delete_mcp_registry_entry(server_id: str, root: Path | None = None) -> dict[str, Any]:
    normalized_id = str(server_id).strip()
    path = get_mcp_registry_path(root)
    document = _read_registry_document(path)
    raw_servers = document.get("servers", {}) if isinstance(document, dict) else {}
    if not isinstance(raw_servers, dict):
        raw_servers = {}
        document["servers"] = raw_servers
    removed = raw_servers.pop(normalized_id, None)
    _write_registry_document(path, document)
    return {
        "id": normalized_id,
        "deleted": removed is not None,
        "source": str(path),
    }


def probe_mcp_registry_entry(server_id: str, root: Path | None = None, timeout_seconds: float = 3.0) -> dict[str, Any]:
    registry = load_mcp_registry(root)
    entry = registry.get("servers", {}).get(str(server_id).strip())
    if not isinstance(entry, dict):
        raise ValueError(f"Unknown MCP registry entry: {server_id}")
    result = _probe_entry(entry, timeout_seconds=timeout_seconds)
    _persist_probe_result(entry, result, root)
    return result


def probe_all_mcp_registry_entries(root: Path | None = None, timeout_seconds: float = 3.0) -> dict[str, Any]:
    entries = list_mcp_registry(root)
    results: list[dict[str, Any]] = []
    for entry in entries:
        result = _probe_entry(entry, timeout_seconds=timeout_seconds)
        _persist_probe_result(entry, result, root)
        results.append(result)
    return {
        "counts": {
            "total": len(results),
            "healthy": sum(1 for item in results if str(item.get("status", "")).lower() == "healthy"),
            "degraded": sum(1 for item in results if str(item.get("status", "")).lower() == "degraded"),
            "disabled": sum(1 for item in results if str(item.get("status", "")).lower() == "disabled"),
        },
        "servers": results,
        "checked_at": time.time(),
    }


def _read_registry_document(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"servers": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"servers": {}}
    if not isinstance(payload, dict):
        return {"servers": {}}
    payload.setdefault("servers", {})
    return payload


def _write_registry_document(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")


def _write_mcp_health_state(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")


def _normalize_registry_entry(server_id: str, details: dict[str, Any], path: Path) -> dict[str, Any]:
    transport = str(details.get("transport") or "").strip().lower()
    if not transport:
        if details.get("url"):
            transport = "http"
        elif details.get("command"):
            transport = "stdio"
        else:
            transport = "unknown"
    enabled = bool(details.get("enabled", True))
    entry: dict[str, Any] = {
        "id": server_id,
        "name": str(details.get("name") or server_id.replace("_", " ").replace("-", " ").title()),
        "transport": transport,
        "status": "registered" if enabled else "disabled",
        "enabled": enabled,
        "source": str(path),
        "kind": "mcp_server",
    }
    if details.get("description"):
        entry["description"] = str(details.get("description"))
    if details.get("url"):
        entry["url"] = str(details.get("url"))
    if details.get("command"):
        entry["command"] = str(details.get("command"))
    if isinstance(details.get("args"), list):
        entry["args"] = [str(item) for item in details.get("args", [])]
    return entry


def _probe_entry(entry: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
    server_id = str(entry.get("id", "")).strip()
    enabled = bool(entry.get("enabled", True))
    if not enabled:
        return {
            "id": server_id,
            "status": "disabled",
            "checked_at": time.time(),
            "transport": entry.get("transport", "unknown"),
            "probe_target": entry.get("url") or entry.get("command") or "",
        }

    transport = str(entry.get("transport", "unknown")).strip().lower()
    if transport == "http":
        return _probe_http_entry(entry, timeout_seconds)
    if transport == "stdio":
        return _probe_stdio_entry(entry)
    return {
        "id": server_id,
        "status": "degraded",
        "checked_at": time.time(),
        "transport": transport,
        "last_error": f"Unsupported transport: {transport}",
        "probe_target": entry.get("url") or entry.get("command") or "",
    }


def _probe_http_entry(entry: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
    server_id = str(entry.get("id", "")).strip()
    url = str(entry.get("url", "")).strip()
    payload = {
        "jsonrpc": "2.0",
        "id": f"probe-{server_id}",
        "method": "initialize",
        "params": {"protocolVersion": "2024-11-05"},
    }
    req = request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    checked_at = time.time()
    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
            parsed = json.loads(body) if body else {}
            status = "healthy" if isinstance(parsed, dict) and "result" in parsed else "degraded"
            result = {
                "id": server_id,
                "status": status,
                "checked_at": checked_at,
                "transport": "http",
                "probe_method": "initialize",
                "probe_target": url,
                "http_status": int(getattr(response, "status", 200) or 200),
            }
            if isinstance(parsed, dict) and isinstance(parsed.get("result"), dict):
                server_info = parsed.get("result", {}).get("serverInfo", {})
                if isinstance(server_info, dict) and server_info:
                    result["server_info"] = server_info
            return result
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return {
            "id": server_id,
            "status": "degraded",
            "checked_at": checked_at,
            "transport": "http",
            "probe_method": "initialize",
            "probe_target": url,
            "last_error": raw or str(exc),
            "last_failure_code": exc.code,
            "http_status": exc.code,
        }
    except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {
            "id": server_id,
            "status": "degraded",
            "checked_at": checked_at,
            "transport": "http",
            "probe_method": "initialize",
            "probe_target": url,
            "last_error": str(exc),
        }


def _probe_stdio_entry(entry: dict[str, Any]) -> dict[str, Any]:
    server_id = str(entry.get("id", "")).strip()
    command = str(entry.get("command", "")).strip()
    checked_at = time.time()
    resolved_command = shutil.which(command) if command else None
    if resolved_command or Path(command).exists():
        return {
            "id": server_id,
            "status": "healthy",
            "checked_at": checked_at,
            "transport": "stdio",
            "probe_method": "command-resolution",
            "probe_target": command,
            "resolved_command": resolved_command or str(Path(command)),
        }
    return {
        "id": server_id,
        "status": "degraded",
        "checked_at": checked_at,
        "transport": "stdio",
        "probe_method": "command-resolution",
        "probe_target": command,
        "last_error": f"Command not found: {command}",
    }


def _persist_probe_result(entry: dict[str, Any], result: dict[str, Any], root: Path | None) -> None:
    path = get_mcp_health_state_path(root)
    state = load_mcp_health_state(root)
    servers = state.get("servers", {})
    if not isinstance(servers, dict):
        servers = {}
    server_id = str(entry.get("id", "")).strip()
    previous = servers.get(server_id, {}) if isinstance(servers.get(server_id, {}), dict) else {}
    failure_count = int(previous.get("failure_count", 0) or 0)
    status = str(result.get("status", "unknown")).lower()
    if status == "healthy":
        failure_count = 0
    elif status not in {"disabled", "registered"}:
        failure_count += 1
    persisted = {
        "status": result.get("status", "unknown"),
        "checked_at": result.get("checked_at", time.time()),
        "failure_count": failure_count,
        "last_error": result.get("last_error"),
        "last_failure_code": result.get("last_failure_code"),
        "last_restored_at": result.get("checked_at") if status == "healthy" else previous.get("last_restored_at"),
        "transport": entry.get("transport", "unknown"),
        "source": entry.get("source"),
        "probe_method": result.get("probe_method"),
        "probe_target": result.get("probe_target"),
    }
    if result.get("resolved_command"):
        persisted["resolved_command"] = result["resolved_command"]
    if result.get("server_info"):
        persisted["server_info"] = result["server_info"]
    servers[server_id] = persisted
    document = {"version": state.get("version", 1), "servers": servers}
    _write_mcp_health_state(path, document)