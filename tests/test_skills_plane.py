"""Tests for core.skills_plane.SkillsPlane."""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestSkillsPlaneStatus(unittest.TestCase):
    """Tests for SkillsPlane.status()."""

    def _make_plane(self, skills: list[dict] | None = None):
        from core.skills_plane import SkillsPlane

        plane = SkillsPlane(root=Path("/fake"))
        skills = skills or []
        with patch.object(plane._registry, "list_kind", return_value=skills):
            status = plane.status()
        return status

    def test_status_returns_total(self):
        status = self._make_plane(skills=[{"id": "a"}, {"id": "b"}])
        self.assertEqual(status["total"], 2)

    def test_status_loaded_zero_initially(self):
        status = self._make_plane(skills=[{"id": "a"}])
        self.assertEqual(status["loaded"], 0)

    def test_status_root_field(self):
        status = self._make_plane()
        self.assertIn("skills", status["root"])

    def test_status_empty_skills(self):
        status = self._make_plane(skills=[])
        self.assertEqual(status["total"], 0)


class TestSkillsPlaneListAndGet(unittest.TestCase):
    """Tests for list_skills(), get_skill(), categories()."""

    _SAMPLE_SKILLS = [
        {"id": "audit-trail", "name": "Audit Trail", "description": "Hash-chained audit log", "category": "security", "kind": "skill", "path": "/s/audit/SKILL.md"},
        {"id": "code-reviewer", "name": "Code Reviewer", "description": "Review code quality", "category": "engineering", "kind": "skill", "path": "/s/code/SKILL.md"},
        {"id": "token-fracture", "name": "Token Fracture", "description": "Token budget fracture", "category": "engineering", "kind": "skill", "path": "/s/token/SKILL.md"},
    ]

    def setUp(self):
        from core.skills_plane import SkillsPlane

        self.plane = SkillsPlane(root=Path("/fake"))
        self._patcher = patch.object(self.plane._registry, "list_kind", return_value=self._SAMPLE_SKILLS)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()

    def test_list_all(self):
        result = self.plane.list_skills()
        self.assertEqual(len(result), 3)

    def test_list_by_category(self):
        result = self.plane.list_skills(category="security")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "audit-trail")

    def test_list_by_keyword_name(self):
        result = self.plane.list_skills(keyword="review")
        ids = [s["id"] for s in result]
        self.assertIn("code-reviewer", ids)

    def test_list_by_keyword_description(self):
        result = self.plane.list_skills(keyword="budget")
        self.assertEqual(result[0]["id"], "token-fracture")

    def test_list_category_and_keyword(self):
        result = self.plane.list_skills(category="engineering", keyword="review")
        self.assertEqual(len(result), 1)

    def test_list_no_match_returns_empty(self):
        result = self.plane.list_skills(keyword="xyzzy-nonexistent")
        self.assertEqual(result, [])

    def test_get_skill_found(self):
        skill = self.plane.get_skill("code-reviewer")
        self.assertIsNotNone(skill)
        self.assertEqual(skill["name"], "Code Reviewer")

    def test_get_skill_not_found(self):
        skill = self.plane.get_skill("does-not-exist")
        self.assertIsNone(skill)

    def test_categories_returns_unique_sorted(self):
        cats = self.plane.categories()
        self.assertEqual(cats, ["engineering", "security"])


class TestSkillsPlaneLoadModule(unittest.TestCase):
    """Tests for load_skill_module()."""

    def _make_plane_with_skill(self, tmpdir: Path, py_content: str, skill_id: str = "my-skill") -> "SkillsPlane":
        from core.skills_plane import SkillsPlane

        skill_dir = tmpdir / skill_id
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(f"# {skill_id}\n")

        source_file = skill_dir / f"{skill_id.replace('-', '_')}.py"
        source_file.write_text(py_content)

        plane = SkillsPlane(root=tmpdir)

        # Inject skill metadata so get_skill() works without full FS scan
        fake_skills = [
            {
                "id": skill_id,
                "name": skill_id,
                "description": "",
                "category": "test",
                "path": str(skill_dir / "SKILL.md"),
                "kind": "skill",
            }
        ]
        patch.object(plane._registry, "list_kind", return_value=fake_skills).start()
        return plane

    def setUp(self):
        import tempfile
        self._tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_load_module_returns_module(self):
        plane = self._make_plane_with_skill(self._tmpdir, "VALUE = 42\n")
        mod = plane.load_skill_module("my-skill")
        self.assertEqual(mod.VALUE, 42)

    def test_load_module_cached_on_second_call(self):
        plane = self._make_plane_with_skill(self._tmpdir, "VALUE = 99\n")
        mod1 = plane.load_skill_module("my-skill")
        mod2 = plane.load_skill_module("my-skill")
        self.assertIs(mod1, mod2)

    def test_load_unknown_skill_raises_import_error(self):
        from core.skills_plane import SkillsPlane

        plane = SkillsPlane(root=self._tmpdir)
        patch.object(plane._registry, "list_kind", return_value=[]).start()
        with self.assertRaises(ImportError):
            plane.load_skill_module("ghost-skill")

    def test_load_skill_with_no_py_raises_import_error(self):
        from core.skills_plane import SkillsPlane

        skill_id = "no-python"
        skill_dir = self._tmpdir / skill_id
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text("# no python skill\n")

        plane = SkillsPlane(root=self._tmpdir)
        fake_skills = [
            {
                "id": skill_id,
                "name": skill_id,
                "description": "",
                "category": "test",
                "path": str(skill_dir / "SKILL.md"),
                "kind": "skill",
            }
        ]
        patch.object(plane._registry, "list_kind", return_value=fake_skills).start()
        with self.assertRaises(ImportError):
            plane.load_skill_module(skill_id)


