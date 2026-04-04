from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[1]
SKILLS = {
    "astrbot": "astrbot",
    "deer-flow": "deer-flow",
    "khoj": "khoj",
    "ragflow": "ragflow",
    "llamafactory": "llamafactory",
    "swe-agent": "swe-agent",
}


class SkillMetadataTests(unittest.TestCase):
    def test_bridge_skills_have_frontmatter_name_and_description(self) -> None:
        for folder_name, skill_name in SKILLS.items():
            skill_path = ROOT / "skills" / folder_name / "SKILL.md"
            content = skill_path.read_text(encoding="utf-8")
            self.assertTrue(content.startswith("---\n"), folder_name)
            self.assertIn(f'name: "{skill_name}"', content, folder_name)
            self.assertIn("description:", content, folder_name)


if __name__ == "__main__":
    unittest.main()


class SkillsPlaneUnitTests(unittest.TestCase):
    """Unit tests for SkillsPlane runtime interface (API-level, no real FS)."""

    _SAMPLE_SKILLS = [
        {
            "id": "audit-trail",
            "name": "Audit Trail",
            "description": "Hash-chained audit log",
            "category": "security",
            "kind": "skill",
            "path": "/s/audit/SKILL.md",
        },
        {
            "id": "code-reviewer",
            "name": "Code Reviewer",
            "description": "Review code quality",
            "category": "engineering",
            "kind": "skill",
            "path": "/s/code/SKILL.md",
        },
    ]

    def _make_plane(self, skills=None):
        from core.skills_plane import SkillsPlane

        plane = SkillsPlane(root=Path("/fake"))
        plane._registry = MagicMock()
        plane._registry.list_kind.return_value = skills if skills is not None else self._SAMPLE_SKILLS
        return plane

    # ------------------------------------------------------------------
    # list_skills()
    # ------------------------------------------------------------------

    def test_list_skills_returns_a_list(self):
        plane = self._make_plane()
        result = plane.list_skills()
        self.assertIsInstance(result, list)

    def test_list_skills_empty_registry_returns_empty_list(self):
        plane = self._make_plane(skills=[])
        result = plane.list_skills()
        self.assertEqual(result, [])

    # ------------------------------------------------------------------
    # get_skill()
    # ------------------------------------------------------------------

    def test_get_skill_returns_none_for_unknown_id(self):
        plane = self._make_plane()
        result = plane.get_skill("this-skill-does-not-exist")
        self.assertIsNone(result)

    def test_get_skill_returns_metadata_for_known_id(self):
        plane = self._make_plane()
        result = plane.get_skill("audit-trail")
        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "Audit Trail")

    # ------------------------------------------------------------------
    # invoke_skill() with unknown id raises ImportError
    # ------------------------------------------------------------------

    def test_invoke_skill_raises_import_error_for_unknown_id(self):
        plane = self._make_plane(skills=[])
        with self.assertRaises(ImportError):
            plane.invoke_skill("nonexistent-skill")

    # ------------------------------------------------------------------
    # status()
    # ------------------------------------------------------------------

    def test_status_has_required_keys(self):
        plane = self._make_plane()
        st = plane.status()
        for key in ("total", "loaded", "root"):
            self.assertIn(key, st)

    def test_status_total_matches_registry_count(self):
        plane = self._make_plane()
        st = plane.status()
        self.assertEqual(st["total"], len(self._SAMPLE_SKILLS))

    def test_status_loaded_starts_at_zero(self):
        plane = self._make_plane()
        st = plane.status()
        self.assertEqual(st["loaded"], 0)

    def test_status_root_contains_skills_suffix(self):
        plane = self._make_plane()
        st = plane.status()
        self.assertIn("skills", st["root"])
