"""Tests for core.integration — dynamic module import utility."""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import textwrap
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from core.integration import import_module_from_file


class TestImportModuleFromFile(unittest.TestCase):
    def _write_module(self, directory: Path, filename: str, content: str) -> Path:
        path = directory / filename
        path.write_text(textwrap.dedent(content), encoding="utf-8")
        return path

    def test_loads_simple_module(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = self._write_module(Path(td), "simple.py", """
                VALUE = 42
                def greet(name):
                    return f"Hello, {name}"
            """)
            mod = import_module_from_file("test_simple_dyn", path)
            self.assertEqual(mod.VALUE, 42)
            self.assertEqual(mod.greet("world"), "Hello, world")

    def test_module_is_registered_in_sys_modules(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = self._write_module(Path(td), "reg.py", "SENTINEL = 'registered'")
            import_module_from_file("test_reg_dyn_unique", path)
            self.assertIn("test_reg_dyn_unique", sys.modules)
            # Cleanup
            del sys.modules["test_reg_dyn_unique"]

    def test_file_not_found_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            import_module_from_file("nonexistent", Path("/no/such/path/file.py"))

    def test_repo_root_added_and_removed_from_sys_path(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = self._write_module(Path(td), "pathtest.py", "X = 1")
            fake_root = Path(td) / "reporoot"
            fake_root.mkdir()
            root_str = str(fake_root)
            # Ensure not already in path
            if root_str in sys.path:
                sys.path.remove(root_str)
            import_module_from_file("test_pathtest_dyn", path, repo_root=fake_root)
            # Root should be cleaned up after import
            self.assertNotIn(root_str, sys.path)
            del sys.modules["test_pathtest_dyn"]

    def test_invalid_python_raises_import_error(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = self._write_module(Path(td), "bad.py", "this is not valid python !!!")
            with self.assertRaises(SyntaxError):
                import_module_from_file("test_bad_dyn", path)

    def test_module_with_imports_runs_correctly(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = self._write_module(Path(td), "uses_os.py", """
                import os
                HOME = os.path.expanduser("~")
            """)
            mod = import_module_from_file("test_uses_os_dyn", path)
            self.assertIsInstance(mod.HOME, str)
            del sys.modules["test_uses_os_dyn"]


class TestImportModuleFromFileExtended(unittest.TestCase):
    """Additional coverage for edge cases and sys.path / sys.modules behaviour."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.tmp = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()
        for key in list(sys.modules.keys()):
            if key.startswith("_tc_"):
                del sys.modules[key]

    def _write(self, name: str, source: str) -> Path:
        path = self.tmp / f"{name}.py"
        path.write_text(textwrap.dedent(source), encoding="utf-8")
        return path

    # ------------------------------------------------------------------
    # Return-value assertions
    # ------------------------------------------------------------------

    def test_returned_object_is_module_type(self) -> None:
        path = self._write("_tc_typecheck", "X = 1")
        mod = import_module_from_file("_tc_typecheck", path)
        self.assertIsInstance(mod, types.ModuleType)

    def test_module_name_attribute_matches_given_name(self) -> None:
        path = self._write("_tc_nameattr", "X = 1")
        mod = import_module_from_file("_tc_nameattr", path)
        self.assertEqual(mod.__name__, "_tc_nameattr")

    def test_module_function_callable(self) -> None:
        path = self._write("_tc_func", "def greet(n): return f'hi {n}'")
        mod = import_module_from_file("_tc_func", path)
        self.assertEqual(mod.greet("tester"), "hi tester")

    def test_module_class_instantiable(self) -> None:
        path = self._write("_tc_cls", "class Foo:\n    val = 42")
        mod = import_module_from_file("_tc_cls", path)
        self.assertEqual(mod.Foo.val, 42)

    def test_module_list_attribute(self) -> None:
        path = self._write("_tc_list", "ITEMS = [1, 2, 3]")
        mod = import_module_from_file("_tc_list", path)
        self.assertEqual(mod.ITEMS, [1, 2, 3])

    # ------------------------------------------------------------------
    # Error cases
    # ------------------------------------------------------------------

    def test_spec_none_raises_import_error(self) -> None:
        path = self._write("_tc_nospec", "X = 1")
        with patch("importlib.util.spec_from_file_location", return_value=None):
            with self.assertRaises(ImportError):
                import_module_from_file("_tc_nospec", path)

    # ------------------------------------------------------------------
    # sys.modules management
    # ------------------------------------------------------------------

    def test_sys_modules_value_is_same_object_as_returned(self) -> None:
        path = self._write("_tc_sysmatch", "X = 99")
        mod = import_module_from_file("_tc_sysmatch", path)
        self.assertIs(sys.modules["_tc_sysmatch"], mod)

    def test_overwrites_existing_sys_modules_entry(self) -> None:
        name = "_tc_overwrite"
        dummy = types.ModuleType("dummy_placeholder")
        sys.modules[name] = dummy
        path = self._write(name, "X = 7")
        mod = import_module_from_file(name, path)
        self.assertIsNot(sys.modules[name], dummy)
        self.assertEqual(mod.X, 7)

    # ------------------------------------------------------------------
    # sys.path management
    # ------------------------------------------------------------------

    def test_without_repo_root_syspath_unchanged(self) -> None:
        path = self._write("_tc_noroot", "X = 1")
        before = list(sys.path)
        import_module_from_file("_tc_noroot", path)
        self.assertEqual(sys.path, before)

    def test_repo_root_removed_after_successful_import(self) -> None:
        path = self._write("_tc_cleanup", "X = 1")
        repo_root = self.tmp / "fakerepo"
        repo_root.mkdir()
        root_str = str(repo_root)
        if root_str in sys.path:
            sys.path.remove(root_str)
        import_module_from_file("_tc_cleanup", path, repo_root=repo_root)
        self.assertNotIn(root_str, sys.path)

    def test_repo_root_already_present_not_duplicated(self) -> None:
        path = self._write("_tc_nodup", "X = 1")
        repo_root = self.tmp / "fakerepo2"
        repo_root.mkdir()
        root_str = str(repo_root)
        if root_str not in sys.path:
            sys.path.insert(0, root_str)
        count_before = sys.path.count(root_str)
        import_module_from_file("_tc_nodup", path, repo_root=repo_root)
        self.assertEqual(sys.path.count(root_str), count_before)
        while root_str in sys.path:
            sys.path.remove(root_str)

    def test_repo_root_already_present_not_removed_after(self) -> None:
        """Pre-existing repo_root entry must survive the call."""
        path = self._write("_tc_preexist", "X = 1")
        repo_root = self.tmp / "fakerepo3"
        repo_root.mkdir()
        root_str = str(repo_root)
        if root_str not in sys.path:
            sys.path.insert(0, root_str)
        import_module_from_file("_tc_preexist", path, repo_root=repo_root)
        self.assertIn(root_str, sys.path)
        while root_str in sys.path:
            sys.path.remove(root_str)

    def test_accepts_string_for_file_path(self) -> None:
        path = self._write("_tc_strpath", "X = 55")
        mod = import_module_from_file("_tc_strpath", str(path))
        self.assertEqual(mod.X, 55)


if __name__ == "__main__":
    unittest.main()
