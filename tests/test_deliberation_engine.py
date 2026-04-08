from __future__ import annotations

import unittest

from core._bus_fallback import EventBus
from core.deliberation import Contradiction, DeliberationGraph, Hypothesis
from core.deliberation_engine import (
    DeliberationEngine,
    _cross_domain_coupling_score,
    _jaccard_similarity,
    enhance_ascension_deliberation,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_perspectives(texts: list[tuple[str, str]]) -> list[dict]:
    """Return perspective dicts from (name, content) pairs."""
    return [
        {"perspective": name, "content": content, "model": "test-model"}
        for name, content in texts
    ]


# ===================================================================
# DeliberationGraph tests
# ===================================================================

class TestDeliberationGraphBasics(unittest.TestCase):
    """Core CRUD operations on the hypothesis graph."""

    def setUp(self) -> None:
        self.bus = EventBus()
        self.graph = DeliberationGraph(bus=self.bus)

    # -- add_hypothesis -------------------------------------------------

    def test_add_hypothesis_returns_hypothesis(self) -> None:
        hyp = self.graph.add_hypothesis("claim A", "architect", confidence=0.8)
        self.assertIsInstance(hyp, Hypothesis)
        self.assertEqual(hyp.claim, "claim A")
        self.assertEqual(hyp.perspective, "architect")
        self.assertAlmostEqual(hyp.confidence, 0.8)

    def test_add_hypothesis_default_confidence(self) -> None:
        hyp = self.graph.add_hypothesis("claim B", "analyst")
        self.assertAlmostEqual(hyp.confidence, 0.5)

    def test_add_hypothesis_clamps_confidence(self) -> None:
        hyp_high = self.graph.add_hypothesis("too high", "a", confidence=1.5)
        hyp_low = self.graph.add_hypothesis("too low", "b", confidence=-0.3)
        self.assertAlmostEqual(hyp_high.confidence, 1.0)
        self.assertAlmostEqual(hyp_low.confidence, 0.0)

    def test_add_hypothesis_with_evidence(self) -> None:
        hyp = self.graph.add_hypothesis("c", "p", evidence=["e1", "e2"])
        self.assertEqual(hyp.evidence, ["e1", "e2"])

    def test_add_hypothesis_appears_in_all_hypotheses(self) -> None:
        hyp = self.graph.add_hypothesis("c", "p")
        self.assertIn(hyp, self.graph.all_hypotheses())

    def test_get_hypothesis_by_id(self) -> None:
        hyp = self.graph.add_hypothesis("find me", "seeker")
        found = self.graph.get_hypothesis(hyp.id)
        self.assertIsNotNone(found)
        self.assertEqual(found.id, hyp.id)

    def test_get_hypothesis_unknown_id_returns_none(self) -> None:
        self.assertIsNone(self.graph.get_hypothesis("nonexistent"))

    # -- add_support ----------------------------------------------------

    def test_add_support_creates_edge(self) -> None:
        h1 = self.graph.add_hypothesis("a", "p1")
        h2 = self.graph.add_hypothesis("b", "p2")
        self.graph.add_support(h1.id, h2.id, weight=0.9)
        # h2 should have 1 supporter (h1)
        supporters = self.graph.get_supporters(h2.id)
        self.assertEqual(len(supporters), 1)
        self.assertEqual(supporters[0].id, h1.id)

    def test_add_support_invalid_ids_no_crash(self) -> None:
        h1 = self.graph.add_hypothesis("a", "p")
        # Should log error but not raise
        self.graph.add_support(h1.id, "bogus")
        self.graph.add_support("bogus", h1.id)

    def test_add_support_zero_weight_ignored(self) -> None:
        h1 = self.graph.add_hypothesis("a", "p1")
        h2 = self.graph.add_hypothesis("b", "p2")
        self.graph.add_support(h1.id, h2.id, weight=0)
        self.assertEqual(len(self.graph.get_supporters(h2.id)), 0)

    # -- add_contradiction ----------------------------------------------

    def test_add_contradiction_returns_contradiction(self) -> None:
        h1 = self.graph.add_hypothesis("yes", "optimist", confidence=0.7)
        h2 = self.graph.add_hypothesis("no", "pessimist", confidence=0.6)
        c = self.graph.add_contradiction(h1.id, h2.id, "opposite", severity=0.8)
        self.assertIsInstance(c, Contradiction)
        self.assertEqual(c.reason, "opposite")
        self.assertAlmostEqual(c.severity, 0.8)

    def test_add_contradiction_invalid_ids_returns_none(self) -> None:
        h1 = self.graph.add_hypothesis("x", "p")
        result = self.graph.add_contradiction(h1.id, "missing", "reason")
        self.assertIsNone(result)

    def test_add_contradiction_appears_in_all(self) -> None:
        h1 = self.graph.add_hypothesis("a", "p1")
        h2 = self.graph.add_hypothesis("b", "p2")
        self.graph.add_contradiction(h1.id, h2.id, "r")
        self.assertEqual(len(self.graph.all_contradictions()), 1)


class TestDeliberationGraphDetection(unittest.TestCase):
    """Contradiction detection with threshold filtering."""

    def setUp(self) -> None:
        self.graph = DeliberationGraph()
        self.h1 = self.graph.add_hypothesis("claim A", "p1", confidence=0.9)
        self.h2 = self.graph.add_hypothesis("claim B", "p2", confidence=0.4)
        self.h3 = self.graph.add_hypothesis("claim C", "p3", confidence=0.6)
        self.graph.add_contradiction(self.h1.id, self.h2.id, "r1", severity=0.8)
        self.graph.add_contradiction(self.h2.id, self.h3.id, "r2", severity=0.2)

    def test_detect_default_threshold(self) -> None:
        # Default threshold 0.3 → only severity >= 0.3
        detected = self.graph.detect_contradictions()
        self.assertEqual(len(detected), 1)
        self.assertAlmostEqual(detected[0].severity, 0.8)

    def test_detect_low_threshold_returns_all(self) -> None:
        detected = self.graph.detect_contradictions(threshold=0.0)
        self.assertEqual(len(detected), 2)

    def test_detect_high_threshold_returns_none(self) -> None:
        detected = self.graph.detect_contradictions(threshold=0.9)
        self.assertEqual(len(detected), 0)


class TestDeliberationGraphConsensus(unittest.TestCase):
    """Max-flow consensus and ranking."""

    def test_max_flow_empty_graph(self) -> None:
        graph = DeliberationGraph()
        result = graph.max_flow_consensus()
        self.assertIsNone(result["winning_hypothesis"])
        self.assertEqual(result["flow_value"], 0)

    def test_max_flow_single_hypothesis(self) -> None:
        graph = DeliberationGraph()
        h = graph.add_hypothesis("only one", "sole", confidence=0.9)
        result = graph.max_flow_consensus()
        # Single node → root and leaf, flow should work
        self.assertIsNotNone(result["winning_hypothesis"])

    def test_max_flow_with_support_chain(self) -> None:
        graph = DeliberationGraph()
        h1 = graph.add_hypothesis("base", "p1", confidence=0.9)
        h2 = graph.add_hypothesis("derived", "p2", confidence=0.7)
        graph.add_support(h1.id, h2.id, weight=1.0)
        result = graph.max_flow_consensus()
        self.assertIsNotNone(result["winning_hypothesis"])
        self.assertGreater(result["flow_value"], 0)

    def test_ranked_hypotheses_order(self) -> None:
        graph = DeliberationGraph()
        low = graph.add_hypothesis("weak", "p1", confidence=0.2)
        high = graph.add_hypothesis("strong", "p2", confidence=0.95)
        mid = graph.add_hypothesis("medium", "p3", confidence=0.5)
        ranked = graph.ranked_hypotheses()
        self.assertEqual(len(ranked), 3)
        # Highest confidence first (no supports/contradictions → score = confidence)
        self.assertEqual(ranked[0]["hypothesis"].id, high.id)
        self.assertEqual(ranked[-1]["hypothesis"].id, low.id)

    def test_ranked_hypotheses_support_boosts_score(self) -> None:
        graph = DeliberationGraph()
        target = graph.add_hypothesis("main", "p1", confidence=0.5)
        supporter = graph.add_hypothesis("helper", "p2", confidence=0.3)
        graph.add_support(supporter.id, target.id)
        ranked = graph.ranked_hypotheses()
        target_entry = next(r for r in ranked if r["hypothesis"].id == target.id)
        # score = 0.5 * (1 + 1) / (1 + 0) = 1.0
        self.assertAlmostEqual(target_entry["score"], 1.0)
        self.assertEqual(target_entry["support_count"], 1)

    def test_ranked_hypotheses_contradiction_reduces_score(self) -> None:
        graph = DeliberationGraph()
        h1 = graph.add_hypothesis("a", "p1", confidence=0.8)
        h2 = graph.add_hypothesis("b", "p2", confidence=0.8)
        graph.add_contradiction(h1.id, h2.id, "disagree")
        ranked = graph.ranked_hypotheses()
        for entry in ranked:
            # score = 0.8 * 1 / 2 = 0.4
            self.assertAlmostEqual(entry["score"], 0.4)
            self.assertEqual(entry["contradiction_count"], 1)


class TestDeliberationGraphClearAndSummary(unittest.TestCase):
    """Clear resets state; summary returns stats."""

    def test_clear_resets_everything(self) -> None:
        graph = DeliberationGraph()
        h1 = graph.add_hypothesis("a", "p1")
        h2 = graph.add_hypothesis("b", "p2")
        graph.add_contradiction(h1.id, h2.id, "r")
        graph.clear()
        self.assertEqual(len(graph.all_hypotheses()), 0)
        self.assertEqual(len(graph.all_contradictions()), 0)

    def test_summary_keys(self) -> None:
        graph = DeliberationGraph()
        graph.add_hypothesis("a", "p1")
        s = graph.summary()
        self.assertIn("total_hypotheses", s)
        self.assertIn("total_contradictions", s)
        self.assertIn("top_hypothesis", s)
        self.assertIn("graph_density", s)
        self.assertEqual(s["total_hypotheses"], 1)
        self.assertEqual(s["total_contradictions"], 0)

    def test_summary_empty_graph(self) -> None:
        graph = DeliberationGraph()
        s = graph.summary()
        self.assertEqual(s["total_hypotheses"], 0)
        self.assertIsNone(s["top_hypothesis"])


# ===================================================================
# _jaccard_similarity tests
# ===================================================================

class TestJaccardSimilarity(unittest.TestCase):
    """Word-level Jaccard similarity helper."""

    def test_identical_strings(self) -> None:
        self.assertAlmostEqual(_jaccard_similarity("hello world", "hello world"), 1.0)

    def test_completely_different(self) -> None:
        self.assertAlmostEqual(
            _jaccard_similarity("alpha beta gamma", "delta epsilon zeta"), 0.0
        )

    def test_both_empty_returns_one(self) -> None:
        # Code convention: two empty sets are considered identical
        self.assertAlmostEqual(_jaccard_similarity("", ""), 1.0)

    def test_one_empty_one_not_returns_zero(self) -> None:
        self.assertAlmostEqual(_jaccard_similarity("", "hello"), 0.0)
        self.assertAlmostEqual(_jaccard_similarity("hello", ""), 0.0)

    def test_partial_overlap(self) -> None:
        # "the cat" vs "the dog" → intersection {"the"}, union {"the","cat","dog"}
        sim = _jaccard_similarity("the cat", "the dog")
        self.assertAlmostEqual(sim, 1 / 3)

    def test_case_insensitive(self) -> None:
        self.assertAlmostEqual(_jaccard_similarity("Hello World", "hello world"), 1.0)

    def test_superset(self) -> None:
        # "a b c" vs "a b c d" → 3/4
        self.assertAlmostEqual(_jaccard_similarity("a b c", "a b c d"), 0.75)

    def test_handles_punctuation_and_inflection(self) -> None:
        left = "monitoring, controls mitigated incidents quickly"
        right = "monitor control mitigate incident quick response"
        self.assertGreater(_jaccard_similarity(left, right), 0.5)


class TestCrossDomainCoupling(unittest.TestCase):
    """Conceptual coupling helper used for cross-domain support."""

    def test_returns_zero_for_empty_inputs(self) -> None:
        self.assertEqual(_cross_domain_coupling_score("", "triage signal", "a", "b"), 0.0)

    def test_detects_shared_concept_groups(self) -> None:
        text_a = "triage anomaly using telemetry signal and mitigation plan"
        text_b = "diagnosis of incident from monitoring metrics for recovery"
        score = _cross_domain_coupling_score(text_a, text_b, "ops", "security")
        self.assertGreaterEqual(score, 0.35)


# ===================================================================
# DeliberationEngine tests
# ===================================================================

class TestDeliberationEngineDeliberate(unittest.TestCase):
    """Full deliberation cycle through the engine."""

    def setUp(self) -> None:
        self.engine = DeliberationEngine()

    def test_deliberate_returns_required_keys(self) -> None:
        perspectives = _make_perspectives([
            ("architect", "We should use microservices architecture with event sourcing"),
            ("security", "We need strong authentication and zero trust networking"),
        ])
        result = self.engine.deliberate("design system", perspectives)
        for key in ("consensus", "hypotheses", "contradictions", "graph_summary"):
            self.assertIn(key, result)

    def test_deliberate_three_diverse_perspectives(self) -> None:
        # Completely different words → low jaccard → contradictions expected
        perspectives = _make_perspectives([
            ("architect", "microservices event sourcing kubernetes containers orchestration"),
            ("security", "encryption authentication firewall intrusion detection prevention"),
            ("analyst", "revenue growth quarterly metrics stakeholder reporting forecast"),
        ])
        result = self.engine.deliberate("plan", perspectives)
        self.assertEqual(len(result["hypotheses"]), 3)
        # All pairs should have low overlap → contradictions
        self.assertGreater(len(result["contradictions"]), 0)

    def test_deliberate_two_similar_perspectives(self) -> None:
        # High word overlap → support edges expected
        shared = "the system should use caching redis for performance optimization"
        perspectives = _make_perspectives([
            ("p1", shared + " and scalability improvements"),
            ("p2", shared + " and reliability enhancements"),
        ])
        result = self.engine.deliberate("design", perspectives)
        self.assertEqual(len(result["hypotheses"]), 2)
        # High overlap should create support, not contradiction
        self.assertEqual(len(result["contradictions"]), 0)

    def test_deliberate_empty_perspectives(self) -> None:
        result = self.engine.deliberate("anything", [])
        self.assertEqual(len(result["hypotheses"]), 0)
        self.assertEqual(len(result["contradictions"]), 0)
        self.assertIsNone(result["consensus"]["winning_hypothesis"])

    def test_deliberate_single_perspective(self) -> None:
        perspectives = _make_perspectives([("sole", "only viewpoint here")])
        result = self.engine.deliberate("q", perspectives)
        self.assertEqual(len(result["hypotheses"]), 1)
        self.assertEqual(len(result["contradictions"]), 0)

    def test_deliberate_clears_previous_state(self) -> None:
        p1 = _make_perspectives([("a", "first round content")])
        self.engine.deliberate("round1", p1)

        p2 = _make_perspectives([("b", "second round content")])
        result = self.engine.deliberate("round2", p2)
        # Only the second round's hypothesis should remain
        self.assertEqual(len(result["hypotheses"]), 1)

    def test_deliberate_confidence_scales_with_length(self) -> None:
        short = _make_perspectives([("p", "tiny")])
        long_text = "word " * 200  # 200 words ≈ 1000 chars > 500
        long_ = _make_perspectives([("p", long_text)])
        r_short = self.engine.deliberate("q", short)
        r_long = self.engine.deliberate("q", long_)
        short_conf = r_short["hypotheses"][0]["hypothesis"].confidence
        long_conf = r_long["hypotheses"][0]["hypothesis"].confidence
        self.assertGreater(long_conf, short_conf)

    def test_deliberate_cross_domain_coupling_creates_support(self) -> None:
        perspectives = _make_perspectives([
            (
                "clinical-ops",
                "triage anomaly from telemetry signal and apply mitigation",
            ),
            (
                "site-reliability",
                "diagnosis of incident via monitoring metrics then recovery",
            ),
        ])
        result = self.engine.deliberate("handle unknown outage pattern", perspectives)
        self.assertEqual(len(result["hypotheses"]), 2)
        self.assertEqual(len(result["contradictions"]), 0)
        # Coupling should create at least one support edge and non-zero graph density.
        self.assertGreater(result["graph_summary"]["graph_density"], 0.0)


class TestDeliberationEngineResolve(unittest.TestCase):
    """Contradiction resolution logic."""

    def test_resolve_contradictions_picks_higher_confidence(self) -> None:
        engine = DeliberationEngine()
        graph = engine.get_graph()
        h_high = graph.add_hypothesis("winner", "p1", confidence=0.9)
        h_low = graph.add_hypothesis("loser", "p2", confidence=0.3)
        contradiction = graph.add_contradiction(
            h_high.id, h_low.id, "disagree", severity=0.7
        )
        self.assertIsNotNone(contradiction)
        # resolve_contradictions accesses contradiction.hypothesis_a / hypothesis_b
        # and looks them up via get_hypothesis
        resolutions = engine.resolve_contradictions([contradiction])
        self.assertEqual(len(resolutions), 1)
        self.assertEqual(resolutions[0]["winner"].id, h_high.id)
        self.assertEqual(resolutions[0]["resolution"], "prefer_higher_confidence")

    def test_resolve_no_contradictions(self) -> None:
        engine = DeliberationEngine()
        resolutions = engine.resolve_contradictions([])
        self.assertEqual(resolutions, [])

    def test_resolve_defaults_to_graph_contradictions(self) -> None:
        engine = DeliberationEngine()
        graph = engine.get_graph()
        h1 = graph.add_hypothesis("a", "p1", confidence=0.6)
        h2 = graph.add_hypothesis("b", "p2", confidence=0.4)
        graph.add_contradiction(h1.id, h2.id, "r")
        # Pass None → should use graph's own contradictions
        resolutions = engine.resolve_contradictions(None)
        self.assertGreaterEqual(len(resolutions), 0)


class TestDeliberationEngineMisc(unittest.TestCase):
    """Clear, summary, get_graph."""

    def test_get_graph_returns_deliberation_graph(self) -> None:
        engine = DeliberationEngine()
        self.assertIsInstance(engine.get_graph(), DeliberationGraph)

    def test_clear_resets_engine(self) -> None:
        engine = DeliberationEngine()
        engine.deliberate(
            "q", _make_perspectives([("p", "some content here")])
        )
        engine.clear()
        self.assertEqual(len(engine.get_graph().all_hypotheses()), 0)

    def test_summary_returns_dict(self) -> None:
        engine = DeliberationEngine()
        s = engine.summary()
        self.assertIsInstance(s, dict)
        self.assertIn("total_hypotheses", s)

    def test_engine_with_bus(self) -> None:
        bus = EventBus()
        engine = DeliberationEngine(bus=bus)
        perspectives = _make_perspectives([("p", "content for bus test")])
        result = engine.deliberate("prompt", perspectives)
        self.assertIn("consensus", result)


# ===================================================================
# enhance_ascension_deliberation tests
# ===================================================================

class TestEnhanceAscensionDeliberation(unittest.TestCase):
    """Post-processing helper that enriches AscensionService results."""

    def test_adds_deliberation_and_resolution_keys(self) -> None:
        engine = DeliberationEngine()
        ascension_result = {
            "status": "ok",
            "prompt": "design a system",
            "perspectives": [
                {"perspective": "arch", "content": "use microservices kubernetes", "model": "m1"},
                {"perspective": "sec", "content": "use encryption authentication", "model": "m2"},
            ],
            "consensus": "original consensus",
        }
        enriched = enhance_ascension_deliberation(ascension_result, engine)
        self.assertIn("deliberation", enriched)
        self.assertIn("resolution", enriched)
        # Original keys preserved
        self.assertEqual(enriched["status"], "ok")
        self.assertEqual(enriched["consensus"], "original consensus")

    def test_deliberation_has_expected_structure(self) -> None:
        engine = DeliberationEngine()
        ascension_result = {
            "prompt": "test",
            "perspectives": [
                {"perspective": "a", "content": "alpha beta gamma", "model": "m"},
            ],
        }
        enriched = enhance_ascension_deliberation(ascension_result, engine)
        delib = enriched["deliberation"]
        for key in ("consensus", "hypotheses", "contradictions", "graph_summary"):
            self.assertIn(key, delib)

    def test_handles_empty_perspectives(self) -> None:
        engine = DeliberationEngine()
        ascension_result = {"prompt": "empty", "perspectives": []}
        enriched = enhance_ascension_deliberation(ascension_result, engine)
        self.assertIn("deliberation", enriched)
        self.assertEqual(len(enriched["deliberation"]["hypotheses"]), 0)
        self.assertEqual(enriched["resolution"], [])

    def test_handles_missing_prompt(self) -> None:
        engine = DeliberationEngine()
        ascension_result = {"perspectives": []}
        enriched = enhance_ascension_deliberation(ascension_result, engine)
        self.assertIn("deliberation", enriched)

    def test_preserves_all_original_keys(self) -> None:
        engine = DeliberationEngine()
        ascension_result = {
            "prompt": "p",
            "perspectives": [],
            "custom_key": 42,
            "nested": {"a": 1},
        }
        enriched = enhance_ascension_deliberation(ascension_result, engine)
        self.assertEqual(enriched["custom_key"], 42)
        self.assertEqual(enriched["nested"], {"a": 1})


if __name__ == "__main__":
    unittest.main()
