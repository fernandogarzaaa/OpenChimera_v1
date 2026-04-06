"""Tests for core.inference_plane — InferencePlane helper utilities.

Tests cover: compress/dedup helpers, _supports_free_fallback_candidate,
_free_fallback_candidates ranking, _extract_remote_completion_text, and
_call_ollama_free_model path (with Ollama mocked).

All tests are offline by default. The live Ollama test is gated via
pytest.mark.skipif.
"""
from __future__ import annotations
import sys
import unittest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helper: build a minimal InferencePlane without a real kernel
# ---------------------------------------------------------------------------

def _make_plane(
    profile: dict | None = None,
    cloud_models: list | None = None,
    credential_store: MagicMock | None = None,
) -> "InferencePlane":
    from core.inference_plane import InferencePlane

    mock_llm = MagicMock()
    mock_llm._prompt_strategy_for_model.return_value = "chat"
    mock_llm._is_usable_completion.return_value = True
    mock_llm._record_route_outcome = MagicMock()

    mock_registry = MagicMock()
    mock_registry.status.return_value = {
        "cloud_models": cloud_models or [],
        "discovery": {},
    }

    mock_cred = credential_store or MagicMock()
    mock_cred.get_provider_credentials.return_value = {}

    mock_minimind = MagicMock()
    mock_minimind.get_runtime_status.return_value = {"status": "idle"}

    mock_rag = MagicMock()
    mock_rag.search.return_value = []

    mock_bus = MagicMock()
    mock_bus.publish_nowait = MagicMock()

    merged_profile = {
        "providers": {"prefer_free_models": True},
        "local_runtime": {"local_timeout_s": 5.0},
    }
    if profile:
        merged_profile.update(profile)

    mock_personality = MagicMock()
    mock_router = MagicMock()
    mock_observability = MagicMock()

    return InferencePlane(
        personality=mock_personality,
        rag=mock_rag,
        llm_manager=mock_llm,
        minimind=mock_minimind,
        router=mock_router,
        model_registry=mock_registry,
        credential_store=mock_cred,
        observability=mock_observability,
        bus=mock_bus,
        profile_getter=lambda: merged_profile,
    )


class TestExtractRemoteCompletionText(unittest.TestCase):
    """Tests for _extract_remote_completion_text parsing."""

    def _plane(self):
        return _make_plane()

    def test_openai_style_payload(self):
        plane = self._plane()
        payload = {
            "choices": [{"message": {"role": "assistant", "content": "hello"}}]
        }
        result = plane._extract_remote_completion_text(payload)
        self.assertEqual(result, "hello")

    def test_ollama_style_payload(self):
        plane = self._plane()
        payload = {"message": {"content": "ollama says hi"}}
        result = plane._extract_remote_completion_text(payload)
        self.assertEqual(result, "ollama says hi")

    def test_empty_payload_returns_empty_string(self):
        plane = self._plane()
        result = plane._extract_remote_completion_text({})
        self.assertEqual(result, "")

    def test_list_content_joined(self):
        plane = self._plane()
        payload = {
            "choices": [
                {
                    "message": {
                        "content": [
                            {"type": "text", "text": "part1"},
                            {"type": "text", "text": "part2"},
                        ]
                    }
                }
            ]
        }
        result = plane._extract_remote_completion_text(payload)
        self.assertIn("part1", result)
        self.assertIn("part2", result)


class TestSupportsFreeCandidate(unittest.TestCase):
    def _plane(self):
        return _make_plane()

    def test_ollama_provider_always_supported(self):
        plane = self._plane()
        self.assertTrue(plane._supports_free_fallback_candidate({"provider": "ollama", "id": "gemma4:latest"}))

    def test_unknown_provider_no_api_key_not_supported(self):
        plane = self._plane()
        self.assertFalse(plane._supports_free_fallback_candidate({"provider": "openrouter", "id": "gpt-4o"}))

    def test_free_model_id_with_api_key_supported(self):
        cred = MagicMock()
        cred.get_provider_credentials.return_value = {"OPENROUTER_API_KEY": "sk-test"}
        plane = _make_plane(credential_store=cred)
        # Patch env var as well
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "sk-test"}):
            self.assertTrue(plane._supports_free_fallback_candidate({"provider": "openrouter", "id": "qwen:free"}))

    def test_autonomy_sync_source_with_api_key_supported(self):
        cred = MagicMock()
        cred.get_provider_credentials.return_value = {}
        plane = _make_plane(credential_store=cred)
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "sk-test"}):
            self.assertTrue(plane._supports_free_fallback_candidate({
                "provider": "openrouter",
                "id": "some-model",
                "source": "autonomy-sync",
            }))


