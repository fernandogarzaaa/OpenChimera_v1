from __future__ import annotations

import importlib
import sys
import types
import unittest

import core.database as _database_module


class DatabaseBackendTests(unittest.TestCase):
    def test_backend_returns_string(self) -> None:
        """backend() must return a string."""
        result = _database_module.backend()
        self.assertIsInstance(result, str)

    def test_backend_returns_known_value(self) -> None:
        """backend() must return one of the two valid backend identifiers."""
        result = _database_module.backend()
        self.assertIn(result, {"rust", "python"})

    def test_backend_returns_rust_when_chimera_core_importable(self) -> None:
        """
        Simulate chimera_core.db being importable so the _BACKEND = "rust" branch
        (line 5 of core/database.py) is executed.
        """
        fake_db = types.ModuleType("chimera_core.db")
        fake_db.Database = object  # type: ignore[attr-defined]

        fake_core = types.ModuleType("chimera_core")
        fake_core.db = fake_db  # type: ignore[attr-defined]

        saved: dict[str, object] = {
            k: sys.modules.get(k)  # type: ignore[arg-type]
            for k in ("chimera_core", "chimera_core.db", "core.database")
        }
        try:
            sys.modules["chimera_core"] = fake_core
            sys.modules["chimera_core.db"] = fake_db
            sys.modules.pop("core.database", None)

            reloaded = importlib.import_module("core.database")
            self.assertEqual(reloaded.backend(), "rust")
            self.assertEqual(reloaded._BACKEND, "rust")
        finally:
            # Restore original sys.modules entries.
            for key, value in saved.items():
                if value is None:
                    sys.modules.pop(key, None)
                else:
                    sys.modules[key] = value  # type: ignore[assignment]
            # Reload the real module so subsequent tests see the original state.
            importlib.reload(_database_module)


if __name__ == "__main__":
    unittest.main()
