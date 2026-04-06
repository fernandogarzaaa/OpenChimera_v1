from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.config import get_minimind_api_base_url, get_minimind_api_port, get_minimind_python_executable
from core.minimind_service import MiniMindService


class MiniMindConfigTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32", "Windows-only: python executable is python.exe")
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


    def test_reasoning_completion_returns_error_when_api_unhealthy(self) -> None:
        service = MiniMindService()
        # _api_is_healthy() will return False because the server is not running
        result = service.reasoning_completion(
            [{"role": "user", "content": "Hello"}]
        )
        self.assertEqual(result["content"], "")
        self.assertEqual(result["model"], "minimind")
        self.assertIsNotNone(result["error"])

    def test_start_server_returns_error_when_workspace_unavailable(self) -> None:
        service = MiniMindService()
        service.available = False
        result = service.start_server()
        self.assertEqual(result["status"], "error")
        self.assertIn("error", result)

    def test_stop_training_job_not_in_processes_returns_not_running(self) -> None:
        service = MiniMindService()
        result = service.stop_training_job("ghost-job-id")
        self.assertEqual(result["status"], "not-running")
        self.assertEqual(result["job_id"], "ghost-job-id")

    def test_start_training_job_unavailable_returns_error(self) -> None:
        service = MiniMindService()
        service.available = False
        result = service.start_training_job(mode="reason_sft")
        self.assertEqual(result["status"], "error")

    def test_start_training_job_missing_dataset_manifest_returns_error(self) -> None:
        service = MiniMindService()
        service.available = True
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            service.training_output_dir = Path(tmpdir)
            result = service.start_training_job(mode="reason_sft")
            self.assertEqual(result["status"], "error")
            self.assertIn("manifest", result["error"].lower())

    def test_stop_server_when_not_running_returns_not_running(self) -> None:
        service = MiniMindService()
        result = service.stop_server()
        self.assertEqual(result["status"], "not-running")

    def test_collect_weight_files_returns_empty_for_missing_dir(self) -> None:
        service = MiniMindService()
        result = service._collect_weight_files(Path("/nonexistent/checkpoints"))
        self.assertEqual(result, [])

    def test_collect_jsonl_files_returns_empty_for_missing_dir(self) -> None:
        service = MiniMindService()
        result = service._collect_jsonl_files(Path("/nonexistent/dataset"))
        self.assertEqual(result, [])

    def test_collect_weight_files_returns_sorted_pth_files(self) -> None:
        service = MiniMindService()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "model_b.pth").write_bytes(b"")
            (root / "model_a.pth").write_bytes(b"")
            (root / "readme.txt").write_bytes(b"")
            result = service._collect_weight_files(root)
            self.assertEqual(len(result), 2)
            self.assertIn("model_a.pth", result[0])
            # .txt must be excluded
            self.assertFalse(any("readme" in p for p in result))

    def test_collect_jsonl_files_returns_sorted_jsonl_files(self) -> None:
        service = MiniMindService()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "dataset_b.jsonl").write_bytes(b"")
            (root / "dataset_a.jsonl").write_bytes(b"")
            result = service._collect_jsonl_files(root)
            self.assertEqual(len(result), 2)
            self.assertIn("dataset_a.jsonl", result[0])

    def test_build_inference_messages_simplified_returns_single_user_message(self) -> None:
        service = MiniMindService()
        original = [{"role": "system", "content": "Be concise."}, {"role": "user", "content": "Hello?"}]
        prompt = service._flatten_messages(original)
        result = service._build_inference_messages(original, prompt, simplified=True)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["role"], "user")
        self.assertIn("plain text", result[0]["content"])

    def test_build_inference_messages_not_simplified_strips_system(self) -> None:
        service = MiniMindService()
        original = [{"role": "system", "content": "Be concise."}, {"role": "user", "content": "Hello?"}]
        prompt = service._flatten_messages(original)
        result = service._build_inference_messages(original, prompt, simplified=False)
        roles = [m["role"] for m in result]
        self.assertNotIn("system", roles)
        self.assertIn("user", roles)

    def test_sanitize_generated_content_strips_code_fences(self) -> None:
        service = MiniMindService()
        raw = "```python\ndef hello():\n    pass\n```"
        result = service._sanitize_generated_content(raw)
        self.assertNotIn("```", result)

    def test_reasoning_config_returns_dict(self) -> None:
        service = MiniMindService()
        result = service._reasoning_config()
        self.assertIsInstance(result, dict)

    def test_build_runtime_summary_contains_root_mention(self) -> None:
        service = MiniMindService()
        identity = {"root": "/tmp/openchimera", "hardware": {}, "local_runtime": {}, "model_inventory": {}, "integration_roots": {}}
        result = service._build_runtime_summary(identity)
        self.assertIn("/tmp/openchimera", result)
        self.assertIsInstance(result, str)

    def test_build_training_strategy_contains_commands_and_tools(self) -> None:
        service = MiniMindService()
        harness_status = {"commands": [{"name": "cmd-a"}, {"name": "cmd-b"}], "tools": [{"name": "tool-x"}]}
        result = service._build_training_strategy(harness_status, {})
        self.assertIn("cmd-a", result)
        self.assertIn("tool-x", result)

    def test_build_training_strategy_empty_harness_uses_none(self) -> None:
        service = MiniMindService()
        result = service._build_training_strategy({}, {})
        self.assertIn("none", result)


