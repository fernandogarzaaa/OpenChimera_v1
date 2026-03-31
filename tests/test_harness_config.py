from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.config import is_supported_harness_repo_root


class HarnessConfigTests(unittest.TestCase):
    def test_supported_harness_repo_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            src = root / "src"
            src.mkdir(parents=True)
            for relative_path in [
                "main.py",
                "port_manifest.py",
                "query_engine.py",
                "commands.py",
                "tools.py",
            ]:
                (src / relative_path).write_text("# stub\n", encoding="utf-8")

            self.assertTrue(is_supported_harness_repo_root(root))

    def test_sourcemap_style_layout_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            src = root / "src"
            src.mkdir(parents=True)
            for relative_path in [
                "main.py",
                "port_manifest.py",
                "query_engine.py",
                "commands.py",
                "tools.py",
            ]:
                (src / relative_path).write_text("# stub\n", encoding="utf-8")

            (root / "extract-sources.js").write_text("// blocked\n", encoding="utf-8")

            self.assertFalse(is_supported_harness_repo_root(root))


if __name__ == "__main__":
    unittest.main()