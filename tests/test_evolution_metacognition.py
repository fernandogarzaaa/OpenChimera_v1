from __future__ import annotations

import math
import os
import struct
import tempfile
import unittest
from unittest.mock import MagicMock

from core._bus_fallback import EventBus
from core._database_fallback import DatabaseManager
from core.memory.episodic import EpisodicMemory
from core.evolution import EvolutionEngine
from core.metacognition import MetacognitionEngine


class TestBase(unittest.TestCase):
    def setUp(self):
        self.bus = EventBus()
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.db = DatabaseManager(self._tmp.name)
        self.db.initialize()

    def tearDown(self):
        self.db.close()
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass


# ======================================================================
# EvolutionEngine tests
# ======================================================================


class TestCosineSimilarityIdentical(TestBase):
    def test_identical_vectors_return_one(self):
        emb = struct.pack("3f", 1.0, 0.0, 0.0)
        result = EvolutionEngine._cosine_similarity(emb, emb)
        self.assertAlmostEqual(result, 1.0, places=5)

    def test_identical_non_unit_vectors(self):
        emb = struct.pack("3f", 3.0, 4.0, 0.0)
        result = EvolutionEngine._cosine_similarity(emb, emb)
        self.assertAlmostEqual(result, 1.0, places=5)


class TestCosineSimilarityOrthogonal(TestBase):
    def test_orthogonal_vectors_return_zero(self):
        emb_a = struct.pack("3f", 1.0, 0.0, 0.0)
        emb_b = struct.pack("3f", 0.0, 1.0, 0.0)
        result = EvolutionEngine._cosine_similarity(emb_a, emb_b)
        self.assertAlmostEqual(result, 0.0, places=5)


class TestCosineSimilaritySimilar(TestBase):
    def test_similar_vectors_high_value(self):
        emb_a = struct.pack("3f", 1.0, 0.0, 0.0)
        emb_b = struct.pack("3f", 0.98, 0.1, 0.05)
        result = EvolutionEngine._cosine_similarity(emb_a, emb_b)
        self.assertGreater(result, 0.85)
        self.assertLess(result, 1.0)


class TestCosineSimilarityEdge(TestBase):
    def test_empty_bytes_return_zero(self):
        result = EvolutionEngine._cosine_similarity(b"", b"")
        self.assertEqual(result, 0.0)

    def test_mismatched_length_return_zero(self):
        emb_a = struct.pack("3f", 1.0, 0.0, 0.0)
        emb_b = struct.pack("2f", 1.0, 0.0)
        result = EvolutionEngine._cosine_similarity(emb_a, emb_b)
        self.assertEqual(result, 0.0)

    def test_none_input_returns_zero(self):
        emb = struct.pack("3f", 1.0, 0.0, 0.0)
        result = EvolutionEngine._cosine_similarity(None, emb)
        self.assertEqual(result, 0.0)

    def test_zero_vector_returns_zero(self):
        emb_a = struct.pack("3f", 0.0, 0.0, 0.0)
        emb_b = struct.pack("3f", 1.0, 0.0, 0.0)
        result = EvolutionEngine._cosine_similarity(emb_a, emb_b)
        self.assertEqual(result, 0.0)


