"""
Regression test: _database_path() and _backup_root() must resolve under ROOT,
not under the module file's parent directory.

When OpenChimera is installed as a wheel, `Path(run.__file__).parent` resolves
to the site-packages directory, not the user's workspace root. These functions
must use ROOT from core.config instead.
"""
from __future__ import annotations

import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


def _import_run_module() -> types.ModuleType:
    if "run" in sys.modules:
        return sys.modules["run"]
    import run as _run
    return _run


class TestInstallerPathResolution(unittest.TestCase):
    def test_database_path_is_under_root_not_module_dir(self) -> None:
        """_database_path() must return a path under core.config.ROOT."""
        import run as _run
        from core.config import ROOT

        db_path = _run._database_path()

        self.assertTrue(
            str(db_path).startswith(str(ROOT)),
            f"_database_path() returned {db_path} but expected a path under ROOT={ROOT}",
        )

        # When run.py is installed outside ROOT (i.e. in site-packages), its
        # parent dir must NOT match ROOT.  Only assert divergence when they differ.
        module_dir = Path(_run.__file__).resolve().parent
        if module_dir != ROOT:
            self.assertFalse(
                str(db_path).startswith(str(module_dir)),
                f"_database_path() resolved under module dir {module_dir} "
                f"instead of ROOT {ROOT}.",
            )

    def test_backup_root_is_under_root_not_module_dir(self) -> None:
        """_backup_root() must return a path under core.config.ROOT."""
        import run as _run
        from core.config import ROOT

        backup_path = _run._backup_root()

        self.assertTrue(
            str(backup_path).startswith(str(ROOT)),
            f"_backup_root() returned {backup_path} but expected a path under ROOT={ROOT}",
        )

        module_dir = Path(_run.__file__).resolve().parent
        if module_dir != ROOT:
            self.assertFalse(
                str(backup_path).startswith(str(module_dir)),
                f"_backup_root() resolved under module dir {module_dir} "
                f"instead of ROOT {ROOT}.",
            )

    def test_database_path_uses_explicit_override(self) -> None:
        """When a path is passed explicitly, it must be used as-is."""
        import run as _run

        explicit = Path("/tmp/custom.db")
        result = _run._database_path(explicit)
        self.assertEqual(result, explicit)

    def test_backup_root_uses_explicit_override(self) -> None:
        """When a path is passed explicitly, it must be used as-is."""
        import run as _run

        explicit = Path("/tmp/backups")
        result = _run._backup_root(explicit)
        self.assertEqual(result, explicit)

    def test_database_path_simulates_site_packages_install(self) -> None:
        """
        Simulate installed-package path: patch __file__ on the run module to a
        fake site-packages location, then confirm _database_path() still resolves
        under ROOT (not the fake site-packages dir).
        """
        import run as _run
        from core.config import ROOT

        fake_site_packages = Path("C:/fake/site-packages/run.py")

        with patch.object(_run, "__file__", str(fake_site_packages)):
            db_path = _run._database_path()

        self.assertFalse(
            str(db_path).startswith(str(fake_site_packages.parent)),
            f"_database_path() used __file__ parent ({fake_site_packages.parent}) "
            f"instead of ROOT when installed as a package.",
        )
        self.assertTrue(
            str(db_path).startswith(str(ROOT)),
            f"Expected path under ROOT={ROOT}, got {db_path}",
        )


if __name__ == "__main__":
    unittest.main()
