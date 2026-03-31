from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def import_module_from_file(module_name: str, file_path: Path, repo_root: Path | None = None) -> ModuleType:
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"Module file not found: {file_path}")

    inserted_path = False
    if repo_root is not None:
        repo_root = Path(repo_root)
        repo_root_str = str(repo_root)
        if repo_root_str not in sys.path:
            sys.path.insert(0, repo_root_str)
            inserted_path = True

    try:
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Unable to create module spec for {file_path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        if inserted_path:
            sys.path.remove(str(repo_root))