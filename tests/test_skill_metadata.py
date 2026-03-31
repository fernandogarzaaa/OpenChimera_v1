from __future__ import annotations

import unittest
from pathlib import Path


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