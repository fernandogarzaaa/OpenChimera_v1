from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.local_llm import LocalLLMManager


class LocalLLMQualityTests(unittest.TestCase):
    def test_usable_completion_accepts_plain_sentence(self) -> None:
        manager = LocalLLMManager()
        self.assertTrue(manager._is_usable_completion("OpenChimera coordinates local runtimes through one provider."))

    def test_usable_completion_rejects_repetitive_or_skeletal_output(self) -> None:
        manager = LocalLLMManager()
        self.assertFalse(manager._is_usable_completion("PPPPPPPPPPPPPPPPPP"))
        self.assertFalse(manager._is_usable_completion("### :\n- \n- \n-"))
        self.assertFalse(manager._is_usable_completion("```\n\n```"))

    def test_small_models_receive_simplified_prompt(self) -> None:
        manager = LocalLLMManager()
        shaped = manager._build_model_messages(
            "phi-3.5-mini",
            [
                {"role": "system", "content": "Be concise."},
                {"role": "user", "content": "Explain OpenChimera."},
            ],
            query_type="general",
        )
        self.assertEqual(len(shaped), 1)
        self.assertEqual(shaped[0]["role"], "user")
        self.assertIn("Respond in plain text.", shaped[0]["content"])
        self.assertIn("Guidance:", shaped[0]["content"])
        self.assertIn("User request:", shaped[0]["content"])

    def test_larger_models_keep_chat_structure_with_style_instruction(self) -> None:
        manager = LocalLLMManager()
        shaped = manager._build_model_messages(
            "qwen2.5-7b",
            [
                {"role": "system", "content": "Be concise."},
                {"role": "user", "content": "Explain OpenChimera."},
            ],
            query_type="reasoning",
        )
        self.assertEqual(shaped[0]["role"], "system")
        self.assertIn("Respond in plain text.", shaped[0]["content"])
        self.assertIn("For analysis, give a short direct explanation", shaped[0]["content"])
        self.assertEqual(shaped[1]["role"], "user")
        self.assertEqual(shaped[1]["content"], "Explain OpenChimera.")

    def test_prompt_strategy_classifies_models(self) -> None:
        manager = LocalLLMManager()
        self.assertEqual(manager._prompt_strategy_for_model("phi-3.5-mini"), "flattened_plaintext")
        self.assertEqual(manager._prompt_strategy_for_model("llama-3.2-3b"), "flattened_plaintext")
        self.assertEqual(manager._prompt_strategy_for_model("qwen2.5-7b"), "chat_guided")

    def test_preferred_prompt_strategy_can_learn_from_route_memory(self) -> None:
        manager = LocalLLMManager()
        snapshot = {
            "qwen2.5-7b": {
                "general": {
                    "successes": 2,
                    "failures": 2,
                    "low_quality_failures": 2,
                    "avg_latency_ms": 10.0,
                    "last_success_at": 4102444800.0,
                    "last_failure_at": 4102444800.0,
                    "prompt_strategies": {
                        "chat_guided": {
                            "successes": 0,
                            "failures": 2,
                            "low_quality_failures": 2,
                            "last_success_at": 0.0,
                            "last_failure_at": 4102444800.0,
                        },
                        "flattened_plaintext": {
                            "successes": 2,
                            "failures": 0,
                            "low_quality_failures": 0,
                            "last_success_at": 4102444800.0,
                            "last_failure_at": 0.0,
                        },
                    },
                }
            }
        }
        self.assertEqual(
            manager._preferred_prompt_strategy("qwen2.5-7b", "general", snapshot),
            "flattened_plaintext",
        )

    def test_missing_configured_model_path_falls_back_to_discovered_search_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            search_root = Path(temp_dir) / "search-root"
            search_root.mkdir(parents=True)
            discovered = search_root / "phi-3.5-mini-instruct-q8_0.gguf"
            discovered.write_text("stub", encoding="utf-8")
            profile = {
                "model_inventory": {
                    "available_models": [],
                    "model_files": {"phi-3.5-mini": str(Path(temp_dir) / "missing" / "phi.gguf")},
                    "models_dir": str(Path(temp_dir) / "models"),
                    "search_roots": [str(search_root)],
                },
                "local_runtime": {
                    "preferred_local_models": ["phi-3.5-mini"],
                    "launcher": {"enabled": True, "auto_start": False, "shutdown_with_manager": False, "llama_server_path": ""},
                },
            }

            with patch("core.local_llm.load_runtime_profile", return_value=profile):
                manager = LocalLLMManager()

            runtime_status = manager.get_runtime_status()
            phi_status = runtime_status["models"]["phi-3.5-mini"]
            self.assertTrue(phi_status["model_path_exists"])
            self.assertEqual(phi_status["model_path"], str(discovered))
            self.assertIn("phi-3.5-mini", runtime_status["discovery"]["available_models"])

    def test_chat_completion_retries_with_alternate_prompt_strategy(self) -> None:
        manager = LocalLLMManager()
        with tempfile.TemporaryDirectory() as temp_dir:
            manager._route_memory_path = Path(temp_dir) / "route_memory.json"
            manager._route_memory = {}
            manager.models["qwen2.5-7b"].status = "healthy"
            manager._post_json = unittest.mock.MagicMock(
                side_effect=[
                    {"choices": [{"message": {"content": "### :\n- \n- \n-"}}], "usage": {"completion_tokens": 4}},
                    {
                        "choices": [{"message": {"content": "OpenChimera coordinates local runtimes through one provider."}}],
                        "usage": {"completion_tokens": 12},
                    },
                ]
            )

            result = manager.chat_completion(
                messages=[{"role": "user", "content": "Explain OpenChimera."}],
                model="qwen2.5-7b",
                query_type="general",
            )

            self.assertIsNone(result["error"])
            self.assertEqual(result["prompt_strategy"], "flattened_plaintext")
            self.assertEqual(result["prompt_strategies_tried"], ["chat_guided", "flattened_plaintext"])
            first_payload = manager._post_json.call_args_list[0].args[1]
            second_payload = manager._post_json.call_args_list[1].args[1]
            self.assertEqual(first_payload["messages"][0]["role"], "system")
            self.assertEqual(second_payload["messages"][0]["role"], "user")

    def test_chat_completion_starts_with_learned_preferred_prompt_strategy(self) -> None:
        manager = LocalLLMManager()
        manager.models["qwen2.5-7b"].status = "healthy"
        manager._route_memory = {
            "qwen2.5-7b": {
                "general": {
                    "successes": 2,
                    "failures": 2,
                    "low_quality_failures": 2,
                    "avg_latency_ms": 10.0,
                    "last_success_at": 4102444800.0,
                    "last_failure_at": 4102444800.0,
                    "prompt_strategies": {
                        "chat_guided": {
                            "successes": 0,
                            "failures": 2,
                            "low_quality_failures": 2,
                            "last_success_at": 0.0,
                            "last_failure_at": 4102444800.0,
                        },
                        "flattened_plaintext": {
                            "successes": 2,
                            "failures": 0,
                            "low_quality_failures": 0,
                            "last_success_at": 4102444800.0,
                            "last_failure_at": 0.0,
                        },
                    },
                }
            }
        }
        manager._post_json = unittest.mock.MagicMock(
            return_value={
                "choices": [{"message": {"content": "OpenChimera coordinates local runtimes through one provider."}}],
                "usage": {"completion_tokens": 12},
            }
        )

        result = manager.chat_completion(
            messages=[{"role": "user", "content": "Explain OpenChimera."}],
            model="qwen2.5-7b",
            query_type="general",
        )

        self.assertIsNone(result["error"])
        self.assertEqual(result["prompt_strategy"], "flattened_plaintext")
        self.assertEqual(result["prompt_strategies_tried"], ["flattened_plaintext"])
        first_payload = manager._post_json.call_args_list[0].args[1]
        self.assertEqual(first_payload["messages"][0]["role"], "user")

    def test_chat_completion_reports_all_prompt_strategies_on_failure(self) -> None:
        manager = LocalLLMManager()
        with tempfile.TemporaryDirectory() as temp_dir:
            manager._route_memory_path = Path(temp_dir) / "route_memory.json"
            manager._route_memory = {}
            manager.models["qwen2.5-7b"].status = "healthy"
            manager._post_json = unittest.mock.MagicMock(
                return_value={"choices": [{"message": {"content": "### :\n- \n- \n-"}}], "usage": {"completion_tokens": 4}}
            )

            result = manager.chat_completion(
                messages=[{"role": "user", "content": "Explain OpenChimera."}],
                model="qwen2.5-7b",
                query_type="general",
            )

            self.assertEqual(result["error"], "Low-quality local model response")
            self.assertEqual(result["prompt_strategy"], "flattened_plaintext")
            self.assertEqual(result["prompt_strategies_tried"], ["chat_guided", "flattened_plaintext"])

    def test_route_memory_records_success_and_failure(self) -> None:
        manager = LocalLLMManager()
        with tempfile.TemporaryDirectory() as temp_dir:
            manager._route_memory_path = Path(temp_dir) / "route_memory.json"
            manager._route_memory = {}
            manager._record_route_outcome("qwen2.5-7b", "general", success=True, latency_ms=100.0, low_quality=False)
            manager._record_route_outcome("qwen2.5-7b", "general", success=False, latency_ms=200.0, low_quality=True)
            manager._record_prompt_strategy_outcome("qwen2.5-7b", "general", "chat_guided", success=False, low_quality=True)
            manager._record_prompt_strategy_outcome("qwen2.5-7b", "general", "flattened_plaintext", success=True, low_quality=False)
            memory = manager.get_route_memory()
            bucket = memory["qwen2.5-7b"]["general"]
            self.assertEqual(bucket["successes"], 1)
            self.assertEqual(bucket["failures"], 1)
            self.assertEqual(bucket["low_quality_failures"], 1)
            self.assertGreater(bucket["last_success_at"], 0.0)
            self.assertGreater(bucket["last_failure_at"], 0.0)
            self.assertEqual(bucket["prompt_strategies"]["chat_guided"]["failures"], 1)
            self.assertEqual(bucket["prompt_strategies"]["flattened_plaintext"]["successes"], 1)
            self.assertTrue(manager._route_memory_path.exists())

    def test_adaptive_penalty_prefers_successful_models(self) -> None:
        manager = LocalLLMManager()
        snapshot = {
            "qwen2.5-7b": {
                "general": {
                    "successes": 4,
                    "failures": 0,
                    "low_quality_failures": 0,
                    "last_success_at": 4102444800.0,
                    "last_failure_at": 0.0,
                }
            },
            "phi-3.5-mini": {
                "general": {
                    "successes": 0,
                    "failures": 3,
                    "low_quality_failures": 2,
                    "last_success_at": 0.0,
                    "last_failure_at": 4102444800.0,
                }
            },
        }
        self.assertLess(
            manager._adaptive_penalty("qwen2.5-7b", "general", snapshot),
            manager._adaptive_penalty("phi-3.5-mini", "general", snapshot),
        )

    def test_adaptive_penalty_degrades_old_failures(self) -> None:
        manager = LocalLLMManager()
        snapshot = {
            "phi-3.5-mini": {
                "general": {
                    "successes": 0,
                    "failures": 2,
                    "low_quality_failures": 1,
                    "last_success_at": 0.0,
                    "last_failure_at": 1000000000.0,
                }
            },
            "llama-3.2-3b": {
                "general": {
                    "successes": 0,
                    "failures": 2,
                    "low_quality_failures": 1,
                    "last_success_at": 0.0,
                    "last_failure_at": 4102444800.0,
                }
            },
        }
        self.assertLess(
            manager._adaptive_penalty("phi-3.5-mini", "general", snapshot),
            manager._adaptive_penalty("llama-3.2-3b", "general", snapshot),
        )

    def test_fallback_helper_preserves_query_type(self) -> None:
        manager = LocalLLMManager()
        manager.get_ranked_models = unittest.mock.MagicMock(return_value=["llama-3.2-3b"])
        manager.chat_completion = unittest.mock.MagicMock(
            return_value={"content": "OpenChimera answer", "model": "llama-3.2-3b", "error": None}
        )

        result = manager.chat_completion_with_fallback(
            messages=[{"role": "user", "content": "Explain the architecture."}],
            query_type="reasoning",
        )

        self.assertEqual(result["model"], "llama-3.2-3b")
        self.assertEqual(manager.chat_completion.call_args.kwargs["query_type"], "reasoning")


if __name__ == "__main__":
    unittest.main()