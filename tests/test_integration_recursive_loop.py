"""Integration tests for the full recursive intelligence loop.

Wires together all 5 subsystems: MemorySystem, DeliberationEngine,
GoalPlanner, EvolutionEngine, MetacognitionEngine — using real
implementations against a temp SQLite database.
"""
from __future__ import annotations

import os
import struct
import tempfile
import unittest

from core._bus_fallback import EventBus
from core._database_fallback import DatabaseManager
from core.deliberation_engine import DeliberationEngine
from core.evolution import EvolutionEngine
from core.goal_planner import GoalPlanner, GoalStatus
from core.memory_system import MemorySystem
from core.metacognition import MetacognitionEngine


def _make_env(dim: int = 3, *values: float) -> bytes:
    """Pack float32 values into bytes for embedding storage."""
    return struct.pack(f"{dim}f", *values)


# Convenience embeddings (identical → cosine 1.0)
EMB_A = _make_env(3, 1.0, 0.0, 0.0)
EMB_B = _make_env(3, 1.0, 0.0, 0.0)  # identical to A
EMB_C = _make_env(3, 0.0, 1.0, 0.0)  # orthogonal to A


class _TempDBMixin:
    """Shared setUp / tearDown that provisions a temp DB + bus."""

    def setUp(self) -> None:
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.db_path = self._tmp.name
        self.db = DatabaseManager(db_path=self.db_path)
        self.db.initialize()
        self.bus = EventBus()

    def tearDown(self) -> None:
        self.db.close()
        try:
            os.unlink(self.db_path)
        except OSError:
            pass


# ======================================================================
# 1. End-to-End Loop
# ======================================================================


class TestRecursiveLoop(_TempDBMixin, unittest.TestCase):
    """Full recursive-loop integration across all 5 subsystems."""

    def setUp(self) -> None:
        super().setUp()
        self.mem = MemorySystem(db=self.db, bus=self.bus)
        self.delib = DeliberationEngine(bus=self.bus)
        self.planner = GoalPlanner(db=self.db, bus=self.bus)
        self.evo = EvolutionEngine(db=self.db, bus=self.bus)
        self.meta = MetacognitionEngine(db=self.db, bus=self.bus)

    def test_full_loop_interop(self):
        """Episode → knowledge → goal → deliberation → metacognition."""
        # 1. Record episode
        ep = self.mem.record_episode(
            session_id="s1",
            goal="solve quadratic",
            outcome="success",
            confidence_initial=0.6,
            confidence_final=0.9,
            models_used=["gpt-4"],
            reasoning_chain=["factor", "solve"],
            domain="math",
            embedding=EMB_A,
        )
        self.assertIn("id", ep)

        # 2. Add knowledge triple
        self.mem.add_knowledge("quadratic", "has_method", "factoring")
        triples = self.mem.query_knowledge(subject="quadratic")
        self.assertGreaterEqual(len(triples), 1)

        # 3. Create a goal
        goal = self.planner.create_goal(
            description="master algebra",
            domain="math",
        )
        self.assertEqual(goal.status, GoalStatus.PENDING)

        # 4. Deliberate
        result = self.delib.deliberate(
            prompt="best algebra method",
            perspectives=[
                {"perspective": "analytical", "content": "use factoring for simple quadratics", "model": "gpt-4"},
                {"perspective": "numerical", "content": "use numerical approximation for complex roots", "model": "gpt-4"},
            ],
        )
        self.assertIn("consensus", result)
        self.assertIn("hypotheses", result)

        # 5. Metacognition
        ece = self.meta.compute_ece(domain="math")
        self.assertIn("ece", ece)
        self.assertEqual(ece["total_episodes"], 1)

    def test_multiple_episodes_feed_dpo(self):
        """Multiple success/failure episodes produce DPO pairs."""
        # Record matching-embedding success + failure
        self.mem.record_episode(
            session_id="s1", goal="parse JSON", outcome="success",
            confidence_initial=0.5, confidence_final=0.9,
            models_used=["m1"], reasoning_chain=["try parse"],
            domain="code", embedding=EMB_A,
        )
        self.mem.record_episode(
            session_id="s2", goal="parse JSON strict", outcome="failure",
            confidence_initial=0.5, confidence_final=0.3,
            models_used=["m1"], reasoning_chain=["strict parse failed"],
            failure_reason="schema mismatch", domain="code", embedding=EMB_B,
        )

        pairs = self.evo.generate_dpo_pairs(domain="code", min_similarity=0.85)
        self.assertGreaterEqual(len(pairs), 1)
        self.assertGreater(pairs[0]["similarity"], 0.85)

    def test_goal_decompose_complete_evolution_signal(self):
        """Planner decomposes → subtasks complete → evolution extracts signal."""
        root = self.planner.create_goal(description="build API", domain="code")
        subs = self.planner.decompose(
            root.id, ["design schema", "implement endpoints"],
        )
        self.assertEqual(len(subs), 2)

        # Complete subtasks and record episodes per subtask
        for i, sub in enumerate(subs):
            self.planner.update_goal(sub.id, status=GoalStatus.COMPLETED)
            outcome = "success" if i == 0 else "failure"
            self.mem.record_episode(
                session_id=f"sub_{i}", goal=sub.description, outcome=outcome,
                confidence_initial=0.5, confidence_final=0.8 if outcome == "success" else 0.2,
                models_used=["m1"], reasoning_chain=[f"step_{i}"],
                domain="code", embedding=EMB_A,
            )

        # Evolution should see the episodes
        fitness = self.evo.compute_model_fitness(domain="code")
        self.assertIn("m1", fitness)
        self.assertGreater(fitness["m1"]["total_episodes"], 0)


