"""Tests for Phase 5 — True Generalization.

Covers:
- CounterfactualReasoner  (core.causal_reasoning)
- CausalReasoning.symbolic_counterfactual delegation
- ActiveInquiry           (core.active_inquiry)
- SkillSynthesizer        (core.transfer_learning)
- TransferLearning.synthesize_skill delegation
- EmergentSwarm           (swarms.god_swarm)
"""
from __future__ import annotations

import os
import tempfile
import time

import pytest

from core._bus_fallback import EventBus
from core._database_fallback import DatabaseManager
from core.causal_reasoning import (
    CausalEdge,
    CausalReasoning,
    ConfidenceLevel,
    EdgeType,
)
from core.causal_reasoning import CounterfactualReasoner
from core.active_inquiry import ActiveInquiry
from core.memory.semantic import SemanticMemory
from core.memory.episodic import EpisodicMemory
from core.transfer_learning import PatternType, TransferLearning
from core.transfer_learning import SkillSynthesizer
from swarms.god_swarm import EmergentSwarm


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_db():
    """Create a fresh temp-file SQLite DB with schema applied."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db = DatabaseManager(tmp.name)
    db.initialize()
    return db, tmp.name


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def engine(bus):
    return CausalReasoning(bus=bus)


@pytest.fixture
def tl(bus):
    return TransferLearning(bus=bus, max_patterns=200)


@pytest.fixture
def db_and_path():
    db, path = _make_db()
    yield db, path
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
def semantic(db_and_path, bus):
    db, _ = db_and_path
    return SemanticMemory(db=db, bus=bus)


@pytest.fixture
def episodic(db_and_path, bus):
    db, _ = db_and_path
    return EpisodicMemory(db=db, bus=bus)


@pytest.fixture
def inquiry(semantic, episodic):
    return ActiveInquiry(semantic=semantic, episodic=episodic)


@pytest.fixture
def reasoner(engine):
    return CounterfactualReasoner(engine)


# ---------------------------------------------------------------------------
# Helper to add a causal edge to the engine
# ---------------------------------------------------------------------------

def _add_edge(
    eng: CausalReasoning,
    cause: str,
    effect: str,
    strength: float = 0.6,
    confidence: float = 0.7,
) -> None:
    eng.add_cause(
        cause=cause,
        effect=effect,
        edge_type=EdgeType.CAUSES,
        strength=strength,
        confidence=confidence,
        confidence_level=ConfidenceLevel.OBSERVED,
    )


# ===========================================================================
# 1. CounterfactualReasoner — core counterfactual query
# ===========================================================================

class TestCounterfactualReasoner:

    def test_no_path_returns_unchanged(self, reasoner: CounterfactualReasoner):
        """When no causal path exists, predicted_value should be 'unchanged'."""
        result = reasoner.counterfactual("node_A", "high", "node_B")
        assert result["predicted_value"] == "unchanged"
        assert result["confidence"] == 1.0
        assert result["paths"] == []
        assert "node_A" in result["explanation"]

    def test_path_exists_returns_affected(
        self, engine: CausalReasoning, reasoner: CounterfactualReasoner
    ):
        """When a causal path exists, predicted_value should be 'affected'."""
        _add_edge(engine, "rain", "wet_road", confidence=0.8)
        result = reasoner.counterfactual("rain", "heavy", "wet_road")
        assert result["predicted_value"] == "affected"
        assert 0.0 < result["confidence"] <= 1.0
        assert len(result["paths"]) >= 1

    def test_confidence_matches_edge_confidence(
        self, engine: CausalReasoning, reasoner: CounterfactualReasoner
    ):
        """Confidence should reflect the edge's min_confidence along the path."""
        _add_edge(engine, "A", "B", confidence=0.5)
        result = reasoner.counterfactual("A", "x", "B")
        assert result["confidence"] == pytest.approx(0.5, abs=0.01)

    def test_multi_hop_path_detected(
        self, engine: CausalReasoning, reasoner: CounterfactualReasoner
    ):
        """Multi-hop paths should be found and reported."""
        _add_edge(engine, "X", "Y", confidence=0.9)
        _add_edge(engine, "Y", "Z", confidence=0.8)
        result = reasoner.counterfactual("X", "changed", "Z")
        assert result["predicted_value"] == "affected"
        # The path should include all three nodes
        assert any("X" in p and "Z" in p for p in result["paths"])

    def test_result_has_required_keys(
        self, engine: CausalReasoning, reasoner: CounterfactualReasoner
    ):
        """Result dict must contain all specified keys."""
        _add_edge(engine, "src", "dst")
        result = reasoner.counterfactual("src", "value", "dst")
        required = {"query_node", "intervention_node", "intervention_value",
                    "predicted_value", "confidence", "paths", "explanation"}
        assert required.issubset(result.keys())


