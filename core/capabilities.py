from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from core.config import ROOT, get_provider_base_url
from core.mcp_registry import list_mcp_registry


_FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)
_DESCRIPTION_HEADING_RE = re.compile(
    r"^##\s+Description\s*$\n(?P<body>.*?)(?=^##\s+|\Z)",
    re.MULTILINE | re.DOTALL,
)
_TITLE_RE = re.compile(r"^#\s+(?P<title>.+)$", re.MULTILINE)


def _clean_text(value: str) -> str:
    return " ".join(str(value).strip().split())


def _parse_frontmatter(text: str) -> dict[str, str]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}
    result: dict[str, str] = {}
    for raw_line in match.group(1).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip().strip('"\'')
    return result


def _extract_description(text: str) -> str:
    frontmatter = _parse_frontmatter(text)
    if frontmatter.get("description"):
        return _clean_text(frontmatter["description"])
    heading_match = _DESCRIPTION_HEADING_RE.search(text)
    if heading_match:
        return _clean_text(heading_match.group("body"))
    lines = [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]
    return _clean_text(lines[0]) if lines else ""


def _extract_title(text: str, fallback: str) -> str:
    frontmatter = _parse_frontmatter(text)
    if frontmatter.get("name"):
        return frontmatter["name"]
    match = _TITLE_RE.search(text)
    if match:
        return _clean_text(match.group("title"))
    return fallback


