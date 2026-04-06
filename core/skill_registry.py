"""
SkillRegistry
=============
Unified skill index combining filesystem discovery (via SkillsPlane) and
programmatic registration.

Supports filtering by category, keyword, and capability tags, and provides
a refresh path to re-seed from the filesystem without discarding
programmatically registered entries.
"""
from __future__ import annotations

import logging

from typing import Any


class SkillEntry:
    """A single registered skill entry."""

    def __init__(
        self,
        skill_id: str,
        name: str,
        description: str = "",
        category: str = "general",
        tags: list[str] | None = None,
        source: str = "programmatic",
        path: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.skill_id = skill_id
        self.name = name
        self.description = description
        self.category = category
        self.tags = list(tags or [])
        self.source = source
        self.path = path
        self.metadata = dict(metadata or {})

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "tags": list(self.tags),
            "source": self.source,
            "path": self.path,
            "kind": "skill",
        }


class SkillRegistry:
    """Unified skill index combining filesystem discovery and programmatic registration.

    If a *skills_plane* is provided its current skill list is used to seed the
    registry at construction time.  Additional entries can be registered
    programmatically at any time via :meth:`register`.

    Parameters
    ----------
    skills_plane:
        Optional ``SkillsPlane`` instance for filesystem-discovered skills.
    bus:
        Optional event bus for publish_nowait calls.
    """

    def __init__(
        self,
        skills_plane: Any | None = None,
        bus: Any | None = None,
    ) -> None:
        self._skills_plane = skills_plane
        self._bus = bus
        self._skills: dict[str, SkillEntry] = {}
        if skills_plane is not None:
            self._seed_from_plane()

    # ------------------------------------------------------------------
    # Seeding
    # ------------------------------------------------------------------

    def _seed_from_plane(self) -> None:
        for skill in self._skills_plane.list_skills():
            entry = SkillEntry(
                skill_id=str(skill.get("id", "")),
                name=str(skill.get("name") or skill.get("id") or ""),
                description=str(skill.get("description", "")),
                category=str(skill.get("category", "general")),
                tags=list(skill.get("tags", [])),
                source="filesystem",
                path=str(skill.get("path", "")),
            )
            if entry.skill_id:
                self._skills[entry.skill_id] = entry

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def register(self, entry: SkillEntry) -> SkillEntry:
        """Register or replace a skill entry."""
        if not entry.skill_id or not entry.skill_id.strip():
            raise ValueError("Skill id must be non-empty")
        self._skills[entry.skill_id] = entry
        self._publish("system/skills", {"action": "register", "skill_id": entry.skill_id})
        return entry

    def unregister(self, skill_id: str) -> bool:
        """Remove a skill by id.  Returns True if found and removed."""
        removed = self._skills.pop(skill_id, None) is not None
        if removed:
            self._publish("system/skills", {"action": "unregister", "skill_id": skill_id})
        return removed

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def list_skills(
        self,
        category: str | None = None,
        keyword: str | None = None,
        tag: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return all skills, optionally filtered by category, keyword, and/or tag."""
        entries = sorted(self._skills.values(), key=lambda e: e.skill_id)
        if category:
            entries = [e for e in entries if e.category.lower() == category.lower()]
        if keyword:
            kw = keyword.lower()
            entries = [
                e for e in entries
                if kw in e.skill_id.lower()
                or kw in e.name.lower()
                or kw in e.description.lower()
            ]
        if tag:
            tag_lower = tag.lower()
            entries = [e for e in entries if any(tag_lower == t.lower() for t in e.tags)]
        return [e.to_dict() for e in entries]

    def describe(self, skill_id: str) -> SkillEntry:
        """Return the SkillEntry for a specific skill."""
        entry = self._skills.get(skill_id)
        if entry is None:
            raise ValueError(f"Unknown skill: {skill_id!r}")
        return entry

    def categories(self) -> list[str]:
        """Return unique category names, sorted."""
        return sorted({e.category for e in self._skills.values()})

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------

    def refresh_from_plane(self) -> int:
        """Re-seed filesystem skills from the SkillsPlane.

        Only adds skills not already in the registry (does not overwrite
        programmatic registrations).  Returns the number of new entries added.
        """
        if self._skills_plane is None:
            return 0
        added = 0
        for skill in self._skills_plane.list_skills():
            skill_id = str(skill.get("id", ""))
            if skill_id and skill_id not in self._skills:
                entry = SkillEntry(
                    skill_id=skill_id,
                    name=str(skill.get("name") or skill_id),
                    description=str(skill.get("description", "")),
                    category=str(skill.get("category", "general")),
                    tags=list(skill.get("tags", [])),
                    source="filesystem",
                    path=str(skill.get("path", "")),
                )
                self._skills[skill_id] = entry
                added += 1
        return added

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        entries = list(self._skills.values())
        return {
            "counts": {
                "total": len(entries),
                "filesystem": sum(1 for e in entries if e.source == "filesystem"),
                "programmatic": sum(1 for e in entries if e.source == "programmatic"),
            },
            "categories": self.categories(),
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
            logging.getLogger(__name__).debug("Bus publish failed for topic %s", topic, exc_info=True)
