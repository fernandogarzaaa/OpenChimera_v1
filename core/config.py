from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_AETHER_ROOT = Path(r"D:\Project AETHER")
DEFAULT_WRAITH_ROOT = Path(r"D:\Project Wraith")
DEFAULT_EVO_ROOT = Path(r"D:\project-evo")
DEFAULT_OPENCLAW_ROOT = Path(r"D:\openclaw")
DEFAULT_HARNESS_REPO_ROOT = Path(r"D:\repos\upstream-harness-repo")
DEFAULT_LEGACY_HARNESS_SNAPSHOT_ROOT = DEFAULT_OPENCLAW_ROOT / "integrations" / "legacy-harness-snapshot"
DEFAULT_MINIMIND_ROOT = Path(r"D:\openclaw\research\minimind")
DEFAULT_PROVIDER_HOST = "127.0.0.1"
DEFAULT_PROVIDER_PORT = 7870


@lru_cache(maxsize=None)
def resolve_root(env_var: str, default_path: Path) -> Path:
    configured = os.getenv(env_var)
    candidate = Path(configured) if configured else default_path
    return candidate.expanduser()


def get_aether_root() -> Path:
    return resolve_root("AETHER_ROOT", DEFAULT_AETHER_ROOT)


def get_wraith_root() -> Path:
    return resolve_root("WRAITH_ROOT", DEFAULT_WRAITH_ROOT)


def get_evo_root() -> Path:
    return resolve_root("EVO_ROOT", DEFAULT_EVO_ROOT)


def get_openclaw_root() -> Path:
    return resolve_root("OPENCLAW_ROOT", DEFAULT_OPENCLAW_ROOT)


def get_harness_repo_root() -> Path:
    configured = os.getenv("OPENCHIMERA_HARNESS_ROOT") or os.getenv("CLAUDE_CODE_ROOT")
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.exists():
            return candidate
    return DEFAULT_HARNESS_REPO_ROOT


def get_legacy_harness_snapshot_root() -> Path:
    configured = os.getenv("OPENCHIMERA_LEGACY_HARNESS_ROOT")
    return Path(configured).expanduser() if configured else DEFAULT_LEGACY_HARNESS_SNAPSHOT_ROOT


def get_minimind_root() -> Path:
    return resolve_root("MINIMIND_ROOT", DEFAULT_MINIMIND_ROOT)


def get_provider_host() -> str:
    return os.getenv("OPENCHIMERA_HOST", DEFAULT_PROVIDER_HOST)


def get_provider_port() -> int:
    raw_port = os.getenv("OPENCHIMERA_PORT", str(DEFAULT_PROVIDER_PORT))
    try:
        return int(raw_port)
    except ValueError:
        return DEFAULT_PROVIDER_PORT


def get_provider_base_url() -> str:
    return f"http://{get_provider_host()}:{get_provider_port()}"


def get_chimera_kb_path() -> Path:
    return ROOT / "chimera_kb.json"


def get_rag_storage_path() -> Path:
    return ROOT / "rag_storage.json"


def get_minimind_training_output_dir() -> Path:
    profile = load_runtime_profile()
    configured = (
        profile.get("reasoning_engine", {}).get("training_output_dir")
        or profile.get("local_runtime", {}).get("reasoning_engine_config", {}).get("training_output_dir")
    )
    if configured:
        return Path(configured)
    return ROOT / "data" / "minimind"


@lru_cache(maxsize=1)
def load_runtime_profile() -> dict[str, Any]:
    profile_path = ROOT / "config" / "runtime_profile.json"
    if not profile_path.exists():
        return {}

    try:
        return json.loads(profile_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def get_watch_files() -> list[str]:
    preferred = [
        ROOT / "README.md",
        get_chimera_kb_path(),
        get_rag_storage_path(),
        ROOT / "config" / "runtime_profile.json",
        ROOT / "memory" / "evo_memory.json",
    ]

    watch_files: list[str] = []
    for path in preferred:
        if path.exists():
            watch_files.append(str(path))
    return watch_files


def build_identity_snapshot() -> dict[str, Any]:
    runtime_profile = load_runtime_profile()
    hardware = runtime_profile.get("hardware", {})
    local_runtime = runtime_profile.get("local_runtime", {})
    model_inventory = runtime_profile.get("model_inventory", {})
    reasoning_engine = local_runtime.get("reasoning_engine", "unknown")
    return {
        "root": str(ROOT),
        "provider_url": get_provider_base_url(),
        "watch_files": get_watch_files(),
        "hardware": hardware,
        "local_runtime": local_runtime,
        "reasoning_engine": reasoning_engine,
        "launcher": local_runtime.get("launcher", {}),
        "model_inventory": model_inventory,
        "external_roots": {
            "aether": str(get_aether_root()),
            "wraith": str(get_wraith_root()),
            "evo": str(get_evo_root()),
            "openclaw": str(get_openclaw_root()),
        },
        "integration_roots": {
            "harness_repo": str(get_harness_repo_root()),
            "legacy_harness_snapshot": str(get_legacy_harness_snapshot_root()),
            "minimind": str(get_minimind_root()),
            "minimind_training_output": str(get_minimind_training_output_dir()),
        },
    }