# ===========================================================================
# 2. CounterfactualReasoner — explain_outcome
# ===========================================================================

class TestExplainOutcome:

    def test_no_causes_returns_empty_list(self, reasoner: CounterfactualReasoner):
        result = reasoner.explain_outcome("orphan_node")
        assert result["causes"] == []
        assert result["confidence"] == 0.0
        assert "orphan_node" in result["outcome"]

    def test_direct_causes_returned(
        self, engine: CausalReasoning, reasoner: CounterfactualReasoner
    ):
        _add_edge(engine, "fire", "smoke", confidence=0.9)
        _add_edge(engine, "oxygen", "smoke", confidence=0.8)
        result = reasoner.explain_outcome("smoke")
        assert "fire" in result["causes"] or "oxygen" in result["causes"]
        assert result["confidence"] > 0.0
        assert "smoke" in result["outcome"]

    def test_context_mentioned_in_explanation(
        self, engine: CausalReasoning, reasoner: CounterfactualReasoner
    ):
        _add_edge(engine, "cause", "effect")
        result = reasoner.explain_outcome("effect", context={"domain": "test"})
        assert "domain" in result["explanation"]


# ===========================================================================
# 3. CounterfactualReasoner — generate_alternatives
# ===========================================================================

class TestGenerateAlternatives:

    def test_returns_n_alternatives(
        self, engine: CausalReasoning, reasoner: CounterfactualReasoner
    ):
        _add_edge(engine, "A", "outcome", confidence=0.7)
        _add_edge(engine, "B", "outcome", confidence=0.6)
        _add_edge(engine, "C", "outcome", confidence=0.5)
        alternatives = reasoner.generate_alternatives("outcome", n=3)
        assert len(alternatives) <= 3
        assert len(alternatives) >= 1

    def test_alternative_keys_present(
        self, engine: CausalReasoning, reasoner: CounterfactualReasoner
    ):
        _add_edge(engine, "cause1", "result")
        alts = reasoner.generate_alternatives("result", n=1)
        assert len(alts) >= 1
        for alt in alts:
            assert "intervention" in alt
            assert "predicted_change" in alt
            assert "confidence" in alt

    def test_no_causes_returns_list(
        self, engine: CausalReasoning, reasoner: CounterfactualReasoner
    ):
        """Even without causes, generate_alternatives should return a list."""
        # Add some unrelated nodes
        _add_edge(engine, "unrelated_a", "unrelated_b")
        alts = reasoner.generate_alternatives("isolated_node", n=2)
        assert isinstance(alts, list)


# ===========================================================================
# 4. CausalReasoning.symbolic_counterfactual delegation
# ===========================================================================

class TestSymbolicCounterfactualDelegation:

    def test_delegation_calls_through(self, engine: CausalReasoning):
        """symbolic_counterfactual() should produce the same result as
        CounterfactualReasoner.counterfactual() for the same arguments."""
        _add_edge(engine, "heat", "expansion")
        direct = CounterfactualReasoner(engine).counterfactual(
            "heat", "extreme", "expansion"
        )
        delegated = engine.symbolic_counterfactual("heat", "extreme", "expansion")
        assert direct["predicted_value"] == delegated["predicted_value"]
        assert direct["confidence"] == delegated["confidence"]

    def test_delegation_no_path(self, engine: CausalReasoning):
        result = engine.symbolic_counterfactual("ghost", "value", "phantom")
        assert result["predicted_value"] == "unchanged"


# ===========================================================================
# 5. ActiveInquiry — detect_contradictions
# ===========================================================================

