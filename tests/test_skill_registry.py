"""Tests for core.skill_registry — SkillEntry and SkillRegistry."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from core.skill_registry import SkillEntry, SkillRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bus() -> MagicMock:
    bus = MagicMock()
    bus.publish_nowait = MagicMock()
    return bus


def _make_entry(
    skill_id: str = "test-skill",
    name: str = "Test Skill",
    description: str = "Does something",
    category: str = "general",
    tags: list[str] | None = None,
    source: str = "programmatic",
    path: str = "",
) -> SkillEntry:
    return SkillEntry(
        skill_id=skill_id,
        name=name,
        description=description,
        category=category,
        tags=tags or [],
        source=source,
        path=path,
    )


def _make_registry(entries: list[SkillEntry] | None = None, bus=None) -> SkillRegistry:
    registry = SkillRegistry(bus=bus)
    for entry in entries or []:
        registry.register(entry)
    return registry


def _make_mock_skills_plane(skills: list[dict]) -> MagicMock:
    plane = MagicMock()
    plane.list_skills.return_value = skills
    return plane


# ---------------------------------------------------------------------------
# SkillEntry.to_dict
# ---------------------------------------------------------------------------

class TestSkillEntryToDict(unittest.TestCase):
    def test_to_dict_has_required_keys(self):
        entry = _make_entry()
        d = entry.to_dict()
        for key in ("id", "name", "description", "category", "tags", "source", "path", "kind"):
            self.assertIn(key, d)

    def test_kind_is_skill(self):
        self.assertEqual(_make_entry().to_dict()["kind"], "skill")

    def test_id_matches_skill_id(self):
        entry = _make_entry(skill_id="my-skill")
        self.assertEqual(entry.to_dict()["id"], "my-skill")

    def test_tags_is_list(self):
        entry = _make_entry(tags=["a", "b"])
        self.assertEqual(entry.to_dict()["tags"], ["a", "b"])

    def test_source_reflected(self):
        entry = _make_entry(source="filesystem")
        self.assertEqual(entry.to_dict()["source"], "filesystem")


# ---------------------------------------------------------------------------
# SkillRegistry — construction and seeding
# ---------------------------------------------------------------------------

class TestSkillRegistryConstruction(unittest.TestCase):
    def test_empty_registry_has_zero_skills(self):
        reg = SkillRegistry()
        self.assertEqual(len(reg.list_skills()), 0)

    def test_seed_from_skills_plane(self):
        plane = _make_mock_skills_plane([
            {"id": "skill-a", "name": "A", "description": "desc a", "category": "test", "tags": [], "path": "/a"},
            {"id": "skill-b", "name": "B", "description": "desc b", "category": "test", "tags": [], "path": "/b"},
        ])
        reg = SkillRegistry(skills_plane=plane)
        ids = {s["id"] for s in reg.list_skills()}
        self.assertIn("skill-a", ids)
        self.assertIn("skill-b", ids)

    def test_seed_skips_entries_with_empty_id(self):
        plane = _make_mock_skills_plane([
            {"id": "", "name": "Bad", "description": "", "category": "", "tags": [], "path": ""},
        ])
        reg = SkillRegistry(skills_plane=plane)
        self.assertEqual(len(reg.list_skills()), 0)

    def test_seeded_entries_have_source_filesystem(self):
        plane = _make_mock_skills_plane([
            {"id": "fs-skill", "name": "FS", "description": "", "category": "x", "tags": [], "path": "/p"},
        ])
        reg = SkillRegistry(skills_plane=plane)
        entry = reg.describe("fs-skill")
        self.assertEqual(entry.source, "filesystem")


# ---------------------------------------------------------------------------
# SkillRegistry — register / unregister
# ---------------------------------------------------------------------------

class TestSkillRegistryRegisterUnregister(unittest.TestCase):
    def test_register_adds_skill(self):
        reg = _make_registry()
        reg.register(_make_entry("skill-x"))
        self.assertEqual(len(reg.list_skills()), 1)

    def test_register_replaces_existing_by_id(self):
        reg = _make_registry()
        reg.register(_make_entry("dup", description="v1"))
        reg.register(_make_entry("dup", description="v2"))
        skills = reg.list_skills()
        self.assertEqual(len(skills), 1)
        self.assertEqual(skills[0]["description"], "v2")

    def test_register_empty_id_raises_value_error(self):
        reg = _make_registry()
        with self.assertRaises(ValueError):
            reg.register(_make_entry(skill_id=""))

    def test_register_returns_the_entry(self):
        reg = _make_registry()
        entry = _make_entry("ret-test")
        returned = reg.register(entry)
        self.assertIs(returned, entry)

    def test_register_publishes_to_bus(self):
        bus = _make_bus()
        reg = SkillRegistry(bus=bus)
        reg.register(_make_entry("pub-test"))
        bus.publish_nowait.assert_called_once()
        topic, payload = bus.publish_nowait.call_args[0]
        self.assertEqual(topic, "system/skills")
        self.assertEqual(payload["action"], "register")

    def test_unregister_removes_skill(self):
        reg = _make_registry([_make_entry("del-me")])
        removed = reg.unregister("del-me")
        self.assertTrue(removed)
        self.assertEqual(len(reg.list_skills()), 0)

    def test_unregister_unknown_returns_false(self):
        reg = _make_registry()
        self.assertFalse(reg.unregister("no-such"))

    def test_unregister_publishes_to_bus(self):
        bus = _make_bus()
        reg = SkillRegistry(bus=bus)
        reg.register(_make_entry("del-pub"))
        bus.reset_mock()
        reg.unregister("del-pub")
        bus.publish_nowait.assert_called_once()
        _, payload = bus.publish_nowait.call_args[0]
        self.assertEqual(payload["action"], "unregister")

    def test_unregister_unknown_does_not_publish(self):
        bus = _make_bus()
        reg = SkillRegistry(bus=bus)
        reg.unregister("nonexistent")
        bus.publish_nowait.assert_not_called()


# ---------------------------------------------------------------------------
# SkillRegistry — list_skills
# ---------------------------------------------------------------------------

class TestSkillRegistryListSkills(unittest.TestCase):
    def setUp(self):
        self.reg = SkillRegistry()
        self.reg.register(_make_entry("alpha", category="security", tags=["audit"]))
        self.reg.register(_make_entry("beta", category="engineering", tags=["code"]))
        self.reg.register(_make_entry("gamma", category="security", tags=["audit", "code"]))

    def test_list_all_skills(self):
        self.assertEqual(len(self.reg.list_skills()), 3)

    def test_list_sorted_by_id(self):
        ids = [s["id"] for s in self.reg.list_skills()]
        self.assertEqual(ids, sorted(ids))

    def test_filter_by_category(self):
        skills = self.reg.list_skills(category="security")
        ids = {s["id"] for s in skills}
        self.assertIn("alpha", ids)
        self.assertIn("gamma", ids)
        self.assertNotIn("beta", ids)

    def test_filter_category_case_insensitive(self):
        skills = self.reg.list_skills(category="SECURITY")
        self.assertEqual(len(skills), 2)

    def test_filter_by_keyword_in_id(self):
        skills = self.reg.list_skills(keyword="alpha")
        self.assertEqual(len(skills), 1)
        self.assertEqual(skills[0]["id"], "alpha")

    def test_filter_by_keyword_in_name(self):
        reg = _make_registry([_make_entry("x", name="Quantum Engine")])
        skills = reg.list_skills(keyword="quantum")
        self.assertEqual(len(skills), 1)

    def test_filter_by_keyword_in_description(self):
        reg = _make_registry([_make_entry("x", description="Hash-chained audit log")])
        skills = reg.list_skills(keyword="audit")
        self.assertEqual(len(skills), 1)

    def test_filter_by_tag(self):
        skills = self.reg.list_skills(tag="audit")
        ids = {s["id"] for s in skills}
        self.assertIn("alpha", ids)
        self.assertIn("gamma", ids)
        self.assertNotIn("beta", ids)

    def test_filter_tag_case_insensitive(self):
        skills = self.reg.list_skills(tag="CODE")
        self.assertEqual(len(skills), 2)

    def test_filter_category_and_tag_combined(self):
        skills = self.reg.list_skills(category="security", tag="code")
        ids = {s["id"] for s in skills}
        self.assertEqual(ids, {"gamma"})

    def test_no_match_returns_empty_list(self):
        skills = self.reg.list_skills(category="nonexistent")
        self.assertEqual(skills, [])


# ---------------------------------------------------------------------------
# SkillRegistry — describe
# ---------------------------------------------------------------------------

class TestSkillRegistryDescribe(unittest.TestCase):
    def test_describe_returns_entry(self):
        reg = _make_registry([_make_entry("desc-test")])
        entry = reg.describe("desc-test")
        self.assertEqual(entry.skill_id, "desc-test")

    def test_describe_unknown_raises_value_error(self):
        reg = _make_registry()
        with self.assertRaises(ValueError):
            reg.describe("ghost")


# ---------------------------------------------------------------------------
# SkillRegistry — categories
# ---------------------------------------------------------------------------

class TestSkillRegistryCategories(unittest.TestCase):
    def test_categories_unique_sorted(self):
        reg = _make_registry([
            _make_entry("a", category="security"),
            _make_entry("b", category="engineering"),
            _make_entry("c", category="security"),
        ])
        cats = reg.categories()
        self.assertEqual(cats, sorted(set(cats)))
        self.assertIn("security", cats)
        self.assertIn("engineering", cats)

    def test_categories_empty_when_no_skills(self):
        reg = SkillRegistry()
        self.assertEqual(reg.categories(), [])


# ---------------------------------------------------------------------------
# SkillRegistry — refresh_from_plane
# ---------------------------------------------------------------------------

class TestSkillRegistryRefreshFromPlane(unittest.TestCase):
    def test_refresh_without_plane_returns_zero(self):
        reg = SkillRegistry()
        added = reg.refresh_from_plane()
        self.assertEqual(added, 0)

    def test_refresh_adds_new_filesystem_skills(self):
        plane = _make_mock_skills_plane([
            {"id": "new-skill", "name": "New", "description": "", "category": "x", "tags": [], "path": ""},
        ])
        reg = SkillRegistry(skills_plane=plane)
        # Now plane returns a new skill
        plane.list_skills.return_value = [
            {"id": "new-skill", "name": "New", "description": "", "category": "x", "tags": [], "path": ""},
            {"id": "added-skill", "name": "Added", "description": "", "category": "y", "tags": [], "path": ""},
        ]
        added = reg.refresh_from_plane()
        self.assertEqual(added, 1)
        self.assertIsNotNone(reg._skills.get("added-skill"))

    def test_refresh_does_not_overwrite_programmatic_entry(self):
        plane = _make_mock_skills_plane([])
        reg = SkillRegistry(skills_plane=plane)
        reg.register(_make_entry("manual", description="programmatic"))
        plane.list_skills.return_value = [
            {"id": "manual", "name": "Manual FS", "description": "fs version", "category": "x", "tags": [], "path": ""},
        ]
        added = reg.refresh_from_plane()
        self.assertEqual(added, 0)
        self.assertEqual(reg.describe("manual").description, "programmatic")


# ---------------------------------------------------------------------------
# SkillRegistry — status
# ---------------------------------------------------------------------------

class TestSkillRegistryStatus(unittest.TestCase):
    def test_status_total_count(self):
        reg = _make_registry([_make_entry("a"), _make_entry("b")])
        self.assertEqual(reg.status()["counts"]["total"], 2)

    def test_status_sources(self):
        plane = _make_mock_skills_plane([
            {"id": "fs", "name": "FS", "description": "", "category": "x", "tags": [], "path": ""},
        ])
        reg = SkillRegistry(skills_plane=plane)
        reg.register(_make_entry("prog", source="programmatic"))
        status = reg.status()
        self.assertEqual(status["counts"]["filesystem"], 1)
        self.assertEqual(status["counts"]["programmatic"], 1)

    def test_status_categories_present(self):
        reg = _make_registry([
            _make_entry("a", category="cat1"),
            _make_entry("b", category="cat2"),
        ])
        self.assertIn("categories", reg.status())

    def test_status_empty_registry(self):
        reg = SkillRegistry()
        status = reg.status()
        self.assertEqual(status["counts"]["total"], 0)


if __name__ == "__main__":
    unittest.main()
