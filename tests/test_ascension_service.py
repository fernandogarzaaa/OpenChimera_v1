"""Tests for core.ascension_service — AscensionService lifecycle, deliberation, and consensus."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, call

from core.ascension_service import AscensionService


def _make_service(minimind_content: str = "thoughtful analysis", minimind_model: str = "minimind-v1") -> tuple[AscensionService, MagicMock, MagicMock]:
    mock_llm = MagicMock()
    mock_minimind = MagicMock()
    mock_minimind.reasoning_completion.return_value = {
        "content": minimind_content,
        "model": minimind_model,
    }
    svc = AscensionService(llm_manager=mock_llm, minimind=mock_minimind)
    return svc, mock_llm, mock_minimind


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

class TestAscensionServiceLifecycle(unittest.TestCase):
    def setUp(self) -> None:
        self.svc, self.mock_llm, self.mock_minimind = _make_service()

    def test_initial_running_is_false(self) -> None:
        self.assertFalse(self.svc.running)

    def test_initial_last_result_is_none(self) -> None:
        self.assertIsNone(self.svc.last_result)

    def test_start_sets_running_true(self) -> None:
        self.svc.start()
        self.assertTrue(self.svc.running)

    def test_start_returns_dict(self) -> None:
        result = self.svc.start()
        self.assertIsInstance(result, dict)

    def test_start_returns_running_true(self) -> None:
        result = self.svc.start()
        self.assertTrue(result["running"])

    def test_stop_sets_running_false(self) -> None:
        self.svc.start()
        self.svc.stop()
        self.assertFalse(self.svc.running)

    def test_stop_returns_dict(self) -> None:
        result = self.svc.stop()
        self.assertIsInstance(result, dict)

    def test_stop_returns_running_false(self) -> None:
        self.svc.start()
        result = self.svc.stop()
        self.assertFalse(result["running"])

    def test_start_stop_cycle(self) -> None:
        self.svc.start()
        self.assertTrue(self.svc.running)
        self.svc.stop()
        self.assertFalse(self.svc.running)


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

class TestAscensionServiceStatus(unittest.TestCase):
    def setUp(self) -> None:
        self.svc, _, _ = _make_service()

    def test_status_has_name_key(self) -> None:
        self.assertIn("name", self.svc.status())

    def test_status_has_available_key(self) -> None:
        self.assertIn("available", self.svc.status())

    def test_status_has_running_key(self) -> None:
        self.assertIn("running", self.svc.status())

    def test_status_has_last_result_key(self) -> None:
        self.assertIn("last_result", self.svc.status())

    def test_status_has_capabilities_key(self) -> None:
        self.assertIn("capabilities", self.svc.status())

    def test_status_name_is_ascension(self) -> None:
        self.assertEqual(self.svc.status()["name"], "ascension")

    def test_status_available_true(self) -> None:
        self.assertTrue(self.svc.status()["available"])

    def test_status_capabilities_includes_deliberation(self) -> None:
        self.assertIn("multi-perspective-deliberation", self.svc.status()["capabilities"])

    def test_status_capabilities_includes_consensus(self) -> None:
        self.assertIn("consensus-synthesis", self.svc.status()["capabilities"])

    def test_status_last_result_none_initially(self) -> None:
        self.assertIsNone(self.svc.status()["last_result"])


# ---------------------------------------------------------------------------
# Deliberate — happy path
# ---------------------------------------------------------------------------

class TestAscensionServiceDeliberate(unittest.TestCase):
    def setUp(self) -> None:
        self.svc, self.mock_llm, self.mock_minimind = _make_service("concrete reasoning here")

    def test_deliberate_returns_dict(self) -> None:
        result = self.svc.deliberate("What is the best architecture?")
        self.assertIsInstance(result, dict)

    def test_deliberate_status_ok(self) -> None:
        result = self.svc.deliberate("test prompt")
        self.assertEqual(result["status"], "ok")

    def test_deliberate_includes_correct_prompt(self) -> None:
        result = self.svc.deliberate("design the system")
        self.assertEqual(result["prompt"], "design the system")

    def test_deliberate_includes_running_key(self) -> None:
        result = self.svc.deliberate("test")
        self.assertIn("running", result)

    def test_deliberate_running_matches_service_state(self) -> None:
        self.svc.start()
        result = self.svc.deliberate("test")
        self.assertTrue(result["running"])

    def test_deliberate_includes_perspectives_list(self) -> None:
        result = self.svc.deliberate("test")
        self.assertIsInstance(result["perspectives"], list)

    def test_deliberate_includes_consensus_string(self) -> None:
        result = self.svc.deliberate("test")
        self.assertIsInstance(result["consensus"], str)

    def test_deliberate_includes_generated_at_float(self) -> None:
        result = self.svc.deliberate("test")
        self.assertIn("generated_at", result)
        self.assertIsInstance(result["generated_at"], float)

    def test_deliberate_default_three_perspectives(self) -> None:
        result = self.svc.deliberate("test")
        self.assertEqual(len(result["perspectives"]), 3)

    def test_deliberate_perspective_has_required_fields(self) -> None:
        result = self.svc.deliberate("test")
        for p in result["perspectives"]:
            self.assertIn("perspective", p)
            self.assertIn("model", p)
            self.assertIn("source", p)
            self.assertIn("content", p)

    def test_deliberate_calls_minimind_per_perspective(self) -> None:
        self.svc.deliberate("test")
        self.assertEqual(self.mock_minimind.reasoning_completion.call_count, 3)

    def test_deliberate_source_is_minimind_when_content_returned(self) -> None:
        result = self.svc.deliberate("test")
        for p in result["perspectives"]:
            self.assertEqual(p["source"], "minimind")

    def test_deliberate_stores_result_in_last_result(self) -> None:
        result = self.svc.deliberate("test prompt")
        self.assertIs(self.svc.last_result, result)

    def test_deliberate_last_result_visible_in_status(self) -> None:
        self.svc.deliberate("status check")
        self.assertIsNotNone(self.svc.status()["last_result"])

    def test_multiple_deliberates_update_last_result(self) -> None:
        r1 = self.svc.deliberate("first prompt")
        r2 = self.svc.deliberate("second prompt")
        self.assertIs(self.svc.last_result, r2)
        self.assertIsNot(self.svc.last_result, r1)

    def test_deliberate_does_not_call_llm_manager_when_minimind_succeeds(self) -> None:
        self.svc.deliberate("test")
        self.mock_llm.get_ranked_models.assert_not_called()
        self.mock_llm.chat_completion.assert_not_called()


# ---------------------------------------------------------------------------
# Deliberate — custom / capped perspectives
# ---------------------------------------------------------------------------

class TestAscensionServicePerspectives(unittest.TestCase):
    def setUp(self) -> None:
        self.svc, self.mock_llm, self.mock_minimind = _make_service("ok response")

    def test_deliberate_custom_perspectives_reflected(self) -> None:
        result = self.svc.deliberate("test", perspectives=["tester", "reviewer"])
        names = [p["perspective"] for p in result["perspectives"]]
        self.assertIn("tester", names)
        self.assertIn("reviewer", names)

    def test_deliberate_caps_at_four_perspectives(self) -> None:
        result = self.svc.deliberate("test", perspectives=["a", "b", "c", "d", "e"])
        self.assertLessEqual(len(result["perspectives"]), 4)
        self.assertEqual(self.mock_minimind.reasoning_completion.call_count, 4)

    def test_deliberate_single_perspective(self) -> None:
        result = self.svc.deliberate("test", perspectives=["strategist"])
        self.assertEqual(len(result["perspectives"]), 1)
        self.assertEqual(result["perspectives"][0]["perspective"], "strategist")


# ---------------------------------------------------------------------------
# Deliberate — fallback paths
# ---------------------------------------------------------------------------

class TestAscensionServiceFallback(unittest.TestCase):
    def setUp(self) -> None:
        self.svc, self.mock_llm, self.mock_minimind = _make_service(minimind_content="")

    def test_fallback_calls_get_ranked_models(self) -> None:
        self.mock_llm.get_ranked_models.return_value = ["local-model"]
        self.mock_llm.chat_completion.return_value = {"content": "llm fallback", "model": "local-model"}
        self.svc.deliberate("test")
        self.mock_llm.get_ranked_models.assert_called()

    def test_fallback_calls_chat_completion(self) -> None:
        self.mock_llm.get_ranked_models.return_value = ["local-model"]
        self.mock_llm.chat_completion.return_value = {"content": "llm fallback", "model": "local-model"}
        self.svc.deliberate("test")
        self.mock_llm.chat_completion.assert_called()

    def test_fallback_source_is_local_llm(self) -> None:
        self.mock_llm.get_ranked_models.return_value = ["local-model"]
        self.mock_llm.chat_completion.return_value = {"content": "fallback content", "model": "local-model"}
        result = self.svc.deliberate("test")
        for p in result["perspectives"]:
            self.assertEqual(p["source"], "local-llm")

    def test_fallback_uses_cannot_resolve_when_no_models(self) -> None:
        self.mock_llm.get_ranked_models.return_value = []
        result = self.svc.deliberate("test", perspectives=["skeptic"])
        self.assertIn("could not be resolved", result["perspectives"][0]["content"])

    def test_fallback_uses_cannot_resolve_when_both_empty(self) -> None:
        self.mock_llm.get_ranked_models.return_value = ["local-model"]
        self.mock_llm.chat_completion.return_value = {"content": "", "model": "local-model"}
        result = self.svc.deliberate("test", perspectives=["operator"])
        self.assertIn("could not be resolved", result["perspectives"][0]["content"])


# ---------------------------------------------------------------------------
# Deliberate — max_tokens
# ---------------------------------------------------------------------------

class TestAscensionServiceMaxTokens(unittest.TestCase):
    def setUp(self) -> None:
        self.svc, _, self.mock_minimind = _make_service("response")

    def test_max_tokens_passed_to_minimind_is_bounded(self) -> None:
        self.svc.deliberate("test", max_tokens=100)
        for c in self.mock_minimind.reasoning_completion.call_args_list:
            passed = c.kwargs.get("max_tokens", c[1].get("max_tokens", 0))
            self.assertLessEqual(passed, 100)

    def test_max_tokens_at_least_96_for_low_input(self) -> None:
        # max(96, max_tokens // 2) ensures at least 96 tokens
        self.svc.deliberate("test", max_tokens=50)
        for c in self.mock_minimind.reasoning_completion.call_args_list:
            passed = c.kwargs.get("max_tokens", c[1].get("max_tokens", 0))
            self.assertGreaterEqual(passed, 96)


# ---------------------------------------------------------------------------
# _build_consensus
# ---------------------------------------------------------------------------

class TestBuildConsensus(unittest.TestCase):
    def setUp(self) -> None:
        self.svc, _, _ = _make_service()

    def test_build_consensus_returns_non_empty_string(self) -> None:
        responses = [{"perspective": "architect", "content": "use microservices"}]
        result = self.svc._build_consensus("my prompt", responses)
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    def test_build_consensus_contains_prompt(self) -> None:
        responses = [{"perspective": "tester", "content": "test everything"}]
        result = self.svc._build_consensus("sentinel-xyz-prompt", responses)
        self.assertIn("sentinel-xyz-prompt", result)

    def test_build_consensus_contains_perspective_content(self) -> None:
        responses = [{"perspective": "operator", "content": "keep it running 24/7"}]
        result = self.svc._build_consensus("uptime", responses)
        self.assertIn("operator", result)

    def test_build_consensus_multiple_perspectives(self) -> None:
        responses = [
            {"perspective": "architect", "content": "design first"},
            {"perspective": "skeptic", "content": "question assumptions"},
        ]
        result = self.svc._build_consensus("big question", responses)
        self.assertIn("architect", result)
        self.assertIn("skeptic", result)

    def test_deliberate_consensus_contains_prompt(self) -> None:
        result = self.svc.deliberate("unique-sentinel-prompt")
        self.assertIn("unique-sentinel-prompt", result["consensus"])


if __name__ == "__main__":
    unittest.main()