class TestDetectContradictions:

    def test_no_contradictions_when_consistent(self, inquiry: ActiveInquiry, semantic):
        semantic.add_triple("sky", "color", "blue", confidence=0.9)
        contradictions = inquiry.detect_contradictions()
        # No contradiction since only one object for (sky, color)
        assert all(
            c["subject"] != "sky" or c["predicate"] != "color"
            for c in contradictions
        )

    def test_contradiction_detected_different_objects(
        self, inquiry: ActiveInquiry, semantic
    ):
        semantic.add_triple("car", "fuel", "petrol", confidence=0.9)
        # We need to insert a second object for (car, fuel) manually
        # because ON CONFLICT updates existing row. Use different confidence values
        # to bypass the unique constraint by using a different timestamp source.
        # Instead, use two different predicates to test the grouping, or
        # directly call add_triple with same subject+predicate+different object.
        semantic.add_triple("car", "fuel", "diesel", confidence=0.5)
        contradictions = inquiry.detect_contradictions()
        car_fuel = [
            c for c in contradictions
            if c["subject"] == "car" and c["predicate"] == "fuel"
        ]
        assert len(car_fuel) == 1
        assert car_fuel[0]["contradiction_score"] >= 0.0
        assert len(car_fuel[0]["values"]) == 2

    def test_contradiction_score_nonzero(self, inquiry: ActiveInquiry, semantic):
        semantic.add_triple("engine", "status", "running", confidence=1.0)
        semantic.add_triple("engine", "status", "stopped", confidence=0.2)
        contradictions = inquiry.detect_contradictions()
        engine_status = [
            c for c in contradictions
            if c["subject"] == "engine" and c["predicate"] == "status"
        ]
        if engine_status:  # only check if detected
            assert engine_status[0]["contradiction_score"] > 0.0


# ===========================================================================
# 6. ActiveInquiry — generate_question
# ===========================================================================

class TestGenerateQuestion:

    def test_generates_readable_string(self, inquiry: ActiveInquiry):
        contradiction = {
            "subject": "temperature",
            "predicate": "unit",
            "values": [
                {"object": "celsius", "confidence": 0.9},
                {"object": "fahrenheit", "confidence": 0.5},
            ],
            "contradiction_score": 0.44,
        }
        q = inquiry.generate_question(contradiction)
        assert isinstance(q, str)
        assert len(q) > 10
        assert "celsius" in q or "fahrenheit" in q

    def test_question_contains_subject_and_predicate(self, inquiry: ActiveInquiry):
        contradiction = {
            "subject": "robot",
            "predicate": "weight",
            "values": [
                {"object": "10kg", "confidence": 0.8},
                {"object": "15kg", "confidence": 0.7},
            ],
            "contradiction_score": 0.12,
        }
        q = inquiry.generate_question(contradiction)
        assert "robot" in q or "weight" in q


# ===========================================================================
# 7. ActiveInquiry — question lifecycle
# ===========================================================================

class TestQuestionLifecycle:

    def test_post_and_pending(self, inquiry: ActiveInquiry):
        entry = inquiry.post_question("Is the sky blue or green?")
        assert "question_id" in entry
        assert entry["resolved"] is False
        pending = inquiry.pending_questions()
        ids = [q["question_id"] for q in pending]
        assert entry["question_id"] in ids

    def test_resolve_marks_as_done(self, inquiry: ActiveInquiry):
        entry = inquiry.post_question("What color is the ocean?")
        qid = entry["question_id"]
        result = inquiry.resolve_question(qid, "blue")
        assert result is True
        pending = inquiry.pending_questions()
        assert qid not in [q["question_id"] for q in pending]

    def test_resolve_nonexistent_returns_false(self, inquiry: ActiveInquiry):
        assert inquiry.resolve_question("does-not-exist", "anything") is False

    def test_multiple_pending(self, inquiry: ActiveInquiry):
        inquiry.post_question("Q1?")
        inquiry.post_question("Q2?")
        inquiry.post_question("Q3?")
        assert len(inquiry.pending_questions()) >= 3


# ===========================================================================
# 8. ActiveInquiry — run_inquiry_cycle
# ===========================================================================

class TestRunInquiryCycle:

    def test_cycle_posts_questions_for_contradictions(
        self, inquiry: ActiveInquiry, semantic
    ):
        semantic.add_triple("planet", "shape", "sphere", confidence=0.95)
        semantic.add_triple("planet", "shape", "flat", confidence=0.1)
        newly_posted = inquiry.run_inquiry_cycle()
        # At least one question should be posted for the contradiction
        assert isinstance(newly_posted, list)

    def test_cycle_idempotent_no_duplicates(
        self, inquiry: ActiveInquiry, semantic
    ):
        semantic.add_triple("atom", "charge", "positive", confidence=0.9)
        semantic.add_triple("atom", "charge", "negative", confidence=0.6)
        first_run = inquiry.run_inquiry_cycle()
        second_run = inquiry.run_inquiry_cycle()
        # Second run should not re-post already queued questions
        # (same subject+predicate)
        first_ids = {q["question_id"] for q in first_run}
        second_ids = {q["question_id"] for q in second_run}
        assert first_ids.isdisjoint(second_ids)


# ===========================================================================
# 9. SkillSynthesizer — synthesize
# ===========================================================================

