"""Phase 4 — Meta-Learning test suite.

Covers:
  - HyperparameterTuner (core.meta_learning)
  - DecompositionStrategyLearner (core.goal_planner)
  - SkillComposer (core.skills_plane)
  - ContinualLearningPipeline (core.evolution)
"""
from __future__ import annotations

import time

import pytest

# ---------------------------------------------------------------------------
# HyperparameterTuner
# ---------------------------------------------------------------------------
from core.meta_learning import (
    HyperparameterTuner,
    register_subsystem,
    observe_metric,
    tune_subsystem,
    _TUNER,
)


class TestHyperparameterTuner:
    def _fresh(self) -> HyperparameterTuner:
        return HyperparameterTuner()

    def test_register_stores_defaults(self):
        tuner = self._fresh()
        tuner.register_subsystem("planner", {"lr": 0.01, "batch": 32.0})
        params = tuner.get_params("planner")
        assert params == {"lr": 0.01, "batch": 32.0}

    def test_register_idempotent(self):
        """Second register call for same subsystem must not overwrite params."""
        tuner = self._fresh()
        tuner.register_subsystem("planner", {"lr": 0.01})
        tuner.register_subsystem("planner", {"lr": 99.0})  # should be ignored
        assert tuner.get_params("planner")["lr"] == pytest.approx(0.01)

    def test_get_params_unknown_returns_empty(self):
        tuner = self._fresh()
        assert tuner.get_params("ghost") == {}

    def test_observe_appends_to_history(self):
        tuner = self._fresh()
        tuner.register_subsystem("encoder", {"dropout": 0.1})
        tuner.observe("encoder", "accuracy", 0.75)
        tuner.observe("encoder", "accuracy", 0.80)
        history = tuner.export_history()
        assert len(history) == 2
        assert history[0]["subsystem"] == "encoder"
        assert history[0]["metric_name"] == "accuracy"
        assert history[0]["metric_value"] == pytest.approx(0.75)

    def test_tune_no_history_returns_current(self):
        tuner = self._fresh()
        tuner.register_subsystem("decoder", {"temperature": 0.9})
        result = tuner.tune("decoder")
        assert result == {"temperature": pytest.approx(0.9)}

    def test_tune_one_observation_returns_current(self):
        tuner = self._fresh()
        tuner.register_subsystem("decoder", {"temperature": 0.9})
        tuner.observe("decoder", "loss", 1.2)
        result = tuner.tune("decoder")
        # Only one observation — no direction to infer
        assert result == {"temperature": pytest.approx(0.9)}

    def test_tune_with_improving_metric_moves_params(self):
        tuner = self._fresh()
        tuner.register_subsystem("agent", {"alpha": 0.5})
        tuner.observe("agent", "score", 0.6)
        tuner.observe("agent", "score", 0.8)  # improvement
        result = tuner.tune("agent")
        # alpha should have moved (either direction) — just verify it changed
        assert "alpha" in result
        assert result["alpha"] != pytest.approx(0.5)

    def test_export_history_returns_all_entries(self):
        tuner = self._fresh()
        tuner.register_subsystem("x", {"p": 1.0})
        for v in [0.1, 0.2, 0.3]:
            tuner.observe("x", "metric", v)
        h = tuner.export_history()
        assert len(h) == 3

    def test_module_level_convenience_api(self):
        """Module-level singleton functions must delegate correctly."""
        register_subsystem("__test_subsystem__", {"eta": 0.05})
        observe_metric("__test_subsystem__", "perf", 0.9)
        observe_metric("__test_subsystem__", "perf", 0.95)
        result = tune_subsystem("__test_subsystem__")
        assert "eta" in result


# ---------------------------------------------------------------------------
# DecompositionStrategyLearner
# ---------------------------------------------------------------------------
from core.goal_planner import DecompositionStrategyLearner


class TestDecompositionStrategyLearner:
    def _fresh(self) -> DecompositionStrategyLearner:
        return DecompositionStrategyLearner()

    def test_record_and_retrieve_best_strategy(self):
        dsl = self._fresh()
        dsl.record_decomposition("search", ["fetch", "rank", "return"], succeeded=True)
        best = dsl.best_strategy("search")
        assert best == ["fetch", "rank", "return"]

    def test_best_strategy_no_history_returns_none(self):
        dsl = self._fresh()
        assert dsl.best_strategy("nonexistent") is None

    def test_best_strategy_picks_highest_success_rate(self):
        dsl = self._fresh()
        # Record two strategies, A with 100% and B with 0%
        dsl.record_decomposition("plan", ["a1", "a2"], succeeded=True)
        dsl.record_decomposition("plan", ["b1"], succeeded=False)
        best = dsl.best_strategy("plan")
        assert best == ["a1", "a2"]

    def test_counters_update_for_same_steps(self):
        dsl = self._fresh()
        dsl.record_decomposition("type1", ["step-x"], succeeded=True)
        dsl.record_decomposition("type1", ["step-x"], succeeded=False)
        strategies = dsl.all_strategies()
        entry = strategies["type1"][0]
        assert entry["attempts"] == 2
        assert entry["successes"] == 1
        assert entry["success_rate"] == pytest.approx(0.5)

    def test_all_strategies_returns_deep_copy(self):
        dsl = self._fresh()
        dsl.record_decomposition("g", ["s1"], succeeded=True)
        result = dsl.all_strategies()
        result["g"][0]["steps"].append("injected")  # mutate copy
        # Original must be unchanged
        assert "injected" not in dsl.all_strategies()["g"][0]["steps"]

    def test_multiple_goal_types_independent(self):
        dsl = self._fresh()
        dsl.record_decomposition("t_a", ["x"], succeeded=True)
        dsl.record_decomposition("t_b", ["y", "z"], succeeded=False)
        assert dsl.best_strategy("t_a") == ["x"]
        assert dsl.best_strategy("t_b") == ["y", "z"]


