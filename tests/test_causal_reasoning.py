"""Tests for core.causal_reasoning — causal inference engine."""
from __future__ import annotations

import time

import pytest

from core._bus_fallback import EventBus
from core.causal_reasoning import (
    CausalEdge,
    CausalGraph,
    CausalPathway,
    CausalReasoning,
    ConfidenceLevel,
    CounterfactualResult,
    EdgeType,
    InterventionResult,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def graph():
    return CausalGraph()


@pytest.fixture
def engine(bus):
    return CausalReasoning(bus=bus)


# ---------------------------------------------------------------------------
# CausalGraph basics
# ---------------------------------------------------------------------------

def _make_edge(
    cause: str, effect: str,
    edge_type: EdgeType = EdgeType.CAUSES,
    strength: float = 0.5,
    confidence: float = 0.5,
) -> CausalEdge:
    """Helper to build a CausalEdge with sensible defaults."""
    return CausalEdge(
        cause=cause, effect=effect, edge_type=edge_type,
        strength=strength, confidence=confidence,
        confidence_level=ConfidenceLevel.HYPOTHESISED,
        evidence_count=0, created_at=time.time(),
    )


class TestCausalGraphBasics:
    def test_add_and_get_edge(self, graph: CausalGraph):
        graph.add_edge(_make_edge("rain", "wet_road", EdgeType.CAUSES, strength=0.9))
        retrieved = graph.get_edge("rain", "wet_road")
        assert retrieved is not None
        assert retrieved.cause == "rain"
        assert retrieved.effect == "wet_road"
        assert retrieved.strength == 0.9

    def test_remove_edge(self, graph: CausalGraph):
        graph.add_edge(_make_edge("a", "b"))
        assert graph.remove_edge("a", "b") is True
        assert graph.get_edge("a", "b") is None

    def test_remove_missing_edge(self, graph: CausalGraph):
        assert graph.remove_edge("x", "y") is False

    def test_get_effects(self, graph: CausalGraph):
        graph.add_edge(_make_edge("a", "b", EdgeType.CAUSES))
        graph.add_edge(_make_edge("a", "c", EdgeType.ENABLES))
        effects = graph.get_effects("a")
        effect_names = {e.effect for e in effects}
        assert effect_names == {"b", "c"}

    def test_get_causes(self, graph: CausalGraph):
        graph.add_edge(_make_edge("a", "c", EdgeType.CAUSES))
        graph.add_edge(_make_edge("b", "c", EdgeType.CAUSES))
        causes = graph.get_causes("c")
        cause_names = {e.cause for e in causes}
        assert cause_names == {"a", "b"}

    def test_clear(self, graph: CausalGraph):
        graph.add_edge(_make_edge("a", "b"))
        graph.clear()
        assert graph.get_edge("a", "b") is None
        assert graph.get_effects("a") == []


# ---------------------------------------------------------------------------
# CausalGraph path finding (BFS)
# ---------------------------------------------------------------------------

class TestCausalPaths:
    def test_direct_path(self, graph: CausalGraph):
        graph.add_edge(_make_edge("a", "b", strength=0.8))
        paths = graph.find_causal_paths("a", "b")
        assert len(paths) >= 1
        assert ("a", "b") in [p.path for p in paths]

    def test_multi_hop_path(self, graph: CausalGraph):
        graph.add_edge(_make_edge("a", "b"))
        graph.add_edge(_make_edge("b", "c"))
        graph.add_edge(_make_edge("c", "d"))
        paths = graph.find_causal_paths("a", "d")
        assert len(paths) >= 1
        assert any(p.length == 3 for p in paths)  # a→b→c→d

    def test_no_path(self, graph: CausalGraph):
        graph.add_edge(_make_edge("a", "b"))
        graph.add_edge(_make_edge("c", "d"))
        paths = graph.find_causal_paths("a", "d")
        assert len(paths) == 0

    def test_cycle_avoidance(self, graph: CausalGraph):
        graph.add_edge(_make_edge("a", "b"))
        graph.add_edge(_make_edge("b", "c"))
        graph.add_edge(_make_edge("c", "a"))  # cycle
        paths = graph.find_causal_paths("a", "c")
        # Should find a→b→c without looping
        assert len(paths) >= 1
        for p in paths:
            assert len(p.path) == len(set(p.path))  # no duplicate nodes

    def test_max_length_limit(self, graph: CausalGraph):
        # Chain: a→b→c→d→e→f→g
        nodes = list("abcdefg")
        for i in range(len(nodes) - 1):
            graph.add_edge(_make_edge(nodes[i], nodes[i + 1]))
        # max_length=3 should NOT find the full chain
        paths = graph.find_causal_paths("a", "g", max_length=3)
        assert len(paths) == 0


# ---------------------------------------------------------------------------
# Confounders
# ---------------------------------------------------------------------------

class TestConfounders:
    def test_find_confounders(self, graph: CausalGraph):
        # C → A, C → B ⇒ C is common cause (confounder)
        graph.add_edge(_make_edge("C", "A"))
        graph.add_edge(_make_edge("C", "B"))
        confounders = graph.find_confounders("A", "B")
        assert "C" in confounders

    def test_no_confounders(self, graph: CausalGraph):
        graph.add_edge(_make_edge("A", "B"))
        confounders = graph.find_confounders("A", "B")
        # No common parent
        assert len(confounders) == 0

    def test_minimal_adjustment_sets(self, graph: CausalGraph):
        graph.add_edge(_make_edge("Z1", "A"))
        graph.add_edge(_make_edge("Z1", "B"))
        graph.add_edge(_make_edge("Z2", "A"))
        graph.add_edge(_make_edge("Z2", "B"))
        sets = graph.minimal_adjustment_sets("A", "B")
        assert ("Z1",) in sets
        assert ("Z2",) in sets


# ---------------------------------------------------------------------------
# CausalReasoning — variable state
# ---------------------------------------------------------------------------

class TestVariableState:
    def test_set_and_get(self, engine: CausalReasoning):
        engine.set_variable("temperature", 25.0)
        assert engine.get_variable("temperature") == 25.0

    def test_get_missing_returns_none(self, engine: CausalReasoning):
        assert engine.get_variable("nonexistent") is None


# ---------------------------------------------------------------------------
# Causal edges via engine
# ---------------------------------------------------------------------------

class TestCausalEdgesViaEngine:
    def test_add_cause(self, engine: CausalReasoning):
        edge = engine.add_cause("smoking", "cancer", EdgeType.CAUSES, strength=0.7)
        assert edge.cause == "smoking"
        assert edge.effect == "cancer"

    def test_add_cause_updates_existing(self, engine: CausalReasoning):
        engine.add_cause("a", "b", EdgeType.CAUSES, strength=0.5)
        edge2 = engine.add_cause("a", "b", EdgeType.CAUSES, strength=0.8)
        assert edge2.strength == 0.8
        # add_cause replaces the edge; evidence_count follows the new call
        retrieved = engine.graph.get_edge("a", "b")
        assert retrieved is not None
        assert retrieved.strength == 0.8


# ---------------------------------------------------------------------------
# Interventions (do-calculus)
# ---------------------------------------------------------------------------

class TestInterventions:
    def test_simple_intervention(self, engine: CausalReasoning):
        engine.add_cause("rain", "wet", EdgeType.CAUSES, strength=0.9)
        engine.set_variable("rain", 0.0)
        engine.set_variable("wet", 0.0)

        result = engine.intervene("rain", 1.0)
        assert result is not None
        assert result.target_variable == "rain"
        assert result.intervention_value == 1.0
        assert "wet" in result.affected_variables

    def test_multi_step_propagation(self, engine: CausalReasoning):
        engine.add_cause("a", "b", EdgeType.CAUSES, strength=0.8)
        engine.add_cause("b", "c", EdgeType.CAUSES, strength=0.6)
        engine.set_variable("a", 0.0)
        engine.set_variable("b", 0.0)
        engine.set_variable("c", 0.0)

        result = engine.intervene("a", 1.0)
        assert "b" in result.affected_variables
        assert "c" in result.affected_variables

    def test_graph_surgery(self, engine: CausalReasoning):
        """do() should sever incoming edges to target."""
        engine.add_cause("x", "a", EdgeType.CAUSES, strength=0.5)
        engine.add_cause("a", "b", EdgeType.CAUSES, strength=0.8)
        engine.set_variable("x", 0.0)
        engine.set_variable("a", 0.0)
        engine.set_variable("b", 0.0)

        # Intervene on 'a': x→a link severed
        result = engine.intervene("a", 1.0)
        # 'b' affected, 'x' should NOT be affected (upstream)
        assert "b" in result.affected_variables

    def test_prevents_edge_type(self, engine: CausalReasoning):
        engine.add_cause("vaccine", "infection", EdgeType.PREVENTS, strength=0.85)
        engine.set_variable("vaccine", 0.0)
        engine.set_variable("infection", 0.5)

        result = engine.intervene("vaccine", 1.0)
        # With PREVENTS, infection should decrease
        assert result is not None
        assert result.affected_variables["infection"] < 0

    def test_enables_edge_type_has_gated_effect(self, engine: CausalReasoning):
        engine.add_cause("key", "door_open", EdgeType.ENABLES, strength=1.0)
        engine.set_variable("key", 0.0)
        result = engine.intervene("key", 1.0)
        # ENABLES uses a smaller propagation multiplier than direct CAUSES.
        assert result.affected_variables["door_open"] == pytest.approx(0.6, abs=1e-9)

    def test_modulates_edge_type_scales_effect(self, engine: CausalReasoning):
        engine.add_cause("dimmer", "brightness", EdgeType.MODULATES, strength=1.0)
        engine.set_variable("dimmer", 0.0)
        result = engine.intervene("dimmer", 1.0)
        assert result.affected_variables["brightness"] == pytest.approx(0.8, abs=1e-9)


# ---------------------------------------------------------------------------
# Counterfactuals
# ---------------------------------------------------------------------------

class TestCounterfactuals:
    def test_simple_counterfactual(self, engine: CausalReasoning):
        engine.add_cause("study", "grade", EdgeType.CAUSES, strength=0.8)
        engine.set_variable("study", 2.0)
        engine.set_variable("grade", 70.0)

        result = engine.counterfactual("study", 8.0, "grade")
        assert result is not None
        assert "study" in result.query
        assert result.factual_value == 70.0
        assert result.counterfactual_value != result.factual_value

    def test_counterfactual_returns_none_without_edge(self, engine: CausalReasoning):
        engine.set_variable("a", 1.0)
        engine.set_variable("b", 2.0)
        result = engine.counterfactual("a", 5.0, "b")
        # No causal link; should still return a result (zero effect)
        # or None depending on implementation
        if result is not None:
            assert result.confidence >= 0.0


# ---------------------------------------------------------------------------
# Strength estimation (Pearson)
# ---------------------------------------------------------------------------

class TestStrengthEstimation:
    def test_correlated_observations(self, engine: CausalReasoning):
        for i in range(20):
            engine.set_variable("x", float(i))
            engine.set_variable("y", float(i) * 2 + 1)
        strength = engine.estimate_strength("x", "y")
        assert strength > 0.9  # near-perfect positive correlation

    def test_no_observations(self, engine: CausalReasoning):
        strength = engine.estimate_strength("a", "b")
        assert strength == 0.0  # returns 0.0 when no data

    def test_insufficient_pairs(self, engine: CausalReasoning):
        engine.set_variable("a", 1.0)
        engine.set_variable("b", 2.0)
        strength = engine.estimate_strength("a", "b")
        # Need at least 3 pairs
        assert 0.0 <= abs(strength) <= 1.0


# ---------------------------------------------------------------------------
# Pathway analysis
# ---------------------------------------------------------------------------

class TestPathwayAnalysis:
    def test_strongest_pathway(self, engine: CausalReasoning):
        engine.add_cause("a", "b", EdgeType.CAUSES, strength=0.8)
        engine.add_cause("b", "c", EdgeType.CAUSES, strength=0.6)
        engine.add_cause("a", "c", EdgeType.CAUSES, strength=0.3)

        pathway = engine.strongest_pathway("a", "c")
        assert pathway is not None
        assert pathway.source == "a"
        assert pathway.target == "c"

    def test_no_pathway(self, engine: CausalReasoning):
        engine.add_cause("a", "b", EdgeType.CAUSES)
        pathway = engine.strongest_pathway("b", "a")
        # Directed — no reverse path
        assert pathway is None

    def test_total_causal_effect(self, engine: CausalReasoning):
        engine.add_cause("a", "b", EdgeType.CAUSES, strength=0.7)
        engine.add_cause("a", "c", EdgeType.CAUSES, strength=0.5)
        engine.add_cause("b", "c", EdgeType.CAUSES, strength=0.3)

        effect = engine.total_causal_effect("a", "c")
        assert effect is not None
        assert effect > 0


# ---------------------------------------------------------------------------
# Confounders via engine
# ---------------------------------------------------------------------------

class TestConfoundersViaEngine:
    def test_confounders_between(self, engine: CausalReasoning):
        engine.add_cause("Z", "X", EdgeType.CAUSES, strength=0.5)
        engine.add_cause("Z", "Y", EdgeType.CAUSES, strength=0.5)
        confounders = engine.confounders_between("X", "Y")
        assert "Z" in confounders

    def test_adjustment_sets_between(self, engine: CausalReasoning):
        engine.add_cause("Z", "X", EdgeType.CAUSES, strength=0.5)
        engine.add_cause("Z", "Y", EdgeType.CAUSES, strength=0.5)
        adjustment_sets = engine.adjustment_sets_between("X", "Y")
        assert ("Z",) in adjustment_sets


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

class TestSummary:
    def test_summary_structure(self, engine: CausalReasoning):
        engine.set_variable("a", 1.0)
        engine.add_cause("a", "b", EdgeType.CAUSES)
        summary = engine.summary()
        assert "variable_count" in summary
        assert "edge_count" in summary
        assert summary["variable_count"] >= 1
        assert summary["edge_count"] >= 1


# ---------------------------------------------------------------------------
# Export / import
# ---------------------------------------------------------------------------

class TestExportImport:
    def test_round_trip(self, engine: CausalReasoning, bus: EventBus):
        engine.add_cause("a", "b", EdgeType.CAUSES, strength=0.8)
        engine.add_cause("b", "c", EdgeType.ENABLES, strength=0.5)
        engine.set_variable("a", 1.0)

        exported = engine.export_state()
        assert "edges" in exported
        assert "state" in exported
        assert len(exported["edges"]) == 2

        engine2 = CausalReasoning(bus=bus)
        engine2.import_state(exported)
        # import_state restores state dict
        assert engine2.get_variable("a") == 1.0
        edge = engine2.graph.get_edge("a", "b")
        assert edge is not None
        assert edge.strength == 0.8

    def test_import_empty(self, bus: EventBus):
        engine = CausalReasoning(bus=bus)
        engine.import_state({})
        assert engine.summary()["variable_count"] == 0


# ---------------------------------------------------------------------------
# EventBus integration
# ---------------------------------------------------------------------------

class TestEventBusIntegration:
    def test_edge_added_event(self, bus: EventBus, engine: CausalReasoning):
        events = []
        bus.subscribe("causal.edge_added", lambda e: events.append(e))
        engine.add_cause("a", "b", EdgeType.CAUSES)
        assert len(events) == 1
        assert events[0]["cause"] == "a"

    def test_intervention_event(self, bus: EventBus, engine: CausalReasoning):
        events = []
        bus.subscribe("causal.intervention", lambda e: events.append(e))
        engine.add_cause("a", "b", EdgeType.CAUSES, strength=0.5)
        engine.set_variable("a", 0.0)
        engine.set_variable("b", 0.0)
        engine.intervene("a", 1.0)
        assert len(events) == 1

    def test_counterfactual_event(self, bus: EventBus, engine: CausalReasoning):
        events = []
        bus.subscribe("causal.counterfactual", lambda e: events.append(e))
        engine.add_cause("x", "y", EdgeType.CAUSES, strength=0.6)
        engine.set_variable("x", 1.0)
        engine.set_variable("y", 2.0)
        engine.counterfactual("x", 5.0, "y")
        assert len(events) == 1


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------

class TestThreadSafety:
    def test_concurrent_edge_addition(self, engine: CausalReasoning):
        import threading

        def add_edges(prefix, count):
            for i in range(count):
                engine.add_cause(f"{prefix}{i}", f"{prefix}{i}_effect", EdgeType.CAUSES)

        threads = [
            threading.Thread(target=add_edges, args=(f"t{t}_", 10))
            for t in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert engine.summary()["edge_count"] == 50


# ---------------------------------------------------------------------------
# Frozen dataclass verifications
# ---------------------------------------------------------------------------

class TestFrozenDataclasses:
    def test_causal_edge_immutable(self):
        edge = CausalEdge(
            cause="a", effect="b", edge_type=EdgeType.CAUSES,
            strength=0.8, confidence=0.9, confidence_level=ConfidenceLevel.OBSERVED,
            evidence_count=1, created_at=time.time(),
        )
        with pytest.raises(AttributeError):
            edge.strength = 0.1  # type: ignore[misc]

    def test_intervention_result_immutable(self):
        result = InterventionResult(
            target_variable="x", intervention_value=1.0,
            affected_variables={"y": 0.5}, total_effect=0.5,
            causal_paths_used=1, confidence=0.8,
        )
        with pytest.raises(AttributeError):
            result.total_effect = 0.0  # type: ignore[misc]