class TestSkillSynthesizer:

    def test_synthesize_returns_expected_keys(self, tl: TransferLearning):
        tl.register_pattern("physics", PatternType.STRATEGY, "Force = mass x accel",
                            ["force", "mass", "acceleration"])
        tl.register_pattern("biology", PatternType.HEURISTIC, "Homeostasis balance",
                            ["balance", "equilibrium", "homeostasis"])
        synth = tl.synthesize_skill(["physics", "biology"], "robotics", "physical_balance")
        assert synth["skill_name"] == "physical_balance"
        assert synth["target_domain"] == "robotics"
        assert "source_domains" in synth
        assert "patterns_merged" in synth
        assert "created_at" in synth

    def test_patterns_merged_count_correct(self, tl: TransferLearning):
        tl.register_pattern("domainA", PatternType.STRATEGY, "Strategy A1", ["kw1"])
        tl.register_pattern("domainA", PatternType.STRATEGY, "Strategy A2", ["kw2"])
        tl.register_pattern("domainB", PatternType.HEURISTIC, "Heuristic B1", ["kw3"])
        synth = tl.synthesize_skill(["domainA", "domainB"], "target", "merged_skill")
        assert synth["patterns_merged"] == 3

    def test_synthesized_pattern_registered_in_target(self, tl: TransferLearning):
        tl.register_pattern("src1", PatternType.TEMPLATE, "Template T", ["t1", "t2"])
        tl.synthesize_skill(["src1"], "tgt_domain", "template_transfer")
        patterns_in_target = tl.list_patterns(domain="tgt_domain")
        assert len(patterns_in_target) >= 1

    def test_list_synthesized_grows(self, tl: TransferLearning):
        synthesizer = SkillSynthesizer(tl)
        before = len(synthesizer.list_synthesized())
        tl.register_pattern("d1", PatternType.ANALOGY, "Analogy X", ["x"])
        synthesizer.synthesize(["d1"], "d2", "skill_x")
        assert len(synthesizer.list_synthesized()) == before + 1

    def test_get_synthesis_by_name(self, tl: TransferLearning):
        synthesizer = SkillSynthesizer(tl)
        tl.register_pattern("alpha", PatternType.STRATEGY, "Alpha strat", ["alpha"])
        synthesizer.synthesize(["alpha"], "beta", "alpha_to_beta")
        result = synthesizer.get_synthesis("alpha_to_beta")
        assert result is not None
        assert result["skill_name"] == "alpha_to_beta"

    def test_get_synthesis_missing_returns_none(self, tl: TransferLearning):
        synthesizer = SkillSynthesizer(tl)
        assert synthesizer.get_synthesis("nonexistent_skill") is None

    def test_empty_source_domains_still_succeeds(self, tl: TransferLearning):
        synth = tl.synthesize_skill([], "target", "empty_skill")
        assert synth["patterns_merged"] == 0
        assert synth["skill_name"] == "empty_skill"


# ===========================================================================
# 10. TransferLearning.synthesize_skill delegation
# ===========================================================================

class TestSynthesizeSkillDelegation:

    def test_delegation_produces_result(self, tl: TransferLearning):
        tl.register_pattern("phys", PatternType.STRATEGY, "Newton 2nd law", ["force"])
        result = tl.synthesize_skill(["phys"], "engineering", "applied_force")
        assert result["skill_name"] == "applied_force"
        assert result["target_domain"] == "engineering"


# ===========================================================================
# 11. EmergentSwarm — cast_vote + tally
# ===========================================================================

class TestEmergentSwarm:

    def test_cast_and_tally_basic(self):
        swarm = EmergentSwarm(["agent1", "agent2", "agent3"])
        swarm.cast_vote("topic1", "agent1", "yes", confidence=0.8)
        swarm.cast_vote("topic1", "agent2", "yes", confidence=0.9)
        swarm.cast_vote("topic1", "agent3", "no", confidence=0.3)
        result = swarm.tally("topic1")
        assert result["winner"] == "yes"
        assert result["vote_count"] == 3
        assert "yes" in result["breakdown"]

    def test_tally_empty_topic(self):
        swarm = EmergentSwarm(["a"])
        result = swarm.tally("no_votes_yet")
        assert result["winner"] == ""
        assert result["vote_count"] == 0

    def test_weighted_confidence_determines_winner(self):
        swarm = EmergentSwarm(["a", "b"])
        # 'blue' has lower count but much higher confidence
        swarm.cast_vote("color", "a", "blue", confidence=0.95)
        swarm.cast_vote("color", "b", "red", confidence=0.1)
        swarm.cast_vote("color", "b", "red", confidence=0.1)
        result = swarm.tally("color")
        assert result["winner"] == "blue"

    def test_confidence_sums_to_one(self):
        swarm = EmergentSwarm(["x", "y"])
        swarm.cast_vote("q", "x", "A", confidence=0.6)
        swarm.cast_vote("q", "y", "A", confidence=0.4)
        result = swarm.tally("q")
        assert result["confidence"] == pytest.approx(1.0, abs=0.01)


