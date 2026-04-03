from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

from core.config import get_harness_repo_root, get_legacy_harness_snapshot_root, is_supported_harness_repo_root


class HarnessPortAdapter:
    def __init__(self):
        self.root = get_harness_repo_root()
        self.src_root = self.root / "src"
        self.legacy_snapshot_root = get_legacy_harness_snapshot_root()
        self.available = is_supported_harness_repo_root(self.root)
        self.error: str | None = None
        self._manifest_module = None
        self._query_engine_module = None
        self._commands_module = None
        self._tools_module = None

        if not self.available:
            self.error = self._build_unavailable_reason()

        if self.available:
            try:
                root_str = str(self.root)
                inserted = False
                if root_str not in sys.path:
                    sys.path.insert(0, root_str)
                    inserted = True
                try:
                    self._manifest_module = importlib.import_module("src.port_manifest")
                    self._query_engine_module = importlib.import_module("src.query_engine")
                    self._commands_module = importlib.import_module("src.commands")
                    self._tools_module = importlib.import_module("src.tools")
                finally:
                    if inserted:
                        sys.path.remove(root_str)
            except Exception as exc:
                self.available = False
                self.error = str(exc)

    def status(self) -> dict[str, Any]:
        legacy_snapshot = self._legacy_snapshot_status()
        if not self.available or None in {
            self._manifest_module,
            self._query_engine_module,
            self._commands_module,
            self._tools_module,
        }:
            return {
                "available": False,
                "root": str(self.root),
                "src_root": str(self.src_root),
                "legacy_snapshot": legacy_snapshot,
                "error": self.error,
            }

        manifest = self._manifest_module.build_port_manifest(self.src_root)
        summary = self._sanitize_text(self._query_engine_module.QueryEnginePort(manifest).render_summary())
        command_backlog = self._commands_module.build_command_backlog()
        tool_backlog = self._tools_module.build_tool_backlog()

        return {
            "available": True,
            "root": str(self.root),
            "src_root": str(self.src_root),
            "neutral_name": "harness-port",
            "total_python_files": manifest.total_python_files,
            "summary": summary,
            "top_level_modules": [
                {
                    "name": subsystem.name,
                    "path": subsystem.path,
                    "file_count": subsystem.file_count,
                    "notes": subsystem.notes,
                }
                for subsystem in manifest.top_level_modules
            ],
            "commands": [
                {
                    "name": module.name,
                    "responsibility": module.responsibility,
                    "source_hint": module.source_hint,
                    "status": module.status,
                }
                for module in command_backlog.modules
            ],
            "tools": [
                {
                    "name": module.name,
                    "responsibility": module.responsibility,
                    "source_hint": module.source_hint,
                    "status": module.status,
                }
                for module in tool_backlog.modules
            ],
            "legacy_snapshot": legacy_snapshot,
        }

    def build_sft_examples(self) -> list[dict[str, Any]]:
        status = self.status()
        if not status.get("available"):
            return []

        summary = status.get("summary", "")
        commands = status.get("commands", [])
        tools = status.get("tools", [])
        modules = status.get("top_level_modules", [])
        legacy = status.get("legacy_snapshot", {})
        legacy_skills = ", ".join(legacy.get("notable_skills", [])) or "none"
        system_prompt = (
            "You are MiniMind, the lightweight reasoning engine for OpenChimera. "
            "Answer using internal architecture context precisely and without pretending unavailable components exist."
        )
        command_lines = "\n".join(
            f"- {item['name']}: {item['responsibility']} ({item['status']})"
            for item in commands
        )
        tool_lines = "\n".join(
            f"- {item['name']}: {item['responsibility']} ({item['status']})"
            for item in tools
        )
        module_lines = "\n".join(
            f"- {item['name']}: {item['file_count']} files, {item['notes']}"
            for item in modules
        )
        return [
            {
                "conversations": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "Summarize the upstream Python harness workspace that OpenChimera extracted."},
                    {"role": "assistant", "content": summary},
                ]
            },
            {
                "conversations": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "What command surface exists in the upstream Python harness workspace?"},
                    {"role": "assistant", "content": command_lines},
                ]
            },
            {
                "conversations": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "What tool surface exists in the upstream Python harness workspace?"},
                    {"role": "assistant", "content": tool_lines},
                ]
            },
            {
                "conversations": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "List the top Python modules in the upstream harness workspace and what they do."},
                    {"role": "assistant", "content": module_lines},
                ]
            },
            {
                "conversations": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "What legacy reverse-engineered workflow clues were preserved in the compatibility snapshot?"},
                    {
                        "role": "assistant",
                        "content": (
                            "The legacy compatibility snapshot preserved an agent archive under "
                            f"{legacy.get('root', 'unknown')} with notable skill clues: {legacy_skills}. "
                            "Treat it as a workflow and skill reference, not as a model runtime."
                        ),
                    },
                ]
            },
        ]

    def _legacy_snapshot_status(self) -> dict[str, Any]:
        skills_root = self.legacy_snapshot_root / ".agents" / "skills"
        if not skills_root.exists():
            return {
                "available": False,
                "root": str(self.legacy_snapshot_root),
                "skill_count": 0,
                "notable_skills": [],
            }

        skill_names = sorted(path.name for path in skills_root.iterdir() if path.is_dir())
        notable = [
            name
            for name in skill_names
            if name in {"dmux-workflows", "eval-harness", "deep-research", "documentation-lookup"}
        ]
        if not notable:
            notable = skill_names[:8]

        return {
            "available": True,
            "root": str(self.legacy_snapshot_root),
            "skill_count": len(skill_names),
            "notable_skills": notable,
        }

    def _sanitize_text(self, text: str) -> str:
        sanitized = text.replace("Claude Code", "Upstream Harness")
        sanitized = sanitized.replace("claude-code", "upstream-harness-repo")
        sanitized = sanitized.replace("Claude", "Harness")
        sanitized = sanitized.replace("Anthropic", "upstream vendor")
        return sanitized

    def _build_unavailable_reason(self) -> str:
        if not self.root.exists():
            return f"Harness root does not exist: {self.root}"
        suspicious_markers = [
            self.root / "extract-sources.js",
            self.root / "package" / "cli.js",
            self.root / "package" / "cli.js.map",
            self.root / "restored-src",
        ]
        if any(path.exists() for path in suspicious_markers):
            return (
                "Harness root failed safety validation: source-map/package restoration trees are not allowed as live "
                "OpenChimera harness inputs."
            )
        return (
            "Harness root failed structural validation: expected a Python port workspace with src/main.py, "
            "src/port_manifest.py, src/query_engine.py, src/commands.py, and src/tools.py."
        )