# ======================================================================
# 2. Cross-System Bus Events
# ======================================================================


class TestBusIntegration(_TempDBMixin, unittest.TestCase):
    """Verify EventBus propagation across subsystems."""

    def setUp(self) -> None:
        super().setUp()
        self.mem = MemorySystem(db=self.db, bus=self.bus)
        self.received: list[dict] = []

    def test_episode_recorded_event(self):
        """Recording an episode publishes memory.episode.recorded."""
        self.bus.subscribe(
            "memory.episode.recorded",
            lambda data: self.received.append(data),
        )
        self.mem.record_episode(
            session_id="s1", goal="test", outcome="success",
            confidence_initial=0.5, confidence_final=0.9,
            models_used=["m1"], reasoning_chain=["step"],
        )
        self.assertEqual(len(self.received), 1)
        self.assertIn("episode_id", self.received[0])

    def test_store_and_link_emits_linked_event(self):
        """store_and_link publishes memory.linked with episode_id."""
        self.bus.subscribe(
            "memory.linked",
            lambda data: self.received.append(data),
        )
        result = self.mem.store_and_link(
            session_id="s1", goal="link test", outcome="success",
            confidence_initial=0.5, confidence_final=0.8,
            models_used=["m1"], reasoning_chain=["r"],
            knowledge_triples=[("A", "rel", "B")],
        )
        self.assertEqual(len(self.received), 1)
        self.assertIn("triples_added", self.received[0])
        self.assertEqual(self.received[0]["triples_added"], 1)
        self.assertEqual(result["triples_added"], 1)

    def test_multiple_subscribers_receive_event(self):
        """Two subscribers both receive the same published event."""
        box_a: list[dict] = []
        box_b: list[dict] = []
        self.bus.subscribe("memory.episode.recorded", lambda d: box_a.append(d))
        self.bus.subscribe("memory.episode.recorded", lambda d: box_b.append(d))

        self.mem.record_episode(
            session_id="s1", goal="multi", outcome="success",
            confidence_initial=0.5, confidence_final=0.7,
            models_used=["m1"], reasoning_chain=["x"],
        )
        self.assertEqual(len(box_a), 1)
        self.assertEqual(len(box_b), 1)
        self.assertEqual(box_a[0]["episode_id"], box_b[0]["episode_id"])

    def test_goal_created_event(self):
        """Goal creation publishes planner.goal.created."""
        self.bus.subscribe(
            "planner.goal.created",
            lambda data: self.received.append(data),
        )
        planner = GoalPlanner(db=self.db, bus=self.bus)
        planner.create_goal(description="bus goal", domain="general")
        self.assertEqual(len(self.received), 1)
        self.assertIn("goal", self.received[0])

    def test_triple_added_event(self):
        """Adding a semantic triple publishes memory.triple.added."""
        self.bus.subscribe(
            "memory.triple.added",
            lambda data: self.received.append(data),
        )
        self.mem.add_knowledge("X", "relates_to", "Y")
        self.assertEqual(len(self.received), 1)
        self.assertEqual(self.received[0]["subject"], "X")