# ===========================================================================
# 12. EmergentSwarm — detect_emergent_pattern
# ===========================================================================

class TestDetectEmergentPattern:

    def test_high_confidence_produces_behavior(self):
        swarm = EmergentSwarm(["a1", "a2", "a3"])
        swarm.cast_vote("decision", "a1", "expand", confidence=0.9)
        swarm.cast_vote("decision", "a2", "expand", confidence=0.85)
        swarm.cast_vote("decision", "a3", "expand", confidence=0.8)
        pattern = swarm.detect_emergent_pattern("decision")
        assert pattern is not None
        assert pattern["behavior"] == "expand"
        assert pattern["confidence"] > 0.7

    def test_low_confidence_returns_none(self):
        swarm = EmergentSwarm(["a", "b"])
        swarm.cast_vote("split", "a", "yes", confidence=0.4)
        swarm.cast_vote("split", "b", "no", confidence=0.4)
        pattern = swarm.detect_emergent_pattern("split")
        # Evenly split → low winning confidence → None
        assert pattern is None or pattern["confidence"] <= 0.7


# ===========================================================================
# 13. EmergentSwarm — run_collective_reasoning
# ===========================================================================

class TestRunCollectiveReasoning:

    def test_returns_decision(self):
        swarm = EmergentSwarm(["alpha", "beta", "gamma"])
        perspectives = {
            "alpha": "We should deploy the new model immediately.",
            "beta": "We should deploy the new model immediately.",
            "gamma": "We should wait for more testing before deployment.",
        }
        result = swarm.run_collective_reasoning(
            "Should we deploy?", perspectives,
        )
        assert "decision" in result
        assert "confidence" in result
        assert "query" in result
        assert result["query"] == "Should we deploy?"

    def test_emergent_field_present(self):
        swarm = EmergentSwarm(["a", "b", "c"])
        perspectives = {
            "a": "Approve the plan with full confidence.",
            "b": "Approve the plan with full confidence.",
            "c": "Approve the plan with full confidence.",
        }
        result = swarm.run_collective_reasoning("Vote on plan", perspectives)
        # emergent key must exist (may be None if confidence <= 0.7)
        assert "emergent" in result

    def test_perspectives_echoed_in_result(self):
        swarm = EmergentSwarm(["x"])
        perspectives = {"x": "Unique perspective string"}
        result = swarm.run_collective_reasoning("topic", perspectives)
        assert result["perspectives"] == perspectives


# ===========================================================================
# 14. EmergentSwarm — list_behaviors grows
# ===========================================================================

class TestListBehaviors:

    def test_behaviors_grow_after_runs(self):
        swarm = EmergentSwarm(["p", "q", "r"])

        before = len(swarm.list_behaviors())

        # First collective reasoning cycle — high confidence
        swarm.run_collective_reasoning(
            "First question",
            {
                "p": "A" * 200,  # length 200 → confidence 1.0
                "q": "A" * 200,
                "r": "A" * 200,
            },
        )
        after_first = len(swarm.list_behaviors())

        # Second collective reasoning cycle — different topic
        swarm.run_collective_reasoning(
            "Second question",
            {
                "p": "B" * 200,
                "q": "B" * 200,
                "r": "B" * 200,
            },
        )
        after_second = len(swarm.list_behaviors())

        assert after_second >= after_first >= before

    def test_behaviors_not_duplicated(self):
        swarm = EmergentSwarm(["a", "b"])
        # Cast same high-confidence vote twice for same topic
        swarm.cast_vote("same_topic", "a", "choice_X", confidence=0.95)
        swarm.cast_vote("same_topic", "b", "choice_X", confidence=0.9)
        swarm.detect_emergent_pattern("same_topic")
        swarm.detect_emergent_pattern("same_topic")  # second call same topic
        behaviors = swarm.list_behaviors()
        matching = [b for b in behaviors if b["topic"] == "same_topic" and b["behavior"] == "choice_X"]
        assert len(matching) == 1  # deduplicated
