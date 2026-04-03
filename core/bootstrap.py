from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.config import (
    ROOT,
    default_runtime_profile,
    get_chimera_kb_path,
    get_rag_storage_path,
    get_runtime_profile_path,
    normalize_runtime_profile,
    save_runtime_profile,
)
from core.transactions import atomic_write_json


def build_default_directories(root: Path) -> list[Path]:
    return [
        root / "logs",
        root / "logs" / "local_llm",
        root / "logs" / "minimind",
        root / "data",
        root / "data" / "migrations",
        root / "data" / "autonomy",
        root / "data" / "minimind",
        root / "data" / "transactions",
        root / "memory",
        root / "checkpoints",
        root / "models",
        root / "sandbox",
        root / "sandbox" / "workspaces",
        root / "sandbox" / "artifacts",
    ]


def build_default_json_files(root: Path) -> dict[Path, Any]:
    return {
        root / "chimera_kb.json": [],
        root / "rag_storage.json": [],
        root / "memory" / "evo_memory.json": {},
        root / "data" / "autonomy" / "skill_audit.json": {"status": "bootstrap", "missing_skills": []},
        root / "data" / "autonomy" / "scouted_models_registry.json": {"status": "bootstrap", "models": []},
        root / "data" / "minimind" / "minimind_runtime_manifest.json": {"runtime": {}},
        root / "data" / "minimind" / "minimind_training_jobs.json": {},
        root / "data" / "onboarding_state.json": {"started_at": 0, "last_applied_at": None, "last_payload": {}, "steps": [], "completed": False},
        root / "data" / "browser_sessions.json": [],
        root / "data" / "plugins_state.json": {"installed": []},
        root / "data" / "subsystem_audit.json": {"events": []},
        root / "data" / "model_registry.json": {"status": "bootstrap", "providers": [], "local_models": [], "cloud_models": []},
    }


def bootstrap_workspace(root: Path | None = None) -> dict[str, Any]:
    workspace_root = root or ROOT
    created_directories: list[str] = []
    created_files: list[str] = []
    normalized_files: list[str] = []

    for directory in build_default_directories(workspace_root):
        if not directory.exists():
            directory.mkdir(parents=True, exist_ok=True)
            created_directories.append(str(directory))

    profile_path = workspace_root / "config" / "runtime_profile.json" if root is not None else get_runtime_profile_path()
    if profile_path.exists():
        try:
            current_profile = json.loads(profile_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            current_profile = default_runtime_profile()
            if root is None:
                save_runtime_profile(current_profile)
            else:
                profile_path.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_json(profile_path, current_profile)
            normalized_files.append(str(profile_path))
        else:
            normalized_profile, changed = normalize_runtime_profile(current_profile)
            if changed:
                if root is None:
                    save_runtime_profile(normalized_profile)
                else:
                    profile_path.parent.mkdir(parents=True, exist_ok=True)
                    atomic_write_json(profile_path, normalized_profile)
                normalized_files.append(str(profile_path))
    else:
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(profile_path, default_runtime_profile())
        created_files.append(str(profile_path))

    for file_path, default_content in build_default_json_files(workspace_root).items():
        if not file_path.exists():
            file_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(file_path, default_content)
            created_files.append(str(file_path))

    return {
        "status": "ok",
        "created_directories": created_directories,
        "created_files": created_files,
        "normalized_files": normalized_files,
        "workspace_root": str(workspace_root),
    }