class TestDPOPairGeneration(TestBase):
    def _insert_episodes(self, mem, emb_success, emb_failure):
        mem.record_episode(
            session_id="s1", goal="solve X", outcome="success",
            confidence_initial=0.5, confidence_final=0.9,
            models_used=["model-a"], reasoning_chain=["step1", "step2"],
            domain="math", embedding=emb_success,
        )
        mem.record_episode(
            session_id="s2", goal="solve X", outcome="failure",
            confidence_initial=0.5, confidence_final=0.3,
            models_used=["model-a"], reasoning_chain=["step1", "wrong"],
            failure_reason="bad approach", domain="math",
            embedding=emb_failure,
        )

    def test_pairs_generated_when_similarity_above_threshold(self):
        evo = EvolutionEngine(self.db, self.bus)
        mem = EpisodicMemory(self.db, self.bus)
        emb_a = struct.pack("3f", 1.0, 0.0, 0.0)
        emb_b = struct.pack("3f", 0.98, 0.1, 0.05)
        self._insert_episodes(mem, emb_a, emb_b)

        pairs = evo.generate_dpo_pairs(domain="math")
        self.assertGreater(len(pairs), 0)
        self.assertIn("chosen", pairs[0])
        self.assertIn("rejected", pairs[0])
        self.assertGreater(pairs[0]["similarity"], 0.85)

    def test_no_pairs_when_similarity_below_threshold(self):
        evo = EvolutionEngine(self.db, self.bus)
        mem = EpisodicMemory(self.db, self.bus)
        emb_a = struct.pack("3f", 1.0, 0.0, 0.0)
        emb_c = struct.pack("3f", 0.0, 0.0, 1.0)
        self._insert_episodes(mem, emb_a, emb_c)

        pairs = evo.generate_dpo_pairs(domain="math")
        self.assertEqual(len(pairs), 0)

    def test_no_pairs_when_no_failures(self):
        evo = EvolutionEngine(self.db, self.bus)
        mem = EpisodicMemory(self.db, self.bus)
        emb = struct.pack("3f", 1.0, 0.0, 0.0)
        mem.record_episode(
            session_id="s1", goal="solve X", outcome="success",
            confidence_initial=0.5, confidence_final=0.9,
            models_used=["model-a"], reasoning_chain=["step1"],
            domain="math", embedding=emb,
        )
        pairs = evo.generate_dpo_pairs(domain="math")
        self.assertEqual(len(pairs), 0)


class TestPreferenceDataset(TestBase):
    def test_filters_identical_reasoning(self):
        chain = ["step1", "step2"]
        pairs = [
            {
                "chosen": {"goal": "X", "reasoning_chain": chain},
                "rejected": {"goal": "X", "reasoning_chain": chain},
                "similarity": 0.95,
            }
        ]
        dataset = EvolutionEngine.generate_preference_dataset(pairs)
        self.assertEqual(len(dataset), 0)

    def test_produces_dataset_for_different_reasoning(self):
        pairs = [
            {
                "chosen": {"goal": "X", "reasoning_chain": ["good1", "good2"]},
                "rejected": {"goal": "X", "reasoning_chain": ["bad1"]},
                "similarity": 0.92,
            }
        ]
        dataset = EvolutionEngine.generate_preference_dataset(pairs)
        self.assertEqual(len(dataset), 1)
        self.assertEqual(dataset[0]["prompt"], "X")
        self.assertIn("good1", dataset[0]["chosen"])
        self.assertIn("bad1", dataset[0]["rejected"])
        self.assertEqual(dataset[0]["similarity"], 0.92)


class TestModelFitness(TestBase):
    def test_correct_success_rate(self):
        mem = EpisodicMemory(self.db, self.bus)
        for i in range(3):
            mem.record_episode(
                session_id=f"s{i}", goal="task", outcome="success",
                confidence_initial=0.5, confidence_final=0.8,
                models_used=["model-a"], reasoning_chain=["s"],
                domain="math",
            )
        mem.record_episode(
            session_id="s_fail", goal="task", outcome="failure",
            confidence_initial=0.5, confidence_final=0.2,
            models_used=["model-a"], reasoning_chain=["f"],
            domain="math",
        )

        evo = EvolutionEngine(self.db, self.bus)
        fitness = evo.compute_model_fitness(domain="math")
        self.assertIn("model-a", fitness)
        self.assertAlmostEqual(fitness["model-a"]["success_rate"], 0.75, places=2)
        self.assertEqual(fitness["model-a"]["total_episodes"], 4)


class TestRecommendations(TestBase):
    def test_retrain_for_low_success(self):
        fitness = {"bad-model": {"success_rate": 0.3, "total_episodes": 10}}
        recs = EvolutionEngine.recommend_model_updates(fitness)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["action"], "retrain")

    def test_promote_for_high_success(self):
        fitness = {"great-model": {"success_rate": 0.95, "total_episodes": 50}}
        recs = EvolutionEngine.recommend_model_updates(fitness)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["action"], "promote")

    def test_monitor_for_middle_success(self):
        fitness = {"ok-model": {"success_rate": 0.75, "total_episodes": 30}}
        recs = EvolutionEngine.recommend_model_updates(fitness)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["action"], "monitor")


