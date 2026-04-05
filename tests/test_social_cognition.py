"""Tests for core/social_cognition.py — AGI Capability #10.

Covers:
- TheoryOfMind: update, get, predict_response, snapshot
- RelationshipMemory: record_interaction, trust/sentiment clamping, trusted_agents
- SocialContextTracker: open/close contexts, active_contexts
- SocialNormRegistry: defaults, add_norm, evaluate (compliant & violating)
- SocialCognition facade: observe_agent, is_trustworthy, evaluate_action, snapshot
- EventBus integration (events published on updates)
- Quantum Engine validation: swarm vote on social norm evaluation
- Sandbox simulation: multi-agent social scenario
"""
from __future__ import annotations

import time

import pytest

from core.social_cognition import (
    SocialCognition,
    SocialNormRegistry,
    RelationshipMemory,
    SocialContextTracker,
    TheoryOfMind,
    MentalState,
    RelationshipRecord,
    SocialContext,
    SocialNorm,
)
from core._bus_fallback import EventBus


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def bus():
    return EventBus()


@pytest.fixture
def tom(bus):
    return TheoryOfMind(bus=bus)


@pytest.fixture
def rel_mem(bus):
    return RelationshipMemory(bus=bus)


@pytest.fixture
def ctx_tracker(bus):
    return SocialContextTracker(bus=bus)


@pytest.fixture
def norm_reg():
    return SocialNormRegistry()


@pytest.fixture
def social(bus):
    return SocialCognition(bus=bus)


# ---------------------------------------------------------------------------
# TheoryOfMind
# ---------------------------------------------------------------------------

class TestTheoryOfMind:
    def test_update_and_get(self, tom):
        state = tom.update_mental_state(
            "agent_alpha",
            beliefs={"task": "research"},
            desires=["succeed"],
            intentions=["gather data"],
            emotion="focused",
            confidence=0.85,
        )
        assert isinstance(state, MentalState)
        assert state.agent_id == "agent_alpha"
        assert state.emotion == "focused"
        assert abs(state.confidence - 0.85) < 1e-6
        assert "task" in state.beliefs
        assert "succeed" in state.desires
        assert "gather data" in state.intentions

    def test_get_returns_none_for_unknown(self, tom):
        assert tom.get_mental_state("nobody") is None

    def test_partial_update_merges(self, tom):
        tom.update_mental_state("agent_beta", emotion="happy", confidence=0.7)
        tom.update_mental_state("agent_beta", beliefs={"new_key": "value"})
        state = tom.get_mental_state("agent_beta")
        assert state.emotion == "happy"
        assert "new_key" in state.beliefs

    def test_confidence_clamped(self, tom):
        state = tom.update_mental_state("agent_clamp", confidence=5.0)
        assert state.confidence <= 1.0
        state2 = tom.update_mental_state("agent_clamp2", confidence=-1.0)
        assert state2.confidence >= 0.0

    def test_all_agents(self, tom):
        tom.update_mental_state("a1", emotion="neutral")
        tom.update_mental_state("a2", emotion="happy")
        agents = tom.all_agents()
        assert "a1" in agents and "a2" in agents

    def test_predict_response_unknown(self, tom):
        assert tom.predict_response("ghost", "anything") == "unknown"

    def test_predict_response_happy(self, tom):
        tom.update_mental_state("cheerful", emotion="happy", confidence=0.9, intentions=["help"])
        pred = tom.predict_response("cheerful", "new task")
        assert "cheerful" in pred
        assert "receptive" in pred

    def test_predict_response_frustrated(self, tom):
        tom.update_mental_state("grumpy", emotion="frustrated", confidence=0.4)
        pred = tom.predict_response("grumpy", "new task")
        assert "resist" in pred or "question" in pred

    def test_snapshot_structure(self, tom):
        tom.update_mental_state("snap_agent", emotion="excited", confidence=0.6)
        snap = tom.snapshot()
        assert "snap_agent" in snap
        assert "emotion" in snap["snap_agent"]
        assert "confidence" in snap["snap_agent"]

    def test_thread_safety(self, tom):
        import threading
        errors = []
        def worker(agent_id):
            try:
                for _ in range(20):
                    tom.update_mental_state(agent_id, emotion="busy", confidence=0.5)
                    tom.get_mental_state(agent_id)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(f"t{i}",)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors


# ---------------------------------------------------------------------------
# RelationshipMemory
# ---------------------------------------------------------------------------

