"""Phase 2 — Self-Awareness: unit tests.

Covers:
1. EpisodicMemory.consolidate_to_semantic() — triple promotion
2. MetacognitionEngine.adapt_thresholds()   — threshold adjustment (both directions)
3. EvolutionEngine.adapt_thresholds()       — similarity threshold adjustment
4. CausalReasoning.discover_from_episodes() — causal edge extraction
5. AutonomyScheduler._apply_repair()        — repair dispatch for all categories

All tests use in-process SQLite via DatabaseManager (no external models needed).
"""
from __future__ import annotations

import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core._bus_fallback import EventBus
from core._database_fallback import DatabaseManager
from core.causal_reasoning import CausalReasoning, EdgeType
from core.evolution import EvolutionEngine
from core.memory.episodic import EpisodicMemory
from core.memory.semantic import SemanticMemory
from core.metacognition import MetacognitionEngine


# ---------------------------------------------------------------------------
# Shared test infrastructure
# ---------------------------------------------------------------------------

class _DBBase(unittest.TestCase):
    """Base class: spins up an in-memory SQLite DB for each test."""

    def setUp(self) -> None:
        self.bus = EventBus()
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.db = DatabaseManager(self._tmp.name)
        self.db.initialize()

    def tearDown(self) -> None:
        self.db.close()
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# 1. EpisodicMemory.consolidate_to_semantic()
# ---------------------------------------------------------------------------

class TestConsolidateToSemantic(_DBBase):
    """Verify that episodic patterns are correctly promoted to semantic triples."""

    def _make_mem(self) -> tuple[EpisodicMemory, SemanticMemory]:
        return EpisodicMemory(self.db, self.bus), SemanticMemory(self.db, self.bus)

    def _add_episodes(
        self,
        episodic: EpisodicMemory,
        domain: str,
        outcome: str,
        count: int,
        reasoning_steps: list[str] | None = None,
        failure_reason: str | None = None,
    ) -> None:
        for i in range(count):
            steps = reasoning_steps or [f"step_{i}"]
            episodic.record_episode(
                session_id=f"sess-{domain}-{outcome}-{i}",
                goal=f"goal for {domain}",
                outcome=outcome,
                confidence_initial=0.5,
                confidence_final=0.7 if outcome == "success" else 0.3,
                models_used=["test-model"],
                reasoning_chain=steps,
                failure_reason=failure_reason,
                domain=domain,
            )

    def test_success_pattern_triple_promoted(self) -> None:
        episodic, semantic = self._make_mem()
        self._add_episodes(episodic, "math", "success", 4)

        result = episodic.consolidate_to_semantic(semantic, min_occurrences=3)

        self.assertGreaterEqual(result["pattern_triples"], 1)
        triples = semantic.get_triples(subject="math", predicate="has_pattern", object_="successful_approach")
        self.assertEqual(len(triples), 1)

    def test_failure_pattern_triple_promoted(self) -> None:
        episodic, semantic = self._make_mem()
        self._add_episodes(episodic, "code", "failure", 5)

        result = episodic.consolidate_to_semantic(semantic, min_occurrences=3)

        self.assertGreaterEqual(result["pattern_triples"], 1)
        triples = semantic.get_triples(subject="code", predicate="has_pattern", object_="failure_mode")
        self.assertEqual(len(triples), 1)

    def test_below_threshold_not_promoted(self) -> None:
        episodic, semantic = self._make_mem()
        self._add_episodes(episodic, "general", "success", 2)  # < min_occurrences=3

        episodic.consolidate_to_semantic(semantic, min_occurrences=3)

        triples = semantic.get_triples(subject="general", predicate="has_pattern")
        self.assertEqual(len(triples), 0)

    def test_key_reasoning_step_triple_promoted(self) -> None:
        episodic, semantic = self._make_mem()
        # 3 episodes with the same leading step, 1 with a different one
        self._add_episodes(episodic, "reasoning", "success", 3, reasoning_steps=["observe first", "then hypothesis"])
        self._add_episodes(episodic, "reasoning", "success", 1, reasoning_steps=["skip ahead"])

        episodic.consolidate_to_semantic(semantic, min_occurrences=3)

        triples = semantic.get_triples(subject="reasoning", predicate="key_reasoning_step")
        self.assertEqual(len(triples), 1)
        self.assertEqual(triples[0]["object"], "observe first")

    def test_return_dict_keys(self) -> None:
        episodic, semantic = self._make_mem()
        self._add_episodes(episodic, "creative", "success", 4)

        result = episodic.consolidate_to_semantic(semantic, min_occurrences=3)

        self.assertIn("triples_promoted", result)
        self.assertIn("pattern_triples", result)
        self.assertIn("reasoning_step_triples", result)
        self.assertEqual(
            result["triples_promoted"],
            result["pattern_triples"] + result["reasoning_step_triples"],
        )

    def test_both_success_and_failure_promoted(self) -> None:
        episodic, semantic = self._make_mem()
        self._add_episodes(episodic, "code", "success", 3)
        self._add_episodes(episodic, "code", "failure", 3)

        result = episodic.consolidate_to_semantic(semantic, min_occurrences=3)

        success_triples = semantic.get_triples(subject="code", predicate="has_pattern", object_="successful_approach")
        failure_triples = semantic.get_triples(subject="code", predicate="has_pattern", object_="failure_mode")
        self.assertEqual(len(success_triples), 1)
        self.assertEqual(len(failure_triples), 1)
        self.assertGreaterEqual(result["pattern_triples"], 2)