class MiniMindInternalTests(unittest.TestCase):
    def test_pid_is_running_zero_returns_false(self) -> None:
        service = MiniMindService()
        self.assertFalse(service._pid_is_running(0))
        self.assertFalse(service._pid_is_running(-1))

    def test_api_is_healthy_returns_false_when_server_not_running(self) -> None:
        service = MiniMindService()
        self.assertFalse(service._api_is_healthy())

    def test_api_is_healthy_returns_false_when_get_json_fails(self) -> None:
        service = MiniMindService()
        with patch.object(service, "_is_server_running", return_value=True):
            with patch.object(service, "_get_json", side_effect=OSError("connection refused")):
                self.assertFalse(service._api_is_healthy())

    def test_api_is_healthy_returns_true_when_get_json_succeeds(self) -> None:
        service = MiniMindService()
        with patch.object(service, "_is_server_running", return_value=True):
            with patch.object(service, "_get_json", return_value={"openapi": "3.0.0"}):
                self.assertTrue(service._api_is_healthy())

    def test_sanitize_record_replaces_anthropic_brand_names(self) -> None:
        service = MiniMindService()
        record = {"text": "Claude Code is built by Anthropic."}
        result = service._sanitize_record(record)
        self.assertNotIn("Claude", result["text"])
        self.assertNotIn("Anthropic", result["text"])

    def test_finalize_training_job_marks_job_completed_on_zero_returncode(self) -> None:
        service = MiniMindService()
        service._training_jobs = {"job-1": {"status": "running"}}
        with tempfile.TemporaryDirectory() as tmpdir:
            service.training_output_dir = Path(tmpdir)
            service.job_manifest_path = Path(tmpdir) / "jobs.json"
            service._finalize_training_job("job-1", returncode=0)
            self.assertEqual(service._training_jobs["job-1"]["status"], "completed")

    def test_finalize_training_job_marks_job_failed_on_nonzero_returncode(self) -> None:
        service = MiniMindService()
        service._training_jobs = {"job-1": {"status": "running"}}
        with tempfile.TemporaryDirectory() as tmpdir:
            service.training_output_dir = Path(tmpdir)
            service.job_manifest_path = Path(tmpdir) / "jobs.json"
            service._finalize_training_job("job-1", returncode=1)
            self.assertEqual(service._training_jobs["job-1"]["status"], "failed")

    def test_finalize_training_job_marks_stopped_when_forced(self) -> None:
        service = MiniMindService()
        service._training_jobs = {"job-1": {"status": "running"}}
        with tempfile.TemporaryDirectory() as tmpdir:
            service.training_output_dir = Path(tmpdir)
            service.job_manifest_path = Path(tmpdir) / "jobs.json"
            service._finalize_training_job("job-1", returncode=1, forced=True)
            self.assertEqual(service._training_jobs["job-1"]["status"], "stopped")

    def test_finalize_training_job_ignores_missing_job(self) -> None:
        service = MiniMindService()
        service._training_jobs = {}
        with tempfile.TemporaryDirectory() as tmpdir:
            service.training_output_dir = Path(tmpdir)
            service.job_manifest_path = Path(tmpdir) / "jobs.json"
            service._finalize_training_job("nonexistent", returncode=0)  # should not raise

    def test_write_runtime_manifest_creates_file(self) -> None:
        service = MiniMindService()
        with tempfile.TemporaryDirectory() as tmpdir:
            service.training_output_dir = Path(tmpdir)
            service.runtime_manifest_path = Path(tmpdir) / "runtime.json"
            service._write_runtime_manifest()
            self.assertTrue(service.runtime_manifest_path.exists())

    def test_load_training_jobs_returns_empty_when_file_missing(self) -> None:
        service = MiniMindService()
        with tempfile.TemporaryDirectory() as tmpdir:
            service.job_manifest_path = Path(tmpdir) / "nonexistent.json"
            self.assertEqual(service._load_training_jobs(), {})

    def test_load_training_jobs_returns_empty_for_malformed_json(self) -> None:
        service = MiniMindService()
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = Path(tmpdir) / "jobs.json"
            manifest.write_text("{bad json", encoding="utf-8")
            service.job_manifest_path = manifest
            self.assertEqual(service._load_training_jobs(), {})

    def test_reasoning_completion_uses_api_when_healthy(self) -> None:
        service = MiniMindService()
        good_response = {"choices": [{"message": {"content": "OpenChimera provides local LLM orchestration."}}], "model": "minimind"}
        with patch.object(service, "_api_is_healthy", return_value=True):
            with patch.object(service, "_post_json", return_value=good_response):
                result = service.reasoning_completion([{"role": "user", "content": "Explain OpenChimera."}])
                self.assertEqual(result["model"], "minimind")
                self.assertIsNone(result["error"])
                self.assertIn("OpenChimera", result["content"])

    def test_reasoning_completion_returns_error_when_post_fails(self) -> None:
        service = MiniMindService()
        with patch.object(service, "_api_is_healthy", return_value=True):
            with patch.object(service, "_post_json", side_effect=OSError("timeout")):
                result = service.reasoning_completion([{"role": "user", "content": "Hello"}])
                self.assertNotEqual(result["content"], "OpenChimera")
                self.assertIsNotNone(result["error"])

    def test_resolve_device_returns_cpu_when_config_is_cpu(self) -> None:
        service = MiniMindService()
        service.profile = {"local_runtime": {"reasoning_engine_config": {"device": "cpu"}}}
        result = service._resolve_device()
        self.assertEqual(result, "cpu")


if __name__ == "__main__":
    unittest.main()


# ============================================================
# START SERVER coverage tests
# ============================================================