# ---------------------------------------------------------------------------
# SkillComposer
# ---------------------------------------------------------------------------
from core.skills_plane import SkillComposer


class TestSkillComposer:
    def _fresh(self) -> SkillComposer:
        return SkillComposer()

    def test_compose_returns_record(self):
        sc = self._fresh()
        record = sc.compose("search_and_summarise", ["web_search", "summarise"])
        assert record["name"] == "search_and_summarise"
        assert record["steps"] == ["web_search", "summarise"]
        assert "created_at" in record

    def test_compose_with_description(self):
        sc = self._fresh()
        record = sc.compose("pipeline_a", ["s1", "s2"], description="My pipeline")
        assert record["description"] == "My pipeline"

    def test_list_composed_returns_all(self):
        sc = self._fresh()
        sc.compose("a", ["s1"])
        sc.compose("b", ["s2", "s3"])
        listed = sc.list_composed()
        names = {r["name"] for r in listed}
        assert names == {"a", "b"}

    def test_get_existing_skill(self):
        sc = self._fresh()
        sc.compose("magic", ["x", "y", "z"])
        result = sc.get("magic")
        assert result is not None
        assert result["steps"] == ["x", "y", "z"]

    def test_get_missing_returns_none(self):
        sc = self._fresh()
        assert sc.get("ghost") is None

    def test_compose_overwrites_existing(self):
        sc = self._fresh()
        sc.compose("skill_a", ["old_step"])
        sc.compose("skill_a", ["new_step"])
        assert sc.get("skill_a")["steps"] == ["new_step"]


# ---------------------------------------------------------------------------
# ContinualLearningPipeline
# ---------------------------------------------------------------------------
from core.evolution import ContinualLearningPipeline


class TestContinualLearningPipeline:
    def _fresh(self) -> ContinualLearningPipeline:
        return ContinualLearningPipeline()

    def test_register_returns_metadata(self):
        pipe = self._fresh()
        meta = pipe.register_adapter("ada-001", "nlp", "gpt-base", 50)
        assert meta["adapter_id"] == "ada-001"
        assert meta["domain"] == "nlp"
        assert meta["base_model"] == "gpt-base"
        assert meta["dpo_pairs"] == 50
        assert meta["status"] == "ready"
        assert "registered_at" in meta

    def test_list_adapters_sorted_desc(self):
        pipe = self._fresh()
        pipe.register_adapter("a1", "vision", "base", 10)
        time.sleep(0.01)
        pipe.register_adapter("a2", "vision", "base", 20)
        listed = pipe.list_adapters()
        assert listed[0]["adapter_id"] == "a2"  # most recent first
        assert listed[1]["adapter_id"] == "a1"

    def test_select_adapter_returns_most_recent_for_domain(self):
        pipe = self._fresh()
        pipe.register_adapter("x1", "code", "base", 5)
        time.sleep(0.01)
        pipe.register_adapter("x2", "code", "base", 15)
        selected = pipe.select_adapter("code")
        assert selected is not None
        assert selected["adapter_id"] == "x2"

    def test_select_adapter_unknown_domain_returns_none(self):
        pipe = self._fresh()
        assert pipe.select_adapter("unknown-domain") is None

    def test_mark_deployed_returns_true(self):
        pipe = self._fresh()
        pipe.register_adapter("dep-1", "rl", "base", 3)
        assert pipe.mark_deployed("dep-1") is True
        selected = pipe.select_adapter("rl")
        assert selected["status"] == "deployed"

    def test_mark_deployed_missing_returns_false(self):
        pipe = self._fresh()
        assert pipe.mark_deployed("ghost-id") is False

    def test_pipeline_status_counts(self):
        pipe = self._fresh()
        pipe.register_adapter("s1", "nlp", "base", 10)
        pipe.register_adapter("s2", "nlp", "base", 20)
        pipe.register_adapter("s3", "vision", "base", 5)
        pipe.mark_deployed("s1")
        status = pipe.pipeline_status()
        assert status["total_adapters"] == 3
        assert status["deployed"] == 1
        assert status["pending"] == 2
        assert set(status["domains"]) == {"nlp", "vision"}
