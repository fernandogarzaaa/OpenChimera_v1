"""OpenChimera harness port — tools backlog stub."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


@dataclass
class ToolModule:
    name: str
    responsibility: str = ""
    source_hint: str = ""
    status: str = "stub"


@dataclass
class ToolBacklog:
    modules: List[ToolModule] = field(default_factory=list)


def build_tool_backlog() -> ToolBacklog:
    """Return an empty tool backlog (stub implementation)."""
    return ToolBacklog(modules=[])
