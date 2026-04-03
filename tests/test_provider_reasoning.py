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

    def test_provider_chat_completion_delegates_to_inference_plane(self) -> None:
        provider = self._build_provider()
        provider.inference_plane.chat_completion = MagicMock(
            return_value={
                "id": "test",
                "object": "chat.completion",
                "created": 0,
                "model": "openchimera-local",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "delegated"}, "finish_reason": "stop"}],
                "openchimera": {"query_type": "general"},
            }
        )

        response = provider.chat_completion(messages=[{"role": "user", "content": "hello"}], max_tokens=32)

        self.assertEqual(response["choices"][0]["message"]["content"], "delegated")
        provider.inference_plane.chat_completion.assert_called_once_with(
            messages=[{"role": "user", "content": "hello"}],
            model="openchimera-local",
            temperature=0.7,
            max_tokens=32,
            stream=False,
        )

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

    def test_general_query_uses_free_model_fallback_when_enabled(self) -> None:
        provider = self._build_provider()
        provider.profile.setdefault("providers", {})["prefer_free_models"] = True
        provider.router.decide = MagicMock(
            side_effect=[
                RouteDecision(
                    model="qwen2.5-7b",
                    query_type="general",
                    prefer_speed=True,
                    attempted=[],
                    reason="primary-local",
                ),
                RouteDecision(
                    model=None,
                    query_type="general",
                    prefer_speed=True,
                    attempted=["qwen2.5-7b"],
                    reason="no-more-local",
                ),
            ]
        )
        provider.llm_manager.chat_completion = MagicMock(
            return_value={
                "content": "",
                "model": "qwen2.5-7b",
                "prompt_strategy": "chat_guided",
                "prompt_strategies_tried": ["chat_guided", "flattened_plaintext"],
                "error": "Low-quality local model response",
            }
        )
        provider.model_registry.status = MagicMock(
            return_value={
                "cloud_models": [
                    {
                        "id": "openrouter/qwen-free",
                        "provider": "openrouter",
                        "recommended_for": ["general", "fallback"],
                        "source": "autonomy-discovery",
                    }
                ]
            }
        )
        provider.credential_store.get_provider_credentials = MagicMock(return_value={"OPENROUTER_API_KEY": "sk-or-test"})
        provider.inference_plane._call_openrouter_free_model = MagicMock(
            return_value={
                "choices": [
                    {
                        "message": {
                            "content": "OpenChimera recovered through a discovered free fallback model."
                        }
                    }
                ]
            }
        )

        response = provider.chat_completion(
            messages=[{"role": "user", "content": "Summarize OpenChimera in one sentence."}],
            max_tokens=64,
        )

        self.assertEqual(response["model"], "openrouter/qwen-free")
        self.assertEqual(
            response["choices"][0]["message"]["content"],
            "OpenChimera recovered through a discovered free fallback model.",
        )
        self.assertTrue(response["openchimera"]["fallback_used"])
        self.assertTrue(response["openchimera"]["free_fallback_used"])
        self.assertEqual(response["openchimera"]["free_fallback_provider"], "openrouter")
        self.assertEqual(response["openchimera"]["free_fallback_source"], "autonomy-discovery")
        self.assertEqual(response["openchimera"]["route_reason"], "free-fallback-openrouter")
        self.assertEqual(response["openchimera"]["attempted_models"], ["qwen2.5-7b", "openrouter/qwen-free"])
        provider.inference_plane._call_openrouter_free_model.assert_called_once()

    def test_provider_exposes_qwen_agent_context_hub_deepagents_aether_and_aegis_mobile_bridge_status(self) -> None:
        provider = self._build_provider()

        clawd_status = provider.clawd_hybrid_rtx_status()
        qwen_status = provider.qwen_agent_status()
        context_status = provider.context_hub_status()
        deepagents_status = provider.deepagents_stack_status()
        aether_status = provider.aether_operator_stack_status()
        mobile_status = provider.aegis_mobile_gateway_status()

        self.assertEqual(clawd_status["name"], "clawd_hybrid_rtx")
        self.assertIn("quantum-consensus", clawd_status["capabilities"])
        self.assertEqual(qwen_status["name"], "qwen_agent")
        self.assertIn("agent-framework", qwen_status["capabilities"])
        self.assertEqual(context_status["name"], "context_hub")
        self.assertIn("memory-bridge", context_status["capabilities"])
        self.assertEqual(deepagents_status["name"], "deepagents_stack")
        self.assertIn("agent-orchestration", deepagents_status["capabilities"])
        self.assertEqual(aether_status["name"], "aether_operator_stack")
        self.assertIn("operator-routing", aether_status["capabilities"])
        self.assertEqual(mobile_status["name"], "aegis_mobile_gateway")
        self.assertIn("gateway-bridge", mobile_status["capabilities"])

    def test_provider_can_invoke_qwen_agent_context_hub_deepagents_aether_and_aegis_mobile_bridge_status_actions(self) -> None:
        provider = self._build_provider()

        clawd_result = provider.invoke_subsystem("clawd_hybrid_rtx", "status")
        qwen_result = provider.invoke_subsystem("qwen_agent", "status")
        context_result = provider.invoke_subsystem("context_hub", "status")
        deepagents_result = provider.invoke_subsystem("deepagents_stack", "status")
        aether_result = provider.invoke_subsystem("aether_operator_stack", "status")
        mobile_result = provider.invoke_subsystem("aegis_mobile_gateway", "status")

        self.assertEqual(clawd_result["name"], "clawd_hybrid_rtx")
        self.assertEqual(qwen_result["name"], "qwen_agent")
        self.assertEqual(context_result["name"], "context_hub")
        self.assertEqual(deepagents_result["name"], "deepagents_stack")
        self.assertEqual(aether_result["name"], "aether_operator_stack")
        self.assertEqual(mobile_result["name"], "aegis_mobile_gateway")

    def test_integration_audit_does_not_treat_container_roots_as_detected_bridges(self) -> None:
        provider = self._build_provider()

        report = provider.integration_status()
        integrations = report["engines"]

        self.assertFalse(integrations["project_seraph"]["detected"])
        self.assertFalse(integrations["aegis_core_control_plane"]["detected"])
        self.assertTrue(integrations["deepagents_stack"]["detected"])
        self.assertTrue(integrations["aether_operator_stack"]["detected"])
        self.assertEqual(integrations["project_seraph"]["recovery_state"], "memory-lineage")
        self.assertFalse(integrations["project_seraph"]["operator_actionable"])
        self.assertEqual(integrations["tri_core_architecture"]["recovery_state"], "memory-lineage")
        self.assertFalse(integrations["tri_core_architecture"]["operator_actionable"])
        self.assertIn("project_seraph", report["lineage_only"])
        self.assertIn("tri_core_architecture", report["lineage_only"])

    def test_free_model_fallback_prefers_learned_rankings(self) -> None:
        provider = self._build_provider()
        provider.profile.setdefault("providers", {})["prefer_free_models"] = True
        provider.model_registry.status = MagicMock(
            return_value={
                "cloud_models": [
                    {
                        "id": "openrouter/second-choice",
                        "provider": "openrouter",
                        "recommended_for": ["general", "fallback"],
                        "source": "autonomy-discovery",
                        "learned_rank": 2,
                        "learned_degraded": False,
                    },
                    {
                        "id": "openrouter/top-choice",
                        "provider": "openrouter",
                        "recommended_for": ["general", "fallback"],
                        "source": "autonomy-discovery",
                        "learned_rank": 1,
                        "learned_degraded": False,
                    },
                ]
            }
        )
        provider.credential_store.get_provider_credentials = MagicMock(return_value={"OPENROUTER_API_KEY": "sk-or-test"})
        provider.inference_plane._call_openrouter_free_model = MagicMock(
            return_value={
                "choices": [
                    {
                        "message": {
                            "content": "learned choice"
                        }
                    }
                ]
            }
        )

        result = provider._run_free_model_fallback(
            messages=[{"role": "user", "content": "Summarize OpenChimera."}],
            query_type="general",
            temperature=0.2,
            max_tokens=64,
            timeout=10,
        )

        self.assertEqual(result["model"], "openrouter/top-choice")
        self.assertEqual(provider.inference_plane._call_openrouter_free_model.call_args_list[0].args[0], "openrouter/top-choice")

    def test_provider_activation_status_exposes_fallback_learning_summary(self) -> None:
        provider = self._build_provider()
        provider.profile.setdefault("providers", {})["prefer_free_models"] = True
        provider.model_registry.status = MagicMock(
            return_value={
                "providers": [],
                "discovery": {
                    "scouted_models_available": True,
                    "discovered_models_available": True,
                    "learned_rankings_available": True,
                },
                "recommendations": {
                    "learned_free_rankings": [
                        {
                            "id": "openrouter/top-choice",
                            "query_type": "general",
                            "rank": 1,
                            "score": 9.2,
                            "confidence": 0.95,
                            "degraded": False,
                        },
                        {
                            "id": "openrouter/weak-choice",
                            "query_type": "general",
                            "rank": 2,
                            "score": 1.1,
                            "confidence": 0.6,
                            "degraded": True,
                        },
                    ]
                },
            }
        )

        status = provider.provider_activation_status()

        self.assertTrue(status["fallback_learning"]["learned_rankings_available"])
        self.assertEqual(status["fallback_learning"]["top_ranked_models"][0]["id"], "openrouter/top-choice")
        self.assertEqual(status["fallback_learning"]["degraded_models"], ["openrouter/weak-choice"])

    def test_daily_briefing_includes_learned_fallback_visibility(self) -> None:
        provider = self._build_provider()
        provider.profile.setdefault("providers", {})["prefer_free_models"] = True
        provider.model_registry.status = MagicMock(
            return_value={
                "discovery": {
                    "scouted_models_available": True,
                    "discovered_models_available": True,
                    "learned_rankings_available": True,
                },
                "recommendations": {
                    "suggested_free_models": [{"id": "openrouter/top-choice"}],
                    "learned_free_rankings": [
                        {
                            "id": "openrouter/top-choice",
                            "query_type": "general",
                            "rank": 1,
                            "score": 9.2,
                            "confidence": 0.95,
                            "degraded": False,
                        },
                        {
                            "id": "openrouter/weak-choice",
                            "query_type": "general",
                            "rank": 2,
                            "score": 1.1,
                            "confidence": 0.6,
                            "degraded": True,
                        },
                    ],
                },
            }
        )
        provider.integration_status = MagicMock(return_value={"remediation": []})
        provider.onboarding_status = MagicMock(return_value={"suggested_cloud_models": [], "suggested_local_models": [{"id": "qwen2.5-7b"}]})
        provider.autonomy_status = MagicMock(return_value={"jobs": {}})
        provider.llm_manager.get_status = MagicMock(return_value={"healthy_count": 1, "total_count": 2})

        briefing = provider.daily_briefing()

        self.assertIn("learned free fallback leaders", briefing["summary"])
        self.assertEqual(briefing["fallback_learning"]["top_ranked_models"][0]["id"], "openrouter/top-choice")
        self.assertTrue(any("Learned free fallback leader" in item for item in briefing["priorities"]))
        self.assertTrue(any("Deprioritize degraded free fallbacks" in item for item in briefing["priorities"]))

    def test_provider_activation_refreshes_when_discovery_payload_is_empty(self) -> None:
        provider = self._build_provider()
        provider.model_registry.status = MagicMock(return_value={"providers": [], "discovery": {}})
        provider.model_registry.refresh = MagicMock(
            return_value={
                "providers": [{"provider_id": "local-llama-cpp"}],
                "discovery": {
                    "local_model_assets_available": False,
                    "local_search_roots": ["D:/models"],
                },
            }
        )

        status = provider.provider_activation_status()

        provider.model_registry.refresh.assert_called_once()
        self.assertEqual(status["discovery"]["local_search_roots"], ["D:/models"])

    def test_operator_job_executor_forwards_autonomy_payload(self) -> None:
        provider = self._build_provider()
        provider.autonomy.run_job = MagicMock(return_value={"status": "preview"})

        result = provider._execute_operator_job(
            {
                "job_type": "autonomy",
                "payload": {
                    "job": "preview_self_repair",
                    "target_project": "D:/OpenChimera",
                },
            }
        )

        self.assertEqual(result["status"], "preview")
        provider.autonomy.run_job.assert_called_once_with("preview_self_repair", payload={"target_project": "D:/OpenChimera"})

    def test_provider_create_operator_job_delegates_to_autonomy_plane(self) -> None:
        provider = self._build_provider()
        provider.autonomy_plane.create_operator_job = MagicMock(return_value={"status": "queued", "job_type": "autonomy.reporting"})

        result = provider.create_operator_job("autonomy", {"job": "dispatch_operator_digest"}, max_attempts=2)

        self.assertEqual(result["job_type"], "autonomy.reporting")
        provider.autonomy_plane.create_operator_job.assert_called_once_with(
            "autonomy",
            {"job": "dispatch_operator_digest"},
            2,
        )

    def test_provider_integration_status_delegates_to_integration_plane(self) -> None:
        provider = self._build_provider()
        provider.integration_plane.build_integration_status = MagicMock(return_value={"engines": {}, "remediation": [], "lineage_only": []})

        result = provider._build_integration_status()

        self.assertEqual(result["engines"], {})
        provider.integration_plane.build_integration_status.assert_called_once_with()

    def test_provider_activation_status_delegates_to_activation_plane(self) -> None:
        provider = self._build_provider()
        provider.activation_plane.provider_activation_status = MagicMock(return_value={"providers": [], "fallback_learning": {}})

        result = provider.provider_activation_status()

        self.assertEqual(result["providers"], [])
        provider.activation_plane.provider_activation_status.assert_called_once_with()

    def test_provider_configure_provider_activation_delegates_to_activation_plane(self) -> None:
        provider = self._build_provider()
        provider.activation_plane.configure_provider_activation = MagicMock(return_value={"status": "ok", "providers": []})

        result = provider.configure_provider_activation(enabled_provider_ids=["local-llama-cpp"], prefer_free_models=True)

        self.assertEqual(result["status"], "ok")
        provider.activation_plane.configure_provider_activation.assert_called_once_with(
            enabled_provider_ids=["local-llama-cpp"],
            preferred_cloud_provider=None,
            prefer_free_models=True,
        )

    def test_provider_mcp_status_delegates_to_capability_plane(self) -> None:
        provider = self._build_provider()
        provider.capability_plane.mcp_status = MagicMock(return_value={"counts": {"total": 1}, "servers": []})

        result = provider.mcp_status()

        self.assertEqual(result["counts"]["total"], 1)
        provider.capability_plane.mcp_status.assert_called_once_with()

    def test_provider_run_query_delegates_to_interaction_plane(self) -> None:
        provider = self._build_provider()
        provider.interaction_plane.run_query = MagicMock(return_value={"session_id": "qs-1", "response": {"choices": []}})

        result = provider.run_query(query="Fetch a page and summarize it", max_tokens=256)

        self.assertEqual(result["session_id"], "qs-1")
        provider.interaction_plane.run_query.assert_called_once_with(
            query="Fetch a page and summarize it",
            messages=None,
            session_id=None,
            permission_scope="user",
            max_tokens=256,
            allow_tool_planning=True,
            allow_agent_spawn=False,
            spawn_job=None,
        )

    def test_provider_browser_fetch_delegates_to_interaction_plane(self) -> None:
        provider = self._build_provider()
        provider.interaction_plane.browser_fetch = MagicMock(return_value={"action": "fetch", "url": "https://example.com"})

        result = provider.browser_fetch("https://example.com", max_chars=512)

        self.assertEqual(result["action"], "fetch")
        provider.interaction_plane.browser_fetch.assert_called_once_with(url="https://example.com", max_chars=512)

    def test_provider_channel_status_delegates_to_interaction_plane(self) -> None:
        provider = self._build_provider()
        provider.interaction_plane.channel_status = MagicMock(return_value={"counts": {"total": 2}})

        result = provider.channel_status()

        self.assertEqual(result["counts"]["total"], 2)
        provider.interaction_plane.channel_status.assert_called_once_with()

    def test_provider_dispatch_daily_briefing_delegates_to_interaction_plane(self) -> None:
        provider = self._build_provider()
        provider.interaction_plane.dispatch_daily_briefing = MagicMock(return_value={"briefing": {"summary": "ok"}, "delivery": {}})

        result = provider.dispatch_daily_briefing()

        self.assertEqual(result["briefing"]["summary"], "ok")
        provider.interaction_plane.dispatch_daily_briefing.assert_called_once_with()

    def test_provider_invoke_subsystem_delegates_to_service_plane(self) -> None:
        provider = self._build_provider()
        provider.service_plane.invoke_subsystem = MagicMock(return_value={"name": "ascension_engine", "status": "ok"})

        result = provider.invoke_subsystem("ascension_engine", "deliberate", {"prompt": "next"})

        self.assertEqual(result["name"], "ascension_engine")
        provider.service_plane.invoke_subsystem.assert_called_once_with("ascension_engine", "deliberate", {"prompt": "next"})

    def test_provider_run_aegis_workflow_delegates_to_service_plane(self) -> None:
        provider = self._build_provider()
        provider.service_plane.run_aegis_workflow = MagicMock(return_value={"status": "preview", "target_project": "D:/OpenChimera"})

        result = provider.run_aegis_workflow(target_project="D:/OpenChimera", preview=True)

        self.assertEqual(result["status"], "preview")
        provider.service_plane.run_aegis_workflow.assert_called_once_with(
            target_project="D:/OpenChimera",
            preview=True,
            preview_context=None,
        )

    def test_provider_start_local_models_delegates_to_service_plane(self) -> None:
        provider = self._build_provider()
        provider.service_plane.start_local_models = MagicMock(return_value={"started": ["qwen2.5-7b"], "errors": {}})

        result = provider.start_local_models(["qwen2.5-7b"])

        self.assertEqual(result["started"], ["qwen2.5-7b"])
        provider.service_plane.start_local_models.assert_called_once_with(["qwen2.5-7b"])

    def test_provider_start_minimind_training_delegates_to_service_plane(self) -> None:
        provider = self._build_provider()
        provider.service_plane.start_minimind_training = MagicMock(return_value={"job_id": "minimind-reason-1", "status": "running"})

        result = provider.start_minimind_training(mode="reason_sft", force_dataset=True)

        self.assertEqual(result["status"], "running")
        provider.service_plane.start_minimind_training.assert_called_once_with(mode="reason_sft", force_dataset=True)

    def test_provider_start_delegates_to_bootstrap_plane(self) -> None:
        provider = self._build_provider()
        provider.bootstrap_plane.start = MagicMock()

        provider.start()

        provider.bootstrap_plane.start.assert_called_once_with()

    def test_provider_stop_delegates_to_bootstrap_plane(self) -> None:
        provider = self._build_provider()
        provider.bootstrap_plane.stop = MagicMock()

        provider.stop()

        provider.bootstrap_plane.stop.assert_called_once_with()

    def test_provider_apply_onboarding_delegates_to_bootstrap_plane(self) -> None:
        provider = self._build_provider()
        provider.bootstrap_plane.apply_onboarding = MagicMock(return_value={"completed": True})

        result = provider.apply_onboarding({"preferred_local_model": "qwen2.5-7b"})

        self.assertTrue(result["completed"])
        provider.bootstrap_plane.apply_onboarding.assert_called_once_with({"preferred_local_model": "qwen2.5-7b"})

    def test_provider_reset_onboarding_delegates_to_bootstrap_plane(self) -> None:
        provider = self._build_provider()
        provider.bootstrap_plane.reset_onboarding = MagicMock(return_value={"completed": False})

        result = provider.reset_onboarding()

        self.assertFalse(result["completed"])
        provider.bootstrap_plane.reset_onboarding.assert_called_once_with()

    def test_provider_list_models_delegates_to_runtime_plane(self) -> None:
        provider = self._build_provider()
        provider.runtime_plane.list_models = MagicMock(return_value={"object": "list", "data": [{"id": "openchimera-local"}]})

        result = provider.list_models()

        self.assertEqual(result["data"][0]["id"], "openchimera-local")
        provider.runtime_plane.list_models.assert_called_once_with()

    def test_provider_embeddings_delegate_to_runtime_plane(self) -> None:
        provider = self._build_provider()
        provider.runtime_plane.embeddings = MagicMock(return_value={"data": [{"embedding": [1.0, 0.0]}], "model": "openchimera-local"})

        result = provider.embeddings("status vector")

        self.assertEqual(result["model"], "openchimera-local")
        provider.runtime_plane.embeddings.assert_called_once_with(input_text="status vector", model="openchimera-local")

    def test_provider_status_delegates_to_runtime_plane(self) -> None:
        provider = self._build_provider()
        provider.runtime_plane.status = MagicMock(return_value={"online": True, "base_url": "http://localhost:7870"})

        result = provider.status()

        self.assertTrue(result["online"])
        provider.runtime_plane.status.assert_called_once_with()

    def test_autonomy_diagnostics_loads_existing_artifacts(self) -> None:
        provider = self._build_provider()
        provider.autonomy.status = MagicMock(
            return_value={
                "artifacts": {
                    "self_audit": str(provider.autonomy.data_root / "self_audit.json"),
                }
            }
        )
        provider.job_queue_status = MagicMock(return_value={"counts": {"failed": 0}})
        provider.provider_activation_status = MagicMock(return_value={"prefer_free_models": False})
        provider.autonomy.data_root.mkdir(parents=True, exist_ok=True)
        (provider.autonomy.data_root / "self_audit.json").write_text('{"status": "ok", "findings": []}', encoding="utf-8")

        diagnostics = provider.autonomy_diagnostics()

        self.assertEqual(diagnostics["artifacts"]["self_audit"]["status"], "ok")

    def test_preview_self_repair_can_enqueue_job(self) -> None:
        provider = self._build_provider()
        provider.create_operator_job = MagicMock(return_value={"job_type": "autonomy", "status": "queued"})

        result = provider.preview_self_repair(target_project="D:/OpenChimera", enqueue=True, max_attempts=2)

        self.assertEqual(result["status"], "queued")
        provider.create_operator_job.assert_called_once_with(
            "autonomy",
            {"job": "preview_self_repair", "target_project": "D:/OpenChimera"},
            max_attempts=2,
        )

    def test_create_operator_job_classifies_autonomy_job_types(self) -> None:
        provider = self._build_provider()
        provider.job_queue.enqueue = MagicMock(return_value={"status": "queued", "job_type": "autonomy.preview_repair"})

        result = provider.create_operator_job("autonomy", {"job": "preview_self_repair", "target_project": "D:/OpenChimera"}, max_attempts=2)

        self.assertEqual(result["job_type"], "autonomy.preview_repair")
        provider.job_queue.enqueue.assert_called_once_with(
            job_type="autonomy.preview_repair",
            payload={"job": "preview_self_repair", "target_project": "D:/OpenChimera"},
            max_attempts=2,
            job_class="autonomy.preview_repair",
            label="Preview self repair",
        )

    def test_create_operator_job_classifies_operator_digest_job(self) -> None:
        provider = self._build_provider()
        provider.job_queue.enqueue = MagicMock(return_value={"status": "queued", "job_type": "autonomy.reporting"})

        result = provider.create_operator_job("autonomy", {"job": "dispatch_operator_digest"}, max_attempts=2)

        self.assertEqual(result["job_type"], "autonomy.reporting")
        provider.job_queue.enqueue.assert_called_once_with(
            job_type="autonomy.reporting",
            payload={"job": "dispatch_operator_digest"},
            max_attempts=2,
            job_class="autonomy.reporting",
            label="Dispatch operator digest",
        )

    def test_autonomy_job_event_dispatches_alert_for_high_severity_audit(self) -> None:
        provider = self._build_provider()
        provider.channels.dispatch = MagicMock()
        provider.autonomy.read_artifact = MagicMock(
            return_value={
                "status": "warning",
                "generated_at": "2026-04-01T00:00:00",
                "findings": [
                    {"id": "generation-path-offline", "severity": "critical", "summary": "No healthy local generation path is currently online."}
                ],
            }
        )

        provider._handle_autonomy_job_event({"job": "run_self_audit", "result": {"status": "warning"}})

        self.assertEqual(provider.channels.dispatch.call_args_list[0].args[0], "system/autonomy/job")
        self.assertEqual(provider.channels.dispatch.call_args_list[1].args[0], "system/autonomy/alert")
        self.assertEqual(provider.channels.dispatch.call_args_list[1].args[1]["severity"], "critical")

    def test_dispatch_channel_forwards_topic_and_payload(self) -> None:
        provider = self._build_provider()
        provider.channels.dispatch = MagicMock(return_value={"topic": "system/autonomy/alert", "delivery_count": 1, "results": []})

        result = provider.dispatch_channel("system/autonomy/alert", {"message": "operator attention required"})

        provider.channels.dispatch.assert_called_once_with("system/autonomy/alert", {"message": "operator attention required"})
        self.assertEqual(result["topic"], "system/autonomy/alert")
        self.assertEqual(result["delivery"]["delivery_count"], 1)

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