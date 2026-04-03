from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, request

from core.bootstrap import bootstrap_workspace
from core.config import ROOT, default_runtime_profile


@dataclass(frozen=True)
class SandboxHTTPResponse:
    status_code: int
    payload: dict[str, Any]
    headers: dict[str, str]


class SandboxRuntimeSession:
    def __init__(
        self,
        prepared: dict[str, Any],
        process: subprocess.Popen[bytes],
        provider_base_url: str,
    ) -> None:
        self.prepared = prepared
        self.process = process
        self.provider_base_url = provider_base_url

    def get_json(self, path: str, token: str | None = None, timeout: float = 5.0) -> SandboxHTTPResponse:
        req = request.Request(
            f"{self.provider_base_url}{path}",
            headers=self._headers(token),
            method="GET",
        )
        return self._perform_json_request(req, timeout)

    def post_json(
        self,
        path: str,
        payload: dict[str, Any],
        token: str | None = None,
        timeout: float = 5.0,
    ) -> SandboxHTTPResponse:
        req = request.Request(
            f"{self.provider_base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(token, content_type="application/json"),
            method="POST",
        )
        return self._perform_json_request(req, timeout)

    def stop(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)

    def _headers(self, token: str | None = None, content_type: str | None = None) -> dict[str, str]:
        headers: dict[str, str] = {}
        if content_type:
            headers["Content-Type"] = content_type
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _perform_json_request(self, req: request.Request, timeout: float) -> SandboxHTTPResponse:
        try:
            with request.urlopen(req, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
                payload = json.loads(raw) if raw else {}
                headers = {key: value for key, value in response.headers.items()}
                return SandboxHTTPResponse(status_code=getattr(response, "status", 200), payload=payload, headers=headers)
        except error.HTTPError as exc:
            try:
                raw = exc.read().decode("utf-8")
                payload = json.loads(raw) if raw else {}
                headers = {key: value for key, value in exc.headers.items()} if exc.headers is not None else {}
                return SandboxHTTPResponse(status_code=exc.code, payload=payload, headers=headers)
            finally:
                exc.close()


def allocate_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def prepare_sandbox_workspace(destination: str | Path | None = None) -> dict[str, Any]:
    sandbox_root = Path(destination) if destination is not None else Path(tempfile.mkdtemp(prefix="openchimera-sandbox-"))
    if sandbox_root.exists() and any(sandbox_root.iterdir()):
        workspace_root = sandbox_root / "workspace"
    else:
        workspace_root = sandbox_root / "workspace"
    shutil.copytree(
        ROOT,
        workspace_root,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(
            ".git",
            ".venv",
            ".pytest_cache",
            "__pycache__",
            "*.pyc",
            "*.db",
            "*.db-shm",
            "*.db-wal",
            "build",
            "dist",
            "logs",
            "tmp_sandbox_debug",
            "tmp_sandbox_helper",
            "tmp_sandbox_timing",
            "tmp_session_test",
        ),
    )

    # Reset copied runtime state so sandbox tests exercise a clean first-boot install,
    # not the operator data from the source workspace.
    data_root = workspace_root / "data"
    if data_root.exists():
        for child in data_root.iterdir():
            if child.name == "migrations":
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    logs_root = workspace_root / "logs"
    if logs_root.exists():
        shutil.rmtree(logs_root)
    for transient_path in [workspace_root / "rag_storage.json", workspace_root / "chimera_kb.json"]:
        if transient_path.exists():
            transient_path.unlink()

    stubs_root = workspace_root / "sandbox" / "stubs"
    harness_src = stubs_root / "repos" / "upstream-harness-repo" / "src"
    harness_stub_files = {
        "main.py": "def main() -> int:\n    return 0\n",
        "port_manifest.py": (
            "from __future__ import annotations\n\n"
            "from dataclasses import dataclass\n"
            "from pathlib import Path\n\n"
            "@dataclass\n"
            "class Subsystem:\n"
            "    name: str\n"
            "    path: str\n"
            "    file_count: int\n"
            "    notes: str\n\n"
            "@dataclass\n"
            "class PortManifest:\n"
            "    total_python_files: int\n"
            "    top_level_modules: list[Subsystem]\n\n"
            "def build_port_manifest(src_root: Path) -> PortManifest:\n"
            "    modules = [Subsystem(name='sandbox', path=str(src_root), file_count=5, notes='sandbox harness stub')]\n"
            "    return PortManifest(total_python_files=5, top_level_modules=modules)\n"
        ),
        "query_engine.py": (
            "from __future__ import annotations\n\n"
            "class QueryEnginePort:\n"
            "    def __init__(self, manifest):\n"
            "        self.manifest = manifest\n\n"
            "    def render_summary(self) -> str:\n"
            "        return 'Sandbox harness stub summary'\n"
        ),
        "commands.py": (
            "from __future__ import annotations\n\n"
            "from dataclasses import dataclass\n\n"
            "@dataclass\n"
            "class ModuleEntry:\n"
            "    name: str\n"
            "    responsibility: str\n"
            "    source_hint: str\n"
            "    status: str\n\n"
            "@dataclass\n"
            "class Backlog:\n"
            "    modules: list[ModuleEntry]\n\n"
            "def build_command_backlog() -> Backlog:\n"
            "    return Backlog(modules=[ModuleEntry('sandbox-command', 'sandbox command surface', 'src/commands.py', 'stub')])\n"
        ),
        "tools.py": (
            "from __future__ import annotations\n\n"
            "from dataclasses import dataclass\n\n"
            "@dataclass\n"
            "class ModuleEntry:\n"
            "    name: str\n"
            "    responsibility: str\n"
            "    source_hint: str\n"
            "    status: str\n\n"
            "@dataclass\n"
            "class Backlog:\n"
            "    modules: list[ModuleEntry]\n\n"
            "def build_tool_backlog() -> Backlog:\n"
            "    return Backlog(modules=[ModuleEntry('sandbox-tool', 'sandbox tool surface', 'src/tools.py', 'stub')])\n"
        ),
    }
    for relative, content in harness_stub_files.items():
        path = harness_src / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    minimind_root = stubs_root / "openclaw" / "research" / "minimind"
    for relative in [
        "model/model_minimind.py",
        "scripts/serve_openai_api.py",
        "trainer/train_reason.py",
        "trainer/train_pretrain.py",
        "README.md",
    ]:
        path = minimind_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# sandbox stub\n", encoding="utf-8")

    (stubs_root / "openclaw" / "integrations" / "legacy-harness-snapshot").mkdir(parents=True, exist_ok=True)
    (stubs_root / "Project_AETHER").mkdir(parents=True, exist_ok=True)
    (stubs_root / "Project_Wraith").mkdir(parents=True, exist_ok=True)
    (stubs_root / "project-evo").mkdir(parents=True, exist_ok=True)

    profile_path = workspace_root / "config" / "runtime_profile.json"
    profile = default_runtime_profile()
    profile["local_runtime"]["launcher"]["enabled"] = False
    profile["local_runtime"]["reasoning_engine_config"]["python_executable"] = sys.executable
    profile["local_runtime"]["reasoning_engine_config"]["training_save_dir"] = str(workspace_root / "data" / "minimind")
    profile["model_inventory"]["models_dir"] = str(workspace_root / "models")
    profile_path.write_text(json.dumps(profile, indent=2), encoding="utf-8")

    env = {
        "OPENCHIMERA_SANDBOX": "1",
        "OPENCHIMERA_HOST": "127.0.0.1",
        "OPENCHIMERA_PORT": str(allocate_free_port()),
        "AETHER_ROOT": str(stubs_root / "Project_AETHER"),
        "WRAITH_ROOT": str(stubs_root / "Project_Wraith"),
        "EVO_ROOT": str(stubs_root / "project-evo"),
        "OPENCLAW_ROOT": str(stubs_root / "openclaw"),
        "AEGIS_ROOT": str(stubs_root / "openclaw" / "aegis_swarm"),
        "ASCENSION_ROOT": str(stubs_root / "openclaw" / "aegis_swarm"),
        "OPENCHIMERA_HARNESS_ROOT": str(stubs_root / "repos" / "upstream-harness-repo"),
        "OPENCHIMERA_LEGACY_HARNESS_ROOT": str(stubs_root / "openclaw" / "integrations" / "legacy-harness-snapshot"),
        "MINIMIND_ROOT": str(minimind_root),
        "OPENCHIMERA_MINIMIND_PYTHON": sys.executable,
    }

    return {
        "sandbox_root": str(sandbox_root),
        "workspace_root": str(workspace_root),
        "stubs_root": str(stubs_root),
        "environment": env,
    }


def simulate_installation(destination: str | Path | None = None) -> dict[str, Any]:
    prepared = prepare_sandbox_workspace(destination=destination)
    workspace_root = Path(prepared["workspace_root"])
    original_env = os.environ.copy()
    try:
        os.environ.update(prepared["environment"])
        os.chdir(workspace_root)
        report = bootstrap_workspace(root=workspace_root)
    finally:
        os.environ.clear()
        os.environ.update(original_env)
        os.chdir(ROOT)
    prepared["bootstrap"] = report
    return prepared


def simulate_installation_smoke_run(
    destination: str | Path | None = None,
    startup_timeout_seconds: float = 90.0,
    request_timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    prepared = simulate_installation(destination=destination)
    workspace_root = Path(prepared["workspace_root"])
    environment = os.environ.copy()
    environment.update(prepared["environment"])
    environment.setdefault("PYTHONIOENCODING", "utf-8")
    environment.setdefault("PYTHONUNBUFFERED", "1")

    provider_base_url = (
        f"http://{prepared['environment']['OPENCHIMERA_HOST']}:{prepared['environment']['OPENCHIMERA_PORT']}"
    )
    startup_log_path = workspace_root / "logs" / "sandbox-startup.log"
    startup_log_path.parent.mkdir(parents=True, exist_ok=True)
    startup_log = startup_log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "run.py", "serve"],
        cwd=workspace_root,
        env=environment,
        stdout=startup_log,
        stderr=subprocess.STDOUT,
    )

    def fetch_json(path: str) -> dict[str, Any] | None:
        try:
            with request.urlopen(f"{provider_base_url}{path}", timeout=request_timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            try:
                raw = exc.read().decode("utf-8")
                return json.loads(raw) if raw else None
            except json.JSONDecodeError:
                return None
            finally:
                exc.close()
        except (error.URLError, TimeoutError, json.JSONDecodeError, ConnectionResetError):
            return None

    try:
        deadline = time.time() + startup_timeout_seconds
        health_payload: dict[str, Any] | None = None
        readiness_payload: dict[str, Any] | None = None
        while time.time() < deadline:
            if process.poll() is not None:
                break
            health_payload = fetch_json("/health")
            readiness_payload = fetch_json("/v1/system/readiness")
            if (
                health_payload is not None
                and readiness_payload is not None
                and str(health_payload.get("status", "")).lower() == "online"
                and str(readiness_payload.get("status", "")).lower() in {"ready", "degraded"}
            ):
                break
            time.sleep(0.25)

        if health_payload is None or readiness_payload is None:
            raise RuntimeError(
                "OpenChimera sandbox smoke run did not expose health/readiness endpoints in time. "
                f"process_exit_code={process.poll()} provider_base_url={provider_base_url} startup_log={startup_log_path}"
            )

        system_status = fetch_json("/v1/system/status")
        prepared["smoke_run"] = {
            "status": "ok",
            "provider_base_url": provider_base_url,
            "health": health_payload,
            "readiness": readiness_payload,
            "system_status": system_status,
        }
        return prepared
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        startup_log.close()


@contextmanager
def start_sandbox_runtime(
    destination: str | Path | None = None,
    env_overrides: dict[str, str] | None = None,
    startup_timeout_seconds: float = 90.0,
    request_timeout_seconds: float = 5.0,
):
    prepared = simulate_installation(destination=destination)
    workspace_root = Path(prepared["workspace_root"])
    environment = os.environ.copy()
    environment.update(prepared["environment"])
    if env_overrides:
        environment.update({str(key): str(value) for key, value in env_overrides.items()})
    environment.setdefault("PYTHONIOENCODING", "utf-8")
    environment.setdefault("PYTHONUNBUFFERED", "1")

    provider_base_url = (
        f"http://{environment['OPENCHIMERA_HOST']}:{environment['OPENCHIMERA_PORT']}"
    )
    startup_log_path = workspace_root / "logs" / "sandbox-startup.log"
    startup_log_path.parent.mkdir(parents=True, exist_ok=True)
    startup_log = startup_log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "run.py", "serve"],
        cwd=workspace_root,
        env=environment,
        stdout=startup_log,
        stderr=subprocess.STDOUT,
    )
    session = SandboxRuntimeSession(prepared=prepared, process=process, provider_base_url=provider_base_url)

    deadline = time.time() + startup_timeout_seconds
    ready = False
    api_token = environment.get("OPENCHIMERA_API_TOKEN") or None
    while time.time() < deadline:
        if process.poll() is not None:
            break
        try:
            health = session.get_json("/health", timeout=request_timeout_seconds)
            readiness = session.get_json("/v1/system/readiness", timeout=request_timeout_seconds)
        except (error.URLError, ConnectionResetError, TimeoutError):
            time.sleep(0.25)
            continue
        jobs_ready = True
        if api_token:
            try:
                jobs_status = session.get_json("/v1/jobs/status", token=api_token, timeout=request_timeout_seconds)
            except (error.URLError, ConnectionResetError, TimeoutError):
                jobs_ready = False
            else:
                jobs_ready = jobs_status.status_code == 200 and bool(jobs_status.payload.get("running", False))
        if (
            health.status_code == 200
            and str(health.payload.get("status", "")).lower() == "online"
            and readiness.status_code in {200, 503}
            and jobs_ready
        ):
            ready = True
            break
        time.sleep(0.25)

    if not ready:
        session.stop()
        startup_log.close()
        raise RuntimeError(
            "OpenChimera sandbox runtime did not expose health/readiness endpoints in time. "
            f"process_exit_code={process.poll()} provider_base_url={provider_base_url} startup_log={startup_log_path}"
        )

    try:
        yield session
    finally:
        session.stop()
        startup_log.close()