class CapabilityRegistry:
    def __init__(self, root: Path | None = None):
        self.root = root or ROOT
        self._snapshot: dict[str, Any] | None = None
        self._kind_cache: dict[str, list[dict[str, Any]]] = {}

    def refresh(self) -> dict[str, Any]:
        commands = self._discover_commands()
        tools = self._discover_tools()
        skills = self._discover_skills()
        plugins = self._discover_plugins()
        mcp_servers = self._discover_mcp_servers()
        self._kind_cache = {
            "commands": commands,
            "tools": tools,
            "skills": skills,
            "plugins": plugins,
            "mcp_servers": mcp_servers,
        }
        self._snapshot = {
            "generated_from": str(self.root),
            "counts": {
                "commands": len(commands),
                "tools": len(tools),
                "skills": len(skills),
                "plugins": len(plugins),
                "mcp_servers": len(mcp_servers),
            },
            "commands": commands,
            "tools": tools,
            "skills": skills,
            "plugins": plugins,
            "mcp_servers": mcp_servers,
        }
        return self._snapshot

    def snapshot(self) -> dict[str, Any]:
        return self._snapshot or self.refresh()

    def status(self) -> dict[str, Any]:
        snapshot = self.snapshot()
        return {
            "generated_from": snapshot["generated_from"],
            "counts": snapshot["counts"],
            "plugin_names": [item["id"] for item in snapshot["plugins"][:10]],
            "mcp_server_ids": [item["id"] for item in snapshot["mcp_servers"][:10]],
        }

    def list_kind(self, kind: str) -> list[dict[str, Any]]:
        normalized = kind.strip().lower()
        key = "mcp_servers" if normalized in {"mcp", "mcp_servers", "mcp-server", "mcp-servers"} else normalized
        if key not in {"commands", "tools", "skills", "plugins", "mcp_servers"}:
            raise ValueError(f"Unsupported capability kind: {kind}")
        if self._snapshot is not None and key in self._snapshot:
            return list(self._snapshot[key])
        if key not in self._kind_cache:
            self._kind_cache[key] = self._discover_kind(key)
        return list(self._kind_cache[key])

    def _discover_kind(self, kind: str) -> list[dict[str, Any]]:
        if kind == "commands":
            return self._discover_commands()
        if kind == "tools":
            return self._discover_tools()
        if kind == "skills":
            return self._discover_skills()
        if kind == "plugins":
            return self._discover_plugins()
        if kind == "mcp_servers":
            return self._discover_mcp_servers()
        raise ValueError(f"Unsupported capability kind: {kind}")

    def _discover_commands(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "bootstrap",
                "name": "Bootstrap Workspace",
                "description": "Create missing local state files and normalize the runtime profile.",
                "entrypoint": "openchimera bootstrap",
                "surfaces": ["cli"],
                "kind": "command",
            },
            {
                "id": "doctor",
                "name": "Doctor",
                "description": "Run local diagnostics for auth, runtime roots, and profile health.",
                "entrypoint": "openchimera doctor",
                "surfaces": ["cli"],
                "kind": "command",
            },
            {
                "id": "onboard",
                "name": "Onboard",
                "description": "Inspect onboarding blockers, recommendations, and next actions.",
                "entrypoint": "openchimera onboard",
                "surfaces": ["cli", "api"],
                "kind": "command",
            },
            {
                "id": "status",
                "name": "Status",
                "description": "Return the current runtime supervision and provider snapshot.",
                "entrypoint": "openchimera status",
                "surfaces": ["cli", "api"],
                "kind": "command",
            },
            {
                "id": "serve",
                "name": "Serve",
                "description": "Boot the OpenChimera kernel and hosted API server.",
                "entrypoint": "openchimera serve",
                "surfaces": ["cli"],
                "kind": "command",
            },
            {
                "id": "capabilities",
                "name": "Capabilities",
                "description": "Inspect the discovered command, tool, skill, plugin, and MCP inventory.",
                "entrypoint": "openchimera capabilities",
                "surfaces": ["cli", "api"],
                "kind": "command",
            },
            {
                "id": "tools",
                "name": "Tools",
                "description": "Inspect or execute validated runtime tools.",
                "entrypoint": "openchimera tools",
                "surfaces": ["cli", "api"],
                "kind": "command",
            },
        ]

    def _discover_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "browser.fetch",
                "name": "Browser Fetch",
                "description": "Fetch a web page through the local browser service and persist an artifact.",
                "category": "browser",
                "side_effects": ["artifact", "history"],
                "kind": "tool",
            },
            {
                "id": "browser.submit_form",
                "name": "Browser Submit Form",
                "description": "Submit form data over HTTP through the browser service.",
                "category": "browser",
                "side_effects": ["artifact", "history", "network"],
                "kind": "tool",
            },
            {
                "id": "media.transcribe",
                "name": "Media Transcribe",
                "description": "Convert text or audio payloads into a transcript and record the session.",
                "category": "media",
                "side_effects": ["artifact", "history"],
                "kind": "tool",
            },
            {
                "id": "media.synthesize",
                "name": "Media Synthesize",
                "description": "Generate a local audio artifact from text using the multimedia service.",
                "category": "media",
                "side_effects": ["artifact", "history"],
                "kind": "tool",
            },
            {
                "id": "media.understand_image",
                "name": "Media Understand Image",
                "description": "Analyze an image using the configured multimodal backend.",
                "category": "media",
                "side_effects": ["artifact", "history"],
                "kind": "tool",
            },
            {
                "id": "media.generate_image",
                "name": "Media Generate Image",
                "description": "Generate an image using the configured multimodal backend.",
                "category": "media",
                "side_effects": ["artifact", "history"],
                "kind": "tool",
            },
            {
                "id": "jobs.create",
                "name": "Create Operator Job",
                "description": "Enqueue a durable operator job for asynchronous execution.",
                "category": "runtime",
                "side_effects": ["job-queue"],
                "kind": "tool",
            },
            {
                "id": "autonomy.run_job",
                "name": "Run Autonomy Job",
                "description": "Run one autonomy scheduler job immediately through the validated runtime tool registry.",
                "category": "autonomy",
                "side_effects": ["artifact", "history", "job"],
                "kind": "tool",
            },
            {
                "id": "autonomy.preview_self_repair",
                "name": "Preview Self Repair",
                "description": "Generate or enqueue the preview-only self-repair plan from the autonomy subsystem.",
                "category": "autonomy",
                "side_effects": ["artifact", "history", "job-queue"],
                "kind": "tool",
            },
            {
                "id": "autonomy.dispatch_operator_digest",
                "name": "Dispatch Operator Digest",
                "description": "Generate or enqueue the autonomy operator digest and dispatch it to operator channels.",
                "category": "autonomy",
                "side_effects": ["artifact", "history", "network", "job-queue"],
                "kind": "tool",
            },
            {
                "id": "autonomy.artifact_history",
                "name": "Autonomy Artifact History",
                "description": "Inspect recent autonomy artifact history entries.",
                "category": "autonomy",
                "side_effects": ["history"],
                "kind": "tool",
            },
            {
                "id": "autonomy.artifact_get",
                "name": "Get Autonomy Artifact",
                "description": "Read one autonomy artifact from the autonomy data root.",
                "category": "autonomy",
                "side_effects": ["artifact"],
                "kind": "tool",
            },
            {
                "id": "channels.dispatch_daily_briefing",
                "name": "Dispatch Daily Briefing",
                "description": "Publish the current daily briefing to configured outbound channels.",
                "category": "channels",
                "side_effects": ["network", "history"],
                "kind": "tool",
            },
            {
                "id": "channels.dispatch_topic",
                "name": "Dispatch Channel Topic",
                "description": "Publish an arbitrary topic payload to configured outbound channels for alerting or operator tests.",
                "category": "channels",
                "side_effects": ["network", "history"],
                "kind": "tool",
            },
            {
                "id": "aegis.run_workflow",
                "name": "Run Aegis Workflow",
                "description": "Invoke the Aegis subsystem for preview or execution against a target project.",
                "category": "subsystem",
                "side_effects": ["filesystem"],
                "kind": "tool",
            },
            {
                "id": "ascension.deliberate",
                "name": "Ascension Deliberation",
                "description": "Route a structured deliberation through the Ascension service.",
                "category": "reasoning",
                "side_effects": [],
                "kind": "tool",
            },
            {
                "id": "subsystems.invoke",
                "name": "Invoke Subsystem",
                "description": "Invoke a managed subsystem by id and action.",
                "category": "subsystem",
                "side_effects": ["filesystem", "history"],
                "kind": "tool",
            },
        ]

    def _discover_skills(self) -> list[dict[str, Any]]:
        skills_root = self.root / "skills"
        if not skills_root.exists():
            return []
        discovered: list[tuple[int, dict[str, Any]]] = []
        for skill_path in sorted(skills_root.rglob("SKILL.md")):
            relative_parent = skill_path.parent.relative_to(skills_root)
            category = relative_parent.parts[0] if relative_parent.parts else "root"
            text = skill_path.read_text(encoding="utf-8")
            frontmatter = _parse_frontmatter(text)
            skill_id = _extract_title(text, fallback=skill_path.parent.name).strip().lower().replace(" ", "-")
            discovered.append(
                (
                    0 if frontmatter.get("name") or frontmatter.get("description") else 1,
                    {
                    "id": skill_id,
                    "name": _extract_title(text, fallback=skill_path.parent.name),
                    "description": _extract_description(text),
                    "category": category,
                    "path": str(skill_path),
                    "kind": "skill",
                    },
                )
            )
        return [
            item
            for _, item in sorted(
                discovered,
                key=lambda entry: (entry[0], str(entry[1].get("id", "")), str(entry[1].get("path", ""))),
            )
        ]

    def _discover_plugins(self) -> list[dict[str, Any]]:
        discovered: list[dict[str, Any]] = []
        for plugin_path in sorted((self.root / "plugins").glob("*.json")) if (self.root / "plugins").exists() else []:
            discovered.append(self._load_plugin_manifest(plugin_path))
        skills_root = self.root / "skills"
        if skills_root.exists():
            for plugin_path in sorted(skills_root.rglob("plugin.json")):
                discovered.append(self._load_plugin_manifest(plugin_path))
        return discovered

    def _discover_mcp_servers(self) -> list[dict[str, Any]]:
        servers: dict[str, dict[str, Any]] = {}
        manifest_paths: list[Path] = []
        health_state_path = self.root / "data" / "mcp_health_state.json"
        if health_state_path.exists():
            try:
                health_state = json.loads(health_state_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                health_state = {}
            for server_id, details in (health_state.get("servers", {}) if isinstance(health_state, dict) else {}).items():
                if not isinstance(details, dict):
                    continue
                servers[str(server_id)] = {
                    "id": str(server_id),
                    "name": str(server_id).replace("_", " ").title(),
                    "transport": "health-state",
                    "status": str(details.get("status", "unknown")),
                    "checked_at": details.get("checked_at"),
                    "source": str(health_state_path),
                    "kind": "mcp_server",
                }

        root_manifest = self.root / ".mcp.json"
        if root_manifest.exists():
            manifest_paths.append(root_manifest)
        skills_root = self.root / "skills"
        if skills_root.exists():
            manifest_paths.extend(sorted(skills_root.rglob(".mcp.json")))

        for manifest_path in manifest_paths:
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            raw_servers = manifest.get("mcpServers", {}) if isinstance(manifest, dict) else {}
            if not isinstance(raw_servers, dict):
                continue
            for server_id, details in raw_servers.items():
                if not isinstance(details, dict):
                    continue
                normalized_id = str(server_id)
                discovered = {
                    "id": normalized_id,
                    "name": normalized_id.replace("_", " ").replace("-", " ").title(),
                    "transport": self._infer_mcp_transport(details),
                    "status": "discovered",
                    "source": str(manifest_path),
                    "kind": "mcp_server",
                }
                if "command" in details:
                    discovered["command"] = str(details.get("command", ""))
                if isinstance(details.get("args"), list):
                    discovered["args"] = [str(item) for item in details.get("args", [])]
                if "url" in details:
                    discovered["url"] = str(details.get("url", ""))
                if normalized_id in servers:
                    merged = dict(discovered)
                    merged.update(servers[normalized_id])
                    merged.setdefault("source_manifest", str(manifest_path))
                    if "command" in discovered:
                        merged.setdefault("command", discovered["command"])
                    if "args" in discovered:
                        merged.setdefault("args", discovered["args"])
                    if "url" in discovered:
                        merged.setdefault("url", discovered["url"])
                    servers[normalized_id] = merged
                else:
                    servers[normalized_id] = discovered

        for registered in list_mcp_registry(self.root):
            normalized_id = str(registered.get("id", "")).strip()
            if not normalized_id:
                continue
            if normalized_id in servers:
                merged = dict(registered)
                merged.update(servers[normalized_id])
                merged.setdefault("source_registry", registered.get("source"))
                if "command" in registered:
                    merged.setdefault("command", registered["command"])
                if "args" in registered:
                    merged.setdefault("args", registered["args"])
                if "url" in registered:
                    merged.setdefault("url", registered["url"])
                servers[normalized_id] = merged
            else:
                servers[normalized_id] = registered

        if "openchimera-local" not in servers:
            servers["openchimera-local"] = {
                "id": "openchimera-local",
                "name": "OpenChimera Local MCP",
                "transport": "http",
                "status": "discovered",
                "url": f"{get_provider_base_url().rstrip('/')}/mcp",
                "source": str(self.root / ".mcp.json"),
                "kind": "mcp_server",
            }

        appforge_skill = self.root / "skills" / "appforge-mcp" / "SKILL.md"
        if appforge_skill.exists() and "appforge-local" not in servers:
            servers["appforge-local"] = {
                "id": "appforge-local",
                "name": "AppForge Local MCP",
                "transport": "http",
                "status": "discovered",
                "url": "http://localhost:8000/mcp",
                "source": str(appforge_skill),
                "kind": "mcp_server",
            }
        return sorted(servers.values(), key=lambda item: item["id"])

    def _infer_mcp_transport(self, details: dict[str, Any]) -> str:
        if details.get("url"):
            return "http"
        if details.get("command"):
            return "stdio"
        return "unknown"

    def _load_plugin_manifest(self, plugin_path: Path) -> dict[str, Any]:
        raw = json.loads(plugin_path.read_text(encoding="utf-8"))
        plugin_id = str(raw.get("id") or raw.get("name") or plugin_path.stem)
        return {
            "id": plugin_id,
            "name": str(raw.get("name") or plugin_id),
            "description": _clean_text(str(raw.get("description", ""))),
            "version": str(raw.get("version", "0.0.0")),
            "skills": [str(item) for item in raw.get("skills", []) if item],
            "tools": [str(item) for item in raw.get("tools", []) if item],
            "commands": [str(item) for item in raw.get("commands", []) if item],
            "mcp_servers": [str(item) for item in raw.get("mcp_servers", []) if item],
            "path": str(plugin_path),
            "kind": "plugin",
        }