class MiniMindStartServerCoverageTests(unittest.TestCase):
    def _setup_root(self, tmpdir: str) -> Path:
        root = Path(tmpdir)
        scripts_dir = root / "scripts"
        scripts_dir.mkdir(parents=True)
        (scripts_dir / "serve_openai_api.py").write_text("# stub")
        return root

    def test_start_server_already_running_returns_already_running(self) -> None:
        service = MiniMindService()
        service.available = True
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.pid = 1234
        service._server_process = mock_proc
        result = service.start_server()
        self.assertEqual(result["status"], "already-running")
        self.assertEqual(result["pid"], 1234)

    def test_start_server_missing_api_script_returns_error(self) -> None:
        service = MiniMindService()
        service.available = True
        with patch.object(service, "_is_server_running", return_value=False):
            with tempfile.TemporaryDirectory() as tmpdir:
                service.root = Path(tmpdir)
                result = service.start_server()
        self.assertEqual(result["status"], "error")
        self.assertIn("script", result["error"].lower())

    def test_start_server_missing_python_executable_returns_error(self) -> None:
        service = MiniMindService()
        service.available = True
        with patch.object(service, "_is_server_running", return_value=False):
            with tempfile.TemporaryDirectory() as tmpdir:
                root = self._setup_root(tmpdir)
                service.root = root
                service.python_executable = Path(tmpdir) / "nonexistent_python.exe"
                result = service.start_server()
        self.assertEqual(result["status"], "error")
        self.assertIn("python", result["error"].lower())

    def test_start_server_preflight_error_returns_error(self) -> None:
        service = MiniMindService()
        service.available = True
        with patch.object(service, "_is_server_running", return_value=False):
            with patch.object(service, "_check_python_modules", return_value="Missing module: torch"):
                with tempfile.TemporaryDirectory() as tmpdir:
                    root = self._setup_root(tmpdir)
                    service.root = root
                    result = service.start_server()
        self.assertEqual(result["status"], "error")
        self.assertIn("torch", result["error"])

    def test_start_server_oserror_from_popen_returns_error(self) -> None:
        service = MiniMindService()
        service.available = True
        with patch.object(service, "_is_server_running", return_value=False):
            with patch.object(service, "_check_python_modules", return_value=None):
                with tempfile.TemporaryDirectory() as tmpdir:
                    root = self._setup_root(tmpdir)
                    service.root = root
                    service.log_dir = root / "logs"
                    service.training_output_dir = root / "training"
                    with patch("subprocess.Popen", side_effect=OSError("spawn failed")):
                        result = service.start_server()
        self.assertEqual(result["status"], "error")
        self.assertIn("spawn failed", result["error"])

    def test_start_server_success_path(self) -> None:
        service = MiniMindService()
        service.available = True
        with patch.object(service, "_is_server_running", return_value=False):
            with patch.object(service, "_check_python_modules", return_value=None):
                with tempfile.TemporaryDirectory() as tmpdir:
                    root = self._setup_root(tmpdir)
                    service.root = root
                    service.log_dir = root / "logs"
                    service.training_output_dir = root / "training"
                    service.runtime_manifest_path = root / "training" / "runtime.json"
                    service.job_manifest_path = root / "training" / "jobs.json"
                    mock_proc = MagicMock()
                    mock_proc.pid = 9876
                    mock_proc.poll.return_value = None
                    with patch("subprocess.Popen", return_value=mock_proc):
                        with patch.object(service, "_write_runtime_manifest"):
                            result = service.start_server()
        self.assertEqual(result["status"], "started")
        self.assertEqual(result["pid"], 9876)
        self.assertIn("api_base_url", result)
        self.assertIn("log_path", result)


class MiniMindStopServerCoverageTests(unittest.TestCase):
    def test_stop_server_timeout_triggers_kill_and_returns_stopped(self) -> None:
        import subprocess as _subprocess
        service = MiniMindService()
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_proc.terminate.return_value = None
        mock_proc.wait.side_effect = [_subprocess.TimeoutExpired(cmd=["py"], timeout=15), None]
        service._server_process = mock_proc
        with patch.object(service, "_write_runtime_manifest"):
            result = service.stop_server()
        self.assertEqual(result["status"], "stopped")
        mock_proc.kill.assert_called_once()


# ============================================================
# START / STOP TRAINING JOB coverage tests
# ============================================================