# ---------------------------------------------------------------------------
# 2. MetacognitionEngine.adapt_thresholds()
# ---------------------------------------------------------------------------

class TestMetacognitionAdaptThresholds(_DBBase):
    """Verify that adapt_thresholds adjusts the confidence threshold correctly."""

    def _engine(self) -> MetacognitionEngine:
        return MetacognitionEngine(self.db, self.bus)

    def test_default_threshold_is_0_7(self) -> None:
        engine = self._engine()
        self.assertAlmostEqual(engine._thresholds["confidence_threshold"], 0.7)

    def test_high_ece_increases_threshold(self) -> None:
        engine = self._engine()
        result = engine.adapt_thresholds({"ece": 0.25})
        self.assertAlmostEqual(result["confidence_threshold"], 0.75, places=4)

    def test_low_ece_decreases_threshold(self) -> None:
        engine = self._engine()
        result = engine.adapt_thresholds({"ece": 0.03})
        self.assertAlmostEqual(result["confidence_threshold"], 0.68, places=4)

    def test_mid_ece_no_change(self) -> None:
        engine = self._engine()
        result = engine.adapt_thresholds({"ece": 0.1})
        self.assertAlmostEqual(result["confidence_threshold"], 0.7, places=4)

    def test_threshold_caps_at_0_9(self) -> None:
        engine = self._engine()
        engine._thresholds["confidence_threshold"] = 0.88
        result = engine.adapt_thresholds({"ece": 0.9})
        self.assertLessEqual(result["confidence_threshold"], 0.9)

    def test_threshold_floors_at_0_3(self) -> None:
        engine = self._engine()
        engine._thresholds["confidence_threshold"] = 0.31
        result = engine.adapt_thresholds({"ece": 0.0})
        self.assertGreaterEqual(result["confidence_threshold"], 0.3)

    def test_event_published(self) -> None:
        published: list[tuple[str, dict]] = []
        self.bus.subscribe("metacognition.threshold.adapted", lambda ev: published.append(ev))

        engine = self._engine()
        engine.adapt_thresholds({"ece": 0.25})

        self.assertEqual(len(published), 1)


# ---------------------------------------------------------------------------
# 3. EvolutionEngine.adapt_thresholds()
# ---------------------------------------------------------------------------

