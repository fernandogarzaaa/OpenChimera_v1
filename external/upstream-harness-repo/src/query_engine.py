"""OpenChimera harness port — query engine stub."""
from __future__ import annotations


class QueryEnginePort:
    """Minimal query engine for the harness port."""

    def __init__(self, manifest) -> None:
        self._manifest = manifest

    def render_summary(self) -> str:
        return (
            f"Harness port: {self._manifest.total_python_files} Python files, "
            f"{len(self._manifest.top_level_modules)} subsystems."
        )
