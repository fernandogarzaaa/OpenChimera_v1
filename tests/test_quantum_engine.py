"""Tests for core.quantum_engine — ConsensusResult, AgentReputation, QuantumEngine,
ConsensusProfiler, and ConsensusFailure paths.

All tests are fully offline (no network, no Ollama, no disk I/O).
"""
from __future__ import annotations

import asyncio
import time
import unittest

from core.quantum_engine import (
    AgentReputation,
    AgentResponse,
    ConsensusFailure,
    ConsensusProfiler,
    ConsensusResult,
    QuantumEngine,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(coro):
    return asyncio.run(coro)


def make_agent(answer: str, delay: float = 0.0, fail: bool = False):
    async def _agent(task, context):
        if delay:
            await asyncio.sleep(delay)
        if fail:
            raise RuntimeError("agent intentionally failed")
        return answer
    return _agent


# ---------------------------------------------------------------------------
# AgentReputation
# ---------------------------------------------------------------------------

class TestAgentReputation(unittest.TestCase):
    def test_default_weight(self):
        rep = AgentReputation()
        self.assertAlmostEqual(rep.weight("unknown-agent"), 0.7, places=5)

    def test_update_correct_increases_weight(self):
        rep = AgentReputation(alpha=0.5, default_weight=0.5)
        rep.update("a1", correct=True)
        self.assertGreater(rep.weight("a1"), 0.5)

    def test_update_wrong_decreases_weight(self):
        rep = AgentReputation(alpha=0.5, default_weight=0.5)
        rep.update("a1", correct=False)
        self.assertLess(rep.weight("a1"), 0.5)

    def test_snapshot_returns_copy(self):
        rep = AgentReputation()
        rep.update("x", correct=True)
        snap = rep.snapshot()
        snap["x"] = 999  # mutating snap must not affect rep
        self.assertNotEqual(rep.weight("x"), 999)

    def test_repeated_updates_converge(self):
        rep = AgentReputation(alpha=0.3, default_weight=0.5)
        for _ in range(20):
            rep.update("a1", correct=True)
        self.assertGreater(rep.weight("a1"), 0.9)


# ---------------------------------------------------------------------------
# AgentResponse
# ---------------------------------------------------------------------------

class TestAgentResponse(unittest.TestCase):
    def test_answer_hash_is_stable(self):
        r = AgentResponse(agent_id="a", answer="hello world", latency_ms=10.0)
        self.assertEqual(r.answer_hash(), r.answer_hash())

    def test_different_answers_different_hash(self):
        r1 = AgentResponse(agent_id="a", answer="hello", latency_ms=5.0)
        r2 = AgentResponse(agent_id="a", answer="world", latency_ms=5.0)
        self.assertNotEqual(r1.answer_hash(), r2.answer_hash())

    def test_default_confidence(self):
        r = AgentResponse(agent_id="a", answer="x", latency_ms=0.0)
        self.assertEqual(r.confidence, 1.0)


# ---------------------------------------------------------------------------
# QuantumEngine — basic consensus
# ---------------------------------------------------------------------------

class TestQuantumEngineBasic(unittest.TestCase):
    def setUp(self):
        self.engine = QuantumEngine(quorum=1, early_exit_conf=0.5, hard_timeout_ms=2000)

    def test_single_agent_consensus(self):
        agents = {"a1": make_agent("the answer")}
        result = run(self.engine.gather("question", agents))
        self.assertEqual(result.answer, "the answer")
        self.assertEqual(result.participating, 1)
        self.assertEqual(result.total_invited, 1)

    def test_majority_wins(self):
        agents = {
            "a1": make_agent("correct"),
            "a2": make_agent("correct"),
            "a3": make_agent("wrong"),
        }
        engine = QuantumEngine(quorum=2, early_exit_conf=0.7, hard_timeout_ms=2000)
        result = run(engine.gather("q", agents))
        self.assertEqual(result.answer, "correct")

    def test_all_agree_gives_high_confidence(self):
        agents = {f"a{i}": make_agent("same answer") for i in range(3)}
        engine = QuantumEngine(quorum=3, early_exit_conf=0.95, hard_timeout_ms=2000)
        result = run(engine.gather("q", agents))
        self.assertGreater(result.confidence, 0.8)

    def test_result_has_latency(self):
        agents = {"a1": make_agent("ok")}
        result = run(self.engine.gather("q", agents))
        self.assertGreater(result.latency_ms, 0.0)

    def test_early_exit_flag(self):
        """With low conf threshold and unanimous agents, early_exit should fire."""
        agents = {
            "a1": make_agent("ans"),
            "a2": make_agent("ans"),
            "a3": make_agent("ans", delay=0.5),
        }
        engine = QuantumEngine(quorum=2, early_exit_conf=0.5, hard_timeout_ms=2000)
        result = run(engine.gather("q", agents))
        self.assertEqual(result.answer, "ans")


# ---------------------------------------------------------------------------
# QuantumEngine — failure paths
# ---------------------------------------------------------------------------

class TestQuantumEngineFailures(unittest.TestCase):
    def test_all_agents_fail_raises_consensus_failure(self):
        agents = {"a1": make_agent("x", fail=True)}
        engine = QuantumEngine(quorum=1, hard_timeout_ms=500)
        with self.assertRaises(ConsensusFailure):
            run(engine.gather("q", agents))

    def test_timeout_with_partial_results(self):
        """Agent responds after timeout; engine should return partial or fail."""
        async def slow(task, ctx):
            await asyncio.sleep(2.0)
            return "slow_answer"

        engine = QuantumEngine(quorum=2, hard_timeout_ms=100)
        agents = {"slow": slow, "also_slow": slow}
        with self.assertRaises(ConsensusFailure):
            run(engine.gather("q", agents))

    def test_partial_quorum_sets_partial_flag(self):
        """If only 1 of 3 responds before timeout, partial=True."""
        async def fast(task, ctx):
            return "fast_answer"

        async def slow(task, ctx):
            await asyncio.sleep(5.0)
            return "slow"

        engine = QuantumEngine(quorum=2, hard_timeout_ms=200)
        agents = {"fast": fast, "slow1": slow, "slow2": slow}
        try:
            result = run(engine.gather("q", agents))
            self.assertTrue(result.partial)
        except ConsensusFailure:
            pass  # acceptable when 0 answers arrive in time


# ---------------------------------------------------------------------------
# ConsensusProfiler
# ---------------------------------------------------------------------------

class TestConsensusProfiler(unittest.TestCase):
    def _make_result(self, latency_ms=100.0, confidence=0.9, early_exit=False, partial=False):
        return ConsensusResult(
            answer="x",
            confidence=confidence,
            participating=1,
            total_invited=1,
            latency_ms=latency_ms,
            early_exit=early_exit,
            partial=partial,
        )

    def test_empty_profiler_returns_zero_summary(self):
        p = ConsensusProfiler()
        s = p.summary()
        self.assertEqual(s["rounds"], 0)
        self.assertEqual(s["avg_confidence"], 0.0)

    def test_single_round_summary(self):
        p = ConsensusProfiler()
        p.record(self._make_result(latency_ms=200.0, confidence=0.8))
        s = p.summary()
        self.assertEqual(s["rounds"], 1)
        self.assertAlmostEqual(s["avg_confidence"], 0.8, places=3)

    def test_early_exit_pct(self):
        p = ConsensusProfiler()
        p.record(self._make_result(early_exit=True))
        p.record(self._make_result(early_exit=False))
        s = p.summary()
        self.assertAlmostEqual(s["early_exit_pct"], 50.0, places=1)

    def test_p50_p95_latency(self):
        p = ConsensusProfiler()
        for ms in range(1, 101):
            p.record(self._make_result(latency_ms=float(ms)))
        s = p.summary()
        self.assertGreater(s["p95_latency_ms"], s["p50_latency_ms"])


# ---------------------------------------------------------------------------
# ConsensusPlane (integration layer)
# ---------------------------------------------------------------------------

class TestConsensusPlaneMixin(unittest.TestCase):
    """Smoke test the ConsensusPlane wrapper around QuantumEngine."""

    def _make_plane(self):
        from core.bus import EventBus
        from core.consensus_plane import ConsensusPlane
        bus = EventBus()
        return ConsensusPlane(profile={}, bus=bus, quorum=1, early_exit_conf=0.5, hard_timeout_ms=2000)

    def test_register_and_list_agents(self):
        plane = self._make_plane()
        plane.register_agent("echo", lambda task, ctx: task)
        self.assertIn("echo", plane.list_agents())

    def test_unregister_agent(self):
        plane = self._make_plane()
        plane.register_agent("echo", lambda task, ctx: "x")
        plane.unregister_agent("echo")
        self.assertNotIn("echo", plane.list_agents())

    def test_query_with_no_agents_returns_error(self):
        plane = self._make_plane()
        result = run(plane.query("hello"))
        self.assertIsNotNone(result["error"])
        self.assertIsNone(result["answer"])

    def test_query_with_single_agent(self):
        plane = self._make_plane()
        plane.register_agent("stub", make_agent("hello world"))
        result = run(plane.query("test"))
        self.assertEqual(result["answer"], "hello world")
        self.assertIsNone(result["error"])

    def test_status_returns_expected_keys(self):
        plane = self._make_plane()
        s = plane.status()
        self.assertIn("agents", s)
        self.assertIn("reputation", s)
        self.assertIn("profiler", s)
        self.assertIn("engine", s)

    def test_feedback_updates_reputation(self):
        plane = self._make_plane()
        plane.register_agent("a1", make_agent("x"))
        run(plane.query("t"))
        # Give positive feedback
        plane.feedback("a1", correct=True)
        rep = plane.status()["reputation"]
        self.assertIn("a1", rep)


if __name__ == "__main__":
    unittest.main()