class MiniMindTrainingJobCoverageTests(unittest.TestCase):
    def _make_training_env(self, tmpdir: str) -> tuple:
        root = Path(tmpdir)
        trainer_dir = root / "trainer"
        trainer_dir.mkdir(parents=True)
        (trainer_dir / "train_reason.py").write_text("# stub")
        (trainer_dir / "train_pretrain.py").write_text("# stub")
        output_dir = root / "training_output"
        output_dir.mkdir(parents=True)
        (output_dir / "harness_openchimera_dataset_manifest.json").write_text("{}")
        (output_dir / "harness_openchimera_sft.jsonl").write_text("{}\n")
        (output_dir / "harness_openchimera_pretrain.jsonl").write_text("{}\n")
        return root, output_dir

    def test_start_training_job_unsupported_mode_returns_error(self) -> None:
        service = MiniMindService()
        service.available = True
        with tempfile.TemporaryDirectory() as tmpdir:
            root, output_dir = self._make_training_env(tmpdir)
            service.root = root
            service.training_output_dir = output_dir
            result = service.start_training_job(mode="unsupported_mode")
        self.assertEqual(result["status"], "error")
        self.assertIn("Unsupported", result["error"])

    def test_start_training_job_missing_script_returns_error(self) -> None:
        service = MiniMindService()
        service.available = True
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_dir = root / "training_output"
            output_dir.mkdir(parents=True)
            (output_dir / "harness_openchimera_dataset_manifest.json").write_text("{}")
            (output_dir / "harness_openchimera_sft.jsonl").write_text("{}\n")
            service.root = root
            service.training_output_dir = output_dir
            result = service.start_training_job(mode="reason_sft")
        self.assertEqual(result["status"], "error")
        self.assertIn("Missing training inputs", result["error"])

    def test_start_training_job_preflight_error_returns_error(self) -> None:
        service = MiniMindService()
        service.available = True
        with patch.object(service, "_check_python_modules", return_value="missing torch"):
            with patch.object(service, "_reasoning_config", return_value={"training_from_weight": "none"}):
                with tempfile.TemporaryDirectory() as tmpdir:
                    root, output_dir = self._make_training_env(tmpdir)
                    service.root = root
                    service.training_output_dir = output_dir
                    result = service.start_training_job(mode="reason_sft")
        self.assertEqual(result["status"], "error")
        self.assertIn("torch", result["error"])

    def test_start_training_job_success_reason_sft(self) -> None:
        service = MiniMindService()
        service.available = True
        with patch.object(service, "_check_python_modules", return_value=None):
            with patch.object(service, "_reasoning_config", return_value={"training_from_weight": "none"}):
                with patch.object(service, "_resolve_device", return_value="cpu"):
                    with tempfile.TemporaryDirectory() as tmpdir:
                        root, output_dir = self._make_training_env(tmpdir)
                        service.root = root
                        service.training_output_dir = output_dir
                        service.job_manifest_path = output_dir / "jobs.json"
                        service.log_dir = root / "logs"
                        mock_proc = MagicMock()
                        mock_proc.pid = 5555
                        mock_proc.poll.return_value = None
                        with patch("subprocess.Popen", return_value=mock_proc):
                            result = service.start_training_job(mode="reason_sft")
        self.assertEqual(result["status"], "running")
        self.assertEqual(result["mode"], "reason_sft")
        self.assertIn("job_id", result)
        self.assertEqual(result["pid"], 5555)

    def test_start_training_job_success_pretrain_mode(self) -> None:
        service = MiniMindService()
        service.available = True
        with patch.object(service, "_check_python_modules", return_value=None):
            with patch.object(service, "_reasoning_config", return_value={"training_from_weight": "none"}):
                with patch.object(service, "_resolve_device", return_value="cpu"):
                    with tempfile.TemporaryDirectory() as tmpdir:
                        root, output_dir = self._make_training_env(tmpdir)
                        service.root = root
                        service.training_output_dir = output_dir
                        service.job_manifest_path = output_dir / "jobs.json"
                        service.log_dir = root / "logs"
                        mock_proc = MagicMock()
                        mock_proc.pid = 6666
                        mock_proc.poll.return_value = None
                        with patch("subprocess.Popen", return_value=mock_proc):
                            result = service.start_training_job(mode="pretrain")
        self.assertEqual(result["status"], "running")
        self.assertEqual(result["mode"], "pretrain")

    def test_start_training_job_oserror_from_popen_returns_error(self) -> None:
        service = MiniMindService()
        service.available = True
        with patch.object(service, "_check_python_modules", return_value=None):
            with patch.object(service, "_reasoning_config", return_value={"training_from_weight": "none"}):
                with patch.object(service, "_resolve_device", return_value="cpu"):
                    with tempfile.TemporaryDirectory() as tmpdir:
                        root, output_dir = self._make_training_env(tmpdir)
                        service.root = root
                        service.training_output_dir = output_dir
                        service.job_manifest_path = output_dir / "jobs.json"
                        service.log_dir = root / "logs"
                        with patch("subprocess.Popen", side_effect=OSError("spawn error")):
                            result = service.start_training_job(mode="reason_sft")
        self.assertEqual(result["status"], "error")
        self.assertIn("spawn error", result["error"])

    def test_stop_training_job_timeout_triggers_kill(self) -> None:
        import subprocess as _subprocess
        service = MiniMindService()
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.terminate.return_value = None
        mock_proc.wait.side_effect = [_subprocess.TimeoutExpired(cmd=["py"], timeout=15), None]
        service._training_processes = {"job-x": mock_proc}
        service._training_jobs = {"job-x": {"status": "running", "pid": 1111}}
        with tempfile.TemporaryDirectory() as tmpdir:
            service.training_output_dir = Path(tmpdir)
            service.job_manifest_path = Path(tmpdir) / "jobs.json"
            result = service.stop_training_job("job-x")
        self.assertEqual(result["status"], "stopped")
        mock_proc.kill.assert_called_once()


# ============================================================
# DATASET BUILD coverage tests
# ============================================================

class MiniMindDatasetCoverageTests(unittest.TestCase):
    def _make_harness_port(self) -> MagicMock:
        mock_port = MagicMock()
        mock_port.status.return_value = {
            "commands": [{"name": "cmd-a"}],
            "tools": [{"name": "tool-x"}],
            "summary": "Harness summary.",
        }
        mock_port.root = Path("/tmp/mock_harness")
        mock_port.build_sft_examples.return_value = [
            {
                "conversations": [
                    {"role": "user", "content": "Hello harness"},
                    {"role": "assistant", "content": "Harness response"},
                ]
            }
        ]
        return mock_port

    def _identity(self) -> dict:
        return {
            "root": "/tmp/oc",
            "hardware": {"cpu_count": 4, "ram_gb": 16, "gpu": {"name": "none", "vram_gb": 0}},
            "local_runtime": {"preferred_local_models": []},
            "model_inventory": {"available_models": []},
            "integration_roots": {"harness_repo": "/tmp/h", "minimind": "/tmp/m"},
            "reasoning_engine": "minimind",
        }

    def test_build_training_dataset_creates_manifest(self) -> None:
        service = MiniMindService()
        with patch.object(service, "_resolve_device", return_value="cpu"):
            with tempfile.TemporaryDirectory() as tmpdir:
                service.training_output_dir = Path(tmpdir)
                service.runtime_manifest_path = Path(tmpdir) / "runtime.json"
                service.job_manifest_path = Path(tmpdir) / "jobs.json"
                result = service.build_training_dataset(self._make_harness_port(), self._identity(), force=True)
        self.assertIn("files", result)
        self.assertIn("counts", result)
        self.assertGreater(result["counts"]["sft_records"], 0)
        self.assertGreater(result["counts"]["pretrain_records"], 0)

    def test_build_training_dataset_skips_write_when_files_exist_and_not_force(self) -> None:
        service = MiniMindService()
        with patch.object(service, "_resolve_device", return_value="cpu"):
            with tempfile.TemporaryDirectory() as tmpdir:
                service.training_output_dir = Path(tmpdir)
                service.runtime_manifest_path = Path(tmpdir) / "runtime.json"
                service.job_manifest_path = Path(tmpdir) / "jobs.json"
                service.build_training_dataset(self._make_harness_port(), self._identity(), force=True)
                result = service.build_training_dataset(self._make_harness_port(), self._identity(), force=False)
        self.assertIn("files", result)

    def test_build_sft_records_returns_list_with_conversations(self) -> None:
        service = MiniMindService()
        with patch.object(service, "_resolve_device", return_value="cpu"):
            with tempfile.TemporaryDirectory() as tmpdir:
                service.training_output_dir = Path(tmpdir)
                service.runtime_manifest_path = Path(tmpdir) / "runtime.json"
                service.job_manifest_path = Path(tmpdir) / "jobs.json"
                records = service._build_sft_records(self._make_harness_port(), self._identity())
        self.assertIsInstance(records, list)
        self.assertTrue(all("conversations" in r for r in records))

    def test_build_pretrain_records_returns_list_with_text(self) -> None:
        service = MiniMindService()
        with patch.object(service, "_resolve_device", return_value="cpu"):
            with tempfile.TemporaryDirectory() as tmpdir:
                service.training_output_dir = Path(tmpdir)
                service.runtime_manifest_path = Path(tmpdir) / "runtime.json"
                service.job_manifest_path = Path(tmpdir) / "jobs.json"
                records = service._build_pretrain_records(self._make_harness_port(), self._identity())
        self.assertIsInstance(records, list)
        self.assertTrue(all("text" in r for r in records))

    def test_build_checkpoint_summary_contains_keyword(self) -> None:
        service = MiniMindService()
        with patch.object(service, "_resolve_device", return_value="cpu"):
            with tempfile.TemporaryDirectory() as tmpdir:
                service.training_output_dir = Path(tmpdir)
                service.runtime_manifest_path = Path(tmpdir) / "runtime.json"
                service.job_manifest_path = Path(tmpdir) / "jobs.json"
                service.root = Path(tmpdir)
                result = service._build_checkpoint_summary()
        self.assertIn("checkpoints", result.lower())

    def test_write_jsonl_creates_file_and_sanitizes_content(self) -> None:
        service = MiniMindService()
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "data.jsonl"
            service._write_jsonl(out_path, [{"text": "Claude Code is great. Anthropic made it."}])
            self.assertTrue(out_path.exists())
            content = out_path.read_text(encoding="utf-8")
            self.assertIn("Upstream Harness", content)
            self.assertNotIn("Anthropic", content)