class TestEvolutionCycle(TestBase):
    def test_returns_expected_keys(self):
        evo = EvolutionEngine(self.db, self.bus)
        result = evo.evolution_cycle()
        self.assertIn("pairs", result)
        self.assertIn("dataset_size", result)
        self.assertIn("model_fitness", result)
        self.assertIn("recommendations", result)


class TestEvolutionBusEvent(TestBase):
    def test_bus_event_published_on_pair_generation(self):
        mem = EpisodicMemory(self.db, self.bus)
        emb_a = struct.pack("3f", 1.0, 0.0, 0.0)
        emb_b = struct.pack("3f", 0.98, 0.1, 0.05)
        mem.record_episode(
            session_id="s1", goal="solve", outcome="success",
            confidence_initial=0.5, confidence_final=0.9,
            models_used=["m"], reasoning_chain=["a"],
            domain="math", embedding=emb_a,
        )
        mem.record_episode(
            session_id="s2", goal="solve", outcome="failure",
            confidence_initial=0.5, confidence_final=0.3,
            models_used=["m"], reasoning_chain=["b"],
            domain="math", embedding=emb_b,
        )

        events = []
        self.bus.subscribe("evolution.dpo_pair.generated", lambda d: events.append(d))
        evo = EvolutionEngine(self.db, self.bus)
        evo.generate_dpo_pairs(domain="math")
        self.assertGreater(len(events), 0)
        self.assertIn("pair_id", events[0])


class TestEvolutionSummary(TestBase):
    def test_summary_keys(self):
        evo = EvolutionEngine(self.db, self.bus)
        s = evo.summary()
        self.assertIn("cycles_run", s)
        self.assertIn("total_pairs_generated", s)
        self.assertIn("last_cycle_timestamp", s)
        self.assertEqual(s["cycles_run"], 0)

    def test_summary_updates_after_cycle(self):
        evo = EvolutionEngine(self.db, self.bus)
        evo.evolution_cycle()
        s = evo.summary()
        self.assertEqual(s["cycles_run"], 1)
        self.assertIsNotNone(s["last_cycle_timestamp"])


# ======================================================================
# MetacognitionEngine tests
# ======================================================================


def _insert_calibrated_episodes(db, bus, n=20):
    """Insert well-calibrated episodes: high-conf → success, low-conf → failure."""
    mem = EpisodicMemory(db, bus)
    for i in range(n):
        is_success = i % 2 == 0
        conf = 0.85 if is_success else 0.15
        mem.record_episode(
            session_id=f"cal_{i}", goal=f"task_{i}",
            outcome="success" if is_success else "failure",
            confidence_initial=conf - 0.1, confidence_final=conf,
            models_used=["m"], reasoning_chain=["r"],
            domain="math",
        )


def _insert_badly_calibrated_episodes(db, bus, n=20):
    """Insert badly calibrated: high-conf → failure, low-conf → success."""
    mem = EpisodicMemory(db, bus)
    for i in range(n):
        is_success = i % 2 == 0
        conf = 0.15 if is_success else 0.85
        mem.record_episode(
            session_id=f"bad_{i}", goal=f"task_{i}",
            outcome="success" if is_success else "failure",
            confidence_initial=conf - 0.1, confidence_final=conf,
            models_used=["m"], reasoning_chain=["r"],
            domain="math",
        )


class TestECEWellCalibrated(TestBase):
    def test_low_ece_for_well_calibrated(self):
        _insert_calibrated_episodes(self.db, self.bus, n=40)
        mc = MetacognitionEngine(self.db, self.bus)
        result = mc.compute_ece(domain="math")
        self.assertLessEqual(result["ece"], 0.15)
        self.assertIn(result["calibration_quality"], ("excellent", "good", "fair"))


