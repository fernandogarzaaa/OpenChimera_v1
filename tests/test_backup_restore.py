from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.database import DatabaseManager
from core.credential_store import CredentialStore
from run import _backup_create_payload, _backup_list_payload, _backup_restore_payload, _doctor_payload


class BackupRestoreTests(unittest.TestCase):
    def test_backup_create_list_and_restore_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            database_path = root / "openchimera.db"
            backup_root = root / "backups"

            store = CredentialStore(database_path=database_path)
            store.set_provider_credential("openai", "OPENAI_API_KEY", "sk-initial")

            created = _backup_create_payload(database_path=database_path, backup_root=backup_root)
            self.assertEqual(created["status"], "ok")

            store.set_provider_credential("openai", "OPENAI_API_KEY", "sk-updated")
            restored = _backup_restore_payload(created["backup"]["file"], database_path=database_path, backup_root=backup_root)
            self.assertEqual(restored["status"], "ok")

            reloaded = CredentialStore(database_path=database_path)
            self.assertEqual(reloaded.get_provider_credentials("openai")["OPENAI_API_KEY"], "sk-initial")

            listed = _backup_list_payload(backup_root=backup_root)
            self.assertEqual(listed["count"], 1)
            self.assertEqual(listed["backups"][0]["file"], created["backup"]["file"])

    def test_doctor_payload_reports_database_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "openchimera.db"
            DatabaseManager(db_path=database_path).initialize()

            payload = _doctor_payload(production=True, database_path=database_path)

            self.assertIn("database", payload)
            self.assertTrue(payload["production"]["checks"]["database_available"])
            self.assertTrue(payload["production"]["checks"]["migrations_applied"])


if __name__ == "__main__":
    unittest.main()