# ============================================================
# DEVICE / WORKER / MODULE coverage tests
# ============================================================

class MiniMindDeviceCoverageTests(unittest.TestCase):
    def test_resolve_device_returns_cuda_when_torch_available(self) -> None:
        service = MiniMindService()
        service.profile = {"local_runtime": {"reasoning_engine_config": {"device": "cuda:0"}}}
        mock_result = MagicMock()
        mock_result.stdout = "1\n"
        with patch("subprocess.run", return_value=mock_result):
            device = service._resolve_device()
        self.assertEqual(device, "cuda:0")

    def test_resolve_device_returns_cpu_when_torch_unavailable(self) -> None:
        service = MiniMindService()
        service.profile = {"local_runtime": {"reasoning_engine_config": {"device": "cuda:0"}}}
        mock_result = MagicMock()
        mock_result.stdout = "0\n"
        with patch("subprocess.run", return_value=mock_result):
            device = service._resolve_device()
        self.assertEqual(device, "cpu")

    def test_resolve_device_returns_cpu_on_oserror(self) -> None:
        service = MiniMindService()
        service.profile = {"local_runtime": {"reasoning_engine_config": {"device": "cuda:0"}}}
        with patch("subprocess.run", side_effect=OSError("no python")):
            device = service._resolve_device()
        self.assertEqual(device, "cpu")

    def test_resolve_device_returns_cpu_on_timeout(self) -> None:
        import subprocess as _subprocess
        service = MiniMindService()
        service.profile = {"local_runtime": {"reasoning_engine_config": {"device": "cuda:0"}}}
        with patch("subprocess.run", side_effect=_subprocess.TimeoutExpired(cmd=["py"], timeout=30)):
            device = service._resolve_device()
        self.assertEqual(device, "cpu")

    def test_resolve_training_num_workers_invalid_config_returns_zero(self) -> None:
        service = MiniMindService()
        service.profile = {"local_runtime": {"reasoning_engine_config": {"training_num_workers": "bad"}}}
        result = service._resolve_training_num_workers("cpu")
        self.assertEqual(result, 0)

    def test_resolve_training_num_workers_cuda_defaults_to_two(self) -> None:
        service = MiniMindService()
        service.profile = {"local_runtime": {"reasoning_engine_config": {}}}
        result = service._resolve_training_num_workers("cuda:0")
        self.assertEqual(result, 2)

    def test_check_python_modules_returns_error_on_missing_module(self) -> None:
        service = MiniMindService()
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "torch"
        mock_result.stderr = ""
        with patch("subprocess.run", return_value=mock_result):
            error = service._check_python_modules(["torch"])
        self.assertIsNotNone(error)
        self.assertIn("torch", error)

    def test_check_python_modules_returns_error_on_nonzero_returncode(self) -> None:
        service = MiniMindService()
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "subprocess failed"
        with patch("subprocess.run", return_value=mock_result):
            error = service._check_python_modules(["torch"])
        self.assertIsNotNone(error)

    def test_check_python_modules_returns_error_on_oserror(self) -> None:
        service = MiniMindService()
        with patch("subprocess.run", side_effect=OSError("no exec")):
            error = service._check_python_modules(["torch"])
        self.assertIsNotNone(error)
        self.assertIn("no exec", error)


# ============================================================
# REASONING COMPLETION retry coverage tests
# ============================================================

