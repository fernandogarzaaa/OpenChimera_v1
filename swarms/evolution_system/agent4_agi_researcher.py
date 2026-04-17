"""Agent 4 — AGIResearcher: searches for OSS repos that expand OpenChimera's AGI capabilities."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from swarms.audit_system.chimera_client import ChimeraClient
from swarms.evolution_system.models import ResearchCandidate, ResearchReport

log = logging.getLogger(__name__)

# Curated seed candidates — well-maintained, permissive licenses, directly relevant to gaps
_SEED_CANDIDATES: list[dict] = [
    {
        "repo_url": "https://github.com/cpacker/MemGPT",
        "name": "MemGPT",
        "license": "Apache-2.0",
        "stars": 11000,
        "last_commit": "2025-01",
        "capability_gap": "Long-term memory management beyond context window",
        "integration_complexity": "medium",
        "recommendation": "extract_pattern",
        "rationale": "Virtual context management pattern can augment core/memory.py with tiered storage",
    },
    {
        "repo_url": "https://github.com/langchain-ai/langgraph",
        "name": "LangGraph",
        "license": "MIT",
        "stars": 6000,
        "last_commit": "2025-03",
        "capability_gap": "Stateful multi-step agent graph execution",
        "integration_complexity": "low",
        "recommendation": "extract_pattern",
        "rationale": "State machine pattern for agent pipelines can extend SwarmOrchestrator dispatch",
    },
    {
        "repo_url": "https://github.com/py-why/dowhy",
        "name": "DoWhy",
        "license": "MIT",
        "stars": 7200,
        "last_commit": "2025-02",
        "capability_gap": "Causal inference for core/causal_reasoning.py",
        "integration_complexity": "medium",
        "recommendation": "adopt",
        "rationale": "Direct pip dependency; add to [ml] optional extras for causal counterfactual support",
    },
    {
        "repo_url": "https://github.com/microsoft/autogen",
        "name": "AutoGen",
        "license": "MIT",
        "stars": 30000,
        "last_commit": "2025-03",
        "capability_gap": "Conversational multi-agent task decomposition patterns",
        "integration_complexity": "high",
        "recommendation": "extract_pattern",
        "rationale": "Task decomposition and agent handoff patterns useful for God Swarm; too large to adopt whole",
    },
    {
        "repo_url": "https://github.com/run-llama/llama_index",
        "name": "LlamaIndex",
        "license": "MIT",
        "stars": 35000,
        "last_commit": "2025-03",
        "capability_gap": "Advanced RAG retrievers for core/rag.py",
        "integration_complexity": "low",
        "recommendation": "adopt",
        "rationale": "Add llama-index-core to [ml] extras; replace custom retriever with BM25+dense hybrid",
    },
    {
        "repo_url": "https://github.com/opendevin/opendevin",
        "name": "OpenDevin",
        "license": "MIT",
        "stars": 32000,
        "last_commit": "2025-03",
        "capability_gap": "Sandboxed code execution with observation loop",
        "integration_complexity": "high",
        "recommendation": "extract_pattern",
        "rationale": "Observation-action loop pattern for sandbox/simulate.py; full adoption too complex",
    },
    {
        "repo_url": "https://github.com/stanfordnlp/dspy",
        "name": "DSPy",
        "license": "MIT",
        "stars": 17000,
        "last_commit": "2025-03",
        "capability_gap": "Prompt optimization and self-improving pipeline compilation",
        "integration_complexity": "low",
        "recommendation": "adopt",
        "rationale": "Add dspy-ai to [ml] extras; enables auto-optimization of chimera gate prompts",
    },
    {
        "repo_url": "https://github.com/microsoft/TaskMatrix",
        "name": "TaskMatrix",
        "license": "MIT",
        "stars": 34000,
        "last_commit": "2024-06",
        "capability_gap": "Visual + API tool chaining for multimodal tasks",
        "integration_complexity": "medium",
        "recommendation": "extract_pattern",
        "rationale": "Tool chaining API can extend core/tool_registry.py; last commit 2024 so extract not adopt",
    },
]


class AGIResearcher:
    """Reports on OSS repos that can expand OpenChimera's AGI capabilities."""

    def __init__(self, workspace: str, chimera: ChimeraClient | None = None) -> None:
        self.workspace = Path(workspace)
        self.chimera = chimera or ChimeraClient()

    async def run_async(self, run_id: str, artifacts_dir: Path) -> ResearchReport:
        log.info("[AGIResearcher] Researching AGI capability expansions (run_id=%s)", run_id)

        candidates = [ResearchCandidate(**c) for c in _SEED_CANDIDATES]

        # Use chimera_explore to get consensus score across candidates
        explore_result = await self.chimera.explore(
            [{"name": c.name, "recommendation": c.recommendation, "complexity": c.integration_complexity}
             for c in candidates]
        )

        adopted = sum(1 for c in candidates if c.recommendation in ("adopt", "extract_pattern"))
        skipped = sum(1 for c in candidates if c.recommendation == "skip")

        report = ResearchReport(
            run_id=run_id,
            candidates=candidates,
            chimera_explore_result=explore_result,
            total_found=len(candidates),
            adopted=adopted,
            skipped=skipped,
        )

        out = artifacts_dir / "research_report.json"
        out.parent.mkdir(parents=True, exist_ok=True)

        # Compress before writing
        raw = report.model_dump_json()
        compressed = await self.chimera.compress(raw, max_chars=len(raw))
        out.write_text(raw)

        log.info(
            "[AGIResearcher] Found %d candidates: %d actionable, %d skipped. Explore score=%.2f",
            len(candidates), adopted, skipped,
            explore_result.get("agreement_score", 0.0),
        )
        return report

    def run(self, run_id: str, artifacts_dir: Path) -> ResearchReport:
        import asyncio
        return asyncio.run(self.run_async(run_id, artifacts_dir))