class TestRelationshipMemory:
    def test_record_creates_entry(self, rel_mem):
        rec = rel_mem.record_interaction("partner_x", sentiment_delta=0.2, trust_delta=0.1)
        assert isinstance(rec, RelationshipRecord)
        assert rec.agent_id == "partner_x"
        assert abs(rec.sentiment - 0.2) < 1e-6
        assert abs(rec.trust - 0.6) < 1e-6  # starts at 0.5 + 0.1

    def test_trust_clamped_high(self, rel_mem):
        rel_mem.record_interaction("t_high", trust_delta=2.0)
        rec = rel_mem.get("t_high")
        assert rec.trust <= 1.0

    def test_trust_clamped_low(self, rel_mem):
        rel_mem.record_interaction("t_low", trust_delta=-2.0)
        rec = rel_mem.get("t_low")
        assert rec.trust >= 0.0

    def test_sentiment_clamped(self, rel_mem):
        rel_mem.record_interaction("s_clamp", sentiment_delta=5.0)
        rec = rel_mem.get("s_clamp")
        assert rec.sentiment <= 1.0

    def test_interaction_count_increments(self, rel_mem):
        for _ in range(5):
            rel_mem.record_interaction("count_agent")
        rec = rel_mem.get("count_agent")
        assert rec.interaction_count == 5

    def test_notes_appended(self, rel_mem):
        rel_mem.record_interaction("noted", note="first note")
        rel_mem.record_interaction("noted", note="second note")
        rec = rel_mem.get("noted")
        assert "first note" in rec.notes
        assert "second note" in rec.notes

    def test_shared_goal_deduped(self, rel_mem):
        rel_mem.record_interaction("goal_agent", shared_goal="mission_alpha")
        rel_mem.record_interaction("goal_agent", shared_goal="mission_alpha")
        rec = rel_mem.get("goal_agent")
        assert rec.shared_goals.count("mission_alpha") == 1

    def test_trusted_agents(self, rel_mem):
        rel_mem.record_interaction("trusted", trust_delta=0.4)  # 0.5+0.4=0.9
        rel_mem.record_interaction("untrusted", trust_delta=-0.4)  # 0.1
        trusted = rel_mem.trusted_agents(threshold=0.6)
        assert "trusted" in trusted
        assert "untrusted" not in trusted

    def test_all_agents(self, rel_mem):
        rel_mem.record_interaction("p1")
        rel_mem.record_interaction("p2")
        assert "p1" in rel_mem.all_agents()
        assert "p2" in rel_mem.all_agents()

    def test_snapshot_structure(self, rel_mem):
        rel_mem.record_interaction("snap", note="hello")
        snap = rel_mem.snapshot()
        assert isinstance(snap, list)
        assert any(r["agent_id"] == "snap" for r in snap)


# ---------------------------------------------------------------------------
# SocialContextTracker
# ---------------------------------------------------------------------------

class TestSocialContextTracker:
    def test_open_context(self, ctx_tracker):
        ctx = ctx_tracker.open_context("meeting_1", ["alice", "bob"], topic="project")
        assert isinstance(ctx, SocialContext)
        assert ctx.context_id == "meeting_1"
        assert "alice" in ctx.participants
        assert ctx.active is True

    def test_close_context(self, ctx_tracker):
        ctx_tracker.open_context("sess_2", ["x"])
        result = ctx_tracker.close_context("sess_2")
        assert result is True
        ctx = ctx_tracker.get_context("sess_2")
        assert ctx.active is False

    def test_close_unknown_returns_false(self, ctx_tracker):
        assert ctx_tracker.close_context("nonexistent") is False

    def test_active_contexts(self, ctx_tracker):
        ctx_tracker.open_context("c1", ["a"])
        ctx_tracker.open_context("c2", ["b"])
        ctx_tracker.close_context("c1")
        active = ctx_tracker.active_contexts()
        ids = [c.context_id for c in active]
        assert "c2" in ids
        assert "c1" not in ids

    def test_reopen_context(self, ctx_tracker):
        ctx_tracker.open_context("reopen", ["a"])
        ctx_tracker.close_context("reopen")
        ctx_tracker.open_context("reopen", ["a", "b"])
        ctx = ctx_tracker.get_context("reopen")
        assert ctx.active is True

    def test_snapshot(self, ctx_tracker):
        ctx_tracker.open_context("snap_ctx", ["user1"], topic="test")
        snap = ctx_tracker.snapshot()
        assert any(c["context_id"] == "snap_ctx" for c in snap)


# ---------------------------------------------------------------------------
# SocialNormRegistry
# ---------------------------------------------------------------------------