class MiniMindReasoningCoveragTests(unittest.TestCase):
    def test_reasoning_completion_exhausts_all_retries_when_bad_content(self) -> None:
        service = MiniMindService()
        bad_response = {
            "choices": [{"message": {"content": "### :\n- \n- "}}],
            "model": "minimind",
        }
        with patch.object(service, "_api_is_healthy", return_value=True):
            with patch.object(service, "_post_json", return_value=bad_response):
                result = service.reasoning_completion([{"role": "user", "content": "Hello"}])
        self.assertEqual(result["content"], "")
        self.assertIsNotNone(result["error"])

    def test_reasoning_completion_succeeds_on_second_attempt(self) -> None:
        service = MiniMindService()
        bad_response = {"choices": [{"message": {"content": "### :\n- \n-"}}], "model": "minimind"}
        good_response = {"choices": [{"message": {"content": "OpenChimera orchestrates local LLMs."}}], "model": "minimind"}
        call_count = [0]

        def side_effect(*args, **kwargs):
            resp = bad_response if call_count[0] == 0 else good_response
            call_count[0] += 1
            return resp

        with patch.object(service, "_api_is_healthy", return_value=True):
            with patch.object(service, "_post_json", side_effect=side_effect):
                result = service.reasoning_completion([{"role": "user", "content": "Explain OpenChimera."}])
        self.assertIsNone(result["error"])
        self.assertIn("OpenChimera", result["content"])


# ============================================================
# RUNTIME STATE coverage tests
# ============================================================

class MiniMindRuntimeStateCoverageTests(unittest.TestCase):
    def test_get_runtime_status_with_running_training_process(self) -> None:
        service = MiniMindService()
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        service._training_processes = {"job-active": mock_proc}
        service._training_jobs = {"job-active": {"status": "running", "pid": 1111}}
        with tempfile.TemporaryDirectory() as tmpdir:
            service.training_output_dir = Path(tmpdir)
            service.job_manifest_path = Path(tmpdir) / "jobs.json"
            result = service.get_runtime_status()
        self.assertIn("job-active", result["training"]["active_jobs"])

    def test_get_runtime_status_finalizes_completed_process(self) -> None:
        # get_runtime_status calls _finalize_training_job inside its _lock block;
        # _finalize_training_job also tries to acquire _lock (non-reentrant) → deadlock.
        # Patch _finalize_training_job to test the dispatch branch without deadlocking.
        service = MiniMindService()
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 0
        mock_proc.returncode = 0
        service._training_processes = {"job-done": mock_proc}
        service._training_jobs = {"job-done": {"status": "running", "pid": 1112}}
        with tempfile.TemporaryDirectory() as tmpdir:
            service.training_output_dir = Path(tmpdir)
            service.job_manifest_path = Path(tmpdir) / "jobs.json"
            with patch.object(service, "_finalize_training_job") as mock_finalize:
                service.get_runtime_status()
        mock_finalize.assert_called_once_with("job-done", 0)

    def test_finalize_training_job_marks_completed(self) -> None:
        service = MiniMindService()
        service._training_jobs = {"job-done": {"status": "running", "pid": 1112}}
        with tempfile.TemporaryDirectory() as tmpdir:
            service.training_output_dir = Path(tmpdir)
            service.job_manifest_path = Path(tmpdir) / "jobs.json"
            service._finalize_training_job("job-done", 0)
        self.assertEqual(service._training_jobs["job-done"]["status"], "completed")

    def test_refresh_runtime_state_does_not_raise(self) -> None:
        service = MiniMindService()
        with patch.object(service, "_resolve_device", return_value="cpu"):
            with tempfile.TemporaryDirectory() as tmpdir:
                service.training_output_dir = Path(tmpdir)
                service.runtime_manifest_path = Path(tmpdir) / "runtime.json"
                service.job_manifest_path = Path(tmpdir) / "jobs.json"
                service.refresh_runtime_state()
                self.assertTrue(service.runtime_manifest_path.exists())

    def test_is_server_running_clears_dead_server_process(self) -> None:
        service = MiniMindService()
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1  # process exited
        service._server_process = mock_proc
        result = service._is_server_running()
        self.assertFalse(result)
        self.assertIsNone(service._server_process)


# ============================================================
# _is_usable_response additional branch tests
# ============================================================

class MiniMindUsableResponseBranchTests(unittest.TestCase):
    def test_rejects_very_short_content(self) -> None:
        service = MiniMindService()
        self.assertFalse(service._is_usable_response("ab", "prompt"))

    def test_rejects_too_many_newlines_with_short_text(self) -> None:
        service = MiniMindService()
        # 9 newlines but total length < 80 chars
        self.assertFalse(service._is_usable_response("\n\n\n\n\n\n\n\n\nok", "prompt"))

    def test_rejects_content_starting_with_dash_bullet(self) -> None:
        service = MiniMindService()
        self.assertFalse(service._is_usable_response("- Item one\n- Item two", "prompt"))

    def test_rejects_content_with_placeholder_keyword(self) -> None:
        service = MiniMindService()
        self.assertFalse(service._is_usable_response("Here is a placeholder response.", "prompt"))

    def test_rejects_content_with_tool_call_keyword(self) -> None:
        service = MiniMindService()
        self.assertFalse(service._is_usable_response("tool_call: some action", "prompt"))

    def test_rejects_content_with_zero_alnum_chars(self) -> None:
        service = MiniMindService()
        self.assertFalse(service._is_usable_response("!!! ???", "prompt"))

    def test_rejects_content_with_few_unique_chars(self) -> None:
        service = MiniMindService()
        self.assertFalse(service._is_usable_response("abababababababab", "prompt"))

    def test_rejects_content_with_repetitive_run_of_12(self) -> None:
        service = MiniMindService()
        self.assertFalse(service._is_usable_response("aaaaaaaaaaaa", "prompt"))

    def test_accepts_normal_assistant_sentence(self) -> None:
        service = MiniMindService()
        self.assertTrue(service._is_usable_response("The system is running normally.", "prompt"))


# ============================================================
# _flatten_messages and _build_inference_messages branch tests
# ============================================================

