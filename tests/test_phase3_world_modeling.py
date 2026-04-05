"""Tests for Phase 3 — World Modeling.

Covers:
- SystemWorldModel.snapshot()
- SystemWorldModel.update_from_episode()
- SystemWorldModel.get_model()
- SystemWorldModel.export_graph()
- InterventionSimulator.simulate()
- InterventionSimulator.simulate_repair()
- AutonomyScheduler._should_run_predictive()
- DomainWorldModel.record_skill_outcome() / best_skills() / export()
- TransferLearning.update_domain_model() / get_domain_model()
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_bus():
    """Return a minimal EventBus-compatible mock."""
    bus = MagicMock()
    bus.publish_nowait = MagicMock()
    return bus


def _make_causal(bus=None):
    from core.causal_reasoning import CausalReasoning
    return CausalReasoning(bus=bus or _make_bus())


def _make_world_model(causal=None):
    from core.world_model import SystemWorldModel
    return SystemWorldModel(causal=causal or _make_causal())


# ---------------------------------------------------------------------------
# SystemWorldModel tests
# ---------------------------------------------------------------------------

class TestSystemWorldModel:
    def test_snapshot_returns_all_system_nodes(self):
        wm = _make_world_model()
        snap = wm.snapshot()
        from core.world_model import SYSTEM_NODES
        for node in SYSTEM_NODES:
            assert node in snap, f"Expected node '{node}' in snapshot"

    def test_snapshot_node_has_health_and_edges(self):
        wm = _make_world_model()
        snap = wm.snapshot()
        for node_data in snap.values():
            assert "health" in node_data
            assert "edges" in node_data
            assert isinstance(node_data["health"], float)
            assert isinstance(node_data["edges"], list)

    def test_update_from_episode_adds_degraded_edge_on_failure(self):
        wm = _make_world_model()
        episode = {
            "domain": "memory",
            "outcome": "failure",
            "confidence_final": 0.8,
        }
        wm.update_from_episode(episode)
        graph = wm.get_model()
        edges = graph["edges"]
        degraded_edges = [e for e in edges if e["effect"] == "degraded" and e["cause"] == "memory"]
        assert len(degraded_edges) >= 1, "Expected a 'degraded' edge from 'memory'"

    def test_update_from_episode_reduces_node_health_on_failure(self):
        wm = _make_world_model()
        initial_health = wm.snapshot()["memory"]["health"]
        episode = {"domain": "memory", "outcome": "failure", "confidence_final": 0.5}
        wm.update_from_episode(episode)
        new_health = wm.snapshot()["memory"]["health"]
        assert new_health < initial_health, "Health should decrease after failure episode"

    def test_update_from_episode_unknown_domain_creates_node(self):
        wm = _make_world_model()
        episode = {"domain": "new_subsystem", "outcome": "failure", "confidence_final": 0.9}
        wm.update_from_episode(episode)
        snap = wm.snapshot()
        assert "new_subsystem" in snap

    def test_get_model_returns_correct_structure(self):
        wm = _make_world_model()
        model = wm.get_model()
        assert "nodes" in model
        assert "edges" in model
        assert "updated_at" in model
        assert isinstance(model["nodes"], list)
        assert isinstance(model["edges"], list)

    def test_export_graph_returns_triples_after_episode(self):
        wm = _make_world_model()
        episode = {"domain": "evolution", "outcome": "failure", "confidence_final": 0.7}
        wm.update_from_episode(episode)
        triples = wm.export_graph()
        assert isinstance(triples, list)
        assert len(triples) >= 1
        for triple in triples:
            assert len(triple) == 3
            cause, effect, weight = triple
            assert isinstance(cause, str)
            assert isinstance(effect, str)
            assert isinstance(weight, float)


# ---------------------------------------------------------------------------
# InterventionSimulator tests
# ---------------------------------------------------------------------------

class TestInterventionSimulator:
    def _make_simulator(self):
        from core.world_model import InterventionSimulator
        wm = _make_world_model()
        return InterventionSimulator(wm)

    def test_simulate_clear_on_known_node_returns_improvement(self):
        sim = self._make_simulator()
        result = sim.simulate({"target": "memory", "action": "clear", "params": {}})
        assert result["predicted_outcome"] in ("improvement", "partial_improvement")
        assert 0.0 < result["confidence"] <= 1.0
        assert result["risk"] in ("low", "medium")

    def test_simulate_reload_on_known_node_returns_reset(self):
        sim = self._make_simulator()
        result = sim.simulate({"target": "evolution", "action": "reload", "params": {}})
        assert result["predicted_outcome"] in ("reset", "partial_improvement", "improvement")
        assert 0.0 < result["confidence"] <= 1.0
        assert result["risk"] in ("low", "medium")

    def test_simulate_unknown_target_returns_high_risk(self):
        sim = self._make_simulator()
        result = sim.simulate({"target": "nonexistent_node_xyz", "action": "clear", "params": {}})
        assert result["predicted_outcome"] == "unknown"
        assert result["confidence"] == pytest.approx(0.1)
        assert result["risk"] == "high"

    def test_simulate_default_action_returns_neutral(self):
        sim = self._make_simulator()
        result = sim.simulate({"target": "metacognition", "action": "flush", "params": {}})
        assert result["predicted_outcome"] in ("neutral", "partial_improvement")
        assert result["risk"] in ("low", "medium")

    def test_simulate_returns_affected_nodes_list(self):
        sim = self._make_simulator()
        result = sim.simulate({"target": "memory", "action": "clear", "params": {}})
        assert "affected_nodes" in result
        assert isinstance(result["affected_nodes"], list)

    def test_simulate_repair_wraps_autonomy_repair_dict(self):
        from core.world_model import InterventionSimulator
        wm = _make_world_model()
        sim = InterventionSimulator(wm)
        repair = {"chain": "memory", "category": "memory", "action": "clear"}
        result = sim.simulate_repair(repair)
        assert result["predicted_outcome"] in {"improvement", "partial_improvement", "reset", "neutral", "unknown"}
        assert "confidence" in result
        assert "risk" in result


# ---------------------------------------------------------------------------
# AutonomyScheduler._should_run_predictive tests
# ---------------------------------------------------------------------------

class TestPredictiveScheduling:
    def _make_scheduler(self):
        from core.autonomy import AutonomyScheduler
        bus = _make_bus()
        harness = MagicMock()
        minimind = MagicMock()
        identity = {}
        with patch("core.autonomy.load_runtime_profile", return_value={}), \
             patch("core.autonomy.get_legacy_workspace_root", return_value=MagicMock()), \
             patch("core.autonomy.CausalReasoning", return_value=MagicMock()), \
             patch("core.autonomy.TransferLearning", return_value=MagicMock()):
            scheduler = AutonomyScheduler(bus, harness, minimind, identity)
        return scheduler

    def test_high_ece_triggers_learning_job(self):
        scheduler = self._make_scheduler()
        job = scheduler.jobs.get("learn_fallback_rankings")
        if job is None:
            pytest.skip("learn_fallback_rankings job not present")
        job.last_run_at = time.time() - 10  # recently run, not normally due
        result = scheduler._should_run_predictive("learn_fallback_rankings", job, ece_score=0.20)
        assert result is True

    def test_low_ece_does_not_trigger_learning_job(self):
        scheduler = self._make_scheduler()
        job = scheduler.jobs.get("learn_fallback_rankings")
        if job is None:
            pytest.skip("learn_fallback_rankings job not present")
        job.last_status = "ok"
        job.success_streak = 0
        result = scheduler._should_run_predictive("learn_fallback_rankings", job, ece_score=0.05)
        assert result is False

    def test_failed_job_triggers_early_run_after_half_interval(self):
        scheduler = self._make_scheduler()
        job = scheduler.jobs.get("run_self_audit")
        if job is None:
            pytest.skip("run_self_audit job not present")
        job.last_status = "error"
        job.last_run_at = time.time() - (job.interval_seconds * 0.6)  # past half interval
        result = scheduler._should_run_predictive("run_self_audit", job, ece_score=None)
        assert result is True

    def test_success_streak_defers_run(self):
        scheduler = self._make_scheduler()
        job = scheduler.jobs.get("run_self_audit")
        if job is None:
            pytest.skip("run_self_audit job not present")
        job.last_status = "ok"
        job.success_streak = 10
        # Mark as if run very recently — within normal interval
        job.last_run_at = time.time() - (job.interval_seconds * 0.5)
        result = scheduler._should_run_predictive("run_self_audit", job, ece_score=None)
        assert result is False  # Should be deferred due to extended interval


# ---------------------------------------------------------------------------
# DomainWorldModel tests
# ---------------------------------------------------------------------------

class TestDomainWorldModel:
    def test_record_and_best_skills(self):
        from core.transfer_learning import DomainWorldModel
        dwm = DomainWorldModel("math")
        dwm.record_skill_outcome("algebra", "success", 0.9)
        dwm.record_skill_outcome("algebra", "success", 0.8)
        dwm.record_skill_outcome("calculus", "success", 0.5)
        dwm.record_skill_outcome("geometry", "failure", 0.3)

        best = dwm.best_skills(top_k=2)
        assert len(best) <= 2
        # algebra should rank first (high confidence + success ratio)
        assert best[0] == "algebra"

    def test_export_structure(self):
        from core.transfer_learning import DomainWorldModel
        dwm = DomainWorldModel("science")
        dwm.record_skill_outcome("physics", "success", 0.7)
        dwm.record_skill_outcome("chemistry", "failure", 0.4)
        exported = dwm.export()
        assert exported["domain"] == "science"
        assert "physics" in exported["skills"]
        assert "chemistry" in exported["skills"]
        assert "avg_conf" in exported["skills"]["physics"]
        assert "successes" in exported["skills"]["physics"]
        assert "failures" in exported["skills"]["physics"]


# ---------------------------------------------------------------------------
# TransferLearning domain model integration tests
# ---------------------------------------------------------------------------

class TestTransferLearningDomainModels:
    def _make_tl(self):
        from core.transfer_learning import TransferLearning
        return TransferLearning(bus=_make_bus())

    def test_update_domain_model_creates_and_populates(self):
        tl = self._make_tl()
        tl.update_domain_model("robotics", "grasp_skill", "success", 0.85)
        tl.update_domain_model("robotics", "grasp_skill", "failure", 0.3)
        dm = tl.get_domain_model("robotics")
        exported = dm.export()
        assert exported["domain"] == "robotics"
        assert "grasp_skill" in exported["skills"]
        assert exported["skills"]["grasp_skill"]["successes"] == 1
        assert exported["skills"]["grasp_skill"]["failures"] == 1

    def test_get_domain_model_returns_same_instance(self):
        tl = self._make_tl()
        dm1 = tl.get_domain_model("nlp")
        dm2 = tl.get_domain_model("nlp")
        assert dm1 is dm2

    def test_get_domain_model_creates_empty_for_new_domain(self):
        tl = self._make_tl()
        dm = tl.get_domain_model("unseen_domain")
        assert dm.domain == "unseen_domain"
        exported = dm.export()
        assert exported["skills"] == {}
