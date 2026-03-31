from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.local_llm import LocalLLMManager


@dataclass
class RouteDecision:
    model: str | None
    query_type: str
    prefer_speed: bool
    attempted: list[str]
    reason: str


class OpenChimeraRouter:
    def __init__(self, llm_manager: LocalLLMManager):
        self.llm_manager = llm_manager

    def decide(
        self,
        query: str,
        query_type: str = "general",
        max_tokens: int = 256,
        exclude: list[str] | None = None,
    ) -> RouteDecision:
        exclude = exclude or []
        prefer_speed = query_type in {"fast", "general"} or max_tokens <= 256
        candidates = self.llm_manager.get_ranked_models(
            query_type=query_type,
            prefer_speed=prefer_speed,
            exclude=exclude,
        )
        model = candidates[0] if candidates else None
        reason = self._build_reason(query=query, query_type=query_type, prefer_speed=prefer_speed, model=model)
        return RouteDecision(
            model=model,
            query_type=query_type,
            prefer_speed=prefer_speed,
            attempted=list(exclude),
            reason=reason,
        )

    def status(self) -> dict[str, Any]:
        ranked = self.llm_manager.get_ranked_models(query_type="general", prefer_speed=True)
        llm_status = self.llm_manager.get_status()
        return {
            "available_models": ranked,
            "healthy_models": llm_status.get("healthy_count", 0),
            "known_models": llm_status.get("total_count", 0),
        }

    def _build_reason(self, query: str, query_type: str, prefer_speed: bool, model: str | None) -> str:
        if model is None:
            return f"No healthy model available for query_type={query_type}"
        bias = "speed" if prefer_speed else "quality"
        query_hint = (query or "").strip().replace("\n", " ")[:80]
        return f"Selected {model} for query_type={query_type}, bias={bias}, query={query_hint}"