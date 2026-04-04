"""OpenChimera harness port — port manifest stub."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List


@dataclass
class SubsystemManifest:
    name: str
    path: str
    file_count: int
    notes: str = ""


@dataclass
class PortManifest:
    total_python_files: int
    top_level_modules: List[SubsystemManifest] = field(default_factory=list)


def build_port_manifest(src_root: Path) -> PortManifest:
    """Build a manifest describing the harness port source tree."""
    modules = []
    total = 0
    if src_root.exists():
        for child in src_root.iterdir():
            if child.is_dir():
                py_files = list(child.glob("**/*.py"))
                total += len(py_files)
                modules.append(SubsystemManifest(
                    name=child.name,
                    path=str(child),
                    file_count=len(py_files),
                ))
    return PortManifest(total_python_files=total, top_level_modules=modules)
