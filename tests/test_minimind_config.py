from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.config import get_minimind_api_base_url, get_minimind_api_port, get_minimind_python_executable
from core.minimind_service import MiniMindService


class MiniMindConfigTests(unittest.TestCase):
    def test_minimind_runtime_config_is_resolved(self) -> None:
        self.assertEqual(get_minimind_api_port(), 8998)
        self.assertEqual(get_minimind_api_base_url(), "http://127.0.0.1:8998")
        self.assertTrue(str(get_minimind_python_executable()).lower().endswith("python.exe"))

    def test_minimind_status_includes_runtime_and_jobs(self) -> None:
        service = MiniMindService()
        status = service.status()
        self.assertIn("runtime", status)
        self.assertIn("training_jobs", status)
        self.assertIn("api_base_url", status)

    def test_training_worker_resolution_defaults_to_cpu_safe_value(self) -> None:
        service = MiniMindService()
        self.assertEqual(service._resolve_training_num_workers("cpu"), 0)

    def test_training_worker_resolution_honors_explicit_config(self) -> None:
        service = MiniMindService()
        original_profile = service.profile
        service.profile = {
            "local_runtime": {
                "reasoning_engine_config": {
                    "training_num_workers": 3,
                }
            }
        }
        try:
            self.assertEqual(service._resolve_training_num_workers("cpu"), 3)
        finally:
            service.profile = original_profile

    def test_load_training_jobs_rejects_invalid_manifest(self) -> None:
        service = MiniMindService()
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = Path(temp_dir) / "jobs.json"
            manifest_path.write_text("[]", encoding="utf-8")
            service.job_manifest_path = manifest_path
            self.assertEqual(service._load_training_jobs(), {})

    def test_load_training_jobs_accepts_dict_manifest(self) -> None:
        service = MiniMindService()
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = Path(temp_dir) / "jobs.json"
            manifest_path.write_text('{"job-1": {"status": "running"}}', encoding="utf-8")
            service.job_manifest_path = manifest_path
            self.assertEqual(service._load_training_jobs(), {"job-1": {"status": "running"}})

    def test_runtime_status_marks_stale_running_jobs_abandoned(self) -> None:
        service = MiniMindService()
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = Path(temp_dir) / "jobs.json"
            service.job_manifest_path = manifest_path
            service._training_jobs = {
                "job-1": {
                    "status": "running",
                    "pid": 999999,
                }
            }
            status = service.get_runtime_status()
            self.assertEqual(status["training"]["active_jobs"], [])
            self.assertEqual(service._training_jobs["job-1"]["status"], "abandoned")

    def test_flatten_messages_builds_plain_prompt(self) -> None:
        service = MiniMindService()
        prompt = service._flatten_messages(
            [
                {"role": "system", "content": "Be concise."},
                {"role": "user", "content": "Explain OpenChimera."},
            ]
        )
        self.assertIn("Guidance:", prompt)
        self.assertIn("User request:", prompt)

    def test_usable_response_accepts_plain_sentence(self) -> None:
        service = MiniMindService()
        self.assertTrue(service._is_usable_response("OpenChimera is a local-first orchestration runtime.", "Explain OpenChimera"))

    def test_usable_response_rejects_empty_and_repetitive_content(self) -> None:
        service = MiniMindService()
        self.assertFalse(service._is_usable_response("", "Explain OpenChimera"))
        self.assertFalse(service._is_usable_response("PPPPPPPPPPPPPPPP", "Explain OpenChimera"))
        self.assertFalse(service._is_usable_response("### :\n- \n- \n-", "Explain OpenChimera"))


if __name__ == "__main__":
    unittest.main()