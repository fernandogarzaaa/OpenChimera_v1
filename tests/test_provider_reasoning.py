from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from core.bus import EventBus
from core.personality import Personality
from core.provider import OpenChimeraProvider
from core.router import RouteDecision


class ProviderReasoningTests(unittest.TestCase):
    def _build_provider(self) -> OpenChimeraProvider:
        provider = OpenChimeraProvider(EventBus(), Personality())
        provider.minimind.get_runtime_status = MagicMock(return_value={"server": {"running": False}, "training": {"active_jobs": []}})
        return provider

    def test_reasoning_query_falls_back_when_minimind_is_low_quality(self) -> None:
        provider = self._build_provider()
        provider.minimind.reasoning_completion = MagicMock(
            return_value={"content": "", "model": "minimind", "error": "MiniMind low-quality response"}
        )
        provider.router.decide = MagicMock(
            return_value=RouteDecision(
                model="llama-3.2-3b",
                query_type="reasoning",
                prefer_speed=False,
                attempted=[],
                reason="fallback-local-model",
            )
        )
        provider.llm_manager.chat_completion = MagicMock(
            return_value={
                "content": "OpenChimera is a local-first orchestration runtime.",
                "model": "llama-3.2-3b",
                "prompt_strategy": "flattened_plaintext",
                "prompt_strategies_tried": ["flattened_plaintext"],
                "error": None,
            }
        )

        response = provider.chat_completion(
            messages=[{"role": "user", "content": "Analyze OpenChimera architecture briefly."}],
            max_tokens=96,
        )

        self.assertEqual(response["model"], "llama-3.2-3b")
        self.assertEqual(
            response["choices"][0]["message"]["content"],
            "OpenChimera is a local-first orchestration runtime.",
        )
        self.assertEqual(response["openchimera"]["route_reason"], "fallback-local-model")
        self.assertEqual(response["openchimera"]["query_type"], "reasoning")
        self.assertIsNotNone(response["openchimera"]["prompt_strategy"])
        self.assertEqual(response["openchimera"]["prompt_strategies_tried"], ["flattened_plaintext"])
        provider.llm_manager.chat_completion.assert_called_once()

    def test_reasoning_query_uses_minimind_when_response_is_usable(self) -> None:
        provider = self._build_provider()
        provider.minimind.reasoning_completion = MagicMock(
            return_value={
                "content": "OpenChimera coordinates local runtimes and model services behind one provider.",
                "model": "minimind",
                "error": None,
            }
        )
        provider.llm_manager.chat_completion = MagicMock()

        response = provider.chat_completion(
            messages=[{"role": "user", "content": "Analyze OpenChimera architecture briefly."}],
            max_tokens=96,
        )

        self.assertEqual(response["model"], "minimind")
        self.assertEqual(
            response["openchimera"]["route_reason"],
            "minimind-reasoning-engine",
        )
        self.assertEqual(response["openchimera"]["prompt_strategy"], "minimind_reasoning")
        provider.llm_manager.chat_completion.assert_not_called()

    def test_low_quality_local_response_falls_through_to_next_candidate(self) -> None:
        provider = self._build_provider()
        provider.minimind.reasoning_completion = MagicMock(
            return_value={"content": "", "model": "minimind", "error": "MiniMind low-quality response"}
        )
        provider.router.decide = MagicMock(
            side_effect=[
                RouteDecision(
                    model="qwen2.5-7b",
                    query_type="reasoning",
                    prefer_speed=False,
                    attempted=[],
                    reason="first-choice",
                ),
                RouteDecision(
                    model="llama-3.2-3b",
                    query_type="reasoning",
                    prefer_speed=False,
                    attempted=["qwen2.5-7b"],
                    reason="second-choice",
                ),
            ]
        )
        provider.llm_manager.chat_completion = MagicMock(
            side_effect=[
                {
                    "content": "",
                    "model": "qwen2.5-7b",
                    "prompt_strategy": "flattened_plaintext",
                    "prompt_strategies_tried": ["chat_guided", "flattened_plaintext"],
                    "error": "Low-quality local model response",
                },
                {
                    "content": "OpenChimera is a local-first orchestration runtime.",
                    "model": "llama-3.2-3b",
                    "prompt_strategy": "flattened_plaintext",
                    "prompt_strategies_tried": ["flattened_plaintext"],
                    "error": None,
                },
            ]
        )

        response = provider.chat_completion(
            messages=[{"role": "user", "content": "Analyze OpenChimera architecture briefly."}],
            max_tokens=96,
        )

        self.assertEqual(response["model"], "llama-3.2-3b")
        self.assertEqual(response["openchimera"]["route_reason"], "second-choice")
        self.assertEqual(response["openchimera"]["attempted_models"], ["qwen2.5-7b", "llama-3.2-3b"])
        self.assertEqual(provider.llm_manager.chat_completion.call_args_list[0].kwargs["query_type"], "reasoning")

    def test_short_technical_prompt_is_not_forced_to_fast_path(self) -> None:
        provider = self._build_provider()
        self.assertFalse(
            provider._should_force_fast_path(
                "Give a short technical summary of OpenChimera in two sentences.",
                "general",
                96,
            )
        )


if __name__ == "__main__":
    unittest.main()