# ======================================================================
# 3. Sandbox Simulation
# ======================================================================


class TestSandboxSimulation(_TempDBMixin, unittest.TestCase):
    """Simulate 10 cycles of the recursive intelligence loop."""

    def setUp(self) -> None:
        super().setUp()
        self.mem = MemorySystem(db=self.db, bus=self.bus)
        self.delib = DeliberationEngine(bus=self.bus)
        self.planner = GoalPlanner(db=self.db, bus=self.bus)
        self.evo = EvolutionEngine(db=self.db, bus=self.bus)
        self.meta = MetacognitionEngine(db=self.db, bus=self.bus)

    def _run_cycles(self, n: int = 10) -> None:
        """Run n cycles alternating success/failure."""
        for i in range(n):
            outcome = "success" if i % 2 == 0 else "failure"
            conf_final = 0.85 if outcome == "success" else 0.35
            emb = _make_env(3, 1.0, 0.1 * i, 0.0)

            self.mem.record_episode(
                session_id=f"cycle_{i}",
                goal=f"task_{i}",
                outcome=outcome,
                confidence_initial=0.5,
                confidence_final=conf_final,
                models_used=["alpha"],
                reasoning_chain=[f"step_{i}_a", f"step_{i}_b"],
                domain="general",
                embedding=emb,
                failure_reason="simulated" if outcome == "failure" else None,
            )

            self.mem.add_knowledge(
                f"entity_{i}", "observed_in", f"cycle_{i}",
            )

            goal = self.planner.create_goal(
                description=f"goal_cycle_{i}", domain="general",
            )
            self.planner.update_goal(
                goal.id,
                status=GoalStatus.COMPLETED if outcome == "success" else GoalStatus.FAILED,
            )

    def test_metacognition_after_cycles(self):
        """Metacognition reports reasonable calibration after 10 cycles."""
        self._run_cycles(10)
        ece = self.meta.compute_ece(domain="general")
        self.assertEqual(ece["total_episodes"], 10)
        self.assertIn(ece["calibration_quality"], ("excellent", "good", "fair", "poor"))
        self.assertGreaterEqual(ece["ece"], 0.0)
        self.assertLessEqual(ece["ece"], 1.0)

    def test_dpo_pairs_from_cycles(self):
        """Evolution extracts DPO pairs from accumulated episodes.

        We use identical embeddings for success/failure pairs to guarantee
        cosine similarity = 1.0 (above the 0.85 gate).
        """
        # Record 5 success + 5 failure with IDENTICAL embedding
        for i in range(10):
            outcome = "success" if i % 2 == 0 else "failure"
            self.mem.record_episode(
                session_id=f"dpo_{i}",
                goal=f"dpo_task_{i}",
                outcome=outcome,
                confidence_initial=0.5,
                confidence_final=0.8 if outcome == "success" else 0.2,
                models_used=["alpha"],
                reasoning_chain=[f"r_{i}"],
                domain="general",
                embedding=EMB_A,  # all identical → cosine 1.0
            )

        pairs = self.evo.generate_dpo_pairs(domain="general", min_similarity=0.85)
        # 5 successes × 5 failures = up to 25 pairs (all cosine 1.0)
        self.assertGreater(len(pairs), 0)
        for p in pairs:
            self.assertGreater(p["similarity"], 0.85)

    def test_goal_completion_tracking(self):
        """Goal completion rates are tracked after cycles."""
        self._run_cycles(10)
        completed = self.planner.list_goals(status=GoalStatus.COMPLETED, domain="general")
        failed = self.planner.list_goals(status=GoalStatus.FAILED, domain="general")
        # 5 success cycles → 5 completed, 5 failure → 5 failed
        self.assertEqual(len(completed), 5)
        self.assertEqual(len(failed), 5)

    def test_overconfidence_ratio(self):
        """Overconfidence ratio is computable after cycles."""
        self._run_cycles(10)
        oc = self.meta.compute_overconfidence_ratio(domain="general")
        self.assertIn("overconfident_count", oc)
        self.assertIn("total", oc)
        self.assertEqual(oc["total"], 10)

    def test_model_fitness(self):
        """Model fitness computed from cycle episodes."""
        self._run_cycles(10)
        fitness = self.evo.compute_model_fitness(domain="general")
        self.assertIn("alpha", fitness)
        self.assertEqual(fitness["alpha"]["total_episodes"], 10)
        self.assertAlmostEqual(fitness["alpha"]["success_rate"], 0.5)
        self.assertEqual(fitness["alpha"]["failures"], 5)


