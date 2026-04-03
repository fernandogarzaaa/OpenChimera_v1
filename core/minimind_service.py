from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
import copy
from pathlib import Path
from typing import Any
from urllib import request

from core.harness_port import HarnessPortAdapter
from core.config import (
    ROOT,
    get_minimind_api_base_url,
    get_minimind_api_host,
    get_minimind_api_port,
    get_minimind_python_executable,
    get_minimind_root,
    get_minimind_training_output_dir,
    load_runtime_profile,
)
from core.resilience import retry_call
from core.transactions import atomic_write_json, atomic_write_jsonl


class MiniMindService:
    def __init__(self):
        self.root = get_minimind_root()
        self.profile = load_runtime_profile()
        self.training_output_dir = get_minimind_training_output_dir()
        self.python_executable = get_minimind_python_executable()
        self.api_host = get_minimind_api_host()
        self.api_port = get_minimind_api_port()
        self.api_base_url = get_minimind_api_base_url()
        self.available = (self.root / "model" / "model_minimind.py").exists()
        self.log_dir = ROOT / "logs" / "minimind"
        self.runtime_manifest_path = self.training_output_dir / "minimind_runtime_manifest.json"
        self.job_manifest_path = self.training_output_dir / "minimind_training_jobs.json"
        self._lock = threading.Lock()
        self._server_process: subprocess.Popen[bytes] | None = None
        self._server_started_at = 0.0
        self._training_processes: dict[str, subprocess.Popen[bytes]] = {}
        self._training_jobs: dict[str, dict[str, Any]] = self._load_training_jobs()

    def status(self) -> dict[str, Any]:
        checkpoints = self._collect_weight_files(self.root / "checkpoints")
        outputs = self._collect_weight_files(self.root / "out")
        datasets = self._collect_jsonl_files(self.root / "dataset")
        reasoning_engine = self.profile.get("local_runtime", {}).get("reasoning_engine")
        runtime = self.get_runtime_status()
        return {
            "available": self.available,
            "root": str(self.root),
            "reasoning_engine": reasoning_engine,
            "model_definition": str(self.root / "model" / "model_minimind.py"),
            "api_script": str(self.root / "scripts" / "serve_openai_api.py"),
            "trainer_script": str(self.root / "trainer" / "train_reason.py"),
            "training_output_dir": str(self.training_output_dir),
            "python_executable": str(self.python_executable),
            "python_exists": self.python_executable.exists() if self.python_executable.name != "python" else True,
            "api_base_url": self.api_base_url,
            "resolved_device": self._resolve_device(),
            "checkpoints": checkpoints,
            "out_weights": outputs,
            "datasets": datasets,
            "runtime": runtime,
            "training_jobs": list(self._training_jobs.values()),
        }

    def get_runtime_status(self) -> dict[str, Any]:
        with self._lock:
            server_running = self._server_process is not None and self._server_process.poll() is None
            if self._server_process is not None and not server_running:
                self._server_process = None
            active_jobs = []
            for job_id, process in list(self._training_processes.items()):
                if process.poll() is None:
                    active_jobs.append(job_id)
                else:
                    self._finalize_training_job(job_id, process.returncode)
            self._reconcile_persisted_jobs(active_jobs)

        return {
            "server": {
                "running": server_running,
                "pid": self._server_process.pid if server_running and self._server_process is not None else None,
                "started_at": self._server_started_at or None,
                "api_base_url": self.api_base_url,
                "api_healthy": self._api_is_healthy(),
                "log_path": str(self.log_dir / "minimind_api.log"),
            },
            "training": {
                "active_jobs": active_jobs,
                "job_manifest_path": str(self.job_manifest_path),
            },
        }

    def start_server(self) -> dict[str, Any]:
        if not self.available:
            return {"status": "error", "error": "MiniMind workspace unavailable"}
        if self._is_server_running():
            return {"status": "already-running", "pid": self._server_process.pid if self._server_process else None}

        script = self.root / "scripts" / "serve_openai_api.py"
        if not script.exists():
            return {"status": "error", "error": f"Missing MiniMind API script: {script}"}
        if self.python_executable.name != "python" and not self.python_executable.exists():
            return {"status": "error", "error": f"Missing MiniMind Python executable: {self.python_executable}"}
        preflight_error = self._check_python_modules(["torch", "transformers", "fastapi", "uvicorn"])
        if preflight_error is not None:
            return {"status": "error", "error": preflight_error}

        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.training_output_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.log_dir / "minimind_api.log"
        command = [
            str(self.python_executable),
            "-u",
            str(script),
            "--device",
            self._resolve_device(),
            "--weight",
            str(self._reasoning_config().get("serve_weight", "reason")),
            "--hidden_size",
            str(self._reasoning_config().get("hidden_size", 512)),
            "--num_hidden_layers",
            str(self._reasoning_config().get("num_hidden_layers", 8)),
            "--max_seq_len",
            str(self._reasoning_config().get("serve_max_seq_len", 8192)),
        ]
        env = os.environ.copy()
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env.setdefault("PYTHONUNBUFFERED", "1")
        env["OPENCHIMERA_MINIMIND_HOST"] = self.api_host
        env["OPENCHIMERA_MINIMIND_PORT"] = str(self.api_port)
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

        log_handle = open(log_path, "ab")
        try:
            process = subprocess.Popen(
                command,
                cwd=script.parent,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                creationflags=creationflags,
                env=env,
            )
        except OSError as exc:
            log_handle.close()
            return {"status": "error", "error": str(exc)}
        log_handle.close()

        with self._lock:
            self._server_process = process
            self._server_started_at = time.time()
        self._write_runtime_manifest()
        return {
            "status": "started",
            "pid": process.pid,
            "api_base_url": self.api_base_url,
            "log_path": str(log_path),
        }

    def stop_server(self) -> dict[str, Any]:
        with self._lock:
            process = self._server_process
        if process is None or process.poll() is not None:
            self._server_process = None
            return {"status": "not-running"}
        try:
            process.terminate()
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        finally:
            with self._lock:
                self._server_process = None
                self._server_started_at = 0.0
            self._write_runtime_manifest()
        return {"status": "stopped"}

    def start_training_job(self, mode: str = "reason_sft", force_dataset: bool = False) -> dict[str, Any]:
        if not self.available:
            return {"status": "error", "error": "MiniMind workspace unavailable"}

        if force_dataset or not (self.training_output_dir / "harness_openchimera_dataset_manifest.json").exists():
            return {
                "status": "error",
                "error": "Dataset manifest missing. Build the MiniMind dataset first.",
            }

        script_map = {
            "reason_sft": self.root / "trainer" / "train_reason.py",
            "pretrain": self.root / "trainer" / "train_pretrain.py",
        }
        data_map = {
            "reason_sft": self.training_output_dir / "harness_openchimera_sft.jsonl",
            "pretrain": self.training_output_dir / "harness_openchimera_pretrain.jsonl",
        }
        script = script_map.get(mode)
        data_path = data_map.get(mode)
        if script is None or data_path is None:
            return {"status": "error", "error": f"Unsupported training mode: {mode}"}
        if not script.exists() or not data_path.exists():
            return {"status": "error", "error": f"Missing training inputs for mode {mode}"}
        if self.python_executable.name != "python" and not self.python_executable.exists():
            return {"status": "error", "error": f"Missing MiniMind Python executable: {self.python_executable}"}
        preflight_error = self._check_python_modules(["torch", "datasets"])
        if preflight_error is not None:
            return {"status": "error", "error": preflight_error}

        job_id = f"minimind-{mode}-{int(time.time())}"
        config = self._reasoning_config()
        hidden_size = int(config.get("hidden_size", 512))
        use_moe = bool(config.get("use_moe", False))
        from_weight = str(config.get("training_from_weight", "full_sft" if mode == "reason_sft" else "none"))
        resolved_device = self._resolve_device()
        training_num_workers = self._resolve_training_num_workers(resolved_device)
        if from_weight != "none":
            moe_suffix = "_moe" if use_moe else ""
            base_weight = self.root / "out" / f"{from_weight}_{hidden_size}{moe_suffix}.pth"
            if not base_weight.exists():
                return {
                    "status": "error",
                    "error": f"Missing MiniMind base weight for training: {base_weight}",
                }
        self.log_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.log_dir / f"{job_id}.log"
        output_dir = Path(config.get("training_save_dir") or (self.root / "out"))
        output_dir.mkdir(parents=True, exist_ok=True)
        command = [
            str(self.python_executable),
            "-u",
            str(script),
            "--data_path",
            str(data_path),
            "--epochs",
            str(config.get("training_epochs", 1)),
            "--batch_size",
            str(config.get("training_batch_size", 4 if mode == "reason_sft" else 8)),
            "--device",
            resolved_device,
            "--num_workers",
            str(training_num_workers),
            "--save_dir",
            str(output_dir),
            "--from_weight",
            from_weight,
            "--hidden_size",
            str(hidden_size),
            "--num_hidden_layers",
            str(config.get("num_hidden_layers", 8)),
            "--use_moe",
            "1" if use_moe else "0",
        ]
        env = os.environ.copy()
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env.setdefault("PYTHONUNBUFFERED", "1")
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        log_handle = open(log_path, "ab")
        try:
            process = subprocess.Popen(
                command,
                cwd=script.parent,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                creationflags=creationflags,
                env=env,
            )
        except OSError as exc:
            log_handle.close()
            return {"status": "error", "error": str(exc)}
        log_handle.close()

        job = {
            "job_id": job_id,
            "mode": mode,
            "status": "running",
            "pid": process.pid,
            "started_at": time.time(),
            "data_path": str(data_path),
            "script": str(script),
            "log_path": str(log_path),
            "save_dir": str(output_dir),
            "command": command,
        }
        with self._lock:
            self._training_processes[job_id] = process
            self._training_jobs[job_id] = job
        self._persist_training_jobs()
        return copy.deepcopy(job)

    def stop_training_job(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            process = self._training_processes.get(job_id)
        if process is None:
            return {"status": "not-running", "job_id": job_id}
        try:
            process.terminate()
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        self._finalize_training_job(job_id, process.returncode, forced=True)
        return {"status": "stopped", "job_id": job_id, "returncode": process.returncode}

    def reasoning_completion(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int = 512,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        if not self._api_is_healthy():
            return {"content": "", "model": "minimind", "error": "MiniMind API unavailable"}
        normalized_prompt = self._flatten_messages(messages)
        attempts = [
            self._build_inference_messages(messages, normalized_prompt, simplified=False),
            self._build_inference_messages(messages, normalized_prompt, simplified=True),
        ]
        last_error = "MiniMind response rejected"
        for index, attempt_messages in enumerate(attempts):
            payload = {
                "model": "minimind",
                "messages": attempt_messages,
                "temperature": 0.2 if index == 0 else 0.1,
                "top_p": 0.85,
                "max_tokens": min(max_tokens, 192),
                "stream": False,
            }
            try:
                response = self._post_json(f"{self.api_base_url}/v1/chat/completions", payload, timeout=timeout)
            except Exception as exc:
                last_error = str(exc)
                continue
            content = self._sanitize_generated_content(
                response.get("choices", [{}])[0].get("message", {}).get("content", "")
            )
            if self._is_usable_response(content, normalized_prompt):
                return {
                    "content": content,
                    "model": response.get("model", "minimind"),
                    "error": None,
                }
            last_error = "MiniMind low-quality response"
        return {"content": "", "model": "minimind", "error": last_error}

    def build_training_dataset(
        self,
        harness_port: HarnessPortAdapter,
        identity_snapshot: dict[str, Any],
        force: bool = True,
    ) -> dict[str, Any]:
        self.training_output_dir.mkdir(parents=True, exist_ok=True)
        sft_path = self.training_output_dir / "harness_openchimera_sft.jsonl"
        pretrain_path = self.training_output_dir / "harness_openchimera_pretrain.jsonl"
        manifest_path = self.training_output_dir / "harness_openchimera_dataset_manifest.json"

        sft_records = self._build_sft_records(harness_port, identity_snapshot)
        pretrain_records = self._build_pretrain_records(harness_port, identity_snapshot)

        if force or not sft_path.exists():
            self._write_jsonl(sft_path, sft_records)
        if force or not pretrain_path.exists():
            self._write_jsonl(pretrain_path, pretrain_records)

        manifest = {
            "generated_from": {
                "openchimera_root": str(ROOT),
                "harness_repo_root": str(harness_port.root),
                "minimind_root": str(self.root),
            },
            "files": {
                "sft": str(sft_path),
                "pretrain": str(pretrain_path),
            },
            "counts": {
                "sft_records": len(sft_records),
                "pretrain_records": len(pretrain_records),
            },
            "recommended_commands": {
                "reason_sft": (
                    f"{self.python_executable} {self.root / 'trainer' / 'train_reason.py'} "
                    f"--data_path {sft_path} --epochs 1 --batch_size 4 --device cuda:0"
                ),
                "pretrain": (
                    f"{self.python_executable} {self.root / 'trainer' / 'train_pretrain.py'} "
                    f"--data_path {pretrain_path} --epochs 1 --batch_size 8 --device cuda:0"
                ),
            },
        }
        atomic_write_json(manifest_path, manifest)
        return manifest

    def refresh_runtime_state(self) -> None:
        self.get_runtime_status()
        self._write_runtime_manifest()

    def _build_sft_records(
        self,
        harness_port: HarnessPortAdapter,
        identity_snapshot: dict[str, Any],
    ) -> list[dict[str, Any]]:
        harness_status = harness_port.status()
        runtime_summary = self._build_runtime_summary(identity_snapshot)
        training_strategy = self._build_training_strategy(harness_status, identity_snapshot)
        checkpoint_summary = self._build_checkpoint_summary()
        records = harness_port.build_sft_examples()
        system_prompt = (
            "You are MiniMind, the compact reasoning engine embedded in OpenChimera. "
            "Use architectural context carefully, keep claims grounded in local files, and be explicit about what is only a training artifact."
        )
        records.extend(
            [
                {
                    "conversations": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": "Summarize OpenChimera's current runtime and subsystem layout."},
                        {"role": "assistant", "content": runtime_summary},
                    ]
                },
                {
                    "conversations": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": "How should upstream harness-derived data be used to train MiniMind inside OpenChimera?"},
                        {"role": "assistant", "content": training_strategy},
                    ]
                },
                {
                    "conversations": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": "What MiniMind checkpoints and datasets are currently available?"},
                        {"role": "assistant", "content": checkpoint_summary},
                    ]
                },
            ]
        )
        return records

    def _build_pretrain_records(
        self,
        harness_port: HarnessPortAdapter,
        identity_snapshot: dict[str, Any],
    ) -> list[dict[str, str]]:
        harness_status = harness_port.status()
        records = [
            {"text": harness_status.get("summary", "")},
            {"text": self._build_runtime_summary(identity_snapshot)},
            {"text": self._build_training_strategy(harness_status, identity_snapshot)},
            {"text": self._build_checkpoint_summary()},
        ]
        readme_path = ROOT / "README.md"
        if readme_path.exists():
            records.append({"text": readme_path.read_text(encoding="utf-8", errors="ignore")[:4000]})
        records.append(
            {
                "text": (
                    "Upstream harness source is mounted locally for architectural study only. "
                    "OpenChimera uses sanitized manifest, command, tool, and workflow summaries rather than raw branded README text."
                )
            }
        )
        proposal_path = self.root / "CHIMERA_MINI_PROPOSAL.md"
        if proposal_path.exists():
            records.append({"text": proposal_path.read_text(encoding="utf-8", errors="ignore")[:4000]})
        return [record for record in records if record.get("text")]

    def _build_runtime_summary(self, identity_snapshot: dict[str, Any]) -> str:
        hardware = identity_snapshot.get("hardware", {})
        local_runtime = identity_snapshot.get("local_runtime", {})
        model_inventory = identity_snapshot.get("model_inventory", {})
        integration_roots = identity_snapshot.get("integration_roots", {})
        return (
            "OpenChimera is a local orchestration runtime rooted at "
            f"{identity_snapshot.get('root', 'unknown')}. "
            "It hosts an OpenAI-compatible provider, retrieval layer, token compression, and local llama.cpp process control. "
            f"Preferred local models: {', '.join(local_runtime.get('preferred_local_models', [])) or 'unknown'}. "
            f"Available model inventory: {', '.join(model_inventory.get('available_models', [])) or 'unknown'}. "
            f"Reasoning engine target: {identity_snapshot.get('reasoning_engine', 'unknown')}. "
            f"Harness repo root: {integration_roots.get('harness_repo', 'unknown')}. "
            f"MiniMind root: {integration_roots.get('minimind', 'unknown')}. "
            f"Hardware: cpu_count={hardware.get('cpu_count', 'unknown')}, ram_gb={hardware.get('ram_gb', 'unknown')}, "
            f"gpu={hardware.get('gpu', {}).get('name', 'unknown')}, vram_gb={hardware.get('gpu', {}).get('vram_gb', 'unknown')}."
        )

    def _build_training_strategy(self, harness_status: dict[str, Any], identity_snapshot: dict[str, Any]) -> str:
        command_names = ", ".join(item["name"] for item in harness_status.get("commands", [])) or "none"
        tool_names = ", ".join(item["name"] for item in harness_status.get("tools", [])) or "none"
        return (
            "Use the upstream Python harness port as a curriculum source rather than pretending it is a drop-in model backend. "
            "Train MiniMind on structured architecture summaries, command metadata, tool metadata, and OpenChimera runtime descriptions so it learns the harness shape and operational language. "
            f"Current harness-derived commands: {command_names}. Current harness-derived tools: {tool_names}. "
            "This exported dataset is intended for local SFT or light reasoning distillation, not for claiming upstream model parity."
        )

    def _build_checkpoint_summary(self) -> str:
        status = self.status()
        checkpoints = status.get("checkpoints", [])
        out_weights = status.get("out_weights", [])
        datasets = status.get("datasets", [])
        return (
            f"MiniMind checkpoints: {', '.join(checkpoints) if checkpoints else 'none found'}. "
            f"Output weights: {', '.join(out_weights) if out_weights else 'none found'}. "
            f"Datasets: {', '.join(datasets) if datasets else 'none found'}."
        )

    def _collect_weight_files(self, directory: Path) -> list[str]:
        if not directory.exists():
            return []
        return sorted(str(path) for path in directory.glob("*.pth"))

    def _collect_jsonl_files(self, directory: Path) -> list[str]:
        if not directory.exists():
            return []
        return sorted(str(path) for path in directory.glob("*.jsonl"))

    def _flatten_messages(self, messages: list[dict[str, Any]]) -> str:
        parts: list[str] = []
        system_messages = [str(item.get("content", "")).strip() for item in messages if item.get("role") == "system"]
        user_messages = [str(item.get("content", "")).strip() for item in messages if item.get("role") == "user"]
        assistant_messages = [str(item.get("content", "")).strip() for item in messages if item.get("role") == "assistant"]
        if system_messages:
            parts.append("Guidance:\n" + "\n".join(item for item in system_messages if item))
        if user_messages:
            parts.append("User request:\n" + "\n".join(item for item in user_messages if item))
        if assistant_messages:
            parts.append("Prior assistant context:\n" + "\n".join(item for item in assistant_messages if item))
        flattened = "\n\n".join(part for part in parts if part).strip()
        return flattened or "Respond briefly and clearly to the user request."

    def _build_inference_messages(
        self,
        original_messages: list[dict[str, Any]],
        normalized_prompt: str,
        simplified: bool,
    ) -> list[dict[str, str]]:
        if simplified:
            return [
                {
                    "role": "user",
                    "content": (
                        "Answer the request briefly in plain text. Avoid markdown fences, bullet skeletons, or placeholder tokens.\n\n"
                        + normalized_prompt
                    ),
                }
            ]

        non_system = [
            {
                "role": str(item.get("role", "user")),
                "content": str(item.get("content", "")),
            }
            for item in original_messages
            if str(item.get("role", "user")) != "system"
        ]
        if non_system:
            return non_system
        return [{"role": "user", "content": normalized_prompt}]

    def _sanitize_generated_content(self, content: str) -> str:
        cleaned = content.replace("\r\n", "\n").strip()
        cleaned = re.sub(r"^```(?:[a-zA-Z0-9_+-]+)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
        return cleaned

    def _is_usable_response(self, content: str, normalized_prompt: str) -> bool:
        if not content:
            return False
        stripped = content.strip()
        if len(stripped) < 3:
            return False
        if stripped.count("\n") > 8 and len(stripped) < 80:
            return False
        if stripped.startswith("###") or stripped.startswith("- "):
            return False
        alnum_count = sum(char.isalnum() for char in stripped)
        if alnum_count < 3:
            return False
        unique_chars = set(stripped)
        if len(unique_chars) <= 3 and len(stripped) >= 8:
            return False
        longest_run = 1
        current_run = 1
        for previous, current in zip(stripped, stripped[1:]):
            if current == previous:
                current_run += 1
                longest_run = max(longest_run, current_run)
            else:
                current_run = 1
        if longest_run >= 12:
            return False
        ascii_letters = sum(char.isascii() and char.isalpha() for char in stripped)
        non_space = sum(not char.isspace() for char in stripped)
        if non_space and ascii_letters == 0 and all(ord(char) < 128 or char in "，。！？：；、“”‘’（）《》【】\n " for char in stripped):
            return False
        lowered = stripped.lower()
        if "placeholder" in lowered or "tool_call" in lowered:
            return False
        if normalized_prompt.lower().startswith("user request:\nreply with exactly") and stripped.lower() not in normalized_prompt.lower():
            return False
        return True

    def _reasoning_config(self) -> dict[str, Any]:
        return self.profile.get("local_runtime", {}).get("reasoning_engine_config", {})

    def _resolve_training_num_workers(self, resolved_device: str) -> int:
        configured = self._reasoning_config().get("training_num_workers")
        if configured is not None:
            try:
                return max(0, int(configured))
            except (TypeError, ValueError):
                return 0
        return 2 if resolved_device.startswith("cuda") else 0

    def _resolve_device(self) -> str:
        configured = str(self._reasoning_config().get("device", "cuda:0"))
        if not configured.startswith("cuda"):
            return configured
        command = [str(self.python_executable), "-c", "import torch; print('1' if torch.cuda.is_available() else '0')"]
        try:
            result = subprocess.run(
                command,
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return "cpu"
        return configured if result.stdout.strip() == "1" else "cpu"

    def _is_server_running(self) -> bool:
        with self._lock:
            if self._server_process is None:
                return False
            if self._server_process.poll() is None:
                return True
            self._server_process = None
            self._server_started_at = 0.0
            return False

    def _api_is_healthy(self) -> bool:
        if not self._is_server_running():
            return False
        try:
            self._get_json(f"{self.api_base_url}/openapi.json", timeout=5)
            return True
        except Exception:
            return False

    def _get_json(self, url: str, timeout: float = 5.0) -> dict[str, Any]:
        def _fetch() -> dict[str, Any]:
            req = request.Request(url, method="GET")
            with request.urlopen(req, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}

        return retry_call(_fetch, attempts=2, delay_seconds=0.15, retry_exceptions=(OSError, TimeoutError, json.JSONDecodeError))

    def _post_json(self, url: str, payload: dict[str, Any], timeout: float = 30.0) -> dict[str, Any]:
        def _send() -> dict[str, Any]:
            body = json.dumps(payload).encode("utf-8")
            req = request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
            with request.urlopen(req, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}

        return retry_call(_send, attempts=2, delay_seconds=0.2, retry_exceptions=(OSError, TimeoutError, json.JSONDecodeError))

    def _load_training_jobs(self) -> dict[str, dict[str, Any]]:
        if not self.job_manifest_path.exists():
            return {}
        try:
            raw = json.loads(self.job_manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        if not isinstance(raw, dict):
            return {}
        return {str(key): value for key, value in raw.items() if isinstance(value, dict)}

    def _persist_training_jobs(self) -> None:
        self.training_output_dir.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.job_manifest_path, self._training_jobs)

    def _reconcile_persisted_jobs(self, active_jobs: list[str]) -> None:
        dirty = False
        active_job_ids = set(active_jobs)
        for job_id, job in self._training_jobs.items():
            if job.get("status") != "running":
                continue
            if job_id in active_job_ids:
                continue
            pid = job.get("pid")
            if isinstance(pid, int) and self._pid_is_running(pid):
                active_jobs.append(job_id)
                active_job_ids.add(job_id)
                continue
            job["status"] = "abandoned"
            job.setdefault("finished_at", time.time())
            job.setdefault("returncode", None)
            dirty = True
        if dirty:
            self._persist_training_jobs()

    def _pid_is_running(self, pid: int) -> bool:
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        return True

    def _check_python_modules(self, module_names: list[str]) -> str | None:
        command = [str(self.python_executable), "-c", "import importlib.util, sys; modules=sys.argv[1:]; missing=[name for name in modules if importlib.util.find_spec(name) is None]; print(','.join(missing))"]
        command.extend(module_names)
        try:
            result = subprocess.run(
                command,
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except OSError as exc:
            return str(exc)
        missing = result.stdout.strip()
        if result.returncode != 0:
            return result.stderr.strip() or f"MiniMind preflight failed for modules: {', '.join(module_names)}"
        if missing:
            return f"MiniMind environment missing modules: {missing}"
        return None

    def _finalize_training_job(self, job_id: str, returncode: int | None, forced: bool = False) -> None:
        with self._lock:
            self._training_processes.pop(job_id, None)
            job = self._training_jobs.get(job_id)
            if job is None:
                return
            job["finished_at"] = time.time()
            job["returncode"] = returncode
            job["status"] = "stopped" if forced else ("completed" if returncode == 0 else "failed")
        self._persist_training_jobs()

    def _write_runtime_manifest(self) -> None:
        self.training_output_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": time.time(),
            "runtime": self.get_runtime_status(),
        }
        atomic_write_json(self.runtime_manifest_path, payload)

    def _write_jsonl(self, output_path: Path, records: list[dict[str, Any]]) -> None:
        sanitized = [self._sanitize_record(record) for record in records]
        atomic_write_jsonl(output_path, sanitized)

    def _sanitize_record(self, record: dict[str, Any]) -> dict[str, Any]:
        raw = json.dumps(record, ensure_ascii=False)
        raw = raw.replace("Claude Code", "Upstream Harness")
        raw = raw.replace("claude-code", "upstream-harness-repo")
        raw = raw.replace("Claude", "Harness")
        raw = raw.replace("Anthropic", "upstream vendor")
        return json.loads(raw)