class TestEvolutionAdaptThresholds(_DBBase):
    """Verify that EvolutionEngine.adapt_thresholds() tunes similarity_threshold."""

    def _engine(self) -> EvolutionEngine:
        return EvolutionEngine(self.db, self.bus)

    def test_default_threshold_is_0_85(self) -> None:
        engine = self._engine()
        self.assertAlmostEqual(engine._thresholds["similarity_threshold"], 0.85)

    def test_zero_pairs_decreases_threshold(self) -> None:
        engine = self._engine()
        result = engine.adapt_thresholds({"total_pairs": 0})
        self.assertAlmostEqual(result["similarity_threshold"], 0.80, places=4)

    def test_many_pairs_increases_threshold(self) -> None:
        engine = self._engine()
        result = engine.adapt_thresholds({"total_pairs": 15})
        self.assertAlmostEqual(result["similarity_threshold"], 0.87, places=4)

    def test_few_pairs_no_change(self) -> None:
        engine = self._engine()
        result = engine.adapt_thresholds({"total_pairs": 5})
        self.assertAlmostEqual(result["similarity_threshold"], 0.85, places=4)

    def test_threshold_caps_at_0_95(self) -> None:
        engine = self._engine()
        engine._thresholds["similarity_threshold"] = 0.94
        result = engine.adapt_thresholds({"total_pairs": 100})
        self.assertLessEqual(result["similarity_threshold"], 0.95)

    def test_threshold_floors_at_0_5(self) -> None:
        engine = self._engine()
        engine._thresholds["similarity_threshold"] = 0.51
        result = engine.adapt_thresholds({"total_pairs": 0})
        self.assertGreaterEqual(result["similarity_threshold"], 0.5)

    def test_event_published(self) -> None:
        published: list[tuple[str, dict]] = []
        self.bus.subscribe("evolution.threshold.adapted", lambda ev: published.append(ev))

        engine = self._engine()
        engine.adapt_thresholds({"total_pairs": 0})

        self.assertEqual(len(published), 1)


# ---------------------------------------------------------------------------
# 4. CausalReasoning.discover_from_episodes()
# ---------------------------------------------------------------------------

class TestDiscoverFromEpisodes(unittest.TestCase):
    """Verify causal edge discovery from episodic failure data."""

    def setUp(self) -> None:
        self.bus = EventBus()
        self.causal = CausalReasoning(bus=self.bus)

    def test_basic_edge_extracted(self) -> None:
        episodes = [
            {"outcome": "failure", "domain": "routing", "failure_reason": "timeout"},
            {"outcome": "failure", "domain": "routing", "failure_reason": "timeout"},
        ]
        edges = self.causal.discover_from_episodes(episodes)
        self.assertEqual(len(edges), 1)
        cause, effect, weight = edges[0]
        self.assertEqual(cause, "routing")
        self.assertEqual(effect, "timeout")
        self.assertAlmostEqual(weight, 1.0, places=4)

    def test_non_failure_episodes_ignored(self) -> None:
        episodes = [
            {"outcome": "success", "domain": "routing", "failure_reason": "timeout"},
            {"outcome": "failure", "domain": "routing", "failure_reason": "timeout"},
        ]
        edges = self.causal.discover_from_episodes(episodes)
        # Only the failure episode counts
        self.assertEqual(len(edges), 1)

    def test_multiple_causes_and_effects(self) -> None:
        episodes = [
            {"outcome": "failure", "domain": "math", "failure_reason": "overflow"},
            {"outcome": "failure", "domain": "math", "failure_reason": "overflow"},
            {"outcome": "failure", "domain": "math", "failure_reason": "underflow"},
            {"outcome": "failure", "domain": "routing", "failure_reason": "timeout"},
        ]
        edges = self.causal.discover_from_episodes(episodes)
        self.assertEqual(len(edges), 3)
        causes = {e[0] for e in edges}
        self.assertIn("math", causes)
        self.assertIn("routing", causes)

    def test_weights_sum_to_1(self) -> None:
        episodes = [
            {"outcome": "failure", "domain": "A", "failure_reason": "err1"},
            {"outcome": "failure", "domain": "B", "failure_reason": "err2"},
            {"outcome": "failure", "domain": "C", "failure_reason": "err3"},
        ]
        edges = self.causal.discover_from_episodes(episodes)
        total_weight = sum(w for _, _, w in edges)
        self.assertAlmostEqual(total_weight, 1.0, places=4)

    def test_empty_returns_empty_list(self) -> None:
        edges = self.causal.discover_from_episodes([])
        self.assertEqual(edges, [])

    def test_no_failure_reason_skipped(self) -> None:
        episodes = [
            {"outcome": "failure", "domain": "X", "failure_reason": None},
            {"outcome": "failure", "domain": "X", "failure_reason": ""},
        ]
        edges = self.causal.discover_from_episodes(episodes)
        self.assertEqual(edges, [])

    def test_edges_added_to_graph(self) -> None:
        episodes = [
            {"outcome": "failure", "domain": "db", "failure_reason": "connection_refused"},
        ]
        self.causal.discover_from_episodes(episodes)
        graph_edge = self.causal.graph.get_edge("db", "connection_refused")
        self.assertIsNotNone(graph_edge)