# ======================================================================
# 4. Data Integrity
# ======================================================================


class TestDataIntegrity(_TempDBMixin, unittest.TestCase):
    """Persistence across MemorySystem re-instantiation."""

    def test_episode_persists(self):
        """Episodes survive MemorySystem re-instantiation."""
        mem1 = MemorySystem(db=self.db, bus=self.bus)
        ep = mem1.record_episode(
            session_id="persist", goal="survive restart", outcome="success",
            confidence_initial=0.5, confidence_final=0.9,
            models_used=["m1"], reasoning_chain=["a"],
        )
        ep_id = ep["id"]

        # Re-instantiate with same DB
        mem2 = MemorySystem(db=self.db, bus=self.bus)
        found = mem2.episodic.get_episode(ep_id)
        self.assertIsNotNone(found)
        self.assertEqual(found["goal"], "survive restart")

    def test_semantic_triples_persist(self):
        """Semantic triples survive re-instantiation."""
        mem1 = MemorySystem(db=self.db, bus=self.bus)
        mem1.add_knowledge("cat", "is_a", "animal")

        mem2 = MemorySystem(db=self.db, bus=self.bus)
        triples = mem2.query_knowledge(subject="cat")
        self.assertGreaterEqual(len(triples), 1)
        obj_values = [t.get("object") for t in triples]
        self.assertIn("animal", obj_values)

    def test_working_memory_is_ephemeral(self):
        """Working memory does NOT survive re-instantiation."""
        mem1 = MemorySystem(db=self.db, bus=self.bus)
        mem1.cache_put("temp_key", "temp_value")
        self.assertEqual(mem1.cache_get("temp_key"), "temp_value")

        mem2 = MemorySystem(db=self.db, bus=self.bus)
        self.assertIsNone(mem2.cache_get("temp_key"))

    def test_goal_persists(self):
        """Goals survive planner re-instantiation."""
        p1 = GoalPlanner(db=self.db, bus=self.bus)
        goal = p1.create_goal(description="persist goal", domain="general")

        p2 = GoalPlanner(db=self.db, bus=self.bus)
        found = p2.get_goal(goal.id)
        self.assertIsNotNone(found)
        self.assertEqual(found.description, "persist goal")

    def test_episode_embedding_persists(self):
        """Embedding bytes round-trip through DB correctly."""
        mem1 = MemorySystem(db=self.db, bus=self.bus)
        ep = mem1.record_episode(
            session_id="emb", goal="emb test", outcome="success",
            confidence_initial=0.5, confidence_final=0.9,
            models_used=["m1"], reasoning_chain=["x"],
            embedding=EMB_A,
        )

        mem2 = MemorySystem(db=self.db, bus=self.bus)
        found = mem2.episodic.get_episode(ep["id"])
        self.assertIsNotNone(found)
        self.assertEqual(found["embedding"], EMB_A)