class TestECEBadlyCalibrated(TestBase):
    def test_high_ece_for_badly_calibrated(self):
        _insert_badly_calibrated_episodes(self.db, self.bus, n=40)
        mc = MetacognitionEngine(self.db, self.bus)
        result = mc.compute_ece(domain="math")
        self.assertGreater(result["ece"], 0.2)
        self.assertIn(result["calibration_quality"], ("fair", "poor"))


class TestECEEmpty(TestBase):
    def test_ece_zero_for_no_episodes(self):
        mc = MetacognitionEngine(self.db, self.bus)
        result = mc.compute_ece()
        self.assertEqual(result["ece"], 0.0)
        self.assertEqual(result["mce"], 0.0)
        self.assertEqual(result["total_episodes"], 0)
        self.assertEqual(result["calibration_quality"], "excellent")


class TestECEBinStructure(TestBase):
    def test_bins_have_correct_structure(self):
        _insert_calibrated_episodes(self.db, self.bus, n=20)
        mc = MetacognitionEngine(self.db, self.bus, n_bins=10)
        result = mc.compute_ece(domain="math")
        self.assertEqual(result["n_bins"], 10)
        self.assertEqual(len(result["bins"]), 10)
        for b in result["bins"]:
            self.assertIn("bin_start", b)
            self.assertIn("bin_end", b)
            self.assertIn("avg_confidence", b)
            self.assertIn("avg_accuracy", b)
            self.assertIn("count", b)
            self.assertIn("gap", b)


class TestOverconfidence(TestBase):
    def test_detects_overconfident_episodes(self):
        mem = EpisodicMemory(self.db, self.bus)
        for i in range(10):
            mem.record_episode(
                session_id=f"oc_{i}", goal="hard task", outcome="failure",
                confidence_initial=0.8, confidence_final=0.9,
                models_used=["m"], reasoning_chain=["r"],
                domain="math",
            )
        mc = MetacognitionEngine(self.db, self.bus)
        result = mc.compute_overconfidence_ratio(domain="math")
        self.assertEqual(result["overconfident_count"], 10)
        self.assertAlmostEqual(result["overconfidence_ratio"], 1.0, places=2)

    def test_detects_underconfident_episodes(self):
        mem = EpisodicMemory(self.db, self.bus)
        for i in range(10):
            mem.record_episode(
                session_id=f"uc_{i}", goal="easy task", outcome="success",
                confidence_initial=0.1, confidence_final=0.2,
                models_used=["m"], reasoning_chain=["r"],
                domain="math",
            )
        mc = MetacognitionEngine(self.db, self.bus)
        result = mc.compute_overconfidence_ratio(domain="math")
        self.assertEqual(result["underconfident_count"], 10)
        self.assertAlmostEqual(result["underconfidence_ratio"], 1.0, places=2)


class TestDomainCalibration(TestBase):
    def test_separate_ece_per_domain(self):
        mem = EpisodicMemory(self.db, self.bus)
        for i in range(10):
            mem.record_episode(
                session_id=f"m_{i}", goal="math task", outcome="success",
                confidence_initial=0.7, confidence_final=0.9,
                models_used=["m"], reasoning_chain=["r"], domain="math",
            )
        for i in range(10):
            mem.record_episode(
                session_id=f"c_{i}", goal="code task", outcome="failure",
                confidence_initial=0.8, confidence_final=0.85,
                models_used=["m"], reasoning_chain=["r"], domain="code",
            )
        mc = MetacognitionEngine(self.db, self.bus)
        cals = mc.compute_domain_calibration()
        self.assertIn("math", cals)
        self.assertIn("code", cals)
        self.assertIn("ece", cals["math"])
        self.assertIn("ece", cals["code"])
        # code domain: all failures with 0.85 conf → large gap
        self.assertGreater(cals["code"]["ece"], cals["math"]["ece"])


