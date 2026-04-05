"""Tests for core.quantum_engine — upgraded quantum consensus engine.

Covers:
  1. Confidence parsed from dict response
  2. Confidence heuristic from plain string (hedging vs long)
  3. Destructive interference reduces confidence
  4. Domain-aware reputation
  5. Reputation snapshot round-trip via load()
  6. Early exit fires before all agents return
  7. Hard timeout returns partial=True
  8. ConsensusProfiler records after gather() with with_profiler()
  9. contradictions_found > 0 on ConsensusResult
  10. Embedding similarity groups semantically equivalent answers (mocked)
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import numpy as np
import pytest

from core.quantum_engine import (
    AgentReputation,
    ConsensusFailure,
    ConsensusProfiler,
    QuantumEngine,
)


# ---------------------------------------------------------------------------
# 1. Confidence parsed from dict response
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_confidence_from_dict():
    """Agent returning {answer, confidence} dict has its confidence parsed."""
    engine = QuantumEngine(quorum=1, hard_timeout_ms=3000)

    async def dict_agent(task, ctx):
        return {"answer": "42", "confidence": 0.6}

    resp = await engine._timed_call("a", dict_agent, "test", {})
    assert resp is not None
    assert resp.answer == "42"
    assert resp.confidence == pytest.approx(0.6)
    assert resp.domain == "general"


@pytest.mark.asyncio
async def test_confidence_from_dict_with_domain():
    """Dict response can also carry a domain field."""
    engine = QuantumEngine(quorum=1, hard_timeout_ms=3000)

    async def dict_agent(task, ctx):
        return {"answer": "pi", "confidence": 0.95, "domain": "math"}

    resp = await engine._timed_call("a", dict_agent, "test", {})
    assert resp is not None
    assert resp.confidence == pytest.approx(0.95)
    assert resp.domain == "math"


# ---------------------------------------------------------------------------
# 2. Confidence heuristic from plain string
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_confidence_heuristic_hedging():
    """Hedging words reduce heuristic confidence."""
    engine = QuantumEngine(quorum=1, hard_timeout_ms=3000)

    async def hedging(task, ctx):
        return "maybe possibly uncertain"

    resp = await engine._timed_call("h", hedging, "q", {})
    assert resp is not None
    assert resp.confidence < 0.5  # short + 3 hedging words


@pytest.mark.asyncio
async def test_confidence_heuristic_long_answer():
    """Long answers without hedging produce high confidence."""
    engine = QuantumEngine(quorum=1, hard_timeout_ms=3000)

    async def confident(task, ctx):
        return "x" * 400

    resp = await engine._timed_call("c", confident, "q", {})
    assert resp is not None
    assert resp.confidence > 0.5  # long, no hedging


@pytest.mark.asyncio
async def test_confidence_heuristic_ordering():
    """Confident answer has higher confidence than hedging answer."""
    engine = QuantumEngine(quorum=1, hard_timeout_ms=3000)

    async def hedging(task, ctx):
        return "maybe possibly uncertain"

    async def confident(task, ctx):
        return "x" * 400

    rh = await engine._timed_call("h", hedging, "q", {})
    rc = await engine._timed_call("c", confident, "q", {})
    assert rc.confidence > rh.confidence


# ---------------------------------------------------------------------------
# 3. Destructive interference
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_destructive_interference():
    """Contradicting high-weight agent reduces winner confidence."""
    rep = AgentReputation(default_weight=0.9)
    engine = QuantumEngine(
        quorum=3,
        early_exit_conf=0.99,
        hard_timeout_ms=3000,
        reputation=rep,
        similarity_fn=QuantumEngine._exact_sim,
    )

    async def yes1(t, c):
        return {"answer": "Yes", "confidence": 0.95}

    async def yes2(t, c):
        return {"answer": "Yes", "confidence": 0.95}

    async def no1(t, c):
        return {"answer": "No", "confidence": 0.95}

    result = await engine.gather("q", {"a": yes1, "b": yes2, "c": no1})
    assert result.answer == "Yes"
    # Raw majority confidence would be ~0.667;
    # destructive interference lowers it
    assert result.confidence < 0.667


# ---------------------------------------------------------------------------
# 4. Domain-aware reputation
# ---------------------------------------------------------------------------

def test_domain_aware_reputation():
    """Agent scores differ by domain."""
    rep = AgentReputation(alpha=0.5, default_weight=0.5)
    rep.update("alice", correct=True, domain="math")
    rep.update("alice", correct=False, domain="code")

    math_w = rep.weight("alice", domain="math")
    code_w = rep.weight("alice", domain="code")

    assert math_w > code_w
    assert math_w > 0.5
    assert code_w < 0.5


def test_domain_fallback_to_general():
    """Unknown domain falls back to general, then default."""
    rep = AgentReputation(default_weight=0.6)
    rep.update("bob", correct=True, domain="general")

    w = rep.weight("bob", domain="art")
    general_w = rep.weight("bob", domain="general")
    assert w == general_w  # Falls back to general


# ---------------------------------------------------------------------------
# 5. Reputation snapshot round-trip
# ---------------------------------------------------------------------------

def test_reputation_snapshot_roundtrip():
    """snapshot() -> load() preserves all scores."""
    rep = AgentReputation(alpha=0.3, default_weight=0.5)
    rep.update("bob", correct=True, domain="general")
    rep.update("bob", correct=False, domain="math")
    rep.update("carol", correct=True, domain="code")

    snap = rep.snapshot()
    assert isinstance(snap, dict)
    assert all("::" in k for k in snap)

    rep2 = AgentReputation(alpha=0.3, default_weight=0.5)
    rep2.load(snap)

    for key in snap:
        aid, dom = key.split("::", 1)
        assert abs(rep.weight(aid, dom) - rep2.weight(aid, dom)) < 1e-9


# ---------------------------------------------------------------------------
# 6. Early exit
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_early_exit():
    """Engine exits early when confidence threshold met."""
    rep = AgentReputation(default_weight=0.9)
    engine = QuantumEngine(
        quorum=2,
        early_exit_conf=0.5,
        hard_timeout_ms=10000,
        reputation=rep,
        similarity_fn=QuantumEngine._exact_sim,
    )

    async def fast(t, c):
        return {"answer": "42", "confidence": 0.9}

    async def slow(t, c):
        await asyncio.sleep(60.0)
        return {"answer": "42", "confidence": 0.9}

    result = await engine.gather("q", {
        "fast1": fast, "fast2": fast, "slow": slow,
    })
    assert result.early_exit is True
    assert result.participating >= 2
    assert result.latency_ms < 5000


# ---------------------------------------------------------------------------
# 7. Hard timeout -> partial=True
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hard_timeout_partial():
    """Hard timeout fires before quorum; result is partial."""
    engine = QuantumEngine(
        quorum=3,
        early_exit_conf=0.99,
        hard_timeout_ms=300,
        similarity_fn=QuantumEngine._exact_sim,
    )

    async def fast(t, c):
        return {"answer": "ok", "confidence": 0.8}

    async def slow(t, c):
        await asyncio.sleep(10.0)
        return {"answer": "ok", "confidence": 0.8}

    result = await engine.gather("q", {
        "fast": fast, "slow1": slow, "slow2": slow,
    })
    assert result.partial is True
    assert result.participating < 3


# ---------------------------------------------------------------------------
# 8. ConsensusProfiler via with_profiler()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_profiler_records():
    """Profiler records stats after each gather()."""
    engine = QuantumEngine(
        quorum=1,
        early_exit_conf=0.99,
        hard_timeout_ms=3000,
        similarity_fn=QuantumEngine._exact_sim,
    ).with_profiler()

    async def agent(t, c):
        return {"answer": "ok", "confidence": 0.8}

    await engine.gather("q1", {"a": agent})
    await engine.gather("q2", {"a": agent})

    assert engine.profiler is not None
    summary = engine.profiler.summary()
    assert summary["rounds"] == 2
    assert summary["avg_confidence"] > 0


# ---------------------------------------------------------------------------
# 9. contradictions_found > 0
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_contradictions_found_numerical():
    """Numerical disagreement counted as contradiction."""
    engine = QuantumEngine(
        quorum=2,
        early_exit_conf=0.99,
        hard_timeout_ms=3000,
        similarity_fn=QuantumEngine._exact_sim,
    )

    async def agent_100(t, c):
        return {"answer": "The value is 100", "confidence": 0.9}

    async def agent_200(t, c):
        return {"answer": "The value is 200", "confidence": 0.9}

    result = await engine.gather("q", {"a": agent_100, "b": agent_200})
    assert result.contradictions_found >= 1


@pytest.mark.asyncio
async def test_contradictions_found_negation():
    """Negation pair counted as contradiction."""
    engine = QuantumEngine(
        quorum=2,
        early_exit_conf=0.99,
        hard_timeout_ms=3000,
        similarity_fn=QuantumEngine._exact_sim,
    )

    async def yes_agent(t, c):
        return {"answer": "Yes, correct", "confidence": 0.9}

    async def no_agent(t, c):
        return {"answer": "No, incorrect", "confidence": 0.9}

    result = await engine.gather("q", {"a": yes_agent, "b": no_agent})
    assert result.contradictions_found >= 1


# ---------------------------------------------------------------------------
# 10. Embedding similarity (mocked)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_embedding_similarity_groups():
    """Mock embedding model groups semantically equivalent answers."""

    class FakeModel:
        def encode(self, texts, normalize_embeddings=True):
            vecs = []
            for t in texts:
                if "42" in t or "forty-two" in t:
                    v = np.array([0.9, 0.1, 0.0])
                elif "wrong" in t:
                    v = np.array([0.0, 0.1, 0.9])
                else:
                    v = np.array([0.5, 0.5, 0.0])
                norm = np.linalg.norm(v)
                vecs.append(v / norm if norm > 0 else v)
            return np.array(vecs)

    with patch(
        "core.quantum_engine._get_embed_model",
        return_value=FakeModel(),
    ):
        engine = QuantumEngine(
            quorum=3,
            early_exit_conf=0.99,
            hard_timeout_ms=3000,
        )

        async def agent_42(t, c):
            return {"answer": "The answer is 42", "confidence": 0.9}

        async def agent_42b(t, c):
            return {"answer": "forty-two is the answer", "confidence": 0.85}

        async def agent_wrong(t, c):
            return {"answer": "The wrong answer entirely", "confidence": 0.7}

        result = await engine.gather("q", {
            "a": agent_42, "b": agent_42b, "c": agent_wrong,
        })
        # The two "42" agents should be grouped together and win
        assert "42" in str(result.answer) or "forty-two" in str(result.answer)
        assert result.participating == 3


# ---------------------------------------------------------------------------
# Bonus: _is_contradiction heuristic
# ---------------------------------------------------------------------------

def test_is_contradiction_negation_pairs():
    engine = QuantumEngine()
    assert engine._is_contradiction("Yes definitely", "No way") is True
    assert engine._is_contradiction("True", "False") is True
    assert engine._is_contradiction("valid result", "invalid result") is True


def test_is_contradiction_numerical_divergence():
    engine = QuantumEngine()
    assert engine._is_contradiction("Value is 100", "Value is 200") is True
    assert engine._is_contradiction("Score: 50", "Score: 51") is False  # <20%


def test_is_contradiction_no_conflict():
    engine = QuantumEngine()
    assert engine._is_contradiction("hello", "hello") is False
    assert engine._is_contradiction("The answer is 42", "The answer is 42") is False


# ---------------------------------------------------------------------------
# Bonus: persistence via SemanticMemory
# ---------------------------------------------------------------------------

def test_reputation_persistence_save_load():
    """Reputation auto-saves every 10 updates and loads on init."""
    stored = {}

    class FakeTriple:
        def __init__(self, obj):
            self.object = obj

    class FakeSemantic:
        def assert_fact(self, **kwargs):
            stored["latest"] = kwargs["object"]

        def query(self, **kwargs):
            if "latest" in stored:
                return [FakeTriple(stored["latest"])]
            return []

    sm = FakeSemantic()
    rep = AgentReputation(persistence=sm)

    for i in range(10):
        rep.update(f"agent_{i}", correct=True, domain="general")

    assert "latest" in stored
    snap = json.loads(stored["latest"])
    assert len(snap) == 10

    rep2 = AgentReputation(persistence=sm)
    for key in snap:
        aid, dom = key.split("::", 1)
        assert abs(rep.weight(aid, dom) - rep2.weight(aid, dom)) < 1e-9


# ---------------------------------------------------------------------------
# Bonus: instance-level _round counter
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_round_counter_instance_level():
    """Each engine has its own round counter."""
    e1 = QuantumEngine(
        quorum=1, hard_timeout_ms=3000,
        similarity_fn=QuantumEngine._exact_sim,
    )
    e2 = QuantumEngine(
        quorum=1, hard_timeout_ms=3000,
        similarity_fn=QuantumEngine._exact_sim,
    )

    async def agent(t, c):
        return {"answer": "ok", "confidence": 0.9}

    await e1.gather("q", {"a": agent})
    await e1.gather("q", {"a": agent})
    await e2.gather("q", {"a": agent})

    assert e1._round == 2
    assert e2._round == 1  # Independent counter


# ---------------------------------------------------------------------------
# Bonus: ConsensusFailure when all agents crash
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_consensus_failure_all_agents_crash():
    engine = QuantumEngine(quorum=1, hard_timeout_ms=1000)

    async def crasher(t, c):
        raise RuntimeError("boom")

    with pytest.raises(ConsensusFailure):
        await engine.gather("q", {"a": crasher})
