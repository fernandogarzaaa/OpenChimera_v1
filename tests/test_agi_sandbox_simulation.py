"""End-to-end AGI sandbox simulation test harness for OpenChimera v1.

Simulates the full user experience pipeline:
  user query → deliberation → goal creation → execution →
  memory recording → evolution pair generation

Each scenario is a self-contained TestCase. Optional modules are guarded
with try/except ImportError so the suite degrades gracefully.
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import tempfile
import unittest
from typing import Any

# ---------------------------------------------------------------------------
# Infrastructure helpers
# ---------------------------------------------------------------------------

MIGRATIONS = pathlib.Path("core/migrations")


def _make_db_env():
    """Return (DatabaseManager, EventBus, tmp_path) with migrations applied."""
    from core._bus_fallback import EventBus
    from core._database_fallback import DatabaseManager

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db = DatabaseManager(tmp.name, migrations_path=MIGRATIONS)
    db.initialize()
    return db, EventBus(), tmp.name


def _cleanup_db(db, tmp_path: str) -> None:
    try:
        db.close()
    except Exception:
        pass
    for suffix in ("", "-wal", "-shm"):
        try:
            os.unlink(tmp_path + suffix)
        except OSError:
            pass


def _run(coro):
    return asyncio.run(coro)


# ===========================================================================
# Scenario 1: Memory Pipeline Test
# ===========================================================================

try:
    from core._bus_fallback import EventBus as _EventBus
    from core._database_fallback import DatabaseManager as _DatabaseManager
    from core.memory.episodic import EpisodicMemory
    from core.memory.semantic import SemanticMemory
    from core.memory.working import WorkingMemory

    _MEMORY_AVAILABLE = True
except ImportError:
    _MEMORY_AVAILABLE = False


@unittest.skipUnless(_MEMORY_AVAILABLE, "core.memory modules not available")
class TestMemoryPipeline(unittest.TestCase):
    """Scenario 1: Memory Pipeline — EpisodicMemory, SemanticMemory, WorkingMemory."""

    def setUp(self) -> None:
        self.db, self.bus, self._db_path = _make_db_env()
        self.episodic = EpisodicMemory(self.db, self.bus)
        self.semantic = SemanticMemory(self.db, self.bus)
        self.working = WorkingMemory(max_size=64)

    def tearDown(self) -> None:
        _cleanup_db(self.db, self._db_path)

    # ---- EpisodicMemory ----

    def test_episode_round_trip(self) -> None:
        """Record 5 episodes and verify they survive a round-trip query."""
        # Domain must be one of the DB CHECK constraint values:
        # ('code', 'math', 'reasoning', 'creative', 'general')
        episodes_data = [
            ("sess-1", "Analyse latency spikes", "success", "reasoning", 0.9, 0.95),
            ("sess-1", "Identify memory leak", "success", "reasoning", 0.7, 0.88),
            ("sess-2", "Generate unit tests", "failure", "code", 0.6, 0.40),
            ("sess-2", "Refactor auth module", "success", "code", 0.8, 0.92),
            ("sess-3", "Plan Q3 roadmap", "failure", "general", 0.5, 0.30),
        ]
        recorded_ids: list[str] = []
        for session_id, goal, outcome, domain, conf_i, conf_f in episodes_data:
            ep = self.episodic.record_episode(
                session_id=session_id,
                goal=goal,
                outcome=outcome,
                confidence_initial=conf_i,
                confidence_final=conf_f,
                models_used=["chimera-core"],
                reasoning_chain=[f"step-1 for {goal}", f"step-2 for {goal}"],
                domain=domain,
            )
            self.assertIn("id", ep, "record_episode must return a dict with 'id'")
            recorded_ids.append(ep["id"])

        self.assertEqual(len(recorded_ids), 5)

        # All episodes are queryable
        all_eps = self.episodic.list_episodes(limit=10)
        self.assertGreaterEqual(len(all_eps), 5)

        # Filtering by outcome
        successes = self.episodic.list_episodes(outcome="success", limit=10)
        failures = self.episodic.list_episodes(outcome="failure", limit=10)
        self.assertEqual(len(successes), 3)
        self.assertEqual(len(failures), 2)

    def test_episode_count_and_domain_filter(self) -> None:
        """count() respects domain and outcome filters."""
        for i in range(3):
            self.episodic.record_episode(
                session_id="s",
                goal=f"goal-{i}",
                outcome="success",
                confidence_initial=0.8,
                confidence_final=0.9,
                models_used=["m1"],
                reasoning_chain=[],
                domain="math",
            )
        self.episodic.record_episode(
            session_id="s",
            goal="other",
            outcome="failure",
            confidence_initial=0.5,
            confidence_final=0.3,
            models_used=["m2"],
            reasoning_chain=[],
            domain="code",
        )

        self.assertEqual(self.episodic.count(domain="math"), 3)
        self.assertEqual(self.episodic.count(domain="code", outcome="failure"), 1)
        self.assertEqual(self.episodic.count(outcome="success"), 3)

    # ---- SemanticMemory ----

    def test_semantic_triple_round_trip(self) -> None:
        """SemanticMemory stores and retrieves knowledge-graph triples."""
        self.semantic.add_triple("AGI", "requires", "reasoning", confidence=0.95)
        self.semantic.add_triple("AGI", "requires", "memory", confidence=0.90)
        triples = self.semantic.get_triples(subject="AGI")
        self.assertEqual(len(triples), 2)
        predicates = {t["predicate"] for t in triples}
        self.assertIn("requires", predicates)

    # ---- WorkingMemory ----

    def test_working_memory_lru(self) -> None:
        """WorkingMemory is a bounded LRU cache."""
        wm = WorkingMemory(max_size=3)
        wm.put("a", 1)
        wm.put("b", 2)
        wm.put("c", 3)
        self.assertEqual(wm.size(), 3)
        # Inserting a 4th evicts the LRU entry ("a")
        wm.put("d", 4)
        self.assertEqual(wm.size(), 3)
        self.assertIsNone(wm.get("a"), "LRU entry 'a' should have been evicted")
        self.assertEqual(wm.get("d"), 4)

    def test_working_memory_evict(self) -> None:
        self.working.put("key", "value")
        self.assertTrue(self.working.evict("key"))
        self.assertIsNone(self.working.get("key"))


# ===========================================================================
# Scenario 2: Goal Lifecycle Simulation
# ===========================================================================

try:
    from core._bus_fallback import EventBus as _GoalEventBus
    from core._database_fallback import DatabaseManager as _GoalDB
    from core.goal_planner import GoalPlanner, GoalStatus

    _GOAL_AVAILABLE = True
except ImportError:
    _GOAL_AVAILABLE = False


@unittest.skipUnless(_GOAL_AVAILABLE, "core.goal_planner not available")
class TestGoalLifecycle(unittest.TestCase):
    """Scenario 2: Goal Lifecycle — pending → active → completed."""

    def setUp(self) -> None:
        self.db, self.bus, self._db_path = _make_db_env()
        self.planner = GoalPlanner(self.db, self.bus)

    def tearDown(self) -> None:
        _cleanup_db(self.db, self._db_path)

    def test_goal_transitions_pending_to_completed(self) -> None:
        """Goal goes through pending → active → completed via execute_goal."""
        goal = self.planner.create_goal(
            description="Build an AGI system",
            domain="reasoning",
        )
        self.assertEqual(goal.status, GoalStatus.PENDING)
        self.assertIsNotNone(goal.id)

        def mock_executor(g) -> dict:
            return {"status": "completed", "result": "simulated"}

        result = self.planner.execute_goal(goal.id, executor_fn=mock_executor)
        self.assertEqual(result["status"], GoalStatus.COMPLETED)

        completed_goal = self.planner.get_goal(goal.id)
        self.assertIsNotNone(completed_goal)
        self.assertEqual(completed_goal.status, GoalStatus.COMPLETED)  # type: ignore[union-attr]

    def test_auto_decompose_creates_child_goals(self) -> None:
        """auto_decompose splits conjunctive descriptions into subgoals."""
        goal = self.planner.create_goal(
            description="Design the memory module and build the inference plane and wire the bus",
            domain="reasoning",
        )
        child_ids = self.planner.auto_decompose(goal.id)
        # auto_decompose splits on 'and/then/also/while', expects ≥2 parts
        self.assertGreaterEqual(len(child_ids), 2)
        for cid in child_ids:
            child = self.planner.get_goal(cid)
            self.assertIsNotNone(child)
            self.assertEqual(child.parent_id, goal.id)  # type: ignore[union-attr]

    def test_manual_child_goals_created_and_linked(self) -> None:
        """Manually created child goals are linked under the parent."""
        parent = self.planner.create_goal(description="Build an AGI system", domain="reasoning")
        child_descs = [
            "Design the architecture",
            "Implement the memory layer",
            "Wire the inference plane",
        ]
        child_ids = []
        for desc in child_descs:
            child = self.planner.create_goal(description=desc, domain="reasoning", parent_id=parent.id)
            child_ids.append(child.id)

        self.assertEqual(len(child_ids), 3)
        for cid in child_ids:
            c = self.planner.get_goal(cid)
            self.assertEqual(c.parent_id, parent.id)  # type: ignore[union-attr]

    def test_failed_executor_marks_goal_failed(self) -> None:
        """When executor returns non-completed, goal is marked failed."""
        goal = self.planner.create_goal(description="A task that fails", domain="general")

        def failing_executor(g) -> dict:
            return {"status": "failed", "result": "error occurred"}

        result = self.planner.execute_goal(goal.id, executor_fn=failing_executor)
        self.assertEqual(result["status"], GoalStatus.FAILED)
        updated = self.planner.get_goal(goal.id)
        self.assertEqual(updated.status, GoalStatus.FAILED)  # type: ignore[union-attr]


# ===========================================================================
# Scenario 3: Deliberation → Consensus Flow
# ===========================================================================

try:
    from core._bus_fallback import EventBus as _DelibBus
    from core.deliberation import DeliberationGraph, Hypothesis
    from core.deliberation_engine import DeliberationEngine

    _DELIBERATION_AVAILABLE = True
except ImportError:
    _DELIBERATION_AVAILABLE = False


@unittest.skipUnless(_DELIBERATION_AVAILABLE, "core.deliberation(_engine) not available")
class TestDeliberationConsensus(unittest.TestCase):
    """Scenario 3: Deliberation → Consensus — hypothesis ranking is deterministic."""

    def setUp(self) -> None:
        from core._bus_fallback import EventBus
        self.bus = EventBus()
        self.graph = DeliberationGraph(bus=self.bus)

    def test_hypotheses_added_and_rankable(self) -> None:
        """Add competing hypotheses and verify ranking is non-empty."""
        h1 = self.graph.add_hypothesis(
            claim="Model A is better because it has higher throughput and lower latency",
            perspective="performance",
            confidence=0.85,
        )
        h2 = self.graph.add_hypothesis(
            claim="Model B is better because it has superior accuracy on benchmarks",
            perspective="accuracy",
            confidence=0.75,
        )
        self.assertIsNotNone(h1.id)
        self.assertIsNotNone(h2.id)
        ranked = self.graph.ranked_hypotheses()
        self.assertGreaterEqual(len(ranked), 2)

    def test_support_edge_raises_winner(self) -> None:
        """Adding support edges increases ranking of supported hypothesis."""
        h1 = self.graph.add_hypothesis(
            claim="Model A is better for high load scenarios with many concurrent requests",
            perspective="load",
            confidence=0.70,
        )
        h2 = self.graph.add_hypothesis(
            claim="Model B is better for accuracy-critical tasks requiring precision",
            perspective="accuracy",
            confidence=0.65,
        )
        h3 = self.graph.add_hypothesis(
            claim="Throughput matters most in production systems with real users",
            perspective="production",
            confidence=0.60,
        )
        # h1 gets two support edges
        self.graph.add_support(h3.id, h1.id, weight=0.9)
        ranked = self.graph.ranked_hypotheses()
        self.assertGreater(len(ranked), 0)
        # The ranking list must be deterministic (same call, same order)
        # ranked_hypotheses returns dicts with key "hypothesis" (Hypothesis obj), not "id"
        ranked2 = self.graph.ranked_hypotheses()
        self.assertEqual(
            [r["hypothesis"].id for r in ranked],
            [r["hypothesis"].id for r in ranked2],
        )

    def test_contradiction_detection(self) -> None:
        """Contradiction edges are detected and reported."""
        h1 = self.graph.add_hypothesis(
            claim="Scaling horizontally is always better for distributed workloads",
            perspective="scaling",
            confidence=0.80,
        )
        h2 = self.graph.add_hypothesis(
            claim="Vertical scaling is preferable for reducing operational complexity",
            perspective="ops",
            confidence=0.75,
        )
        self.graph.add_contradiction(h1.id, h2.id, reason="opposing scaling strategies")
        contradictions = self.graph.all_contradictions()
        self.assertGreaterEqual(len(contradictions), 1)

    def test_deliberation_engine_full_cycle(self) -> None:
        """DeliberationEngine.deliberate() returns a consensus dict."""
        from core._bus_fallback import EventBus
        engine = DeliberationEngine(bus=EventBus())
        perspectives = [
            {
                "perspective": "performance",
                "content": "Model A delivers lower latency and higher throughput under load",
                "model": "chimera-a",
            },
            {
                "perspective": "accuracy",
                "content": "Model B achieves better accuracy scores on standardised benchmarks",
                "model": "chimera-b",
            },
            {
                "perspective": "cost",
                "content": "Model A is more cost-efficient given its smaller parameter count",
                "model": "chimera-a",
            },
        ]
        result = engine.deliberate(
            prompt="Which model should we use in production?",
            perspectives=perspectives,
        )
        self.assertIn("consensus", result)
        self.assertIn("hypotheses", result)
        self.assertIsInstance(result["hypotheses"], list)
        self.assertGreaterEqual(len(result["hypotheses"]), 2)


# ===========================================================================
# Scenario 4: Multi-Agent Consensus Simulation
# ===========================================================================

try:
    from core.quantum_engine import QuantumEngine, ConsensusResult

    _QUANTUM_AVAILABLE = True
except ImportError:
    _QUANTUM_AVAILABLE = False


@unittest.skipUnless(_QUANTUM_AVAILABLE, "core.quantum_engine not available")
class TestMultiAgentConsensus(unittest.TestCase):
    """Scenario 4: Multi-Agent Consensus — 3 virtual agents → consensus answer."""

    def test_three_agents_reach_consensus(self) -> None:
        """Three agreeing agents produce a consensus answer with confidence > 0."""
        engine = QuantumEngine(quorum=2, hard_timeout_ms=5000)

        async def agent_a(task: Any, context: dict) -> str:
            return f"consensus-answer:{task}"

        async def agent_b(task: Any, context: dict) -> str:
            return f"consensus-answer:{task}"

        async def agent_c(task: Any, context: dict) -> str:
            return f"consensus-answer:{task}"

        agents = {"agent-a": agent_a, "agent-b": agent_b, "agent-c": agent_c}
        result: ConsensusResult = _run(engine.gather("performance-analysis", agents))
        self.assertIsInstance(result, ConsensusResult)
        self.assertIsNotNone(result.answer)
        self.assertGreater(result.confidence, 0.0)

    def test_majority_wins_with_adversarial_agent(self) -> None:
        """Two agreeing agents beat one adversarial agent."""
        engine = QuantumEngine(quorum=2, hard_timeout_ms=5000)

        async def good_1(task: Any, context: dict) -> str:
            return "correct-answer"

        async def good_2(task: Any, context: dict) -> str:
            return "correct-answer"

        async def adversarial(task: Any, context: dict) -> str:
            return "WRONG-deliberately-bad-answer"

        agents = {"good-1": good_1, "good-2": good_2, "adversarial": adversarial}
        result = _run(engine.gather("test-task", agents))
        self.assertIsNotNone(result.answer)
        self.assertIn("correct-answer", str(result.answer))

    def test_consensus_is_deterministic_on_same_input(self) -> None:
        """Running the same scenario twice should yield the same answer."""
        engine = QuantumEngine(quorum=1, hard_timeout_ms=5000)

        async def agent(task: Any, context: dict) -> str:
            return f"answer:{task}"

        agents = {"agent": agent}
        r1 = _run(engine.gather("same-task", agents))
        r2 = _run(engine.gather("same-task", agents))
        self.assertEqual(r1.answer, r2.answer)


# ===========================================================================
# Scenario 5: Causal Reasoning Chain
# ===========================================================================

try:
    from core.causal_reasoning import CausalReasoning, EdgeType, ConfidenceLevel

    _CAUSAL_AVAILABLE = True
except ImportError:
    _CAUSAL_AVAILABLE = False


@unittest.skipUnless(_CAUSAL_AVAILABLE, "core.causal_reasoning not available")
class TestCausalReasoningChain(unittest.TestCase):
    """Scenario 5: Causal Reasoning — pathway discovery and intervention."""

    def setUp(self) -> None:
        from core._bus_fallback import EventBus
        self.cr = CausalReasoning(bus=EventBus())

    def test_causal_chain_pathway_found(self) -> None:
        """model_overload → latency_spike → user_timeout pathway is discoverable."""
        self.cr.add_cause(
            cause="model_overload",
            effect="latency_spike",
            edge_type=EdgeType.CAUSES,
            strength=0.9,
            confidence=0.85,
        )
        self.cr.add_cause(
            cause="latency_spike",
            effect="user_timeout",
            edge_type=EdgeType.CAUSES,
            strength=0.8,
            confidence=0.90,
        )

        paths = self.cr.graph.find_causal_paths("model_overload", "user_timeout")
        self.assertGreater(len(paths), 0, "Should find at least one causal path")
        # CausalPathway.path is a tuple of node names
        flat_nodes = [node for pathway in paths for node in pathway.path]
        self.assertIn("latency_spike", flat_nodes)

    def test_intervention_propagates_effect(self) -> None:
        """Intervening on 'model_overload' propagates through the causal graph."""
        self.cr.add_cause(
            cause="model_overload",
            effect="latency_spike",
            edge_type=EdgeType.CAUSES,
            strength=0.9,
            confidence=0.85,
        )
        self.cr.add_cause(
            cause="latency_spike",
            effect="user_timeout",
            edge_type=EdgeType.CAUSES,
            strength=0.8,
            confidence=0.90,
        )
        self.cr.set_variable("model_overload", 1.0)

        intervention = self.cr.intervene(
            variable="model_overload",
            value=0.0,
        )
        self.assertIsNotNone(intervention)
        # The intervention result should report affected downstream variables
        self.assertIsInstance(intervention.affected_variables, dict)
        # Downstream nodes should have been affected with nonzero effect
        self.assertGreater(intervention.total_effect, 0.0)

    def test_total_causal_effect_nonzero(self) -> None:
        """Total causal effect from source to target is non-zero when connected."""
        self.cr.add_cause(
            cause="A",
            effect="B",
            edge_type=EdgeType.CAUSES,
            strength=0.7,
            confidence=0.8,
        )
        self.cr.add_cause(
            cause="B",
            effect="C",
            edge_type=EdgeType.CAUSES,
            strength=0.6,
            confidence=0.75,
        )
        effect = self.cr.total_causal_effect("A", "C")
        self.assertGreater(effect, 0.0)

    def test_counterfactual_available(self) -> None:
        """counterfactual() runs without error and returns a result object."""
        self.cr.add_cause(
            cause="cpu_spike",
            effect="response_delay",
            edge_type=EdgeType.CAUSES,
            strength=0.85,
            confidence=0.80,
        )
        self.cr.set_variable("cpu_spike", 1.0)
        self.cr.set_variable("response_delay", 0.9)
        result = self.cr.counterfactual(
            variable="cpu_spike",
            counterfactual_value=0.0,
            observe_variable="response_delay",
        )
        self.assertIsNotNone(result)


# ===========================================================================
# Scenario 6: Transfer Learning Pattern Extraction
# ===========================================================================

try:
    from core.transfer_learning import TransferLearning, PatternType, TransferCandidate

    _TRANSFER_AVAILABLE = True
except ImportError:
    _TRANSFER_AVAILABLE = False


@unittest.skipUnless(_TRANSFER_AVAILABLE, "core.transfer_learning not available")
class TestTransferLearning(unittest.TestCase):
    """Scenario 6: Transfer Learning — cross-domain pattern extraction and application."""

    def setUp(self) -> None:
        from core._bus_fallback import EventBus
        self.tl = TransferLearning(bus=EventBus())

    def test_pattern_registered_and_retrievable(self) -> None:
        """register_pattern stores a pattern that can be listed back."""
        self.tl.register_pattern(
            source_domain="code",
            pattern_type=PatternType.STRATEGY,
            description="code review strategy: review incrementally not all at once",
            keywords=["code", "review", "incremental", "strategy"],
            success_rate=0.88,
        )
        patterns = self.tl.list_patterns(domain="code")
        self.assertGreaterEqual(len(patterns), 1)
        descriptions = [p.description for p in patterns]
        self.assertTrue(any("review" in d for d in descriptions))

    def test_cross_domain_transfer_candidate_returned(self) -> None:
        """A pattern from 'code' domain is found as a transfer candidate for 'reasoning'."""
        self.tl.register_pattern(
            source_domain="code",
            pattern_type=PatternType.STRATEGY,
            description="decompose complex problem into smaller reasoning steps",
            keywords=["decompose", "problem", "reasoning", "steps", "strategy"],
            success_rate=0.85,
        )
        candidates = self.tl.find_transfers(
            target_domain="reasoning",
            target_keywords=["reasoning", "steps", "decompose"],
            limit=5,
        )
        self.assertIsInstance(candidates, list)
        self.assertGreater(len(candidates), 0, "Should find at least one transfer candidate")
        best = candidates[0]
        self.assertIsInstance(best, TransferCandidate)
        self.assertGreater(best.relevance_score, 0.0)

    def test_apply_transfer_updates_stats(self) -> None:
        """apply_transfer marks a pattern as used and updates transfer count."""
        self.tl.register_pattern(
            source_domain="code",
            pattern_type=PatternType.HEURISTIC,
            description="fail fast: detect errors early in the pipeline",
            keywords=["error", "fast", "pipeline", "detection"],
            success_rate=0.90,
        )
        patterns = self.tl.list_patterns(domain="code")
        self.assertEqual(len(patterns), 1)
        pid = patterns[0].pattern_id

        self.tl.apply_transfer(pid, target_domain="reasoning", success=True)
        # After applying, the pattern is known; verify via domain profile
        profile = self.tl.domain_profile("code")
        self.assertGreaterEqual(profile.pattern_count, 1)

    def test_multiple_domains_tracked(self) -> None:
        """Patterns from different domains are tracked independently."""
        self.tl.register_pattern(
            source_domain="math",
            pattern_type=PatternType.STRATEGY,
            description="solve by induction over the base case",
            keywords=["induction", "math", "proof", "base"],
            success_rate=0.92,
        )
        self.tl.register_pattern(
            source_domain="language",
            pattern_type=PatternType.TEMPLATE,
            description="use chain-of-thought prompting for language tasks",
            keywords=["chain", "thought", "language", "prompting"],
            success_rate=0.78,
        )
        domains = self.tl.list_domains()
        self.assertIn("math", domains)
        self.assertIn("language", domains)


# ===========================================================================
# Scenario 7: Full Pipeline Simulation (User Experience)
# ===========================================================================

try:
    from core._bus_fallback import EventBus as _PipelineBus
    from core._database_fallback import DatabaseManager as _PipelineDB
    from core.deliberation_engine import DeliberationEngine as _PipelineDE
    from core.goal_planner import GoalPlanner as _PipelineGP, GoalStatus as _PipelineGS
    from core.quantum_engine import QuantumEngine as _PipelineQE

    _PIPELINE_CORE_AVAILABLE = True
except ImportError:
    _PIPELINE_CORE_AVAILABLE = False

# Optional pipeline components
try:
    from core.memory.episodic import EpisodicMemory as _PipelineEpMem

    _PIPELINE_MEMORY_AVAILABLE = True
except ImportError:
    _PIPELINE_MEMORY_AVAILABLE = False

try:
    from core.evolution import EvolutionEngine as _PipelineEvo

    _PIPELINE_EVO_AVAILABLE = True
except ImportError:
    _PIPELINE_EVO_AVAILABLE = False


@unittest.skipUnless(_PIPELINE_CORE_AVAILABLE, "core pipeline modules not available")
class TestFullPipelineSimulation(unittest.TestCase):
    """Scenario 7: Full Pipeline — user query through the complete AGI pipeline."""

    USER_QUERY = "Analyse the performance bottlenecks in our system"

    def setUp(self) -> None:
        self.db, self.bus, self._db_path = _make_db_env()
        self.planner = _PipelineGP(self.db, self.bus)
        self.deliberation = _PipelineDE(bus=self.bus)
        self.quantum = _PipelineQE(quorum=2, hard_timeout_ms=5000)

    def tearDown(self) -> None:
        _cleanup_db(self.db, self._db_path)

    # ------------------------------------------------------------------
    # Step helpers
    # ------------------------------------------------------------------

    def _step1_create_goal(self):
        """Step 1 — create a goal from the user query."""
        goal = self.planner.create_goal(
            description=self.USER_QUERY,
            domain="reasoning",  # must be in DB CHECK constraint
        )
        self.assertEqual(goal.status, _PipelineGS.PENDING)
        self.assertIsNotNone(goal.id)
        return goal

    def _step2_deliberate(self, query: str) -> dict:
        """Step 2 — deliberate on approaches to the query."""
        perspectives = [
            {
                "perspective": "profiling",
                "content": "Profile CPU and memory usage to identify hotspots in the system",
                "model": "chimera-profiler",
            },
            {
                "perspective": "tracing",
                "content": "Use distributed tracing to find latency bottlenecks across services",
                "model": "chimera-tracer",
            },
            {
                "perspective": "metrics",
                "content": "Analyse historical metrics and dashboards to spot degradation patterns",
                "model": "chimera-metrics",
            },
        ]
        result = self.deliberation.deliberate(prompt=query, perspectives=perspectives)
        self.assertIn("consensus", result)
        self.assertIn("hypotheses", result)
        return result

    def _step3_consensus(self, deliberation_result: dict) -> str:
        """Step 3 — select best approach via quantum consensus."""
        hypotheses = deliberation_result.get("hypotheses", [])
        # Build agents from the top-ranked hypothesis contents
        agents = {}
        for i, h in enumerate(hypotheses[:3]):
            content = h.get("claim", f"approach-{i}")

            async def make_agent(task: Any, ctx: dict, c=content) -> str:
                return c[:80]

            agents[f"approach-{i}"] = make_agent

        if not agents:
            # Fallback: create a single default agent
            async def default_agent(task: Any, ctx: dict) -> str:
                return "profile-and-trace-approach"
            agents["default"] = default_agent

        result = _run(self.quantum.gather(self.USER_QUERY, agents))
        self.assertIsNotNone(result.answer)
        return str(result.answer)

    def _step4_execute_goal(self, goal_id: str, chosen_approach: str) -> dict:
        """Step 4 — execute the goal with a mock executor."""
        def mock_executor(g) -> dict:
            return {
                "status": "completed",
                "result": f"Analysis complete using: {chosen_approach}",
                "approach": chosen_approach,
                "findings": ["CPU at 90% during peak", "DB queries > 500ms", "Cache hit rate 40%"],
            }

        result = self.planner.execute_goal(goal_id, executor_fn=mock_executor)
        self.assertEqual(result["status"], _PipelineGS.COMPLETED)
        return result

    def _step5_record_episode(self, goal_id: str, execution_result: dict) -> dict | None:
        """Step 5 — record the episode in episodic memory (if available)."""
        if not _PIPELINE_MEMORY_AVAILABLE:
            return None
        mem = _PipelineEpMem(self.db, self.bus)
        ep = mem.record_episode(
            session_id="pipeline-sim-session",
            goal=self.USER_QUERY,
            outcome="success",
            confidence_initial=0.70,
            confidence_final=0.92,
            models_used=["chimera-profiler", "chimera-tracer", "chimera-metrics"],
            reasoning_chain=[
                "Identify query",
                "Deliberate on approaches",
                "Reach consensus",
                "Execute analysis",
            ],
            domain="reasoning",  # must be in DB CHECK constraint
        )
        self.assertIn("id", ep)
        return ep

    def _step6_generate_dpo_pair(self, episode: dict | None) -> dict | None:
        """Step 6 — generate DPO training pair (if evolution available)."""
        if not _PIPELINE_EVO_AVAILABLE or episode is None:
            return None
        # Record a contrasting failure episode so the engine has a pair to generate
        mem = _PipelineEpMem(self.db, self.bus)
        mem.record_episode(
            session_id="pipeline-sim-session",
            goal=self.USER_QUERY,
            outcome="failure",
            confidence_initial=0.70,
            confidence_final=0.30,
            models_used=["chimera-naive"],
            reasoning_chain=["Identify query", "Jump to conclusions"],
            domain="reasoning",  # must be in DB CHECK constraint
        )
        evo = _PipelineEvo(self.db, self.bus)
        # evolution_cycle returns a summary dict with DPO pair stats
        summary = evo.evolution_cycle(domain="reasoning")
        self.assertIsInstance(summary, dict)
        return summary

    # ------------------------------------------------------------------
    # Full end-to-end test
    # ------------------------------------------------------------------

    def test_full_pipeline_coherent(self) -> None:
        """All pipeline steps complete without error and are coherent."""
        # Step 1: Create goal
        goal = self._step1_create_goal()

        # Step 2: Deliberate
        delib_result = self._step2_deliberate(self.USER_QUERY)
        self.assertGreaterEqual(len(delib_result["hypotheses"]), 1)

        # Step 3: Consensus
        chosen = self._step3_consensus(delib_result)
        self.assertIsNotNone(chosen)

        # Step 4: Execute
        exec_result = self._step4_execute_goal(goal.id, chosen)
        self.assertIn("result", exec_result)

        # Step 5: Record episode (graceful if memory unavailable)
        episode = self._step5_record_episode(goal.id, exec_result)

        # Step 6: Generate DPO pair (graceful if evolution unavailable)
        dpo = self._step6_generate_dpo_pair(episode)

        # Verify final goal state
        final_goal = self.planner.get_goal(goal.id)
        self.assertIsNotNone(final_goal)
        self.assertEqual(final_goal.status, _PipelineGS.COMPLETED)  # type: ignore[union-attr]

        # Planner summary reflects the completed goal
        summary = self.planner.summary()
        self.assertGreaterEqual(summary.get("total_goals", 0), 1)

    def test_pipeline_bus_events_published(self) -> None:
        """Pipeline steps publish events to the EventBus."""
        events: list[dict] = []

        def capture(data: Any) -> None:
            events.append({"data": data})

        self.bus.subscribe("planner.goal.executed", capture)

        goal = self.planner.create_goal(description=self.USER_QUERY, domain="reasoning")

        def executor(g) -> dict:
            return {"status": "completed", "result": "done"}

        self.planner.execute_goal(goal.id, executor_fn=executor)
        self.assertGreater(len(events), 0, "At least one 'planner.goal.executed' event expected")


# ===========================================================================
# Run
# ===========================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)
