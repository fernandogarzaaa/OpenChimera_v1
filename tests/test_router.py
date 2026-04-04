"""Tests for core.router — model routing logic."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from core.router import OpenChimeraRouter, RouteDecision


def _make_llm_manager(ranked_models: list[str] | None = None, status: dict | None = None) -> MagicMock:
    mgr = MagicMock()
    mgr.get_ranked_models.return_value = ranked_models or []
    mgr.get_status.return_value = status or {"healthy_count": 0, "total_count": 0}
    return mgr


class TestOpenChimeraRouter(unittest.TestCase):
    def test_decide_returns_route_decision(self) -> None:
        mgr = _make_llm_manager(["phi-3.5-mini"])
        router = OpenChimeraRouter(mgr)
        decision = router.decide("What is 2+2?")
        self.assertIsInstance(decision, RouteDecision)

    def test_decide_picks_first_candidate(self) -> None:
        mgr = _make_llm_manager(["phi-3.5-mini", "llama-3.2-3b"])
        router = OpenChimeraRouter(mgr)
        decision = router.decide("test", query_type="general")
        self.assertEqual(decision.model, "phi-3.5-mini")

    def test_decide_returns_none_model_when_no_candidates(self) -> None:
        mgr = _make_llm_manager([])
        router = OpenChimeraRouter(mgr)
        decision = router.decide("test", query_type="general")
        self.assertIsNone(decision.model)

    def test_decide_uses_role_selection_when_available(self) -> None:
        mgr = _make_llm_manager(["phi-3.5-mini", "qwen2.5-7b"])
        role_mgr = MagicMock()
        role_mgr.select_model_for_query_type.return_value = {"model": "qwen2.5-7b", "role": "analyst"}
        router = OpenChimeraRouter(mgr, model_roles=role_mgr)
        decision = router.decide("analyze this", query_type="analysis")
        self.assertEqual(decision.model, "qwen2.5-7b")
        self.assertIn("analyst", decision.reason)

    def test_decide_prefer_speed_for_small_tokens(self) -> None:
        mgr = _make_llm_manager(["phi-3.5-mini"])
        router = OpenChimeraRouter(mgr)
        decision = router.decide("hi", max_tokens=100)
        self.assertTrue(decision.prefer_speed)

    def test_decide_quality_bias_for_large_tokens(self) -> None:
        mgr = _make_llm_manager(["llama-3.1-8b"])
        router = OpenChimeraRouter(mgr)
        decision = router.decide("explain quantum physics in detail", query_type="reasoning", max_tokens=2048)
        self.assertFalse(decision.prefer_speed)

    def test_decide_excludes_specified_models(self) -> None:
        mgr = _make_llm_manager(["phi-3.5-mini"])
        # After exclusion, ranked returns empty
        mgr.get_ranked_models.side_effect = lambda **kw: (
            [] if "phi-3.5-mini" in (kw.get("exclude") or []) else ["phi-3.5-mini"]
        )
        router = OpenChimeraRouter(mgr)
        decision = router.decide("test", exclude=["phi-3.5-mini"])
        self.assertIsNone(decision.model)
        self.assertIn("phi-3.5-mini", decision.attempted)

    def test_status_includes_all_fields(self) -> None:
        mgr = _make_llm_manager(
            ["phi-3.5-mini"],
            status={"healthy_count": 1, "total_count": 2},
        )
        router = OpenChimeraRouter(mgr)
        status = router.status()
        self.assertIn("available_models", status)
        self.assertIn("healthy_models", status)
        self.assertIn("known_models", status)

    def test_status_with_model_roles(self) -> None:
        mgr = _make_llm_manager(["phi-3.5-mini"])
        role_mgr = MagicMock()
        role_mgr.status.return_value = {"roles": {"general": "phi-3.5-mini"}}
        router = OpenChimeraRouter(mgr, model_roles=role_mgr)
        status = router.status()
        self.assertIn("roles", status)

    def test_reason_includes_model_name(self) -> None:
        mgr = _make_llm_manager(["qwen2.5-7b"])
        router = OpenChimeraRouter(mgr)
        decision = router.decide("reason this", query_type="reasoning")
        self.assertIn("qwen2.5-7b", decision.reason)

    def test_reason_for_no_model(self) -> None:
        mgr = _make_llm_manager([])
        router = OpenChimeraRouter(mgr)
        decision = router.decide("test", query_type="fast")
        self.assertIn("No healthy model", decision.reason)

    def test_route_decision_dataclass_fields(self) -> None:
        d = RouteDecision(
            model="phi-3.5-mini",
            query_type="general",
            prefer_speed=True,
            attempted=[],
            reason="selected",
        )
        self.assertEqual(d.model, "phi-3.5-mini")
        self.assertEqual(d.query_type, "general")
        self.assertTrue(d.prefer_speed)


if __name__ == "__main__":
    unittest.main()
