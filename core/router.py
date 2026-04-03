from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.local_llm import LocalLLMManager
from core.model_roles import ModelRoleManager


@dataclass
class RouteDecision:
    model: str | None
    query_type: str
    prefer_speed: bool
    attempted: list[str]
    reason: str


class OpenChimeraRouter:
    def __init__(self, llm_manager: LocalLLMManager, model_roles: ModelRoleManager | None = None):
        self.llm_manager = llm_manager
        self.model_roles = model_roles

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
        preferred_model = None
        role_name = None
        if self.model_roles is not None:
            role_selection = self.model_roles.select_model_for_query_type(query_type=query_type, exclude=exclude)
            preferred_model = str(role_selection.get("model") or "") or None
            role_name = str(role_selection.get("role") or "") or None

        model = preferred_model if preferred_model in candidates else (candidates[0] if candidates else preferred_model)
        reason = self._build_reason(
            query=query,
            query_type=query_type,
            prefer_speed=prefer_speed,
            model=model,
            role_name=role_name,
            role_applied=model == preferred_model and model is not None,
        )
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
        payload = {
            "available_models": ranked,
            "healthy_models": llm_status.get("healthy_count", 0),
            "known_models": llm_status.get("total_count", 0),
        }
        if self.model_roles is not None:
            payload["roles"] = self.model_roles.status().get("roles", {})
        return payload

    def _build_reason(
        self,
        query: str,
        query_type: str,
        prefer_speed: bool,
        model: str | None,
        role_name: str | None = None,
        role_applied: bool = False,
    ) -> str:
        if model is None:
            return f"No healthy model available for query_type={query_type}"
        bias = "speed" if prefer_speed else "quality"
        query_hint = (query or "").strip().replace("\n", " ")[:80]
        role_suffix = f", role={role_name}, role_applied={role_applied}" if role_name else ""
        return f"Selected {model} for query_type={query_type}, bias={bias}{role_suffix}, query={query_hint}"