"""
PluginManifest
==============
Formal descriptor format for OpenChimera plugin manifests.

A manifest is a JSON file that declares the plugin's identity and the
capability bundles it contributes: tools, skills, commands, and MCP
server configurations.

Required fields: ``id``, ``name``, ``version``.

Usage::

    manifest = load_manifest("plugins/my-plugin/manifest.json")
    manifest.tools    # list[str]
    manifest.to_dict()

    # Or validate and build from a raw dict:
    manifest = from_dict({"id": "x", "name": "X", "version": "1.0"})
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_REQUIRED_FIELDS: frozenset[str] = frozenset({"id", "name", "version"})
_LIST_FIELDS: frozenset[str] = frozenset({"tools", "skills", "commands", "tags"})
_METADATA_EXCLUDED: frozenset[str] = frozenset({
    "id", "name", "version", "description", "author", "url",
    "tools", "skills", "commands", "mcp_servers", "tags", "kind",
})


@dataclass
class PluginManifest:
    """Formal descriptor for an OpenChimera plugin.

    Attributes
    ----------
    id:
        Unique plugin identifier (slug form, e.g. ``"my-plugin"``).
    name:
        Human-readable display name.
    version:
        Semantic version string (e.g. ``"1.0.0"``).
    description:
        Optional short description.
    author:
        Optional author name or contact.
    url:
        Optional homepage or repository URL.
    tools:
        List of tool identifiers contributed by this plugin.
    skills:
        List of skill identifiers contributed by this plugin.
    commands:
        List of command identifiers contributed by this plugin.
    mcp_servers:
        List of MCP server configuration dicts contributed by this plugin.
    tags:
        Arbitrary tag strings for categorization and search.
    metadata:
        Any extra fields from the source manifest that are not part of
        the formal schema.
    """

    id: str
    name: str
    version: str
    description: str = ""
    author: str = ""
    url: str = ""
    tools: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    mcp_servers: list[dict[str, Any]] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "url": self.url,
            "tools": list(self.tools),
            "skills": list(self.skills),
            "commands": list(self.commands),
            "mcp_servers": list(self.mcp_servers),
            "tags": list(self.tags),
            "metadata": dict(self.metadata),
            "kind": "plugin",
        }


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def validate_manifest(data: dict[str, Any]) -> list[str]:
    """Validate a raw manifest dict.

    Returns a list of error strings.  An empty list means the manifest is
    valid.  Does not raise.
    """
    if not isinstance(data, dict):
        return ["Manifest must be a JSON object"]

    errors: list[str] = []

    for field_name in sorted(_REQUIRED_FIELDS):
        value = data.get(field_name)
        if not value or not str(value).strip():
            errors.append(f"Missing required field: {field_name!r}")

    for list_field in sorted(_LIST_FIELDS):
        if list_field in data and not isinstance(data[list_field], list):
            errors.append(f"Field {list_field!r} must be a list")

    if "mcp_servers" in data and not isinstance(data["mcp_servers"], list):
        errors.append("Field 'mcp_servers' must be a list")

    return errors


def load_manifest(path: str | Path) -> PluginManifest:
    """Load and parse a JSON plugin manifest file.

    Raises
    ------
    FileNotFoundError
        If the file does not exist.
    ValueError
        If the JSON is invalid or required fields are missing.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Plugin manifest not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in plugin manifest {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Plugin manifest must be a JSON object: {path}")
    return from_dict(data)


def from_dict(data: dict[str, Any]) -> PluginManifest:
    """Build a :class:`PluginManifest` from a raw dict.

    Validates before constructing.  Raises ``ValueError`` with a combined
    error message if validation fails.
    """
    errors = validate_manifest(data)
    if errors:
        raise ValueError(f"Invalid plugin manifest: {'; '.join(errors)}")
    return _build(data)


# ---------------------------------------------------------------------------
# Internal builder
# ---------------------------------------------------------------------------

def _build(data: dict[str, Any]) -> PluginManifest:
    extra = {k: v for k, v in data.items() if k not in _METADATA_EXCLUDED}
    return PluginManifest(
        id=str(data["id"]).strip(),
        name=str(data["name"]).strip(),
        version=str(data["version"]).strip(),
        description=str(data.get("description", "")).strip(),
        author=str(data.get("author", "")).strip(),
        url=str(data.get("url", "")).strip(),
        tools=[str(t) for t in data.get("tools", []) if t],
        skills=[str(s) for s in data.get("skills", []) if s],
        commands=[str(c) for c in data.get("commands", []) if c],
        mcp_servers=[dict(m) for m in data.get("mcp_servers", []) if isinstance(m, dict)],
        tags=[str(t) for t in data.get("tags", []) if t],
        metadata=extra,
    )