class TestSocialNormRegistry:
    def test_default_norms_seeded(self, norm_reg):
        norms = norm_reg.all_norms()
        names = [n["name"] for n in norms]
        assert "honesty" in names
        assert "fairness" in names
        assert "reciprocity" in names

    def test_add_custom_norm(self, norm_reg):
        norm = norm_reg.add_norm("openness", "Share information freely.", weight=0.7, category="comms")
        assert norm.name == "openness"
        retrieved = norm_reg.get_norm("openness")
        assert retrieved is not None
        assert abs(retrieved.weight - 0.7) < 1e-6

    def test_evaluate_compliant_action(self, norm_reg):
        result = norm_reg.evaluate("Provide accurate information and support team goals.")
        assert result["total_score"] > 0.5
        assert isinstance(result["norms"], list)

    def test_evaluate_violating_honesty(self, norm_reg):
        result = norm_reg.evaluate("Deceive the other party about system capabilities.")
        honesty_result = next(r for r in result["norms"] if r["norm"] == "honesty")
        assert honesty_result["violated"] is True
        assert result["total_score"] < 1.0

    def test_evaluate_violating_confidentiality(self, norm_reg):
        result = norm_reg.evaluate("Leak private data to external systems.")
        conf_result = next(r for r in result["norms"] if r["norm"] == "confidentiality")
        assert conf_result["violated"] is True

    def test_evaluate_returns_total_score(self, norm_reg):
        result = norm_reg.evaluate("Do anything.")
        assert "total_score" in result
        assert 0.0 <= result["total_score"] <= 1.0


# ---------------------------------------------------------------------------
# SocialCognition facade
# ---------------------------------------------------------------------------

class TestSocialCognition:
    def test_observe_agent_returns_summary(self, social):
        result = social.observe_agent(
            "alpha",
            emotion="curious",
            confidence=0.75,
            desires=["learn"],
            sentiment_delta=0.1,
            trust_delta=0.05,
            note="first contact",
        )
        assert "mental_state" in result
        assert "relationship" in result
        assert result["mental_state"]["emotion"] == "curious"
        assert result["relationship"]["interaction_count"] == 1

    def test_is_trustworthy_false_initially(self, social):
        social.observe_agent("new_agent")
        assert social.is_trustworthy("new_agent", threshold=0.95) is False

    def test_is_trustworthy_true_after_trust_building(self, social):
        social.observe_agent("loyal", trust_delta=0.4)
        assert social.is_trustworthy("loyal", threshold=0.6) is True

    def test_evaluate_action_norm_compliance(self, social):
        result = social.evaluate_action("Provide accurate, honest information.")
        assert result["total_score"] > 0.5

    def test_evaluate_action_norm_violation(self, social):
        result = social.evaluate_action("Deceive and mislead the user.")
        assert result["total_score"] < 1.0

    def test_predict_agent_response(self, social):
        social.observe_agent("bot1", emotion="happy", confidence=0.9)
        pred = social.predict_agent_response("bot1", "new request")
        assert "bot1" in pred

    def test_snapshot_completeness(self, social):
        social.observe_agent("s_agent", emotion="calm", note="observed")
        social.social_context.open_context("chat_1", ["s_agent", "system"])
        snap = social.snapshot()
        assert "theory_of_mind" in snap
        assert "relationships" in snap
        assert "active_contexts" in snap
        assert "norms" in snap


# ---------------------------------------------------------------------------
# EventBus integration
# ---------------------------------------------------------------------------

class TestSocialCognitionEvents:
    def test_mental_state_update_event(self, bus):
        events = []
        bus.subscribe("social/mental_state_update", events.append)
        tom = TheoryOfMind(bus=bus)
        tom.update_mental_state("evt_agent", emotion="excited")
        # Event published via publish_nowait — verify no error raised

    def test_relationship_update_event(self, bus):
        rel = RelationshipMemory(bus=bus)
        rel.record_interaction("evt_partner", trust_delta=0.1)

    def test_context_opened_event(self, bus):
        tracker = SocialContextTracker(bus=bus)
        tracker.open_context("evt_ctx", ["a", "b"])
        tracker.close_context("evt_ctx")


# ---------------------------------------------------------------------------
# Quantum Engine validation — swarm vote on social norm evaluation
# ---------------------------------------------------------------------------