class TestSkillsPlaneInvoke(unittest.TestCase):
    """Tests for invoke_skill()."""

    def setUp(self):
        import tempfile
        self._tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _make_plane(self, py_content: str, skill_id: str = "test-skill") -> "SkillsPlane":
        from core.skills_plane import SkillsPlane

        skill_dir = self._tmpdir / skill_id
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(f"# {skill_id}\n")
        source_file = skill_dir / f"{skill_id.replace('-', '_')}.py"
        source_file.write_text(py_content)

        plane = SkillsPlane(root=self._tmpdir, bus=MagicMock())
        fake_skills = [
            {
                "id": skill_id,
                "name": skill_id,
                "description": "",
                "category": "test",
                "path": str(skill_dir / "SKILL.md"),
                "kind": "skill",
            }
        ]
        patch.object(plane._registry, "list_kind", return_value=fake_skills).start()
        return plane

    def test_invoke_default_run_function(self):
        plane = self._make_plane("def run(*a, **kw): return 'hello'\n")
        result = plane.invoke_skill("test-skill")
        self.assertEqual(result, "hello")

    def test_invoke_custom_function_name(self):
        plane = self._make_plane("def compute(x): return x * 2\n")
        result = plane.invoke_skill("test-skill", function="compute", args=(21,))
        self.assertEqual(result, 42)

    def test_invoke_with_kwargs(self):
        plane = self._make_plane("def greet(name='World'): return f'Hello {name}'\n")
        result = plane.invoke_skill("test-skill", function="greet", kwargs={"name": "OpenChimera"})
        self.assertEqual(result, "Hello OpenChimera")

    def test_invoke_missing_function_raises_attribute_error(self):
        plane = self._make_plane("VALUE = 1\n")
        with self.assertRaises(AttributeError):
            plane.invoke_skill("test-skill", function="nonexistent")

    def test_invoke_publishes_invoked_event(self):
        plane = self._make_plane("def run(): return 'ok'\n")
        plane.invoke_skill("test-skill")
        calls = [str(c) for c in plane._bus.publish.call_args_list]
        published_events = [c for c in calls if "skill.invoked" in c]
        self.assertTrue(len(published_events) >= 1)

    def test_invoke_publishes_error_event_on_exception(self):
        plane = self._make_plane("def run(): raise ValueError('boom')\n")
        with self.assertRaises(ValueError):
            plane.invoke_skill("test-skill")
        calls = [str(c) for c in plane._bus.publish.call_args_list]
        error_events = [c for c in calls if "skill.error" in c]
        self.assertTrue(len(error_events) >= 1)

    def test_invoke_unknown_skill_raises_import_error(self):
        from core.skills_plane import SkillsPlane

        plane = SkillsPlane(root=self._tmpdir, bus=MagicMock())
        patch.object(plane._registry, "list_kind", return_value=[]).start()
        with self.assertRaises(ImportError):
            plane.invoke_skill("ghost-skill")

    def test_bus_failure_does_not_crash_invoke(self):
        """If the bus raises on publish, invoke must still complete."""
        plane = self._make_plane("def run(): return 'safe'\n")
        plane._bus.publish.side_effect = RuntimeError("bus down")
        result = plane.invoke_skill("test-skill")
        self.assertEqual(result, "safe")


class TestSkillsPlaneScriptsDir(unittest.TestCase):
    """Verify load_module falls back to scripts/ subdirectory."""

    def setUp(self):
        import tempfile
        self._tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_load_from_scripts_subdir(self):
        from core.skills_plane import SkillsPlane

        skill_id = "script-skill"
        skill_dir = self._tmpdir / skill_id
        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("# script skill\n")
        (scripts_dir / "main.py").write_text("RESULT = 'scripts_subdir'\n")

        plane = SkillsPlane(root=self._tmpdir)
        fake_skills = [
            {
                "id": skill_id,
                "name": skill_id,
                "description": "",
                "category": "test",
                "path": str(skill_dir / "SKILL.md"),
                "kind": "skill",
            }
        ]
        patch.object(plane._registry, "list_kind", return_value=fake_skills).start()
        mod = plane.load_skill_module(skill_id)
        self.assertEqual(mod.RESULT, "scripts_subdir")


if __name__ == "__main__":
    unittest.main()
