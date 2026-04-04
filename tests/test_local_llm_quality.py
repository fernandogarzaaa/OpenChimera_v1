from __future__ import annotations

import tempfile
import time
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
        _empty_inv = {"available_models": [], "model_files": {}, "search_roots": [], "scanned_roots": [], "discovered_files": []}
        with patch("core.local_llm.discover_local_model_inventory", return_value=_empty_inv):
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
        _empty_inv = {"available_models": [], "model_files": {}, "search_roots": [], "scanned_roots": [], "discovered_files": []}
        with patch("core.local_llm.discover_local_model_inventory", return_value=_empty_inv):
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
        _empty_inv = {"available_models": [], "model_files": {}, "search_roots": [], "scanned_roots": [], "discovered_files": []}
        with patch("core.local_llm.discover_local_model_inventory", return_value=_empty_inv):
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


class LocalLLMRuntimeTests(unittest.TestCase):
    def _make_manager(self) -> LocalLLMManager:
        _empty_inv = {"available_models": [], "model_files": {}, "search_roots": [], "scanned_roots": [], "discovered_files": []}
        with patch("core.local_llm.discover_local_model_inventory", return_value=_empty_inv):
            return LocalLLMManager()

    def test_get_runtime_status_returns_dict_with_expected_keys(self) -> None:
        manager = self._make_manager()
        status = manager.get_runtime_status()
        for key in ("enabled", "auto_start", "llama_server_path", "models", "discovery"):
            self.assertIn(key, status)

    def test_get_runtime_status_models_dict_is_non_empty(self) -> None:
        manager = self._make_manager()
        status = manager.get_runtime_status()
        self.assertIsInstance(status["models"], dict)
        self.assertGreater(len(status["models"]), 0)

    def test_get_ranked_models_returns_empty_when_all_offline(self) -> None:
        manager = self._make_manager()
        # All models are in "unknown" state by default
        result = manager.get_ranked_models(query_type="general")
        self.assertIsInstance(result, list)
        self.assertEqual(result, [])

    def test_get_ranked_models_returns_healthy_models_only(self) -> None:
        manager = self._make_manager()
        manager.models["qwen2.5-7b"].status = "healthy"
        result = manager.get_ranked_models(query_type="general")
        self.assertIn("qwen2.5-7b", result)

    def test_get_ranked_models_respects_exclude_list(self) -> None:
        manager = self._make_manager()
        manager.models["qwen2.5-7b"].status = "healthy"
        manager.models["phi-3.5-mini"].status = "healthy"
        result = manager.get_ranked_models(query_type="general", exclude=["qwen2.5-7b"])
        self.assertNotIn("qwen2.5-7b", result)

    def test_get_healthy_models_delegates_to_get_ranked_models(self) -> None:
        manager = self._make_manager()
        manager.models["phi-3.5-mini"].status = "healthy"
        result = manager.get_healthy_models()
        self.assertIn("phi-3.5-mini", result)

    def test_launcher_enabled_false_by_default(self) -> None:
        manager = self._make_manager()
        # Default profile has launcher disabled
        result = manager.start_configured_models()
        self.assertIn("skipped", result)

    def test_infer_port_parses_port_from_endpoint(self) -> None:
        manager = self._make_manager()
        self.assertEqual(manager._infer_port("http://127.0.0.1:8080"), 8080)
        self.assertEqual(manager._infer_port("http://127.0.0.1:8080/"), 8080)

    def test_infer_port_returns_none_for_no_port(self) -> None:
        manager = self._make_manager()
        self.assertIsNone(manager._infer_port("http://localhost"))

    def test_normalize_launcher_args_passthrough(self) -> None:
        manager = self._make_manager()
        result = manager._normalize_launcher_args(["--threads", "4", "--verbose"])
        self.assertEqual(result, ["--threads", "4", "--verbose"])

    def test_normalize_launcher_args_explicit_flag_without_value_injects_on(self) -> None:
        manager = self._make_manager()
        result = manager._normalize_launcher_args(["--flash-attn", "--threads", "4"])
        # --flash-attn has no bare value following it, so "on" is injected
        self.assertIn("--flash-attn", result)
        self.assertIn("on", result)

    def test_normalize_launcher_args_explicit_flag_with_value_no_injection(self) -> None:
        manager = self._make_manager()
        result = manager._normalize_launcher_args(["--flash-attn", "false"])
        # Followed by a non-flag value → no "on" injection
        self.assertEqual(result, ["--flash-attn", "false"])

    def test_normalize_launcher_args_cont_batching_flag(self) -> None:
        manager = self._make_manager()
        result = manager._normalize_launcher_args(["-cb"])
        self.assertIn("-cb", result)
        self.assertIn("on", result)

    def test_get_llama_server_path_with_configured_path(self) -> None:
        manager = self._make_manager()
        manager._launcher_config = {"llama_server_path": "custom/llama-server"}
        path = manager._get_llama_server_path()
        self.assertEqual(path.name, "llama-server")

    def test_resolve_model_path_uses_existing_configured_file(self) -> None:
        manager = self._make_manager()
        with tempfile.TemporaryDirectory() as temp_dir:
            model_file = Path(temp_dir) / "phi.gguf"
            model_file.write_text("stub", encoding="utf-8")
            result = manager._resolve_model_path(temp_dir, "phi-3.5-mini", str(model_file))
            self.assertEqual(result, model_file)

    def test_resolve_model_path_falls_back_to_discovered_when_configured_missing(self) -> None:
        manager = self._make_manager()
        with tempfile.TemporaryDirectory() as temp_dir:
            discovered = Path(temp_dir) / "phi-discovered.gguf"
            discovered.write_text("stub", encoding="utf-8")
            result = manager._resolve_model_path(
                temp_dir,
                "phi-3.5-mini",
                str(Path(temp_dir) / "missing.gguf"),
                str(discovered),
            )
            self.assertEqual(result, discovered)

    def test_stop_configured_models_missing_returns_missing(self) -> None:
        manager = self._make_manager()
        result = manager.stop_configured_models(["nonexistent-model"])
        self.assertIn("nonexistent-model", result["missing"])

    def test_add_and_remove_model(self) -> None:
        from core.local_llm import ModelConfig, ModelStats
        manager = self._make_manager()
        config = ModelConfig(
            name="test-model",
            endpoint="http://127.0.0.1:9999",
            model_path="models/test.gguf",
            quantization="q4",
            n_gpu_layers=0,
        )
        manager.add_model(config)
        self.assertIn("test-model", manager.models)
        self.assertIn("test-model", manager.configs)
        manager.remove_model("test-model")
        self.assertNotIn("test-model", manager.models)
        self.assertNotIn("test-model", manager.configs)

    def test_get_status_returns_expected_keys(self) -> None:
        manager = self._make_manager()
        status = manager.get_status()
        self.assertIn("models", status)
        self.assertIn("healthy_count", status)
        self.assertIn("total_count", status)
        self.assertIn("route_memory", status)

    def test_get_route_memory_returns_copy(self) -> None:
        manager = self._make_manager()
        with tempfile.TemporaryDirectory() as temp_dir:
            manager._route_memory_path = Path(temp_dir) / "mem.json"
            manager._route_memory = {}
            mem = manager.get_route_memory()
            self.assertIsInstance(mem, dict)

    def test_load_route_memory_returns_empty_when_no_file(self) -> None:
        manager = self._make_manager()
        with tempfile.TemporaryDirectory() as temp_dir:
            manager._route_memory_path = Path(temp_dir) / "missing_route_memory.json"
            result = manager._load_route_memory()
            self.assertEqual(result, {})

    def test_load_route_memory_returns_empty_on_bad_json(self) -> None:
        manager = self._make_manager()
        with tempfile.TemporaryDirectory() as temp_dir:
            p = Path(temp_dir) / "route_memory.json"
            p.write_text("not json", encoding="utf-8")
            manager._route_memory_path = p
            result = manager._load_route_memory()
            self.assertEqual(result, {})

    def test_load_route_memory_from_valid_file(self) -> None:
        manager = self._make_manager()
        with tempfile.TemporaryDirectory() as temp_dir:
            p = Path(temp_dir) / "route_memory.json"
            p.write_text('{"qwen2.5-7b": {"general": {"successes": 3, "failures": 0, "low_quality_failures": 0, "avg_latency_ms": 100.0, "last_success_at": 1.0, "last_failure_at": 0.0, "prompt_strategies": {}}}}', encoding="utf-8")
            manager._route_memory_path = p
            result = manager._load_route_memory()
            self.assertIn("qwen2.5-7b", result)

    def test_recency_factor_zero_timestamp(self) -> None:
        manager = self._make_manager()
        result = manager._recency_factor(0.0, fresh_seconds=3600, stale_seconds=86400)
        self.assertEqual(result, 0.0)

    def test_recency_factor_fresh_timestamp(self) -> None:
        manager = self._make_manager()
        result = manager._recency_factor(time.time(), fresh_seconds=3600, stale_seconds=86400)
        self.assertEqual(result, 1.0)

    def test_recency_factor_stale_timestamp(self) -> None:
        manager = self._make_manager()
        result = manager._recency_factor(1000.0, fresh_seconds=3600, stale_seconds=86400)
        self.assertAlmostEqual(result, 0.15, places=2)

    def test_chat_completion_urlexception_returns_error(self) -> None:
        manager = self._make_manager()
        manager.models["qwen2.5-7b"].status = "healthy"
        import urllib.error
        manager._post_json = unittest.mock.MagicMock(
            side_effect=urllib.error.URLError("connection refused")
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            manager._route_memory_path = Path(temp_dir) / "mem.json"
            manager._route_memory = {}
            result = manager.chat_completion(
                messages=[{"role": "user", "content": "test"}],
                model="qwen2.5-7b",
                query_type="general",
            )
        self.assertIsNotNone(result["error"])
        self.assertEqual(result["content"], "")

    def test_chat_completion_no_healthy_models(self) -> None:
        manager = self._make_manager()
        # All models are "unknown" (not healthy)
        result = manager.chat_completion(
            messages=[{"role": "user", "content": "test"}],
            query_type="general",
        )
        self.assertIsNotNone(result["error"])
        self.assertIn("No healthy", result["error"])

    def test_chat_completion_model_not_configured(self) -> None:
        manager = self._make_manager()
        result = manager.chat_completion(
            messages=[{"role": "user", "content": "test"}],
            model="nonexistent-model-xyz",
            query_type="general",
        )
        self.assertIsNotNone(result["error"])
        self.assertIn("not configured", result["error"])

    def test_check_model_health_marks_healthy_on_success(self) -> None:
        manager = self._make_manager()
        manager._get_json = unittest.mock.MagicMock(return_value={"status": "ok"})
        stats = manager.models["qwen2.5-7b"]
        stats.status = "unknown"
        manager._check_model_health("qwen2.5-7b", stats)
        self.assertEqual(stats.status, "healthy")

    def test_check_model_health_uses_v1_models_fallback(self) -> None:
        manager = self._make_manager()

        call_count = [0]
        def mock_get_json(url: str, timeout: float = 5.0) -> dict:
            call_count[0] += 1
            if "/health" in url:
                raise Exception("health not found")
            return {"object": "list"}

        manager._get_json = mock_get_json
        stats = manager.models["qwen2.5-7b"]
        stats.status = "unknown"
        manager._check_model_health("qwen2.5-7b", stats)
        self.assertEqual(stats.status, "healthy")
        self.assertEqual(call_count[0], 2)

    def test_check_model_health_marks_offline_on_failure(self) -> None:
        manager = self._make_manager()
        manager._get_json = unittest.mock.MagicMock(side_effect=Exception("unreachable"))
        stats = manager.models["qwen2.5-7b"]
        stats.status = "unknown"
        manager._check_model_health("qwen2.5-7b", stats)
        self.assertEqual(stats.status, "offline")

    def test_start_health_monitoring_starts_thread(self) -> None:
        manager = self._make_manager()
        manager._run_health_checks = unittest.mock.MagicMock()
        manager.start_health_monitoring()
        try:
            self.assertTrue(manager._running)
            self.assertIsNotNone(manager._health_thread)
        finally:
            manager.stop_health_monitoring()

    def test_stop_health_monitoring_stops_thread(self) -> None:
        manager = self._make_manager()
        manager._run_health_checks = unittest.mock.MagicMock()
        manager.start_health_monitoring()
        manager.stop_health_monitoring()
        self.assertFalse(manager._running)

    def test_chat_completion_with_fallback_exhausted(self) -> None:
        manager = self._make_manager()
        manager.get_ranked_models = unittest.mock.MagicMock(return_value=[])
        result = manager.chat_completion_with_fallback(
            messages=[{"role": "user", "content": "test"}],
            query_type="general",
        )
        self.assertEqual(result["content"], "")
        self.assertIn("All local models failed", result["error"])

    def test_record_prompt_strategy_success(self) -> None:
        manager = self._make_manager()
        with tempfile.TemporaryDirectory() as temp_dir:
            manager._route_memory_path = Path(temp_dir) / "mem.json"
            manager._route_memory = {}
            manager._record_prompt_strategy_outcome("qwen2.5-7b", "general", "chat_guided", success=True, low_quality=False)
            bucket = manager._route_memory["qwen2.5-7b"]["general"]["prompt_strategies"]["chat_guided"]
            self.assertEqual(bucket["successes"], 1)
            self.assertEqual(bucket["failures"], 0)

    def test_record_prompt_strategy_failure_low_quality(self) -> None:
        manager = self._make_manager()
        with tempfile.TemporaryDirectory() as temp_dir:
            manager._route_memory_path = Path(temp_dir) / "mem.json"
            manager._route_memory = {}
            manager._record_prompt_strategy_outcome("qwen2.5-7b", "general", "chat_guided", success=False, low_quality=True)
            bucket = manager._route_memory["qwen2.5-7b"]["general"]["prompt_strategies"]["chat_guided"]
            self.assertEqual(bucket["failures"], 1)
            self.assertEqual(bucket["low_quality_failures"], 1)

    def test_record_route_outcome_with_latency(self) -> None:
        manager = self._make_manager()
        with tempfile.TemporaryDirectory() as temp_dir:
            manager._route_memory_path = Path(temp_dir) / "mem.json"
            manager._route_memory = {}
            manager._record_route_outcome("qwen2.5-7b", "general", success=True, latency_ms=150.0, low_quality=False)
            bucket = manager._route_memory["qwen2.5-7b"]["general"]
            self.assertEqual(bucket["successes"], 1)
            self.assertGreater(bucket["avg_latency_ms"], 0.0)


if __name__ == "__main__":
    unittest.main()