# ======================================================================
# 5. Error Resilience
# ======================================================================


class TestErrorResilience(_TempDBMixin, unittest.TestCase):
    """Graceful handling of edge cases."""

    def setUp(self) -> None:
        super().setUp()
        self.mem = MemorySystem(db=self.db, bus=self.bus)

    def test_episode_missing_optional_fields(self):
        """Recording episode without embedding or failure_reason succeeds."""
        ep = self.mem.record_episode(
            session_id="s1", goal="minimal", outcome="success",
            confidence_initial=0.5, confidence_final=0.8,
            models_used=["m1"], reasoning_chain=["step"],
        )
        self.assertIn("id", ep)
        self.assertIsNone(ep.get("embedding"))
        self.assertIsNone(ep.get("failure_reason"))

    def test_deliberation_empty_perspectives(self):
        """Deliberation with no perspectives returns valid result."""
        delib = DeliberationEngine(bus=self.bus)
        result = delib.deliberate(prompt="nothing", perspectives=[])
        self.assertIn("consensus", result)
        self.assertIn("hypotheses", result)
        self.assertIsInstance(result["hypotheses"], list)

    def test_metacognition_zero_episodes(self):
        """Metacognition with no episodes returns valid empty summary."""
        meta = MetacognitionEngine(db=self.db, bus=self.bus)
        ece = meta.compute_ece()
        self.assertEqual(ece["total_episodes"], 0)
        self.assertEqual(ece["ece"], 0.0)
        self.assertEqual(ece["calibration_quality"], "excellent")

    def test_evolution_no_pairs_when_no_episodes(self):
        """Evolution returns empty list when no episodes exist."""
        evo = EvolutionEngine(db=self.db, bus=self.bus)
        pairs = evo.generate_dpo_pairs()
        self.assertEqual(pairs, [])

    def test_goal_planner_get_nonexistent(self):
        """Getting a non-existent goal returns None."""
        planner = GoalPlanner(db=self.db, bus=self.bus)
        self.assertIsNone(planner.get_goal("nonexistent_id"))

    def test_evolution_orthogonal_embeddings_no_pairs(self):
        """Orthogonal embeddings (cosine ≈ 0) produce no DPO pairs."""
        self.mem.record_episode(
            session_id="s1", goal="ortho success", outcome="success",
            confidence_initial=0.5, confidence_final=0.9,
            models_used=["m1"], reasoning_chain=["a"],
            embedding=EMB_A,
        )
        self.mem.record_episode(
            session_id="s2", goal="ortho failure", outcome="failure",
            confidence_initial=0.5, confidence_final=0.2,
            models_used=["m1"], reasoning_chain=["b"],
            embedding=EMB_C,  # orthogonal to EMB_A
        )
        evo = EvolutionEngine(db=self.db, bus=self.bus)
        pairs = evo.generate_dpo_pairs(min_similarity=0.85)
        self.assertEqual(len(pairs), 0)

    def test_metacognition_report_no_crash(self):
        """Full metacognition report works even with zero data."""
        meta = MetacognitionEngine(db=self.db, bus=self.bus)
        report = meta.metacognition_report()
        self.assertIn("calibration", report)
        self.assertIn("overconfidence", report)
        self.assertIn("drift", report)

    def test_deliberation_single_perspective(self):
        """Deliberation with a single perspective still works."""
        delib = DeliberationEngine(bus=self.bus)
        result = delib.deliberate(
            prompt="solo",
            perspectives=[
                {"perspective": "only", "content": "the sole viewpoint", "model": "m1"},
            ],
        )
        self.assertEqual(len(result["hypotheses"]), 1)
        # No contradictions possible with one perspective
        self.assertEqual(len(result["contradictions"]), 0)


if __name__ == "__main__":
    unittest.main()
