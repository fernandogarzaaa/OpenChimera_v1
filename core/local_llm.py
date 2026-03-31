from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, request

from core.config import ROOT, load_runtime_profile


LOGGER = logging.getLogger(__name__)


@dataclass
class ModelStats:
    model_name: str
    endpoint: str
    status: str = "unknown"
    last_check: float = 0.0
    avg_latency_ms: float = 0.0
    tokens_per_sec: float = 0.0
    total_requests: int = 0
    failed_requests: int = 0
    vram_usage_gb: float = 0.0
    context_length: int = 4096
    quantization: str = "unknown"


@dataclass
class ModelConfig:
    name: str
    endpoint: str
    model_path: str
    quantization: str
    n_gpu_layers: int
    context_length: int = 4096
    priority: int = 1
    max_batch_size: int = 512


@dataclass
class ManagedProcess:
    model_name: str
    process: subprocess.Popen[bytes]
    log_path: Path
    started_at: float


class LocalLLMManager:
    def __init__(self):
        self.profile = load_runtime_profile()
        self.models: dict[str, ModelStats] = {}
        self.configs: dict[str, ModelConfig] = {}
        self._lock = threading.Lock()
        self._health_check_interval = 30
        self._health_thread: threading.Thread | None = None
        self._running = False
        self._managed_processes: dict[str, ManagedProcess] = {}
        self._launcher_config = self.profile.get("local_runtime", {}).get("launcher", {})
        self._log_dir = ROOT / "logs" / "local_llm"
        self._initialize_defaults()

    def _initialize_defaults(self) -> None:
        local_runtime = self.profile.get("local_runtime", {})
        model_inventory = self.profile.get("model_inventory", {})
        available_models = model_inventory.get("available_models") or [
            "qwen2.5-7b",
            "gemma-2-9b",
            "llama-3.2-3b",
            "phi-3.5-mini",
        ]
        preferred_models = local_runtime.get("preferred_local_models") or []
        ordered_models: list[str] = []
        for model_name in preferred_models:
            if model_name in available_models and model_name not in ordered_models:
                ordered_models.append(model_name)
        for model_name in available_models:
            if model_name not in ordered_models:
                ordered_models.append(model_name)

        models_dir = model_inventory.get("models_dir", "models")
        model_files = model_inventory.get("model_files", {})
        endpoint_overrides = local_runtime.get("model_endpoints", {})
        gpu_layers = int(local_runtime.get("gpu_layers", 35 if local_runtime.get("vram_gb", 0) else 0))
        default_ports = {
            "qwen2.5-7b": 8080,
            "gemma-2-9b": 8081,
            "llama-3.2-3b": 8082,
            "phi-3.5-mini": 8083,
        }

        for priority, model_name in enumerate(ordered_models, start=1):
            endpoint = endpoint_overrides.get(model_name, f"http://127.0.0.1:{default_ports.get(model_name, 8080 + priority - 1)}")
            config = ModelConfig(
                name=model_name,
                endpoint=endpoint.rstrip("/"),
                model_path=str(self._resolve_model_path(models_dir, model_name, model_files.get(model_name))),
                quantization="runtime-managed",
                n_gpu_layers=gpu_layers,
                context_length=int(local_runtime.get("context_length", 4096)),
                priority=priority,
            )
            self.configs[model_name] = config
            self.models[model_name] = ModelStats(
                model_name=model_name,
                endpoint=config.endpoint,
                context_length=config.context_length,
                quantization=config.quantization,
            )

    def _resolve_model_path(self, models_dir: str, model_name: str, configured_file: str | None) -> Path:
        base_dir = Path(models_dir)
        if configured_file:
            candidate = Path(configured_file)
            return candidate if candidate.is_absolute() else base_dir / candidate

        fallback_names = {
            "qwen2.5-7b": "qwen2.5-7b-instruct-q4_k_m.gguf",
            "gemma-2-9b": "gemma-2-9b-it-q4_k_m.gguf",
            "llama-3.2-3b": "llama-3.2-3b-instruct-q8_0.gguf",
            "phi-3.5-mini": "phi-3.5-mini-instruct-q8_0.gguf",
        }
        return base_dir / fallback_names.get(model_name, f"{model_name}.gguf")

    def _launcher_enabled(self) -> bool:
        return bool(self._launcher_config.get("enabled", False))

    def _launcher_should_autostart(self) -> bool:
        return self._launcher_enabled() and bool(self._launcher_config.get("auto_start", False))

    def _launcher_should_stop_with_manager(self) -> bool:
        return self._launcher_enabled() and bool(self._launcher_config.get("shutdown_with_manager", False))

    def _get_llama_server_path(self) -> Path:
        configured = self._launcher_config.get("llama_server_path")
        if configured:
            return Path(configured)
        return Path(r"D:\appforge-main\infrastructure\clawd-hybrid-rtx\llama.cpp\build-cuda\bin\llama-server.exe")

    def _is_managed_process_running(self, model_name: str) -> bool:
        process_info = self._managed_processes.get(model_name)
        if process_info is None:
            return False
        if process_info.process.poll() is None:
            return True
        self._managed_processes.pop(model_name, None)
        return False

    def _infer_port(self, endpoint: str) -> int | None:
        if ":" not in endpoint:
            return None
        try:
            return int(endpoint.rsplit(":", 1)[1].rstrip("/"))
        except ValueError:
            return None

    def _build_launch_command(self, config: ModelConfig) -> list[str]:
        threads = int(self.profile.get("local_runtime", {}).get("cpu_threads", max((os.cpu_count() or 4), 1)))
        port = self._infer_port(config.endpoint)
        command = [
            str(self._get_llama_server_path()),
            "-m",
            config.model_path,
            "-c",
            str(config.context_length),
            "-ngl",
            str(config.n_gpu_layers),
            "--port",
            str(port or 8080),
            "--host",
            "127.0.0.1",
            "-t",
            str(threads),
        ]
        command.extend(self._normalize_launcher_args(self._launcher_config.get("shared_args", [])))
        command.extend(
            self._normalize_launcher_args(self._launcher_config.get("model_args", {}).get(config.name, []))
        )
        return command

    def _normalize_launcher_args(self, args: list[Any]) -> list[str]:
        normalized: list[str] = []
        explicit_value_flags = {
            "--flash-attn",
            "-fa",
            "--cont-batching",
            "-cb",
        }

        index = 0
        while index < len(args):
            token = str(args[index])
            normalized.append(token)
            if token in explicit_value_flags:
                has_value = index + 1 < len(args) and not str(args[index + 1]).startswith("-")
                if not has_value:
                    normalized.append("on")
            index += 1
        return normalized

    def start_configured_models(self, model_names: list[str] | None = None) -> dict[str, Any]:
        requested = model_names or list(self.configs.keys())
        executable = self._get_llama_server_path()
        results: dict[str, Any] = {}

        if not self._launcher_enabled():
            return {"started": [], "skipped": requested, "errors": {"launcher": "Local launcher disabled"}}

        if not executable.exists():
            return {
                "started": [],
                "skipped": requested,
                "errors": {"llama_server": f"Missing llama-server executable: {executable}"},
            }

        self._log_dir.mkdir(parents=True, exist_ok=True)
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

        for model_name in requested:
            config = self.configs.get(model_name)
            if config is None:
                results[model_name] = {"status": "error", "error": "Model not configured"}
                continue
            if self._is_managed_process_running(model_name):
                results[model_name] = {"status": "already-running"}
                continue

            model_path = Path(config.model_path)
            if not model_path.exists():
                results[model_name] = {"status": "error", "error": f"Missing model file: {model_path}"}
                continue

            log_path = self._log_dir / f"{model_name}.log"
            log_handle = open(log_path, "ab")
            try:
                process = subprocess.Popen(
                    self._build_launch_command(config),
                    cwd=ROOT,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    creationflags=creationflags,
                )
            except OSError as exc:
                log_handle.close()
                results[model_name] = {"status": "error", "error": str(exc)}
                continue

            self._managed_processes[model_name] = ManagedProcess(
                model_name=model_name,
                process=process,
                log_path=log_path,
                started_at=time.time(),
            )
            log_handle.close()
            results[model_name] = {
                "status": "started",
                "pid": process.pid,
                "log_path": str(log_path),
            }

        started = [name for name, result in results.items() if result.get("status") == "started"]
        skipped = [name for name, result in results.items() if result.get("status") == "already-running"]
        errors = {name: result.get("error") for name, result in results.items() if result.get("status") == "error"}
        return {"started": started, "skipped": skipped, "errors": errors, "details": results}

    def stop_configured_models(self, model_names: list[str] | None = None) -> dict[str, Any]:
        requested = model_names or list(self._managed_processes.keys())
        stopped: list[str] = []
        missing: list[str] = []
        errors: dict[str, str] = {}

        for model_name in requested:
            process_info = self._managed_processes.get(model_name)
            if process_info is None:
                missing.append(model_name)
                continue
            try:
                process_info.process.terminate()
                process_info.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process_info.process.kill()
                process_info.process.wait(timeout=5)
            except OSError as exc:
                errors[model_name] = str(exc)
                continue
            self._managed_processes.pop(model_name, None)
            stopped.append(model_name)

        return {"stopped": stopped, "missing": missing, "errors": errors}

    def get_runtime_status(self) -> dict[str, Any]:
        executable = self._get_llama_server_path()
        models: dict[str, Any] = {}
        for name, config in self.configs.items():
            managed = self._managed_processes.get(name)
            running = self._is_managed_process_running(name)
            models[name] = {
                "managed": managed is not None,
                "running": running,
                "pid": managed.process.pid if managed is not None and running else None,
                "log_path": str(managed.log_path) if managed is not None else str(self._log_dir / f"{name}.log"),
                "model_path": config.model_path,
                "model_path_exists": Path(config.model_path).exists(),
                "endpoint": config.endpoint,
            }

        return {
            "enabled": self._launcher_enabled(),
            "auto_start": self._launcher_should_autostart(),
            "shutdown_with_manager": self._launcher_should_stop_with_manager(),
            "llama_server_path": str(executable),
            "llama_server_exists": executable.exists(),
            "log_dir": str(self._log_dir),
            "models": models,
        }

    def _get_json(self, url: str, timeout: float = 5.0) -> dict[str, Any]:
        req = request.Request(url, method="GET")
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}

    def _post_json(self, url: str, payload: dict[str, Any], timeout: float = 30.0) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}

    def start_health_monitoring(self) -> None:
        if self._running:
            return

        if self._launcher_should_autostart():
            self.start_configured_models()
        self._run_health_checks()
        self._running = True
        self._health_thread = threading.Thread(
            target=self._health_monitor_loop,
            daemon=True,
            name="OpenChimera-LocalLLMHealth",
        )
        self._health_thread.start()

    def stop_health_monitoring(self) -> None:
        self._running = False
        if self._health_thread is not None:
            self._health_thread.join(timeout=5)
        if self._launcher_should_stop_with_manager():
            self.stop_configured_models()

    def _health_monitor_loop(self) -> None:
        while self._running:
            self._run_health_checks()
            time.sleep(self._health_check_interval)

    def _run_health_checks(self) -> None:
        for name, stats in self.models.items():
            self._check_model_health(name, stats)

    def _check_model_health(self, name: str, stats: ModelStats) -> None:
        start = time.time()
        try:
            self._get_json(f"{stats.endpoint}/health", timeout=5)
            latency = (time.time() - start) * 1000
            with self._lock:
                stats.status = "healthy"
                stats.last_check = time.time()
                request_count = max(stats.total_requests, 1)
                stats.avg_latency_ms = (stats.avg_latency_ms * request_count + latency) / (request_count + 1)
        except Exception:
            try:
                self._get_json(f"{stats.endpoint}/v1/models", timeout=5)
                latency = (time.time() - start) * 1000
                with self._lock:
                    stats.status = "healthy"
                    stats.last_check = time.time()
                    request_count = max(stats.total_requests, 1)
                    stats.avg_latency_ms = (stats.avg_latency_ms * request_count + latency) / (request_count + 1)
            except Exception as exc:
                with self._lock:
                    stats.status = "offline"
                    stats.last_check = time.time()
                LOGGER.debug("Health check failed for %s: %s", name, exc)

    def get_healthy_models(self) -> list[str]:
        return self.get_ranked_models(query_type="general", prefer_speed=False)

    def get_ranked_models(
        self,
        query_type: str = "general",
        prefer_speed: bool = False,
        exclude: list[str] | None = None,
        min_priority: int = 1,
        max_priority: int = 10,
    ) -> list[str]:
        exclude = set(exclude or [])
        candidates = []
        with self._lock:
            for name, stats in self.models.items():
                config = self.configs.get(name)
                if (
                    stats.status == "healthy"
                    and config is not None
                    and name not in exclude
                    and min_priority <= config.priority <= max_priority
                ):
                    score = self._score_candidate(name, stats, config, query_type=query_type, prefer_speed=prefer_speed)
                    candidates.append((score, config.priority, name))
        candidates.sort(key=lambda item: (item[0], item[1], item[2]))
        return [name for _, _, name in candidates]

    def _score_candidate(
        self,
        name: str,
        stats: ModelStats,
        config: ModelConfig,
        query_type: str,
        prefer_speed: bool,
    ) -> tuple[int, float, int]:
        capability_score = 0
        lowered = name.lower()
        if query_type == "fast":
            if any(token in lowered for token in ["3b", "mini", "phi"]):
                capability_score -= 5
        elif query_type == "code":
            if "qwen" in lowered:
                capability_score -= 5
        elif query_type == "reasoning":
            if "gemma" in lowered:
                capability_score -= 5

        latency = stats.avg_latency_ms if stats.avg_latency_ms > 0 else 999999.0
        speed_score = latency if prefer_speed else 0.0
        reliability_penalty = stats.failed_requests
        return (capability_score + reliability_penalty, speed_score, config.priority)

    def get_best_model(self, query_type: str = "general") -> str | None:
        ranked = self.get_ranked_models(
            query_type=query_type,
            prefer_speed=query_type in {"fast", "general"},
        )
        return ranked[0] if ranked else None

    def chat_completion(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        max_tokens: int = 256,
        temperature: float = 0.7,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        selected_model = model or self.get_best_model()
        if selected_model is None:
            return {"content": "", "model": None, "error": "No healthy local models available"}

        stats = self.models.get(selected_model)
        if stats is None:
            return {"content": "", "model": selected_model, "error": f"Model {selected_model} not configured"}

        payload = {
            "model": selected_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }

        try:
            start = time.time()
            data = self._post_json(f"{stats.endpoint}/v1/chat/completions", payload, timeout=timeout)
            latency = (time.time() - start) * 1000
            with self._lock:
                stats.total_requests += 1
                stats.avg_latency_ms = (
                    (stats.avg_latency_ms * (stats.total_requests - 1) + latency) / stats.total_requests
                )

            choices = data.get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content", "")
                usage = data.get("usage", {})
                completion_tokens = int(usage.get("completion_tokens", max(1, len(content) // 4)))
                elapsed_seconds = max(latency / 1000.0, 0.001)
                with self._lock:
                    stats.tokens_per_sec = completion_tokens / elapsed_seconds
                return {
                    "content": content,
                    "model": selected_model,
                    "usage": usage,
                    "latency_ms": latency,
                    "error": None,
                }
            return {"content": "", "model": selected_model, "error": "No choices in response"}
        except (error.URLError, error.HTTPError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            with self._lock:
                stats.total_requests += 1
                stats.failed_requests += 1
            return {"content": "", "model": selected_model, "error": str(exc)}

    def chat_completion_with_fallback(
        self,
        messages: list[dict[str, str]],
        query_type: str = "general",
        max_tokens: int = 256,
        temperature: float = 0.7,
        timeout: float = 30.0,
        max_retries: int = 2,
    ) -> dict[str, Any]:
        attempted: list[str] = []
        for _ in range(max_retries + 1):
            available = self.get_ranked_models(
                query_type=query_type,
                prefer_speed=query_type in {"fast", "general"},
                exclude=attempted,
            )
            if not available:
                break

            model = available[0]
            if model is None:
                break

            attempted.append(model)
            result = self.chat_completion(
                messages=messages,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout,
            )
            if result.get("content") and not result.get("error"):
                return result

        return {
            "content": "",
            "model": attempted[-1] if attempted else None,
            "error": f"All local models failed (tried: {', '.join(attempted)})",
        }

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "models": {
                    name: {
                        "status": stats.status,
                        "endpoint": stats.endpoint,
                        "avg_latency_ms": round(stats.avg_latency_ms, 2),
                        "tokens_per_sec": round(stats.tokens_per_sec, 2),
                        "total_requests": stats.total_requests,
                        "failed_requests": stats.failed_requests,
                        "vram_usage_gb": round(stats.vram_usage_gb, 2),
                        "quantization": stats.quantization,
                        "context_length": stats.context_length,
                        "config": {
                            "priority": self.configs[name].priority if name in self.configs else None,
                            "n_gpu_layers": self.configs[name].n_gpu_layers if name in self.configs else None,
                            "max_batch_size": self.configs[name].max_batch_size if name in self.configs else None,
                        },
                    }
                    for name, stats in self.models.items()
                },
                "healthy_count": sum(1 for stats in self.models.values() if stats.status == "healthy"),
                "total_count": len(self.models),
                "runtime": self.get_runtime_status(),
            }

    def add_model(self, config: ModelConfig) -> None:
        with self._lock:
            self.configs[config.name] = config
            self.models[config.name] = ModelStats(
                model_name=config.name,
                endpoint=config.endpoint,
                quantization=config.quantization,
                context_length=config.context_length,
            )

    def remove_model(self, name: str) -> None:
        with self._lock:
            self.models.pop(name, None)
            self.configs.pop(name, None)
        self._managed_processes.pop(name, None)