# ---------------------------------------------------------------------------
# 5. AutonomyScheduler._apply_repair()
# ---------------------------------------------------------------------------

class _FakeMiniMind:
    def build_training_dataset(self, harness_port, identity_snapshot, force=True):
        return {"files": {}, "counts": {}}


class TestApplyRepair(unittest.TestCase):
    """Verify _apply_repair dispatches correctly for each category."""

    def _make_scheduler(self, temp_root: Path) -> "AutonomyScheduler":  # type: ignore[name-defined]
        from core.autonomy import AutonomyScheduler
        from core.bus import EventBus as BusImpl

        profile = {
            "autonomy": {"enabled": True, "auto_start": False, "jobs": {}},
            "model_inventory": {},
        }
        with patch("core.autonomy.ROOT", temp_root), \
             patch("core.autonomy.load_runtime_profile", return_value=profile), \
             patch("core.autonomy.get_legacy_workspace_root", return_value=temp_root / "legacy"):
            scheduler = AutonomyScheduler(
                BusImpl(),
                harness_port=object(),
                minimind=_FakeMiniMind(),
                identity_snapshot={},
            )
        return scheduler

    def test_memory_repair_with_no_memory_bound(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scheduler = self._make_scheduler(Path(tmp))
            repair = {"id": "test-repair", "category": "memory"}
            result = scheduler._apply_repair(repair)

        self.assertTrue(result["applied"])
        self.assertIn("action", result)
        self.assertEqual(result["repair"], repair)
        # No memory system bound → skipped cleanly
        self.assertEqual(result["action"], "memory_clear_skipped_no_handle")

    def test_memory_repair_clears_working_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scheduler = self._make_scheduler(Path(tmp))
            mock_working = MagicMock()
            mock_memory = MagicMock()
            mock_memory.working = mock_working
            scheduler._memory = mock_memory

            repair = {"id": "mem-repair", "category": "memory"}
            result = scheduler._apply_repair(repair)

        self.assertTrue(result["applied"])
        self.assertEqual(result["action"], "working_memory_cleared")
        mock_working.clear.assert_called_once()

    def test_model_repair_queued(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scheduler = self._make_scheduler(Path(tmp))
            repair = {"id": "model-repair", "category": "model"}
            result = scheduler._apply_repair(repair)

        self.assertTrue(result["applied"])
        self.assertEqual(result["action"], "model_reload_queued")
        self.assertEqual(result["repair"], repair)

    def test_config_repair_no_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scheduler = self._make_scheduler(Path(tmp))
            repair = {"id": "cfg-repair", "category": "config"}
            result = scheduler._apply_repair(repair)

        self.assertTrue(result["applied"])
        self.assertEqual(result["action"], "config_write_skipped_no_path")

    def test_config_repair_writes_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            scheduler = self._make_scheduler(tmp_path)
            config_target = tmp_path / "test_config.json"
            scheduler._config_path = config_target

            repair = {"id": "cfg-repair", "category": "config", "config_payload": {"key": "value"}}
            result = scheduler._apply_repair(repair)

            self.assertTrue(result["applied"])
            self.assertEqual(result["action"], "config_written")
            self.assertTrue(config_target.exists())

    def test_unknown_category_acknowledged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scheduler = self._make_scheduler(Path(tmp))
            repair = {"id": "unknown-repair", "category": "unknown_category"}
            result = scheduler._apply_repair(repair)

        self.assertTrue(result["applied"])
        self.assertEqual(result["action"], "acknowledged")

    def test_other_category_acknowledged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            scheduler = self._make_scheduler(Path(tmp))
            result = scheduler._apply_repair({"category": "other", "id": "x"})

        self.assertEqual(result["action"], "acknowledged")
        self.assertTrue(result["applied"])


if __name__ == "__main__":
    unittest.main()
