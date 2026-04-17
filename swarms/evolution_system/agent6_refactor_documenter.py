"""Agent 6 — RefactorDocumenter: refactors large files and updates README."""
from __future__ import annotations

import ast
import logging
from pathlib import Path

from swarms.audit_system.chimera_client import ChimeraClient
from swarms.evolution_system.models import RefactorLog, RefactorRecord

log = logging.getLogger(__name__)

# Files > 800 LOC that should be decomposed
_DECOMPOSE_TARGETS = [
    "core/setup_wizard.py",
    "core/api_server.py",
    "core/provider.py",
]

# Core modules that lack type hints on most public functions
_TYPE_HINT_TARGETS = [
    "core/transactions.py",
    "core/plugins.py",
    "core/personality.py",
    "core/mcp_normalization.py",
    "core/health_monitor.py",
    "core/schemas.py",
]


class RefactorDocumenter:
    """Analyzes refactor opportunities and updates README. Does not rewrite production code — logs intent."""

    def __init__(
        self,
        workspace: str,
        dry_run: bool = True,
        chimera: ChimeraClient | None = None,
    ) -> None:
        self.workspace = Path(workspace)
        self.dry_run = dry_run
        self.chimera = chimera or ChimeraClient()

    def _count_lines(self, rel_path: str) -> int:
        p = self.workspace / rel_path
        if not p.exists():
            return 0
        return len(p.read_text(encoding="utf-8", errors="ignore").splitlines())

    def _has_type_hints(self, rel_path: str) -> bool:
        """Return True if most public functions already have return annotations."""
        p = self.workspace / rel_path
        if not p.exists():
            return True
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            return True
        funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")]
        if not funcs:
            return True
        annotated = sum(1 for f in funcs if f.returns is not None)
        return annotated / len(funcs) >= 0.7

    async def _update_readme(self) -> RefactorRecord:
        readme = self.workspace / "README.md"
        if not readme.exists():
            return RefactorRecord(file_path="README.md", action="readme_update", notes="README.md not found")

        content = readme.read_text(encoding="utf-8")
        lines_before = len(content.splitlines())

        agi_section = """
## AGI Capability Expansions

OpenChimera integrates patterns and dependencies from leading open-source AGI projects:

| Capability | Source | Integration |
|-----------|--------|-------------|
| Long-term memory | MemGPT patterns | `core/memory.py` tiered storage |
| Stateful agent graphs | LangGraph patterns | `SwarmOrchestrator` state machine |
| Causal inference | DoWhy (`[ml]` extra) | `core/causal_reasoning.py` |
| Advanced RAG | LlamaIndex (`[ml]` extra) | `core/rag.py` hybrid retrieval |
| Prompt optimization | DSPy (`[ml]` extra) | Chimera gate prompt compilation |
| Task decomposition | AutoGen patterns | God Swarm agent handoff |

Install all ML extras: `pip install "openchimera[ml]"`
"""
        if "AGI Capability Expansions" not in content:
            if self.dry_run:
                log.info("[RefactorDocumenter] DRY-RUN: would append AGI section to README.md")
            else:
                readme.write_text(content + agi_section)
                log.info("[RefactorDocumenter] Updated README.md with AGI capabilities section")

        lines_after = lines_before + len(agi_section.splitlines()) if "AGI Capability Expansions" not in content else lines_before
        return RefactorRecord(
            file_path="README.md",
            action="readme_update",
            lines_before=lines_before,
            lines_after=lines_after,
            notes="Added AGI Capability Expansions section",
        )

    async def run_async(self, run_id: str, artifacts_dir: Path) -> RefactorLog:
        log.info("[RefactorDocumenter] Analyzing refactor opportunities (dry_run=%s, run_id=%s)", self.dry_run, run_id)
        records: list[RefactorRecord] = []

        # 1. Decomposition candidates
        for rel_path in _DECOMPOSE_TARGETS:
            lines = self._count_lines(rel_path)
            if lines > 800:
                records.append(RefactorRecord(
                    file_path=rel_path,
                    action="split",
                    lines_before=lines,
                    lines_after=lines,
                    notes=f"{lines} LOC — flagged for decomposition into sub-modules (manual task)",
                ))
                log.info("[RefactorDocumenter] Decompose candidate: %s (%d LOC)", rel_path, lines)

        # 2. Type hint gaps
        for rel_path in _TYPE_HINT_TARGETS:
            if not self._has_type_hints(rel_path):
                lines = self._count_lines(rel_path)
                records.append(RefactorRecord(
                    file_path=rel_path,
                    action="type_hints",
                    lines_before=lines,
                    lines_after=lines,
                    notes="<70% of public functions have return annotations (flagged for type hint pass)",
                ))
                log.info("[RefactorDocumenter] Type hint gap: %s", rel_path)

        # 3. README update
        readme_record = await self._update_readme()
        records.append(readme_record)

        # Chimera audit on refactor plan
        audit_result = await self.chimera.audit("refactor", {
            "decompose_candidates": len([r for r in records if r.action == "split"]),
            "type_hint_gaps": len([r for r in records if r.action == "type_hints"]),
            "readme_updated": any(r.action == "readme_update" for r in records),
        })
        log.info("[RefactorDocumenter] Refactor trust score: %.2f", audit_result.get("trust_score", 1.0))

        log_obj = RefactorLog(run_id=run_id, records=records)
        out = artifacts_dir / "refactor_log.json"
        out.write_text(log_obj.model_dump_json(indent=2))

        log.info("[RefactorDocumenter] Done: %d refactor records", len(records))
        return log_obj

    def run(self, run_id: str, artifacts_dir: Path) -> RefactorLog:
        import asyncio
        return asyncio.run(self.run_async(run_id, artifacts_dir))
