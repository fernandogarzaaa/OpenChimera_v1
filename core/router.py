from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from core.config import ROOT
from core.local_llm import LocalLLMManager
from core.model_roles import ModelRoleManager

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ModelRole enum — canonical role names for the routing layer
# ---------------------------------------------------------------------------

class ModelRole(str, Enum):
    MAIN = "main"
    FAST = "fast"
    CODE = "code"
    REASONING = "reasoning"
    ADVISOR = "advisor"
    CONSENSUS = "consensus"
    FALLBACK = "fallback"

    def to_query_type(self) -> str:
        """Map ModelRole to a legacy query_type string."""
        _map = {
            ModelRole.MAIN: "general",
            ModelRole.FAST: "fast",
            ModelRole.CODE: "code",
            ModelRole.REASONING: "reasoning",
            ModelRole.ADVISOR: "reasoning",
            ModelRole.CONSENSUS: "reasoning",
            ModelRole.FALLBACK: "general",
        }
        return _map.get(self, "general")


# ---------------------------------------------------------------------------
# ModelRoleAssignment — a role → model binding
# ---------------------------------------------------------------------------

@dataclass
class ModelRoleAssignment:
    """Binds a ModelRole to a specific model identifier."""
    role: ModelRole
    model: str
    reason: str = "manual"
    assigned_at: float = field(default_factory=lambda: __import__("time").time())

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role.value,
            "model": self.model,
            "reason": self.reason,
            "assigned_at": self.assigned_at,
        }


# ---------------------------------------------------------------------------
# RoleRegistry — runtime role → model assignment store
# ---------------------------------------------------------------------------

_ROLE_CONFIG_PATH = ROOT / "config" / "model_role_assignments.json"


class RoleRegistry:
    """Runtime registry for role → model assignments.

    Supports:
    - assign_role() / get_role() / list_roles() / reset_roles()
    - Dynamic reassignment without restart
    - Persistence to config/model_role_assignments.json
    """

    def __init__(self, config_path: Path | None = None) -> None:
        self._config_path = Path(config_path) if config_path else _ROLE_CONFIG_PATH
        self._assignments: dict[ModelRole, ModelRoleAssignment] = {}
        self._load()

    # --- Public API ---

    def assign_role(self, role: ModelRole, model: str, *, reason: str = "manual") -> ModelRoleAssignment:
        """Assign a model to a role at runtime. Persists immediately."""
        if not model or not model.strip():
            raise ValueError(f"Model identifier must be non-empty for role {role.value!r}")
        assignment = ModelRoleAssignment(role=role, model=model.strip(), reason=reason)
        self._assignments[role] = assignment
        self._persist()
        log.info("[RoleRegistry] Assigned role=%s → model=%s (reason=%s)", role.value, model, reason)
        return assignment

    def get_role(self, role: ModelRole) -> ModelRoleAssignment | None:
        """Return the current assignment for a role, or None."""
        return self._assignments.get(role)

    def list_roles(self) -> list[dict[str, Any]]:
        """Return all current role assignments."""
        all_roles = [
            self._assignments.get(r) or ModelRoleAssignment(role=r, model="unassigned", reason="default")
            for r in ModelRole
        ]
        return [a.to_dict() for a in all_roles]

    def reset_roles(self) -> None:
        """Clear all role assignments and persist the empty state."""
        self._assignments.clear()
        self._persist()
        log.info("[RoleRegistry] All role assignments cleared")

    def route_by_role(self, role: ModelRole) -> str | None:
        """Return the assigned model for a role, or None if unassigned."""
        assignment = self._assignments.get(role)
        if assignment and assignment.model != "unassigned":
            return assignment.model
        return None

    # --- Persistence ---

    def _persist(self) -> None:
        try:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)
            data = {r.value: a.to_dict() for r, a in self._assignments.items()}
            self._config_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            log.warning("[RoleRegistry] Failed to persist assignments: %s", exc)

    def _load(self) -> None:
        if not self._config_path.exists():
            return
        try:
            raw = json.loads(self._config_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return
            for role_str, entry in raw.items():
                try:
                    role = ModelRole(role_str)
                    model = str(entry.get("model", "")).strip()
                    reason = str(entry.get("reason", "persisted"))
                    assigned_at = float(entry.get("assigned_at", 0.0))
                    if model and model != "unassigned":
                        self._assignments[role] = ModelRoleAssignment(
                            role=role, model=model, reason=reason, assigned_at=assigned_at
                        )
                except (ValueError, AttributeError):
                    continue
        except Exception as exc:
            log.warning("[RoleRegistry] Failed to load persisted assignments: %s", exc)





@dataclass
class RouteDecision:
    model: str | None
    query_type: str
    prefer_speed: bool
    attempted: list[str]
    reason: str


class OpenChimeraRouter:
    def __init__(
        self,
        llm_manager: LocalLLMManager,
        model_roles: ModelRoleManager | None = None,
        role_registry: RoleRegistry | None = None,
    ):
        self.llm_manager = llm_manager
        self.model_roles = model_roles
        self.role_registry = role_registry

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

    def route_by_role(self, role: ModelRole) -> str | None:
        """Route directly by ModelRole, using RoleRegistry if wired in."""
        if self.role_registry is not None:
            model = self.role_registry.route_by_role(role)
            if model:
                return model
        # Fall back to model_roles if available
        if self.model_roles is not None:
            query_type = role.to_query_type()
            selection = self.model_roles.select_model_for_query_type(query_type=query_type)
            model = str(selection.get("model") or "").strip()
            if model:
                return model
        return None

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
        if self.role_registry is not None:
            payload["role_registry"] = self.role_registry.list_roles()
        return payload
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