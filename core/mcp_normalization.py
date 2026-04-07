"""Shared MCP server entry normalization helper — DRY extraction.

Consolidates MCP server entry normalization logic from mcp_adapter.py and mcp_registry.py.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def normalize_mcp_server_entry(
    server_id: str,
    details: dict[str, Any],
    *,
    source_path: Path | str | None = None,
) -> dict[str, Any]:
    """Normalize an MCP server registry entry to a consistent format.
    
    Parameters
    ----------
    server_id:
        The unique server identifier.
    details:
        Raw details dict from the registry file.
    source_path:
        Optional source file path for tracking provenance.
    
    Returns
    -------
    Normalized entry dict with standardized fields:
        id, name, transport, status, enabled, source, kind, and optional
        description, url, command, args.
    """
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
        "name": str(
            details.get("name") or server_id.replace("_", " ").replace("-", " ").title()
        ),
        "transport": transport,
        "status": "registered" if enabled else "disabled",
        "enabled": enabled,
        "source": str(source_path) if source_path else "unknown",
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