class TestDriftDetection(TestBase):
    def test_no_drift_uniform_episodes(self):
        _insert_calibrated_episodes(self.db, self.bus, n=20)
        mc = MetacognitionEngine(self.db, self.bus)
        result = mc.detect_drift(window_size=10, domain="math")
        self.assertIn("drift", result)
        self.assertIn("drifting", result)
        self.assertIn("recent_ece", result)
        self.assertIn("historical_ece", result)

    def test_drift_false_when_uniform(self):
        mem = EpisodicMemory(self.db, self.bus)
        # All episodes identical calibration profile
        for i in range(100):
            is_success = i % 2 == 0
            conf = 0.8 if is_success else 0.2
            mem.record_episode(
                session_id=f"u_{i}", goal="uniform", outcome="success" if is_success else "failure",
                confidence_initial=conf, confidence_final=conf,
                models_used=["m"], reasoning_chain=["r"], domain="math",
            )
        mc = MetacognitionEngine(self.db, self.bus)
        result = mc.detect_drift(window_size=50, domain="math")
        # ECE for both windows should be similar, drift should be small
        self.assertLess(abs(result["drift"]), 0.1)


class TestConfidenceHistogram(TestBase):
    def test_correct_bin_counts(self):
        mem = EpisodicMemory(self.db, self.bus)
        # Insert 5 episodes with confidence ~0.5 and 5 with ~0.9
        for i in range(5):
            mem.record_episode(
                session_id=f"h1_{i}", goal="mid", outcome="success",
                confidence_initial=0.4, confidence_final=0.5,
                models_used=["m"], reasoning_chain=["r"], domain="math",
            )
        for i in range(5):
            mem.record_episode(
                session_id=f"h2_{i}", goal="high", outcome="success",
                confidence_initial=0.8, confidence_final=0.9,
                models_used=["m"], reasoning_chain=["r"], domain="math",
            )
        mc = MetacognitionEngine(self.db, self.bus)
        hist = mc.confidence_histogram(domain="math")
        self.assertEqual(len(hist["bins"]), 10)
        total_count = sum(b["count"] for b in hist["bins"])
        self.assertEqual(total_count, 10)

    def test_mean_confidence(self):
        mem = EpisodicMemory(self.db, self.bus)
        for i in range(10):
            mem.record_episode(
                session_id=f"hm_{i}", goal="task", outcome="success",
                confidence_initial=0.5, confidence_final=0.7,
                models_used=["m"], reasoning_chain=["r"], domain="math",
            )
        mc = MetacognitionEngine(self.db, self.bus)
        hist = mc.confidence_histogram(domain="math")
        self.assertAlmostEqual(hist["mean_confidence"], 0.7, places=2)

    def test_empty_histogram(self):
        mc = MetacognitionEngine(self.db, self.bus)
        hist = mc.confidence_histogram()
        self.assertEqual(hist["bins"], [])
        self.assertEqual(hist["mean_confidence"], 0.0)


class TestMetacognitionReport(TestBase):
    def test_returns_all_sections(self):
        _insert_calibrated_episodes(self.db, self.bus, n=20)
        mc = MetacognitionEngine(self.db, self.bus)
        report = mc.metacognition_report(domain="math")
        self.assertIn("calibration", report)
        self.assertIn("overconfidence", report)
        self.assertIn("drift", report)
        self.assertIn("histogram", report)
        self.assertIn("ece", report["calibration"])
        self.assertIn("overconfident_count", report["overconfidence"])


class TestMetacognitionSummary(TestBase):
    def test_returns_expected_keys(self):
        mc = MetacognitionEngine(self.db, self.bus)
        s = mc.summary()
        self.assertIn("ece", s)
        self.assertIn("mce", s)
        self.assertIn("calibration_quality", s)
        self.assertIn("total_episodes", s)
        self.assertIn("overconfident_count", s)
        self.assertIn("underconfident_count", s)
        self.assertIn("overconfidence_ratio", s)

    def test_summary_with_data(self):
        _insert_calibrated_episodes(self.db, self.bus, n=10)
        mc = MetacognitionEngine(self.db, self.bus)
        s = mc.summary()
        self.assertEqual(s["total_episodes"], 10)
        self.assertGreaterEqual(s["ece"], 0.0)


if __name__ == "__main__":
    unittest.main()
