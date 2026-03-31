from __future__ import annotations

import time
from typing import Any

from core.local_llm import LocalLLMManager
from core.minimind_service import MiniMindService


class AscensionService:
    def __init__(self, llm_manager: LocalLLMManager, minimind: MiniMindService):
        self.llm_manager = llm_manager
        self.minimind = minimind
        self.running = False
        self.last_result: dict[str, Any] | None = None

    def start(self) -> dict[str, Any]:
        self.running = True
        return self.status()

    def stop(self) -> dict[str, Any]:
        self.running = False
        return self.status()

    def deliberate(
        self,
        prompt: str,
        perspectives: list[str] | None = None,
        max_tokens: int = 256,
    ) -> dict[str, Any]:
        perspectives = perspectives or ["architect", "operator", "skeptic"]
        responses = []
        used_models: list[str] = []

        for perspective in perspectives[:4]:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are part of the OpenChimera Ascension Engine. "
                        f"Respond from the {perspective} perspective with concrete reasoning and no fluff."
                    ),
                },
                {"role": "user", "content": prompt},
            ]
            result = self.minimind.reasoning_completion(
                messages=messages,
                temperature=0.3,
                max_tokens=max(96, max_tokens // 2),
                timeout=45.0,
            )
            content = str(result.get("content") or "").strip()
            model = str(result.get("model") or "minimind")
            source = "minimind"
            if not content:
                ranked_models = self.llm_manager.get_ranked_models(
                    query_type="reasoning",
                    prefer_speed=False,
                    exclude=used_models,
                )
                local_model = ranked_models[0] if ranked_models else None
                if local_model is not None:
                    local_result = self.llm_manager.chat_completion(
                        messages=messages,
                        model=local_model,
                        query_type="reasoning",
                        max_tokens=max(96, max_tokens // 2),
                        temperature=0.3,
                        timeout=25.0,
                    )
                    content = str(local_result.get("content") or "").strip()
                    model = str(local_result.get("model") or local_model)
                    source = "local-llm"
            if not content:
                content = f"{perspective.title()} perspective could not be resolved from the available reasoning engines."
            used_models.append(model)
            responses.append({"perspective": perspective, "model": model, "source": source, "content": content})

        consensus = self._build_consensus(prompt, responses)
        payload = {
            "status": "ok",
            "prompt": prompt,
            "running": self.running,
            "perspectives": responses,
            "consensus": consensus,
            "generated_at": time.time(),
        }
        self.last_result = payload
        return payload

    def status(self) -> dict[str, Any]:
        return {
            "name": "ascension",
            "available": True,
            "running": self.running,
            "last_result": self.last_result,
            "capabilities": ["multi-perspective-deliberation", "consensus-synthesis"],
        }

    def _build_consensus(self, prompt: str, responses: list[dict[str, Any]]) -> str:
        lines = [f"Prompt: {prompt}", "Consensus:"]
        for response in responses:
            lines.append(f"- {response['perspective']}: {response['content'][:220]}")
        return "\n".join(lines)