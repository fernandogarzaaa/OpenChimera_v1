from __future__ import annotations

from pathlib import Path
from typing import Any

from core.config import ROOT, get_appforge_root, get_legacy_workspace_root


MODEL_FILE_HINTS: dict[str, tuple[str, ...]] = {
    "phi-3.5-mini": ("phi-3.5-mini", "phi3.5-mini", "phi-3_5-mini", "phi3_5-mini", "phi-3-mini"),
    "llama-3.2-3b": ("llama-3.2-3b", "llama3.2-3b", "llama-3_2-3b", "llama3_2-3b"),
    "qwen2.5-7b": ("qwen2.5-7b", "qwen2_5-7b", "qwen-2.5-7b", "qwen-2_5-7b"),
    "gemma-2-9b": ("gemma-2-9b", "gemma2-9b", "gemma-2_9b"),
    "mistral-7b": ("mistral-7b", "mistral7b"),
    "llama-3.1-8b": ("llama-3.1-8b", "llama3.1-8b", "llama-3_1-8b", "llama3_1-8b"),
}


def _normalize_filename(name: str) -> str:
    return str(name).strip().lower().replace("_", "-")


def candidate_model_search_roots(profile: dict[str, Any]) -> list[Path]:
    model_inventory = profile.get("model_inventory", {}) if isinstance(profile.get("model_inventory", {}), dict) else {}
    roots: list[Path] = []

    models_dir = model_inventory.get("models_dir")
    if models_dir:
        roots.append(Path(str(models_dir)).expanduser())

    for raw_root in model_inventory.get("search_roots", []) if isinstance(model_inventory.get("search_roots", []), list) else []:
        if raw_root:
            roots.append(Path(str(raw_root)).expanduser())

    appforge_root = get_appforge_root()
    roots.extend(
        [
            ROOT / "models",
            Path(r"D:\models"),
            get_legacy_workspace_root() / "models",
            appforge_root / "models",
            appforge_root / "infrastructure" / "clawd-hybrid-rtx" / "models",
            appforge_root / "infrastructure" / "clawd-hybrid-rtx" / "src" / "models",
        ]
    )

    deduped: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        normalized = str(root)
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(root)
    return deduped


def _identify_model_name(file_path: Path, known_model_names: list[str]) -> str | None:
    normalized_name = _normalize_filename(file_path.stem)
    for model_name in known_model_names:
        for hint in MODEL_FILE_HINTS.get(model_name, (model_name,)):
            if _normalize_filename(hint) in normalized_name:
                return model_name
    return None


def identify_model_name_for_path(file_path: Path, known_model_names: list[str] | None = None) -> str | None:
    model_names = known_model_names or list(MODEL_FILE_HINTS)
    return _identify_model_name(file_path, model_names)


def discover_local_model_inventory(profile: dict[str, Any], known_model_names: list[str] | None = None) -> dict[str, Any]:
    candidate_roots = candidate_model_search_roots(profile)
    model_names = known_model_names or list(MODEL_FILE_HINTS)
    matched_model_files: dict[str, str] = {}
    discovered_files: list[str] = []
    scanned_roots: list[str] = []

    for root in candidate_roots:
        if not root.exists() or not root.is_dir():
            continue
        scanned_roots.append(str(root))
        for file_path in root.rglob("*.gguf"):
            discovered_files.append(str(file_path))
            matched_name = _identify_model_name(file_path, model_names)
            if matched_name and matched_name not in matched_model_files:
                matched_model_files[matched_name] = str(file_path)

    available_models = sorted(matched_model_files)
    return {
        "search_roots": [str(path) for path in candidate_roots],
        "scanned_roots": scanned_roots,
        "discovered_files": sorted(discovered_files),
        "model_files": matched_model_files,
        "available_models": available_models,
    }