class MiniMindMessagesBranchTests(unittest.TestCase):
    def test_flatten_only_user_messages(self) -> None:
        service = MiniMindService()
        result = service._flatten_messages([{"role": "user", "content": "Hello"}])
        self.assertIn("User request:", result)
        self.assertNotIn("Guidance:", result)

    def test_flatten_only_assistant_messages(self) -> None:
        service = MiniMindService()
        result = service._flatten_messages([{"role": "assistant", "content": "I recall..."}])
        self.assertIn("Prior assistant context:", result)

    def test_flatten_empty_messages_returns_default(self) -> None:
        service = MiniMindService()
        result = service._flatten_messages([])
        self.assertIn("Respond briefly", result)

    def test_build_inference_not_simplified_with_user_and_assistant(self) -> None:
        service = MiniMindService()
        original = [
            {"role": "user", "content": "Question?"},
            {"role": "assistant", "content": "Answer."},
        ]
        prompt = service._flatten_messages(original)
        result = service._build_inference_messages(original, prompt, simplified=False)
        roles = [m["role"] for m in result]
        self.assertIn("user", roles)
        self.assertIn("assistant", roles)

    def test_build_inference_not_simplified_only_system_falls_back_to_prompt(self) -> None:
        service = MiniMindService()
        original = [{"role": "system", "content": "sys context"}]
        prompt = "user fallback prompt"
        result = service._build_inference_messages(original, prompt, simplified=False)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["role"], "user")
        self.assertEqual(result[0]["content"], prompt)


# ============================================================
# Additional branch coverage tests targeting remaining lines
# ============================================================

