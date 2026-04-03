from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from core.credential_store import CredentialStore
from core.model_registry import ModelRegistry
from core.resilience import retry_call
from core.transactions import atomic_write_json, atomic_write_jsonl


class ResilienceTests(unittest.TestCase):
    def test_retry_call_retries_then_succeeds(self) -> None:
        attempts = {"count": 0}

        def flaky() -> str:
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise OSError("temporary")
            return "ok"

        result = retry_call(flaky, attempts=3, delay_seconds=0.0, retry_exceptions=(OSError,))
        self.assertEqual(result, "ok")
        self.assertEqual(attempts["count"], 3)

    def test_atomic_write_json_and_jsonl_replace_contents(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            json_path = root / "state.json"
            jsonl_path = root / "events.jsonl"

            atomic_write_json(json_path, {"status": "ok", "count": 2})
            atomic_write_jsonl(jsonl_path, [{"id": 1}, {"id": 2}])

            self.assertEqual(json.loads(json_path.read_text(encoding="utf-8"))["count"], 2)
            lines = jsonl_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            self.assertEqual(json.loads(lines[1])["id"], 2)

    def test_credential_store_persists_provider_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = CredentialStore(store_path=Path(temp_dir) / "credentials.json")
            saved = store.set_provider_credential("openai", "OPENAI_API_KEY", "sk-test-123456")
            self.assertTrue(saved["configured"])
            self.assertTrue(store.has_provider_credentials("openai", ["OPENAI_API_KEY"]))
            self.assertEqual(store.get_provider_credentials("openai")["OPENAI_API_KEY"], "sk-test-123456")

    def test_model_registry_refresh_writes_registry_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = ModelRegistry()
            registry.registry_path = Path(temp_dir) / "model_registry.json"
            registry.profile = {
                "hardware": {
                    "cpu_count": 8,
                    "ram_gb": 16,
                    "gpu": {"available": True, "name": "RTX 2060", "vram_gb": 6, "device_count": 1},
                },
                "model_inventory": {"available_models": ["phi-3.5-mini"], "models_dir": temp_dir},
                "local_runtime": {},
            }
            payload = registry.refresh()
            on_disk = json.loads(registry.registry_path.read_text(encoding="utf-8"))
            self.assertEqual(on_disk["generated_at"], payload["generated_at"])
            self.assertEqual(on_disk["providers"][0]["id"], payload["providers"][0]["id"])


if __name__ == "__main__":
    unittest.main()