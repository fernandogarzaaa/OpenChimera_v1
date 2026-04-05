"""
CommandRegistry
===============
Unified catalog of all user-invocable commands.

Merges commands discovered by CapabilityRegistry with programmatically
registered entries.  Provides filtering by surface and keyword search,
and optional handler dispatch with bus event emission.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class CommandEntry:
    """Describes a single user-invocable command."""

    id: str
    name: str
    description: str
    entrypoint: str = ""
    surfaces: list[str] = field(default_factory=list)
    handler: Callable[..., Any] | None = None
    tags: list[str] = field(default_factory=list)
    requires_admin: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "entrypoint": self.entrypoint,
            "surfaces": list(self.surfaces),
            "tags": list(self.tags),
            "requires_admin": self.requires_admin,
            "executable": self.handler is not None,
            "kind": "command",
        }


class CommandRegistry:
    """Unified catalog of all user-invocable commands.

    Accepts an optional *capability_registry* for seeding the catalog from
    the filesystem-discovered command list.  Additional commands can be
    registered programmatically at any time.

    Parameters
    ----------
    capability_registry:
        If provided, seeds the catalog from
        ``capability_registry.list_kind("commands")``.
    bus:
        Optional event bus for publish_nowait calls.
    """

    def __init__(
        self,
        capability_registry: Any | None = None,
        bus: Any | None = None,
    ) -> None:
        self._capability_registry = capability_registry
        self._bus = bus
        self._commands: dict[str, CommandEntry] = {}
        if capability_registry is not None:
            self._seed_from_capability_registry()

    # ------------------------------------------------------------------
    # Seeding
    # ------------------------------------------------------------------

    def _seed_from_capability_registry(self) -> None:
        for cmd in self._capability_registry.list_kind("commands"):
            entry = CommandEntry(
                id=str(cmd.get("id", "")),
                name=str(cmd.get("name", "")),
                description=str(cmd.get("description", "")),
                entrypoint=str(cmd.get("entrypoint", "")),
                surfaces=list(cmd.get("surfaces", [])),
                tags=list(cmd.get("tags", [])),
            )
            if entry.id:
                self._commands[entry.id] = entry

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def register(self, command: CommandEntry) -> CommandEntry:
        """Register or replace a command by id."""
        if not command.id or not command.id.strip():
            raise ValueError("Command id must be non-empty")
        self._commands[command.id] = command
        self._publish("system/commands", {"action": "register", "command_id": command.id})
        return command

    def unregister(self, command_id: str) -> bool:
        """Remove a command by id.  Returns True if found and removed."""
        removed = self._commands.pop(command_id, None) is not None
        if removed:
            self._publish("system/commands", {"action": "unregister", "command_id": command_id})
        return removed

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def list_commands(
        self,
        surface: str | None = None,
        tag: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return all commands, optionally filtered by surface and/or tag."""
        entries = sorted(self._commands.values(), key=lambda c: c.id)
        if surface:
            entries = [c for c in entries if surface in c.surfaces]
        if tag:
            tag_lower = tag.lower()
            entries = [c for c in entries if any(tag_lower == t.lower() for t in c.tags)]
        return [c.to_dict() for c in entries]

    def describe(self, command_id: str) -> CommandEntry:
        """Return the CommandEntry for a specific command."""
        cmd = self._commands.get(command_id)
        if cmd is None:
            raise ValueError(f"Unknown command: {command_id!r}")
        return cmd

    def find_by_keyword(self, keyword: str) -> list[dict[str, Any]]:
        """Search commands by keyword across id, name, and description."""
        kw = keyword.lower()
        results = [
            c for c in self._commands.values()
            if kw in c.id.lower() or kw in c.name.lower() or kw in c.description.lower()
        ]
        return [c.to_dict() for c in sorted(results, key=lambda c: c.id)]

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute(self, command_id: str, **kwargs: Any) -> Any:
        """Invoke a command handler by id.

        Raises ``ValueError`` if the command is unknown.
        Raises ``NotImplementedError`` if no handler is registered.
        Emits a bus event either way.
        """
        cmd = self._commands.get(command_id)
        if cmd is None:
            raise ValueError(f"Unknown command: {command_id!r}")
        if cmd.handler is None:
            raise NotImplementedError(f"Command {command_id!r} has no executable handler")
        started = time.perf_counter()
        try:
            result = cmd.handler(**kwargs)
            latency_ms = (time.perf_counter() - started) * 1000.0
            self._publish("system/commands", {
                "action": "execute",
                "command_id": command_id,
                "success": True,
                "latency_ms": round(latency_ms, 3),
            })
            return result
        except Exception:
            latency_ms = (time.perf_counter() - started) * 1000.0
            self._publish("system/commands", {
                "action": "execute",
                "command_id": command_id,
                "success": False,
                "latency_ms": round(latency_ms, 3),
            })
            raise

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        cmds = list(self._commands.values())
        surfaces: set[str] = set()
        for c in cmds:
            surfaces.update(c.surfaces)
        return {
            "counts": {
                "total": len(cmds),
                "executable": sum(1 for c in cmds if c.handler is not None),
            },
            "surfaces": sorted(surfaces),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _publish(self, topic: str, payload: dict[str, Any]) -> None:
        if self._bus is None:
            return
        try:
            self._bus.publish_nowait(topic, payload)
        except Exception:
            pass
