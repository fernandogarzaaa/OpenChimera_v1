from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, request

from core.config import ROOT, load_runtime_profile
from core.local_model_inventory import discover_local_model_inventory
from core.resilience import retry_call
from core.transactions import atomic_write_json


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
        self._route_memory_path = ROOT / "data" / "local_llm_route_memory.json"
        self._route_memory = self._load_route_memory()
        self._discovered_inventory = discover_local_model_inventory(self.profile)
        self._initialize_defaults()

    def _initialize_defaults(self) -> None:
        local_runtime = self.profile.get("local_runtime", {})
        model_inventory = self.profile.get("model_inventory", {})
        configured_available_models = list(model_inventory.get("available_models") or [])
        discovered_available_models = list(self._discovered_inventory.get("available_models") or [])
        available_models = configured_available_models + [
            model_name for model_name in discovered_available_models if model_name not in configured_available_models
        ] or [
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
        discovered_model_files = self._discovered_inventory.get("model_files", {}) if isinstance(self._discovered_inventory, dict) else {}
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
                model_path=str(self._resolve_model_path(models_dir, model_name, model_files.get(model_name), discovered_model_files.get(model_name))),
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

    def _resolve_model_path(self, models_dir: str, model_name: str, configured_file: str | None, discovered_file: str | None = None) -> Path:
        base_dir = Path(models_dir)
        if configured_file:
            candidate = Path(configured_file)
            resolved = candidate if candidate.is_absolute() else base_dir / candidate
            if resolved.exists() or not discovered_file:
                return resolved

        if discovered_file:
            return Path(discovered_file)

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
            "route_memory_path": str(self._route_memory_path),
            "discovery": self._discovered_inventory,
            "models": models,
        }

    def _get_json(self, url: str, timeout: float = 5.0) -> dict[str, Any]:
        def _fetch() -> dict[str, Any]:
            req = request.Request(url, method="GET")
            with request.urlopen(req, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}

        return retry_call(_fetch, attempts=2, delay_seconds=0.15, retry_exceptions=(error.URLError, TimeoutError, json.JSONDecodeError))

    def _post_json(self, url: str, payload: dict[str, Any], timeout: float = 30.0) -> dict[str, Any]:
        def _send() -> dict[str, Any]:
            body = json.dumps(payload).encode("utf-8")
            req = request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
            with request.urlopen(req, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}

        return retry_call(_send, attempts=2, delay_seconds=0.2, retry_exceptions=(error.URLError, TimeoutError, json.JSONDecodeError))

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
            route_memory_snapshot = json.loads(json.dumps(self._route_memory))
            for name, stats in self.models.items():
                config = self.configs.get(name)
                if (
                    stats.status == "healthy"
                    and config is not None
                    and name not in exclude
                    and min_priority <= config.priority <= max_priority
                ):
                    score = self._score_candidate(
                        name,
                        stats,
                        config,
                        query_type=query_type,
                        prefer_speed=prefer_speed,
                        route_memory_snapshot=route_memory_snapshot,
                    )
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
        route_memory_snapshot: dict[str, Any],
    ) -> tuple[int, float, int]:
        capability_score = 0
        lowered = name.lower()
        affinity_map = {
            "fast": {
                "phi": -8,
                "mini": -6,
                "3b": -5,
                "qwen": -3,
                "gemma": 0,
            },
            "general": {
                "qwen": -5,
                "llama": -4,
                "phi": -2,
                "gemma": -1,
            },
            "code": {
                "qwen": -7,
                "llama": -4,
                "phi": -1,
                "gemma": 1,
            },
            "reasoning": {
                "llama": -7,
                "qwen": -5,
                "gemma": -2,
                "phi": 1,
            },
        }
        for token, delta in affinity_map.get(query_type, {}).items():
            if token in lowered:
                capability_score += delta

        latency = stats.avg_latency_ms if stats.avg_latency_ms > 0 else 999999.0
        speed_score = latency if prefer_speed else latency * 0.15
        failure_ratio = (stats.failed_requests / stats.total_requests) if stats.total_requests else 0.0
        reliability_penalty = (stats.failed_requests * 4) + int(failure_ratio * 20)
        adaptive_penalty = self._adaptive_penalty(name, query_type, route_memory_snapshot)
        return (capability_score + reliability_penalty + adaptive_penalty, speed_score, config.priority)

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
        query_type: str = "general",
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

        route_memory_snapshot = self.get_route_memory()
        primary_strategy = self._preferred_prompt_strategy(selected_model, query_type, route_memory_snapshot)
        strategy_order = [primary_strategy]
        alternate_strategy = self._alternate_prompt_strategy(primary_strategy)
        if alternate_strategy is not None and alternate_strategy not in strategy_order:
            strategy_order.append(alternate_strategy)

        last_error = "No choices in response"
        last_usage: dict[str, Any] = {}
        last_latency_ms: float | None = None
        last_strategy = primary_strategy
        low_quality_failure = False

        for prompt_strategy in strategy_order:
            last_strategy = prompt_strategy
            payload = {
                "model": selected_model,
                "messages": self._build_model_messages(selected_model, messages, query_type, prompt_strategy=prompt_strategy),
                "max_tokens": max_tokens,
                "temperature": temperature,
                "stream": False,
            }
            try:
                start = time.time()
                data = self._post_json(f"{stats.endpoint}/v1/chat/completions", payload, timeout=timeout)
                latency = (time.time() - start) * 1000
                last_latency_ms = latency
                with self._lock:
                    stats.total_requests += 1
                    stats.avg_latency_ms = (
                        (stats.avg_latency_ms * (stats.total_requests - 1) + latency) / stats.total_requests
                    )

                choices = data.get("choices", [])
                if not choices:
                    last_error = "No choices in response"
                    self._record_prompt_strategy_outcome(
                        selected_model,
                        query_type,
                        prompt_strategy,
                        success=False,
                        low_quality=False,
                    )
                    continue

                raw_content = choices[0].get("message", {}).get("content", "")
                content = self._sanitize_generated_content(raw_content)
                usage = data.get("usage", {})
                last_usage = usage
                completion_tokens = int(usage.get("completion_tokens", max(1, len(content) // 4)))
                elapsed_seconds = max(latency / 1000.0, 0.001)
                with self._lock:
                    stats.tokens_per_sec = completion_tokens / elapsed_seconds
                if not self._is_usable_completion(content):
                    last_error = "Low-quality local model response"
                    low_quality_failure = True
                    self._record_prompt_strategy_outcome(
                        selected_model,
                        query_type,
                        prompt_strategy,
                        success=False,
                        low_quality=True,
                    )
                    continue

                self._record_prompt_strategy_outcome(
                    selected_model,
                    query_type,
                    prompt_strategy,
                    success=True,
                    low_quality=False,
                )
                self._record_route_outcome(selected_model, query_type, success=True, latency_ms=latency, low_quality=False)
                return {
                    "content": content,
                    "model": selected_model,
                    "query_type": query_type,
                    "prompt_strategy": prompt_strategy,
                    "prompt_strategies_tried": strategy_order[: strategy_order.index(prompt_strategy) + 1],
                    "usage": usage,
                    "latency_ms": latency,
                    "error": None,
                }
            except (error.URLError, error.HTTPError, TimeoutError, json.JSONDecodeError, OSError) as exc:
                with self._lock:
                    stats.total_requests += 1
                last_error = str(exc)
                low_quality_failure = False
                self._record_prompt_strategy_outcome(
                    selected_model,
                    query_type,
                    prompt_strategy,
                    success=False,
                    low_quality=False,
                )
                break

        with self._lock:
            stats.failed_requests += 1
        self._record_route_outcome(
            selected_model,
            query_type,
            success=False,
            latency_ms=last_latency_ms,
            low_quality=low_quality_failure,
        )
        return {
            "content": "",
            "model": selected_model,
            "query_type": query_type,
            "prompt_strategy": last_strategy,
            "prompt_strategies_tried": strategy_order,
            "usage": last_usage,
            "latency_ms": last_latency_ms,
            "error": last_error,
        }

    def get_route_memory(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._route_memory))

    def _flatten_messages(self, messages: list[dict[str, str]]) -> str:
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

    def _build_model_messages(
        self,
        model_name: str,
        messages: list[dict[str, str]],
        query_type: str,
        prompt_strategy: str | None = None,
    ) -> list[dict[str, str]]:
        lowered = model_name.lower()
        style_instruction = (
            "Respond in plain text. Be concrete and concise. Avoid markdown fences, bullet skeletons, placeholders, or role labels."
        )
        if query_type == "reasoning":
            style_instruction += " For analysis, give a short direct explanation before any examples or details."
        elif query_type == "code":
            style_instruction += " If code is needed, provide only the minimal code and one short explanation."
        elif query_type == "fast":
            style_instruction += " Keep the answer very short."

        strategy = prompt_strategy or self._prompt_strategy_for_model(model_name)
        simplified_model = strategy == "flattened_plaintext"
        if simplified_model:
            flattened = self._flatten_messages(messages)
            return [
                {
                    "role": "user",
                    "content": style_instruction + "\n\n" + flattened,
                }
            ]

        merged_system: list[str] = []
        passthrough_messages: list[dict[str, str]] = []
        for item in messages:
            role = str(item.get("role", "user"))
            content = str(item.get("content", "")).strip()
            if not content:
                continue
            if role == "system":
                merged_system.append(content)
                continue
            passthrough_messages.append({"role": role, "content": content})

        system_content = "\n\n".join(part for part in [style_instruction, *merged_system] if part)
        if passthrough_messages:
            return [{"role": "system", "content": system_content}, *passthrough_messages]
        return [{"role": "user", "content": system_content}]

    def _prompt_strategy_for_model(self, model_name: str) -> str:
        lowered = model_name.lower()
        if any(token in lowered for token in ["phi", "mini", "3b"]):
            return "flattened_plaintext"
        return "chat_guided"

    def _preferred_prompt_strategy(
        self,
        model_name: str,
        query_type: str,
        route_memory_snapshot: dict[str, Any],
    ) -> str:
        default_strategy = self._prompt_strategy_for_model(model_name)
        bucket = route_memory_snapshot.get(model_name, {}).get(query_type, {})
        strategy_stats = bucket.get("prompt_strategies", {})
        if not isinstance(strategy_stats, dict) or not strategy_stats:
            return default_strategy

        candidates = [default_strategy]
        alternate = self._alternate_prompt_strategy(default_strategy)
        if alternate is not None:
            candidates.append(alternate)

        scored_candidates: list[tuple[float, int, str]] = []
        for strategy in candidates:
            stats = strategy_stats.get(strategy, {})
            successes = int(stats.get("successes", 0))
            failures = int(stats.get("failures", 0))
            low_quality_failures = int(stats.get("low_quality_failures", 0))
            events = successes + failures
            score = self._prompt_strategy_penalty(stats)
            scored_candidates.append((score, -events, strategy))

        scored_candidates.sort(key=lambda item: (item[0], item[1], item[2]))
        best_score, _, best_strategy = scored_candidates[0]
        default_stats = strategy_stats.get(default_strategy, {})
        default_successes = int(default_stats.get("successes", 0))
        default_failures = int(default_stats.get("failures", 0))
        default_events = default_successes + default_failures
        best_stats = strategy_stats.get(best_strategy, {})
        best_successes = int(best_stats.get("successes", 0))
        best_failures = int(best_stats.get("failures", 0))
        best_events = best_successes + best_failures

        if best_strategy == default_strategy:
            return default_strategy
        if best_events == 0 or best_successes == 0:
            return default_strategy
        default_score = self._prompt_strategy_penalty(default_stats)
        if default_events == 0:
            return best_strategy
        if best_score + 0.75 < default_score:
            return best_strategy
        return default_strategy

    def _alternate_prompt_strategy(self, prompt_strategy: str) -> str | None:
        if prompt_strategy == "flattened_plaintext":
            return "chat_guided"
        if prompt_strategy == "chat_guided":
            return "flattened_plaintext"
        return None

    def _sanitize_generated_content(self, content: str) -> str:
        cleaned = content.replace("\r\n", "\n").strip()
        cleaned = re.sub(r"^```(?:[a-zA-Z0-9_+-]+)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
        return cleaned

    def _is_usable_completion(self, content: str) -> bool:
        if not content:
            return False
        stripped = content.strip()
        if len(stripped) < 3:
            return False
        if stripped.startswith("###") or stripped.startswith("- "):
            return False
        if stripped.count("\n") > 10 and len(stripped) < 120:
            return False
        alnum_count = sum(char.isalnum() for char in stripped)
        if alnum_count < 4:
            return False
        unique_chars = set(stripped)
        if len(unique_chars) <= 3 and len(stripped) >= 10:
            return False
        longest_run = 1
        current_run = 1
        for previous, current in zip(stripped, stripped[1:]):
            if previous == current:
                current_run += 1
                longest_run = max(longest_run, current_run)
            else:
                current_run = 1
        if longest_run >= 14:
            return False
        if re.fullmatch(r"[\W_]+", stripped) is not None:
            return False
        return True

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
                query_type=query_type,
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
            models_snapshot = {
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
            }
            healthy_count = sum(1 for stats in self.models.values() if stats.status == "healthy")
            total_count = len(self.models)
            route_memory = json.loads(json.dumps(self._route_memory))
        return {
            "models": models_snapshot,
            "healthy_count": healthy_count,
            "total_count": total_count,
            "runtime": self.get_runtime_status(),
            "route_memory": route_memory,
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

    def _load_route_memory(self) -> dict[str, Any]:
        if not self._route_memory_path.exists():
            return {}
        try:
            raw = json.loads(self._route_memory_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        if not isinstance(raw, dict):
            return {}
        return self._normalize_route_memory(raw)

    def _persist_route_memory(self) -> None:
        self._route_memory_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self._route_memory_path, self._route_memory)

    def _get_route_bucket(self, model_name: str, query_type: str) -> dict[str, Any]:
        model_bucket = self._route_memory.setdefault(model_name, {})
        return model_bucket.setdefault(
            query_type,
            {
                "successes": 0,
                "failures": 0,
                "low_quality_failures": 0,
                "avg_latency_ms": 0.0,
                "last_success_at": 0.0,
                "last_failure_at": 0.0,
                "prompt_strategies": {
                    "chat_guided": self._new_prompt_strategy_bucket(),
                    "flattened_plaintext": self._new_prompt_strategy_bucket(),
                },
            },
        )

    def _new_prompt_strategy_bucket(self) -> dict[str, Any]:
        return {
            "successes": 0,
            "failures": 0,
            "low_quality_failures": 0,
            "last_success_at": 0.0,
            "last_failure_at": 0.0,
        }

    def _normalize_route_memory(self, raw: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for model_name, query_buckets in raw.items():
            if not isinstance(query_buckets, dict):
                continue
            normalized[model_name] = {}
            for query_type, bucket in query_buckets.items():
                if not isinstance(bucket, dict):
                    continue
                prompt_strategies = bucket.get("prompt_strategies")
                if not isinstance(prompt_strategies, dict):
                    prompt_strategies = {}
                normalized[model_name][query_type] = {
                    "successes": int(bucket.get("successes", 0)),
                    "failures": int(bucket.get("failures", 0)),
                    "low_quality_failures": int(bucket.get("low_quality_failures", 0)),
                    "avg_latency_ms": float(bucket.get("avg_latency_ms", 0.0)),
                    "last_success_at": float(bucket.get("last_success_at", 0.0)),
                    "last_failure_at": float(bucket.get("last_failure_at", 0.0)),
                    "prompt_strategies": {
                        "chat_guided": self._normalize_prompt_strategy_bucket(prompt_strategies.get("chat_guided")),
                        "flattened_plaintext": self._normalize_prompt_strategy_bucket(prompt_strategies.get("flattened_plaintext")),
                    },
                }
        return normalized

    def _normalize_prompt_strategy_bucket(self, bucket: Any) -> dict[str, Any]:
        if not isinstance(bucket, dict):
            return self._new_prompt_strategy_bucket()
        return {
            "successes": int(bucket.get("successes", 0)),
            "failures": int(bucket.get("failures", 0)),
            "low_quality_failures": int(bucket.get("low_quality_failures", 0)),
            "last_success_at": float(bucket.get("last_success_at", 0.0)),
            "last_failure_at": float(bucket.get("last_failure_at", 0.0)),
        }

    def _record_prompt_strategy_outcome(
        self,
        model_name: str,
        query_type: str,
        prompt_strategy: str,
        success: bool,
        low_quality: bool,
    ) -> None:
        with self._lock:
            bucket = self._get_route_bucket(model_name, query_type)
            strategy_buckets = bucket.setdefault("prompt_strategies", {})
            strategy_bucket = strategy_buckets.setdefault(prompt_strategy, self._new_prompt_strategy_bucket())
            timestamp = time.time()
            if success:
                strategy_bucket["successes"] += 1
                strategy_bucket["last_success_at"] = timestamp
            else:
                strategy_bucket["failures"] += 1
                strategy_bucket["last_failure_at"] = timestamp
                if low_quality:
                    strategy_bucket["low_quality_failures"] += 1
            self._persist_route_memory()

    def _prompt_strategy_penalty(self, strategy_stats: dict[str, Any]) -> float:
        successes = int(strategy_stats.get("successes", 0))
        failures = int(strategy_stats.get("failures", 0))
        low_quality_failures = int(strategy_stats.get("low_quality_failures", 0))
        if successes == 0 and failures == 0:
            return 0.0
        recent_success_factor = self._recency_factor(
            strategy_stats.get("last_success_at"),
            fresh_seconds=6 * 3600,
            stale_seconds=7 * 24 * 3600,
        )
        recent_failure_factor = self._recency_factor(
            strategy_stats.get("last_failure_at"),
            fresh_seconds=6 * 3600,
            stale_seconds=7 * 24 * 3600,
        )
        penalty = (failures * (1.0 + recent_failure_factor)) + (low_quality_failures * (2.0 + recent_failure_factor))
        bonus = min(successes, 5) * max(recent_success_factor, 0.25)
        return penalty - bonus

    def _record_route_outcome(
        self,
        model_name: str,
        query_type: str,
        success: bool,
        latency_ms: float | None,
        low_quality: bool,
    ) -> None:
        with self._lock:
            bucket = self._get_route_bucket(model_name, query_type)
            timestamp = time.time()
            if success:
                bucket["successes"] += 1
                bucket["last_success_at"] = timestamp
            else:
                bucket["failures"] += 1
                bucket["last_failure_at"] = timestamp
                if low_quality:
                    bucket["low_quality_failures"] += 1
            if latency_ms is not None:
                total = bucket["successes"] + bucket["failures"]
                previous_weight = max(total - 1, 0)
                current = float(bucket.get("avg_latency_ms", 0.0))
                bucket["avg_latency_ms"] = (
                    ((current * previous_weight) + float(latency_ms)) / max(total, 1)
                )
            self._persist_route_memory()

    def _recency_factor(self, last_timestamp: float | int | None, *, fresh_seconds: float, stale_seconds: float) -> float:
        if not last_timestamp:
            return 0.0
        age_seconds = max(time.time() - float(last_timestamp), 0.0)
        if age_seconds <= fresh_seconds:
            return 1.0
        if age_seconds >= stale_seconds:
            return 0.15
        span = max(stale_seconds - fresh_seconds, 1.0)
        remaining = max(stale_seconds - age_seconds, 0.0)
        return 0.15 + 0.85 * (remaining / span)

    def _adaptive_penalty(self, model_name: str, query_type: str, route_memory_snapshot: dict[str, Any]) -> float:
        model_memory = route_memory_snapshot.get(model_name, {})
        bucket = model_memory.get(query_type, {})
        successes = int(bucket.get("successes", 0))
        failures = int(bucket.get("failures", 0))
        low_quality_failures = int(bucket.get("low_quality_failures", 0))
        if successes == 0 and failures == 0:
            return 0
        recent_success_factor = self._recency_factor(
            bucket.get("last_success_at"),
            fresh_seconds=6 * 3600,
            stale_seconds=7 * 24 * 3600,
        )
        recent_failure_factor = self._recency_factor(
            bucket.get("last_failure_at"),
            fresh_seconds=6 * 3600,
            stale_seconds=7 * 24 * 3600,
        )
        penalty = (failures * (1.5 + recent_failure_factor)) + (low_quality_failures * (2.5 + recent_failure_factor))
        bonus = min(successes, 6) * max(recent_success_factor, 0.25)
        return penalty - bonus