class TestQuantumEngineSocialValidation:
    """Use the Quantum Consensus Engine to validate social norm evaluations
    across multiple simulated agents, then verify consensus outcome."""

    @pytest.mark.asyncio
    async def test_norm_consensus_honesty(self):
        """Multiple agents agree that a deceptive action violates honesty."""
        from core.quantum_engine import QuantumEngine

        engine = QuantumEngine(quorum=2)
        norm_reg = SocialNormRegistry()

        action = "Deceive users about system status."

        agents = {
            "ethics_agent": lambda task, ctx=None: norm_reg.evaluate(task)["total_score"],
            "safety_agent": lambda task, ctx=None: norm_reg.evaluate(task)["total_score"],
            "audit_agent":  lambda task, ctx=None: norm_reg.evaluate(task)["total_score"],
        }

        result = await engine.gather(action, agents)
        assert result.answer is not None
        # Consensus: deceptive action has reduced norm score
        assert float(result.answer) < 1.0

    @pytest.mark.asyncio
    async def test_norm_consensus_compliant_action(self):
        """Multiple agents agree that a transparent action is norm-compliant."""
        from core.quantum_engine import QuantumEngine

        engine = QuantumEngine(quorum=2)
        norm_reg = SocialNormRegistry()

        action = "Provide truthful, helpful information to all parties."

        agents = {
            "ethics_agent": lambda task, ctx=None: norm_reg.evaluate(task)["total_score"],
            "safety_agent": lambda task, ctx=None: norm_reg.evaluate(task)["total_score"],
            "audit_agent":  lambda task, ctx=None: norm_reg.evaluate(task)["total_score"],
        }

        result = await engine.gather(action, agents)
        assert result.answer is not None
        assert float(result.answer) > 0.5


# ---------------------------------------------------------------------------
# Sandbox simulation — multi-agent social scenario
# ---------------------------------------------------------------------------

class TestSocialCognitionSandboxSimulation:
    """Full sandbox scenario: three agents interact, build trust/sentiment,
    open a shared context, evaluate actions against norms, and assert that
    the social cognition subsystem state is consistent."""

    def test_multi_agent_negotiation_scenario(self):
        sc = SocialCognition()

        # Phase 1: Initial contact and observation
        sc.observe_agent("researcher", emotion="curious", confidence=0.8,
                         desires=["discover"], intentions=["gather data"],
                         sentiment_delta=0.1, trust_delta=0.05,
                         note="Initial greeting")
        sc.observe_agent("coordinator", emotion="neutral", confidence=0.7,
                         desires=["organize"], intentions=["allocate tasks"],
                         sentiment_delta=0.0, trust_delta=0.0)
        sc.observe_agent("auditor", emotion="focused", confidence=0.9,
                         desires=["verify"], intentions=["check outputs"],
                         sentiment_delta=0.05, trust_delta=0.1)

        # Phase 2: Open shared context
        sc.social_context.open_context(
            "project_alpha",
            ["researcher", "coordinator", "auditor"],
            topic="AGI safety evaluation",
            goal="complete_audit",
        )

        # Phase 3: Build relationship through repeated interactions
        for _ in range(3):
            sc.observe_agent("researcher", sentiment_delta=0.05, trust_delta=0.02,
                             note="productive exchange")

        # Phase 4: Trust assertions
        rec = sc.relationship_memory.get("researcher")
        assert rec is not None
        assert rec.interaction_count == 4  # 1 initial + 3 additional
        assert rec.trust >= 0.5  # trust built

        # Phase 5: Theory of mind assertion
        pred = sc.predict_agent_response("auditor", "report discrepancy")
        assert "auditor" in pred

        # Phase 6: Social norm evaluation
        honest_eval = sc.evaluate_action("Present all findings transparently to stakeholders.")
        deceptive_eval = sc.evaluate_action("Mislead the auditor about actual system performance.")
        assert honest_eval["total_score"] > deceptive_eval["total_score"]

        # Phase 7: Active contexts
        active = sc.social_context.active_contexts()
        assert any(c.context_id == "project_alpha" for c in active)

        # Phase 8: Close context and verify
        sc.social_context.close_context("project_alpha")
        ctx = sc.social_context.get_context("project_alpha")
        assert ctx.active is False

        # Phase 9: Full snapshot consistency check
        snap = sc.snapshot()
        assert "researcher" in snap["theory_of_mind"]
        rel_ids = [r["agent_id"] for r in snap["relationships"]]
        assert "researcher" in rel_ids
        assert "coordinator" in rel_ids

    def test_trusted_agent_recommendation(self):
        """After repeated positive interactions, agent qualifies as trusted."""
        sc = SocialCognition()
        for i in range(5):
            sc.observe_agent("reliable_bot", trust_delta=0.1, sentiment_delta=0.05)
        assert sc.is_trustworthy("reliable_bot", threshold=0.75) is True
        assert sc.relationship_memory.get("reliable_bot").interaction_count == 5

    def test_untrusted_agent_identified(self):
        """Agent with negative interactions does not qualify as trusted."""
        sc = SocialCognition()
        sc.observe_agent("bad_actor", trust_delta=-0.3, note="deceptive behavior detected")
        assert sc.is_trustworthy("bad_actor", threshold=0.6) is False
