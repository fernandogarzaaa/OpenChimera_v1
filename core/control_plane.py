from __future__ import annotations

import time
from typing import Any, Callable

from core.config import build_deployment_status


class OperatorControlPlane:
    def __init__(
        self,
        *,
        base_url_getter: Callable[[], str],
        profile_getter: Callable[[], dict[str, Any]],
        llm_manager: Any,
        rag: Any,
        router: Any,
        harness_port: Any,
        minimind: Any,
        autonomy: Any,
        model_registry: Any,
        model_roles: Any,
        onboarding: Any,
        provider_activation_builder: Callable[[], dict[str, Any]] | None = None,
        fallback_learning_builder: Callable[[dict[str, Any] | None], dict[str, Any]] | None = None,
        integration_status_builder: Callable[[], dict[str, Any]],
        subsystem_status_builder: Callable[[], dict[str, Any]],
        channel_status_builder: Callable[[], dict[str, Any]],
        channel_history_builder: Callable[..., dict[str, Any]],
        bus: Any,
        aegis: Any,
        ascension: Any,
    ):
        self._base_url_getter = base_url_getter
        self._profile_getter = profile_getter
        self.llm_manager = llm_manager
        self.rag = rag
        self.router = router
        self.harness_port = harness_port
        self.minimind = minimind
        self.autonomy = autonomy
        self.model_registry = model_registry
        self.model_roles = model_roles
        self.onboarding = onboarding
        self._provider_activation_builder = provider_activation_builder
        self._fallback_learning_builder = fallback_learning_builder
        self._integration_status_builder = integration_status_builder
        self._subsystem_status_builder = subsystem_status_builder
        self._channel_status_builder = channel_status_builder
        self._channel_history_builder = channel_history_builder
        self.bus = bus
        self.aegis = aegis
        self.ascension = ascension

    def _profile(self) -> dict[str, Any]:
        return self._profile_getter()

    def health(self) -> dict[str, Any]:
        llm_status = self.llm_manager.get_status()
        rag_status = self.rag.get_status()
        healthy_models = int(llm_status.get("healthy_count", 0) or 0)
        known_models = int(llm_status.get("total_count", 0) or 0)
        minimind_available = bool(getattr(self.minimind, "available", False))
        generation_path_ready = healthy_models > 0 or minimind_available
        return {
            "status": "online" if generation_path_ready else "degraded",
            "name": "openchimera",
            "base_url": self._base_url_getter(),
            "components": {
                "local_llm": healthy_models > 0,
                "rag": True,
                "token_fracture": True,
                "router": True,
                "harness_port": self.harness_port.available,
                "minimind": minimind_available,
                "autonomy": self.autonomy.status().get("running", False),
            },
            "healthy_models": healthy_models,
            "known_models": known_models,
            "documents": rag_status.get("documents", 0),
            "router": self.router.status(),
        }

    def provider_activation_status(self) -> dict[str, Any]:
        if self._provider_activation_builder is not None:
            return self._provider_activation_builder()
        profile = self._profile()
        registry = self.model_registry.status()
        if not isinstance(registry.get("discovery", {}), dict) or not registry.get("discovery"):
            registry = self.model_registry.refresh()
        return {
            "providers": registry.get("providers", []),
            "preferred_cloud_provider": profile.get("providers", {}).get("preferred_cloud_provider", ""),
            "prefer_free_models": bool(profile.get("providers", {}).get("prefer_free_models", False)),
            "discovery": registry.get("discovery", {}),
            "fallback_learning": self._fallback_learning_summary(registry),
            "model_roles": self.model_roles.status().get("roles", {}),
        }

    def onboarding_status(self) -> dict[str, Any]:
        return self.onboarding.status()

    def integration_status(self) -> dict[str, Any]:
        return self._integration_status_builder()

    def subsystem_status(self) -> dict[str, Any]:
        return self._subsystem_status_builder()

    def channel_status(self) -> dict[str, Any]:
        return self._channel_status_builder()

    def channel_delivery_history(self, topic: str | None = None, status: str | None = None, limit: int = 20) -> dict[str, Any]:
        return self._channel_history_builder(topic=topic, status=status, limit=limit)

    def _fallback_learning_summary(self, registry: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._fallback_learning_builder is not None:
            return self._fallback_learning_builder(registry)
        profile = self._profile()
        registry = registry or self.model_registry.status()
        discovery = registry.get("discovery", {}) if isinstance(registry.get("discovery", {}), dict) else {}
        recommendations = registry.get("recommendations", {}) if isinstance(registry.get("recommendations", {}), dict) else {}
        learned_rankings = recommendations.get("learned_free_rankings", []) if isinstance(recommendations.get("learned_free_rankings", []), list) else []
        ranked_models = []
        degraded_models = []
        for item in learned_rankings:
            if not isinstance(item, dict):
                continue
            ranked_models.append(
                {
                    "id": str(item.get("id") or ""),
                    "query_type": str(item.get("query_type") or "general"),
                    "rank": int(item.get("rank") or 0),
                    "score": float(item.get("score") or 0.0),
                    "confidence": float(item.get("confidence") or 0.0),
                    "degraded": bool(item.get("degraded", False)),
                }
            )
            if bool(item.get("degraded", False)):
                degraded_models.append(str(item.get("id") or ""))
        return {
            "prefer_free_models": bool(profile.get("providers", {}).get("prefer_free_models", False)),
            "scouted_models_available": bool(discovery.get("scouted_models_available", False)),
            "discovered_models_available": bool(discovery.get("discovered_models_available", False)),
            "learned_rankings_available": bool(discovery.get("learned_rankings_available", False)),
            "top_ranked_models": ranked_models[:3],
            "degraded_models": [item for item in degraded_models[:3] if item],
        }

    def build_daily_briefing(
        self,
        *,
        integrations: dict[str, Any],
        onboarding: dict[str, Any],
        autonomy: dict[str, Any],
        llm_status: dict[str, Any],
        registry: dict[str, Any],
        recent_events: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        fallback_learning = self._fallback_learning_summary(registry)
        recent_events = list(recent_events or [])[-8:]
        priorities: list[str] = []
        if onboarding.get("suggested_cloud_models") and onboarding.get("suggested_local_models") == []:
            priorities.append("Provision a cloud fallback provider because the detected hardware is below the preferred local-only range.")
        onboarding_blockers = onboarding.get("blockers", []) if isinstance(onboarding.get("blockers", []), list) else []
        priorities.extend(str(item) for item in onboarding_blockers[:2] if str(item).strip())
        remediation = integrations.get("remediation", [])
        priorities.extend(remediation[:3])
        stale_jobs = [
            name
            for name, details in autonomy.get("jobs", {}).items()
            if details.get("enabled") and details.get("last_status") in {"never", "error"}
        ]
        if stale_jobs:
            priorities.append("Autonomy jobs need attention: " + ", ".join(stale_jobs))
        if llm_status.get("healthy_count", 0) == 0:
            runtime_models = llm_status.get("runtime", {}).get("models", {}) if isinstance(llm_status.get("runtime", {}), dict) else {}
            local_assets_available = any(
                bool(details.get("model_path_exists")) for details in runtime_models.values() if isinstance(details, dict)
            )
            if local_assets_available:
                priorities.append("No healthy local models are currently online.")
            else:
                priorities.append("No local GGUF model assets are configured or discovered, so the local launcher cannot start any models.")
        top_ranked = fallback_learning.get("top_ranked_models", [])
        if fallback_learning.get("prefer_free_models") and top_ranked:
            top_model = top_ranked[0]
            priorities.append(
                "Learned free fallback leader: "
                + str(top_model.get("id") or "unknown")
                + " for "
                + str(top_model.get("query_type") or "general")
                + " queries."
            )
        degraded_models = fallback_learning.get("degraded_models", [])
        if degraded_models:
            priorities.append("Deprioritize degraded free fallbacks: " + ", ".join(str(item) for item in degraded_models))
        alert_topic = str(self._profile().get("autonomy", {}).get("alerts", {}).get("dispatch_topic", "system/autonomy/alert"))
        recent_alert_history = self.channel_delivery_history(topic=alert_topic, limit=5)
        failed_delivery_history = self.channel_delivery_history(status="error", limit=5)
        recent_alert_items = recent_alert_history.get("history", []) if isinstance(recent_alert_history.get("history", []), list) else []
        failed_delivery_items = failed_delivery_history.get("history", []) if isinstance(failed_delivery_history.get("history", []), list) else []
        if recent_alert_items:
            priorities.append(f"Recent autonomy alerts: {len(recent_alert_items)} deliveries recorded on {alert_topic}.")
        if failed_delivery_items:
            priorities.append(f"Channel delivery failures detected: {len(failed_delivery_items)} recent dispatches need attention.")
        lineage_only = integrations.get("lineage_only", []) if isinstance(integrations.get("lineage_only", []), list) else []
        summary = (
            f"OpenChimera runtime has {llm_status.get('healthy_count', 0)} healthy local models, "
            f"MiniMind available={self.minimind.available}, "
            f"{len(fallback_learning.get('top_ranked_models', []))} learned free fallback leaders, "
            f"{len(recent_alert_items)} recent alert dispatches, {len(remediation)} active integration gaps, and {len(lineage_only)} lineage-only recovered concepts."
        )
        return {
            "generated_at": int(time.time()),
            "summary": summary,
            "priorities": priorities,
            "system": {
                "healthy_local_models": llm_status.get("healthy_count", 0),
                "known_local_models": llm_status.get("total_count", 0),
                "minimind": self.minimind.status(),
                "aegis": self.aegis.status(),
                "ascension": self.ascension.status(),
            },
            "onboarding": onboarding,
            "fallback_learning": fallback_learning,
            "model_registry": {
                "discovery": registry.get("discovery", {}),
                "recommendations": {
                    "suggested_free_models": registry.get("recommendations", {}).get("suggested_free_models", []),
                    "learned_free_rankings": registry.get("recommendations", {}).get("learned_free_rankings", []),
                },
            },
            "channels": {
                "alert_topic": alert_topic,
                "recent_alerts": recent_alert_items,
                "failed_deliveries": failed_delivery_items,
            },
            "integrations": integrations,
            "recent_events": recent_events,
        }

    def daily_briefing(self) -> dict[str, Any]:
        return self.build_daily_briefing(
            integrations=self.integration_status(),
            onboarding=self.onboarding_status(),
            autonomy=self.autonomy.status(),
            llm_status=self.llm_manager.get_status(),
            registry=self.model_registry.status(),
            recent_events=self.bus.recent_events(),
        )

    def readiness_status(self, system_status: dict[str, Any] | None = None, *, auth_required: bool = False) -> dict[str, Any]:
        health = self.health()
        system_status = system_status or {}
        components = health.get("components", {})
        healthy_models = int(health.get("healthy_models", 0) or 0)
        minimind_status = self.minimind.status()
        minimind_available = bool(minimind_status.get("available"))
        router_status = getattr(self.router, "status", None)
        router_ready = True
        if callable(router_status):
            try:
                router_snapshot = router_status()
                router_ready = bool(router_snapshot.get("healthy_models", 0) or router_snapshot.get("known_models", 0))
            except Exception:
                router_ready = True
        rag_ready = bool(components.get("rag", True))
        provider_online = bool(system_status.get("provider_online", health.get("status") == "online"))
        checks = {
            "provider_online": provider_online,
            "rag": rag_ready,
            "router": bool(components.get("router", router_ready)),
            "generation_path": healthy_models > 0 or minimind_available,
        }
        issues = [name for name, ok in checks.items() if not ok]
        payload = {
            "status": "ready" if not issues else "degraded",
            "ready": not issues,
            "checks": checks,
            "healthy_models": healthy_models,
            "minimind_available": minimind_available,
            "auth_required": auth_required,
        }
        if issues:
            payload["issues"] = issues
        return payload

    def status_snapshot(self, *, system_status: dict[str, Any] | None = None, job_queue_status: dict[str, Any] | None = None) -> dict[str, Any]:
        readiness = self.readiness_status(system_status=system_status or {}, auth_required=False)
        channel_status = self.channel_status()
        failed_deliveries = self.channel_delivery_history(status="error", limit=5)
        onboarding = self.onboarding_status()
        integrations = self.integration_status()
        blockers = onboarding.get("blockers", []) if isinstance(onboarding.get("blockers", []), list) else []
        remediation = integrations.get("remediation", []) if isinstance(integrations.get("remediation", []), list) else []
        issues = list(readiness.get("issues", []))
        if blockers:
            issues.extend(str(item) for item in blockers[:3] if str(item).strip())
        if remediation:
            issues.extend(str(item) for item in remediation[:3] if str(item).strip())
        return {
            "generated_at": int(time.time()),
            "health": self.health(),
            "readiness": readiness,
            "deployment": build_deployment_status(),
            "provider_activation": self.provider_activation_status(),
            "onboarding": onboarding,
            "integrations": integrations,
            "subsystems": self.subsystem_status(),
            "channels": {
                "status": channel_status,
                "failed_deliveries": failed_deliveries,
            },
            "jobs": job_queue_status or {"counts": {}, "jobs": []},
            "issues": issues,
        }