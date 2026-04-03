from __future__ import annotations

import hashlib
from typing import Any

from core.config import build_deployment_status


def _count_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


class RuntimePlane:
    def __init__(
        self,
        *,
        base_url_getter: Any,
        profile_getter: Any,
        llm_manager: Any,
        rag: Any,
        router: Any,
        harness_port: Any,
        minimind: Any,
        autonomy: Any,
        observability: Any,
        health_getter: Any,
        autonomy_diagnostics_getter: Any,
        aegis_status_getter: Any,
        ascension_status_getter: Any,
        model_registry_status_getter: Any,
        browser_status_getter: Any,
        media_status_getter: Any,
        query_status_getter: Any,
        model_role_status_getter: Any,
        plugin_status_getter: Any,
        subsystem_status_getter: Any,
        onboarding_status_getter: Any,
        integration_status_getter: Any,
    ) -> None:
        self.base_url_getter = base_url_getter
        self.profile_getter = profile_getter
        self.llm_manager = llm_manager
        self.rag = rag
        self.router = router
        self.harness_port = harness_port
        self.minimind = minimind
        self.autonomy = autonomy
        self.observability = observability
        self.health_getter = health_getter
        self.autonomy_diagnostics_getter = autonomy_diagnostics_getter
        self.aegis_status_getter = aegis_status_getter
        self.ascension_status_getter = ascension_status_getter
        self.model_registry_status_getter = model_registry_status_getter
        self.browser_status_getter = browser_status_getter
        self.media_status_getter = media_status_getter
        self.query_status_getter = query_status_getter
        self.model_role_status_getter = model_role_status_getter
        self.plugin_status_getter = plugin_status_getter
        self.subsystem_status_getter = subsystem_status_getter
        self.onboarding_status_getter = onboarding_status_getter
        self.integration_status_getter = integration_status_getter

    def health(self) -> dict[str, Any]:
        return self.health_getter()

    def list_models(self) -> dict[str, Any]:
        llm_status = self.llm_manager.get_status()
        models = []
        for name, details in llm_status.get("models", {}).items():
            models.append(
                {
                    "id": name,
                    "object": "model",
                    "created": 1704067200,
                    "owned_by": "openchimera",
                    "status": details.get("status"),
                    "endpoint": details.get("endpoint"),
                    "context_length": details.get("context_length"),
                }
            )
        models.append(
            {
                "id": "openchimera-local",
                "object": "model",
                "created": 1704067200,
                "owned_by": "openchimera",
                "status": "healthy",
                "endpoint": self.base_url_getter(),
                "context_length": self.profile_getter().get("local_runtime", {}).get("context_length", 4096),
            }
        )
        return {"object": "list", "data": models}

    def local_runtime_status(self) -> dict[str, Any]:
        return self.llm_manager.get_runtime_status()

    def harness_port_status(self) -> dict[str, Any]:
        return self.harness_port.status()

    def minimind_status(self) -> dict[str, Any]:
        return self.minimind.status()

    def autonomy_status(self) -> dict[str, Any]:
        return self.autonomy.status()

    def observability_status(self) -> dict[str, Any]:
        return self.observability.snapshot()

    def embeddings(self, input_text: str, model: str = "openchimera-local") -> dict[str, Any]:
        vector_size = 64
        vector = [0.0] * vector_size
        for token in input_text.lower().split():
            bucket = int(hashlib.sha256(token.encode("utf-8")).hexdigest(), 16) % vector_size
            vector[bucket] += 1.0
        return {
            "object": "list",
            "data": [{"object": "embedding", "index": 0, "embedding": vector}],
            "model": model,
            "usage": {"prompt_tokens": _count_tokens(input_text), "total_tokens": _count_tokens(input_text)},
        }

    def status(self) -> dict[str, Any]:
        return {
            "online": True,
            "base_url": self.base_url_getter(),
            "deployment": build_deployment_status(),
            "health": self.health(),
            "models": self.list_models().get("data", []),
            "llm": self.llm_manager.get_status(),
            "router": self.router.status(),
            "rag": self.rag.get_status(),
            "harness_port": self.harness_port_status(),
            "minimind": self.minimind_status(),
            "autonomy": self.autonomy_status(),
            "autonomy_diagnostics": self.autonomy_diagnostics_getter(),
            "aegis": self.aegis_status_getter(),
            "ascension": self.ascension_status_getter(),
            "model_registry": self.model_registry_status_getter(),
            "browser": self.browser_status_getter(),
            "media": self.media_status_getter(),
            "query_engine": self.query_status_getter(),
            "model_roles": self.model_role_status_getter(),
            "plugins": self.plugin_status_getter(),
            "subsystems": self.subsystem_status_getter(),
            "observability": self.observability_status(),
            "onboarding": self.onboarding_status_getter(),
            "integrations": self.integration_status_getter(),
        }