class MiniMindAdditionalBranchTests(unittest.TestCase):
    """Target remaining uncovered branches to push coverage above 93%."""

    def test_get_runtime_status_clears_dead_server_process(self) -> None:
        """Line 77: cover path where _server_process is set but has exited."""
        service = MiniMindService()
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1  # process exited
        mock_proc.pid = 9999
        service._server_process = mock_proc
        with tempfile.TemporaryDirectory() as tmpdir:
            service.training_output_dir = Path(tmpdir)
            service.job_manifest_path = Path(tmpdir) / "jobs.json"
            result = service.get_runtime_status()
        self.assertIsNone(service._server_process)
        self.assertFalse(result["server"]["running"])

    def test_start_training_job_unsupported_mode_returns_error(self) -> None:
        """Line 211: unsupported mode hits the script_map None-check."""
        service = MiniMindService()
        service.available = True
        with tempfile.TemporaryDirectory() as tmpdir:
            service.training_output_dir = Path(tmpdir)
            service.job_manifest_path = Path(tmpdir) / "jobs.json"
            manifest = Path(tmpdir) / "harness_openchimera_dataset_manifest.json"
            manifest.write_text("{}", encoding="utf-8")
            result = service.start_training_job(mode="unsupported_xyz_mode")
        self.assertEqual(result["status"], "error")
        self.assertIn("Unsupported", result["error"])

    def test_start_training_job_missing_base_weight_returns_error(self) -> None:
        """Lines 224-227: reason_sft from_weight='full_sft' but base .pth missing."""
        service = MiniMindService()
        service.available = True
        with tempfile.TemporaryDirectory() as tmpdir:
            tp = Path(tmpdir)
            service.training_output_dir = tp
            service.job_manifest_path = tp / "jobs.json"
            service.log_dir = tp / "logs"
            service.root = tp
            # dataset manifest
            (tp / "harness_openchimera_dataset_manifest.json").write_text("{}", encoding="utf-8")
            # trainer script and data
            (tp / "trainer").mkdir()
            (tp / "trainer" / "train_reason.py").write_text("pass", encoding="utf-8")
            (tp / "harness_openchimera_sft.jsonl").write_text("{}", encoding="utf-8")
            # bypass preflight and device
            with patch.object(service, "_check_python_modules", return_value=None):
                with patch.object(service, "_resolve_device", return_value="cpu"):
                    result = service.start_training_job(mode="reason_sft")
        self.assertEqual(result["status"], "error")
        self.assertIn("base weight", result["error"].lower())

    def test_build_pretrain_records_includes_proposal_file(self) -> None:
        """Line 469: proposal file read when CHIMERA_MINI_PROPOSAL.md exists."""
        service = MiniMindService()
        with tempfile.TemporaryDirectory() as tmpdir:
            tp = Path(tmpdir)
            service.root = tp
            service.training_output_dir = tp
            service.log_dir = tp / "logs"
            service.job_manifest_path = tp / "jobs.json"
            service.runtime_manifest_path = tp / "runtime.json"
            (tp / "CHIMERA_MINI_PROPOSAL.md").write_text(
                "# MiniMind Proposal\nContent here.", encoding="utf-8"
            )
            harness_port = MagicMock()
            harness_port.status.return_value = {"summary": "ok"}
            identity = {
                "root": str(tp), "hardware": {}, "local_runtime": {},
                "model_inventory": {}, "integration_roots": {}, "reasoning_engine": "minimind",
            }
            # Patch _api_is_healthy to avoid real network calls in _build_checkpoint_summary → status()
            with patch.object(service, "_resolve_device", return_value="cpu"):
                with patch.object(service, "_api_is_healthy", return_value=False):
                    records = service._build_pretrain_records(harness_port, identity)
        texts = " ".join(r.get("text", "") for r in records)
        self.assertIn("MiniMind Proposal", texts)

    def test_usable_response_rejects_content_with_many_newlines_in_body(self) -> None:
        """Line 577: 9+ newlines embedded → count > 8 and len < 80 → return False."""
        service = MiniMindService()
        # "A\n\n\n\n\n\n\n\n\nZ".strip() keeps the newlines, has 9, len 11 < 80
        content = "A\n\n\n\n\n\n\n\n\nZ"
        self.assertFalse(service._is_usable_response(content, "prompt"))

    def test_usable_response_rejects_long_repetitive_run_with_diverse_prefix(self) -> None:
        """Line 595: longest_run >= 12 but unique_chars > 3 bypasses earlier check."""
        service = MiniMindService()
        # "xyzw" gives 4 unique chars (passes <=3 guard), then 12 'a's → longest_run=12
        content = "xyzw" + "a" * 12
        self.assertFalse(service._is_usable_response(content, "prompt"))

    def test_usable_response_rejects_all_digit_no_ascii_alpha(self) -> None:
        """Line 599: ascii_letters == 0, non_space > 0, all chars < 128 → return False."""
        service = MiniMindService()
        # Digits only: no alpha chars, all < 128, alnum >= 3, unique > 3
        content = "1234 56789"
        self.assertFalse(service._is_usable_response(content, "prompt"))

    def test_usable_response_rejects_exact_reply_mismatch(self) -> None:
        """Line 604: prompt starts with 'user request:\\nreply with exactly' but content not in it."""
        service = MiniMindService()
        prompt = "user request:\nreply with exactly 'yes'"
        content = "This is a completely different response."
        self.assertFalse(service._is_usable_response(content, prompt))

    def test_reconcile_persisted_jobs_adds_running_pid_to_active_list(self) -> None:
        """Lines 657-663: pid IS running → job added to active_jobs, loop continues."""
        service = MiniMindService()
        with tempfile.TemporaryDirectory() as tmpdir:
            service.training_output_dir = Path(tmpdir)
            service.job_manifest_path = Path(tmpdir) / "jobs.json"
            service._training_jobs = {"job-live": {"status": "running", "pid": 12345}}
            active_jobs: list[str] = []
            with patch.object(service, "_pid_is_running", return_value=True):
                service._reconcile_persisted_jobs(active_jobs)
        self.assertIn("job-live", active_jobs)
        self.assertEqual(service._training_jobs["job-live"]["status"], "running")

    def test_pid_is_running_returns_false_for_nonpositive_pid(self) -> None:
        """Lines 666-668: pid <= 0 → return False immediately."""
        service = MiniMindService()
        self.assertFalse(service._pid_is_running(0))
        self.assertFalse(service._pid_is_running(-5))

    def test_pid_is_running_returns_true_when_kill_does_not_raise(self) -> None:
        """Line 673: os.kill doesn't raise → return True (mock to avoid Windows CTRL_C_EVENT on signal 0)."""
        import os as _os
        service = MiniMindService()
        with patch.object(_os, "kill"):  # no-op: doesn't raise → returns True
            result = service._pid_is_running(12345)
        self.assertTrue(result)

    def test_check_python_modules_returns_none_when_all_present(self) -> None:
        """Line 738: returncode=0, stdout='' → no missing modules → return None."""
        service = MiniMindService()
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        with patch("subprocess.run", return_value=mock_result):
            result = service._check_python_modules(["torch"])
        self.assertIsNone(result)

    def test_finalize_training_job_marks_failed_on_nonzero_returncode(self) -> None:
        """Line 717: returncode=1 → status 'failed'."""
        service = MiniMindService()
        service._training_jobs = {"job-fail": {"status": "running", "pid": 9999}}
        with tempfile.TemporaryDirectory() as tmpdir:
            service.training_output_dir = Path(tmpdir)
            service.job_manifest_path = Path(tmpdir) / "jobs.json"
            service._finalize_training_job("job-fail", 1)
        self.assertEqual(service._training_jobs["job-fail"]["status"], "failed")

    def test_finalize_training_job_early_return_for_missing_job(self) -> None:
        """Line 717 early-return: job_id not in _training_jobs → returns without error."""
        service = MiniMindService()
        service._training_jobs = {}
        with tempfile.TemporaryDirectory() as tmpdir:
            service.training_output_dir = Path(tmpdir)
            service.job_manifest_path = Path(tmpdir) / "jobs.json"
            service._finalize_training_job("ghost-job", 0)  # must not raise

    def test_start_training_job_missing_python_executable_returns_error(self) -> None:
        """Line 211: python_executable.name != 'python' AND doesn't exist → error."""
        service = MiniMindService()
        service.available = True
        service.python_executable = Path("/nonexistent/python3.exe")
        with tempfile.TemporaryDirectory() as tmpdir:
            tp = Path(tmpdir)
            service.training_output_dir = tp
            service.root = tp
            service.job_manifest_path = tp / "jobs.json"
            (tp / "harness_openchimera_dataset_manifest.json").write_text("{}", encoding="utf-8")
            (tp / "trainer").mkdir()
            (tp / "trainer" / "train_reason.py").write_text("pass", encoding="utf-8")
            (tp / "harness_openchimera_sft.jsonl").write_text("{}", encoding="utf-8")
            result = service.start_training_job(mode="reason_sft")
        self.assertEqual(result["status"], "error")
        self.assertIn("python", result["error"].lower())

    def test_reconcile_persisted_jobs_skips_non_running_jobs(self) -> None:
        """Line 695: job with status != 'running' → continue (skipped)."""
        service = MiniMindService()
        with tempfile.TemporaryDirectory() as tmpdir:
            service.training_output_dir = Path(tmpdir)
            service.job_manifest_path = Path(tmpdir) / "jobs.json"
            service._training_jobs = {"job-done": {"status": "completed", "pid": 1234}}
            active_jobs: list[str] = []
            service._reconcile_persisted_jobs(active_jobs)
        self.assertEqual(active_jobs, [])
        self.assertEqual(service._training_jobs["job-done"]["status"], "completed")

    def test_get_json_uses_inner_fetch_function(self) -> None:
        """Lines 657-663: _get_json inner _fetch function body executed on successful GET."""
        service = MiniMindService()

        class _FakeResponse:
            def read(self) -> bytes:
                return b'{"status": "ok"}'
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        with patch("core.minimind_service.request.urlopen", return_value=_FakeResponse()):
            result = service._get_json("http://127.0.0.1:9999/test")
        self.assertEqual(result, {"status": "ok"})

    def test_post_json_uses_inner_send_function(self) -> None:
        """Lines 666-673: _post_json inner _send function body executed on successful POST."""
        service = MiniMindService()

        class _FakeResponse:
            def read(self) -> bytes:
                return b'{"result": "created"}'
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass

        with patch("core.minimind_service.request.urlopen", return_value=_FakeResponse()):
            result = service._post_json("http://127.0.0.1:9999/api", {"key": "value"})
        self.assertEqual(result, {"result": "created"})