class TestFreeFallbackCandidates(unittest.TestCase):
    def test_ollama_model_included_in_candidates(self):
        cloud_models = [
            {"id": "gemma4:latest", "provider": "ollama", "recommended_for": ["general"]},
        ]
        plane = _make_plane(cloud_models=cloud_models)
        candidates = plane._free_fallback_candidates("general")
        ids = [c["id"] for c in candidates]
        self.assertIn("gemma4:latest", ids)

    def test_ollama_ranked_first_over_openrouter(self):
        cloud_models = [
            {"id": "openrouter-model:free", "provider": "openrouter", "recommended_for": ["general"]},
            {"id": "gemma4:latest", "provider": "ollama", "recommended_for": ["general"]},
        ]
        with patch.dict("os.environ", {"OPENROUTER_API_KEY": "sk-test"}):
            plane = _make_plane(cloud_models=cloud_models)
            candidates = plane._free_fallback_candidates("general")
        # Ollama should come first (provider_rank=0)
        self.assertEqual(candidates[0]["provider"], "ollama")

    def test_excluded_models_are_skipped(self):
        cloud_models = [
            {"id": "gemma4:latest", "provider": "ollama", "recommended_for": ["general"]},
        ]
        plane = _make_plane(cloud_models=cloud_models)
        candidates = plane._free_fallback_candidates("general", exclude=["gemma4:latest"])
        ids = [c["id"] for c in candidates]
        self.assertNotIn("gemma4:latest", ids)

    def test_empty_model_id_skipped(self):
        cloud_models = [
            {"id": "", "provider": "ollama"},
        ]
        plane = _make_plane(cloud_models=cloud_models)
        candidates = plane._free_fallback_candidates("general")
        self.assertEqual(candidates, [])

    def test_capability_rank_respected(self):
        cloud_models = [
            {"id": "specialist:latest", "provider": "ollama", "recommended_for": ["code"]},
            {"id": "general:latest", "provider": "ollama", "recommended_for": ["general"]},
        ]
        plane = _make_plane(cloud_models=cloud_models)
        candidates = plane._free_fallback_candidates("code")
        # The specialist model recommended_for "code" should rank before general
        self.assertEqual(candidates[0]["id"], "specialist:latest")


class TestCallOllamaMocked(unittest.TestCase):
    """Mock the Ollama HTTP call to verify request construction."""

    def test_ollama_call_constructs_correct_payload(self):
        plane = _make_plane()

        captured = {}

        def fake_post(url, payload, headers=None, timeout=30.0):
            captured["url"] = url
            captured["payload"] = payload
            return {"message": {"content": "mocked_response"}}

        plane._post_json_request = fake_post

        result = plane._call_ollama_free_model(
            model_id="gemma4:latest",
            messages=[{"role": "user", "content": "hello"}],
            temperature=0.1,
            max_tokens=50,
            timeout=10.0,
        )

        self.assertIn("11434", captured["url"])
        self.assertEqual(captured["payload"]["model"], "gemma4:latest")
        self.assertFalse(captured["payload"]["stream"])
        self.assertEqual(captured["payload"]["options"]["num_predict"], 50)

    def test_ollama_response_text_extracted(self):
        plane = _make_plane()
        plane._post_json_request = lambda *a, **kw: {"message": {"content": "ALIVE"}}
        result = plane._call_ollama_free_model("gemma4:latest", [], 0.0, 10, 5.0)
        text = plane._extract_remote_completion_text(result)
        self.assertEqual(text, "ALIVE")


class TestFreeModelFallbackEnabled(unittest.TestCase):
    def test_enabled_when_prefer_free_models_true(self):
        plane = _make_plane(profile={"providers": {"prefer_free_models": True}})
        self.assertTrue(plane._free_model_fallback_enabled())

    def test_disabled_when_prefer_free_models_false(self):
        plane = _make_plane(profile={"providers": {"prefer_free_models": False}})
        self.assertFalse(plane._free_model_fallback_enabled())

    def test_disabled_when_providers_key_missing(self):
        plane = _make_plane(profile={"providers": {}})
        self.assertFalse(plane._free_model_fallback_enabled())


class TestHuggingFaceFreeSupport(unittest.TestCase):

    def test_huggingface_provider_always_supported(self):
        plane = _make_plane()
        self.assertTrue(plane._supports_free_fallback_candidate({"provider": "huggingface", "id": "huggingface/meta-llama/Llama-3"}))

    def test_huggingface_prefix_id_always_supported(self):
        plane = _make_plane()
        self.assertTrue(plane._supports_free_fallback_candidate({"provider": "scouted", "id": "huggingface/bloom-560m"}))

    def test_huggingface_api_key_from_env(self):
        plane = _make_plane()
        with patch.dict("os.environ", {"HF_TOKEN": "hf_test123"}):
            self.assertEqual(plane._huggingface_api_key(), "hf_test123")

    def test_huggingface_api_key_from_credential_store(self):
        cred = MagicMock()
        def _creds(provider):
            if provider == "huggingface":
                return {"HF_TOKEN": "hf_stored"}
            return {}
        cred.get_provider_credentials.side_effect = _creds
        plane = _make_plane(credential_store=cred)
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("HF_TOKEN", None)
            self.assertEqual(plane._huggingface_api_key(), "hf_stored")

    def test_call_huggingface_free_model_strips_prefix(self):
        plane = _make_plane()
        with patch.object(plane, "_post_json_request", return_value={"choices": [{"message": {"content": "hello"}}]}) as mock_post:
            result = plane._call_huggingface_free_model(
                "huggingface/meta-llama/Llama-3.2-3B-Instruct",
                [{"role": "user", "content": "hi"}],
                temperature=0.7,
                max_tokens=256,
                timeout=30.0,
            )
        args = mock_post.call_args
        url = args[0][0]
        self.assertIn("meta-llama/Llama-3.2-3B-Instruct", url)
        self.assertNotIn("huggingface/huggingface/", url)
        self.assertEqual(result["choices"][0]["message"]["content"], "hello")

    def test_fallback_dispatcher_routes_to_huggingface(self):
        cloud_models = [
            {"id": "huggingface/bloom-560m", "provider": "huggingface", "recommended_for": ["general"], "source": "autonomy-discovery"},
        ]
        plane = _make_plane(cloud_models=cloud_models)
        with patch.object(plane, "_call_huggingface_free_model", return_value={"choices": [{"message": {"content": "response"}}]}) as mock_hf:
            result = plane._run_free_model_fallback(
                "general",
                [{"role": "user", "content": "test"}],
                temperature=0.7,
                max_tokens=256,
                timeout=30.0,
            )
        mock_hf.assert_called_once()
        self.assertEqual(result["model"], "huggingface/bloom-560m")


if __name__ == "__main__":
    unittest.main()
