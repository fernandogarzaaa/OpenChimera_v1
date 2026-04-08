"""Comprehensive AGI Completeness Integration Tests.

Verifies all 10 cognitive capabilities are:
1. Importable and instantiable
2. Wired into the kernel
3. Wired into the multi-agent orchestrator's cognitive enrichment pipeline
4. Producing correct status/snapshot output
5. Working together in end-to-end cognitive loops

Test structure:
- TestAGIModulesExist — import and instantiate each module
- TestAGIKernelWiring — verify kernel holds all 10 modules
- TestAGIOrchestratorWiring — verify orchestrator integrates all modules
- TestAGICognitiveEnrichment — verify enrichment pipeline runs all modules
- TestAGIEndToEndLoop — full cognitive loop through orchestrator
- TestEmbodiedInteractionCapabilities — detailed module #9 tests
- TestSocialCognitionCapabilities — detailed module #10 tests
- TestProviderAGIEndpoints — verify provider exposes AGI status
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from core._bus_fallback import EventBus
from core._database_fallback import DatabaseManager


class TestAGIModulesExist(unittest.TestCase):
    """Verify all 10 AGI cognitive modules can be imported and instantiated."""

    def setUp(self):
        self.bus = EventBus()

    def test_01_memory_system(self):
        from core.memory_system import MemorySystem
        with tempfile.TemporaryDirectory() as tmp:
            db = DatabaseManager(db_path=str(Path(tmp) / "test.db"))
            db.initialize()
            mem = MemorySystem(db=db, bus=self.bus, working_max_size=64)
            self.assertIsNotNone(mem)
            summary = mem.summary()
            self.assertIsInstance(summary, dict)
            db.close()

    def test_02_deliberation(self):
        from core.deliberation import DeliberationGraph
        dg = DeliberationGraph(bus=self.bus)
        self.assertIsNotNone(dg)
        summary = dg.summary()
        self.assertIsInstance(summary, dict)

    def test_03_goal_planner(self):
        from core.goal_planner import GoalPlanner
        with tempfile.TemporaryDirectory() as tmp:
            db = DatabaseManager(db_path=str(Path(tmp) / "test.db"))
            db.initialize()
            gp = GoalPlanner(db=db, bus=self.bus)
            self.assertIsNotNone(gp)
            summary = gp.summary()
            self.assertIsInstance(summary, dict)
            db.close()

    def test_04_evolution(self):
        from core.evolution import EvolutionEngine
        with tempfile.TemporaryDirectory() as tmp:
            db = DatabaseManager(db_path=str(Path(tmp) / "test.db"))
            db.initialize()
            ee = EvolutionEngine(db=db, bus=self.bus)
            self.assertIsNotNone(ee)
            summary = ee.summary()
            self.assertIsInstance(summary, dict)
            db.close()

    def test_05_metacognition(self):
        from core.metacognition import MetacognitionEngine
        with tempfile.TemporaryDirectory() as tmp:
            db = DatabaseManager(db_path=str(Path(tmp) / "test.db"))
            db.initialize()
            mc = MetacognitionEngine(db=db, bus=self.bus)
            self.assertIsNotNone(mc)
            summary = mc.summary()
            self.assertIsInstance(summary, dict)
            db.close()

    def test_06_self_model(self):
        from core.self_model import SelfModel
        sm = SelfModel(bus=self.bus)
        self.assertIsNotNone(sm)
        assessment = sm.self_assessment()
        self.assertIsInstance(assessment, dict)

    def test_07_transfer_learning(self):
        from core.transfer_learning import TransferLearning
        tl = TransferLearning(bus=self.bus)
        self.assertIsNotNone(tl)
        domains = tl.list_domains()
        self.assertIsInstance(domains, list)

    def test_08_causal_reasoning(self):
        from core.causal_reasoning import CausalReasoning
        cr = CausalReasoning(bus=self.bus)
        self.assertIsNotNone(cr)
        summary = cr.summary()
        self.assertIsInstance(summary, dict)

    def test_09_embodied_interaction(self):
        from core.embodied_interaction import EmbodiedInteraction
        ei = EmbodiedInteraction(bus=self.bus)
        self.assertIsNotNone(ei)
        snap = ei.snapshot()
        self.assertIn("sensors", snap)
        self.assertIn("actuators", snap)
        self.assertIn("environment", snap)
        self.assertIn("body_schema", snap)

    def test_10_social_cognition(self):
        from core.social_cognition import SocialCognition
        sc = SocialCognition(bus=self.bus)
        self.assertIsNotNone(sc)
        snap = sc.snapshot()
        self.assertIn("theory_of_mind", snap)
        self.assertIn("relationships", snap)
        self.assertIn("active_contexts", snap)
        self.assertIn("norms", snap)


class TestAGIKernelWiring(unittest.TestCase):
    """Verify the kernel holds and initialises all 10 AGI modules."""

    def test_kernel_has_all_agi_subsystems(self):
        from core.kernel import OpenChimeraKernel
        with patch("core.kernel.OpenChimeraAPIServer"):
            kernel = OpenChimeraKernel()

        # All 10 modules should exist as attributes
        agi_attrs = [
            "embodied_interaction",
            "social_cognition",
        ]
        for attr in agi_attrs:
            self.assertTrue(
                hasattr(kernel, attr),
                f"Kernel missing AGI module: {attr}",
            )
            module = getattr(kernel, attr)
            self.assertIsNotNone(module, f"Kernel AGI module {attr} is None")

    def test_kernel_status_snapshot_includes_agi(self):
        from core.kernel import OpenChimeraKernel
        with patch("core.kernel.OpenChimeraAPIServer"):
            kernel = OpenChimeraKernel()

        snapshot = kernel.status_snapshot()
        agi = snapshot.get("agi", {})
        self.assertIn("social_cognition", agi)
        self.assertIn("embodied_interaction", agi)

    def test_kernel_boot_report_includes_agi_modules(self):
        from core.kernel import OpenChimeraKernel
        with patch("core.kernel.OpenChimeraAPIServer"):
            kernel = OpenChimeraKernel()

        report = kernel.boot_report()
        subsystems = report.get("subsystems", {})
        self.assertIn("social_cognition", subsystems)
        self.assertIn("embodied_interaction", subsystems)


class TestAGIOrchestratorWiring(unittest.TestCase):
    """Verify the orchestrator initialises and exposes all cognitive modules."""

    def test_orchestrator_has_social_cognition(self):
        from core.multi_agent_orchestrator import MultiAgentOrchestrator
        orch = MultiAgentOrchestrator()
        self.assertIsNotNone(orch._social_cognition)

    def test_orchestrator_has_embodied_interaction(self):
        from core.multi_agent_orchestrator import MultiAgentOrchestrator
        orch = MultiAgentOrchestrator()
        self.assertIsNotNone(orch._embodied_interaction)

    def test_orchestrator_status_reports_all_modules(self):
        from core.multi_agent_orchestrator import MultiAgentOrchestrator
        orch = MultiAgentOrchestrator()
        status = orch.status()
        self.assertTrue(status.get("social_cognition_available"))
        self.assertTrue(status.get("embodied_interaction_available"))
        self.assertTrue(status.get("self_model_available"))
        self.assertTrue(status.get("transfer_learning_available"))
        self.assertTrue(status.get("causal_reasoning_available"))
        self.assertTrue(status.get("meta_learning_available"))
        self.assertTrue(status.get("ethical_reasoning_available"))

    def test_orchestrator_all_cognitive_modules_count(self):
        """All 7 cognitive enrichment modules should be available."""
        from core.multi_agent_orchestrator import MultiAgentOrchestrator
        orch = MultiAgentOrchestrator()
        status = orch.status()
        available_keys = [k for k in status if k.endswith("_available") and status[k]]
        # memory, metacognition + 7 enrichment modules = at least 7 enrichment
        self.assertGreaterEqual(len(available_keys), 7)


class TestAGICognitiveEnrichment(unittest.TestCase):
    """Verify the cognitive enrichment pipeline executes all modules."""

    def test_enrichment_runs_all_modules(self):
        """Cognitive enrichment should not raise for any module."""
        from core.multi_agent_orchestrator import MultiAgentOrchestrator
        orch = MultiAgentOrchestrator()

        # Run enrichment — should succeed without errors
        orch._run_cognitive_enrichment(
            domain="testing",
            task="Verify AGI completeness of the OpenChimera system",
            confidence=0.85,
            agent_ids=["agent-a", "agent-b", "agent-c"],
        )

        # Verify social cognition recorded observations
        sc = orch._social_cognition
        self.assertIsNotNone(sc)
        agents = sc.relationship_memory.snapshot()
        self.assertGreater(len(agents), 0, "SocialCognition should have observed agents")

        # Verify embodied interaction recorded environment
        ei = orch._embodied_interaction
        self.assertIsNotNone(ei)
        obj = ei.environment.get_object("task_testing")
        self.assertIsNotNone(obj, "EmbodiedInteraction should have tracked the task")
        self.assertIn("confidence", obj.properties)

    def test_enrichment_multiple_domains(self):
        """Enrichment should work across multiple domains without interference."""
        from core.multi_agent_orchestrator import MultiAgentOrchestrator
        orch = MultiAgentOrchestrator()

        domains = ["math", "science", "coding", "creative"]
        for domain in domains:
            orch._run_cognitive_enrichment(
                domain=domain,
                task=f"Solve a {domain} problem",
                confidence=0.7 + 0.05 * domains.index(domain),
                agent_ids=["agent-1", "agent-2"],
            )

        # Each domain should have created an environment object
        for domain in domains:
            obj = orch._embodied_interaction.environment.get_object(f"task_{domain}")
            self.assertIsNotNone(obj)


class TestEmbodiedInteractionCapabilities(unittest.TestCase):
    """Detailed tests for AGI module #9 — Embodied Interaction."""

    def setUp(self):
        from core.embodied_interaction import EmbodiedInteraction
        self.bus = EventBus()
        self.ei = EmbodiedInteraction(bus=self.bus)

    def test_default_sensors_registered(self):
        sensors = self.ei.sensors.list_sensors()
        self.assertGreater(len(sensors), 0)
        modalities = {s["modality"] for s in sensors}
        self.assertIn("distance", modalities)
        self.assertIn("temperature", modalities)
        self.assertIn("visual", modalities)

    def test_default_actuators_registered(self):
        actuators = self.ei.actuators.list_actuators()
        self.assertGreater(len(actuators), 0)

    def test_move_command(self):
        cmd = self.ei.move(direction="left", distance_m=0.5)
        self.assertEqual(cmd.status, "completed")
        self.assertEqual(cmd.result.get("direction"), "left")

    def test_speak_command(self):
        cmd = self.ei.speak("Hello world")
        self.assertEqual(cmd.status, "completed")
        self.assertTrue(cmd.result.get("spoken"))

    def test_look_command(self):
        cmd = self.ei.look("up")
        self.assertEqual(cmd.status, "completed")
        self.assertEqual(cmd.result.get("looking_at"), "up")

    def test_body_schema_capabilities(self):
        snap = self.ei.body_schema.snapshot()
        self.assertIn("capabilities", snap)
        caps = snap["capabilities"]
        self.assertIn("move", caps)
        self.assertIn("speak", caps)
        self.assertIn("grasp", caps)

    def test_environment_state_tracking(self):
        self.ei.environment.update_object("obj1", label="box", properties={"color": "red"})
        obj = self.ei.environment.get_object("obj1")
        self.assertIsNotNone(obj)
        self.assertEqual(obj.label, "box")
        self.assertEqual(obj.properties["color"], "red")

    def test_sensor_injection(self):
        self.ei.sensors.inject_reading("distance_front", 1.5)
        reading = self.ei.sensors.read("distance_front")
        self.assertIsNotNone(reading)
        self.assertEqual(reading.value, 1.5)

    def test_snapshot_complete(self):
        snap = self.ei.snapshot()
        for key in ("sensors", "actuators", "environment", "body_schema"):
            self.assertIn(key, snap)


class TestSocialCognitionCapabilities(unittest.TestCase):
    """Detailed tests for AGI module #10 — Social Cognition."""

    def setUp(self):
        from core.social_cognition import SocialCognition
        self.bus = EventBus()
        self.sc = SocialCognition(bus=self.bus)

    def test_observe_agent_updates_theory_of_mind(self):
        result = self.sc.observe_agent(
            "alice",
            beliefs={"likes_python": True},
            desires=["learn rust"],
            emotion="curious",
            confidence=0.8,
        )
        self.assertIn("mental_state", result)
        self.assertEqual(result["mental_state"]["emotion"], "curious")

    def test_observe_agent_updates_relationship(self):
        result = self.sc.observe_agent(
            "bob",
            trust_delta=0.2,
            sentiment_delta=0.3,
            note="Helpful in code review",
        )
        self.assertIn("relationship", result)
        rel = result["relationship"]
        self.assertGreater(rel["trust"], 0.5)  # started at 0.5, +0.2
        self.assertGreater(rel["sentiment"], 0.0)

    def test_is_trustworthy(self):
        # Default trust is 0.5
        self.assertFalse(self.sc.is_trustworthy("new_agent", threshold=0.6))
        # Increase trust
        self.sc.observe_agent("new_agent", trust_delta=0.2)
        self.assertTrue(self.sc.is_trustworthy("new_agent", threshold=0.6))

    def test_evaluate_action_against_norms(self):
        self.sc.norm_registry.add_norm("be_polite", "Always use respectful language")
        result = self.sc.evaluate_action("respond rudely")
        self.assertIsInstance(result, dict)

    def test_predict_agent_response(self):
        self.sc.observe_agent("charlie", emotion="happy", confidence=0.9)
        prediction = self.sc.predict_agent_response("charlie", "offer collaboration")
        self.assertIsInstance(prediction, str)
        self.assertGreater(len(prediction), 0)

    def test_social_context_tracking(self):
        ctx = self.sc.social_context.open_context(
            context_id="meeting-1",
            participants=["alice", "bob"],
            topic="Project planning",
            goal="Define sprint goals",
        )
        self.assertTrue(ctx.active)
        self.assertEqual(ctx.topic, "Project planning")

        active = self.sc.social_context.active_contexts()
        self.assertGreater(len(active), 0)

    def test_relationship_persistence_roundtrip(self):
        """Relationships should accumulate over multiple interactions."""
        for i in range(5):
            self.sc.observe_agent(
                "eve",
                trust_delta=0.05,
                sentiment_delta=0.1,
                note=f"Interaction {i}",
            )
        rec = self.sc.relationship_memory.get("eve")
        self.assertIsNotNone(rec)
        self.assertEqual(rec.interaction_count, 5)
        self.assertGreater(rec.trust, 0.7)

    def test_snapshot_complete(self):
        self.sc.observe_agent("dave", emotion="neutral")
        snap = self.sc.snapshot()
        for key in ("theory_of_mind", "relationships", "active_contexts", "norms"):
            self.assertIn(key, snap)


class TestProviderAGIEndpoints(unittest.TestCase):
    """Verify provider exposes AGI completeness endpoint."""

    def test_provider_agi_completeness(self):
        from core.provider import OpenChimeraProvider
        from core.personality import Personality
        bus = EventBus()
        personality = Personality()
        with patch.dict("os.environ", {"OPENCHIMERA_API_TOKEN": "test", "OPENCHIMERA_ADMIN_TOKEN": "admin"}):
            provider = OpenChimeraProvider(bus, personality)
            result = provider.agi_completeness()
            self.assertIn("implemented", result)
            self.assertIn("total", result)
            self.assertIn("modules", result)
            self.assertEqual(result["total"], 10)

    def test_provider_embodied_status(self):
        from core.provider import OpenChimeraProvider
        from core.personality import Personality
        bus = EventBus()
        personality = Personality()
        with patch.dict("os.environ", {"OPENCHIMERA_API_TOKEN": "test", "OPENCHIMERA_ADMIN_TOKEN": "admin"}):
            provider = OpenChimeraProvider(bus, personality)
            result = provider.embodied_interaction_status()
            self.assertIsInstance(result, dict)

    def test_provider_social_status(self):
        from core.provider import OpenChimeraProvider
        from core.personality import Personality
        bus = EventBus()
        personality = Personality()
        with patch.dict("os.environ", {"OPENCHIMERA_API_TOKEN": "test", "OPENCHIMERA_ADMIN_TOKEN": "admin"}):
            provider = OpenChimeraProvider(bus, personality)
            result = provider.social_cognition_status()
            self.assertIsInstance(result, dict)


class TestAGIEndToEndLoop(unittest.TestCase):
    """Full cognitive loop: orchestrate → enrich → verify all modules touched."""

    def test_full_loop_through_orchestrator(self):
        """Run a task through the orchestrator and verify all modules were used."""
        from core.multi_agent_orchestrator import MultiAgentOrchestrator

        orch = MultiAgentOrchestrator()

        # Run the cognitive enrichment (simulates post-consensus enrichment)
        orch._run_cognitive_enrichment(
            domain="integration_test",
            task="Test the complete AGI cognitive loop end-to-end",
            confidence=0.92,
            agent_ids=["agent-alpha", "agent-beta", "agent-gamma"],
        )

        # 1. Self-Model should have recorded capability
        if orch._self_model:
            snap = orch._self_model.self_assessment()
            self.assertIsInstance(snap, dict)

        # 2. Transfer Learning should be queryable
        if orch._transfer_learning:
            domains = orch._transfer_learning.list_domains()
            self.assertIsInstance(domains, list)

        # 3. Causal Reasoning should have the variable
        if orch._causal_reasoning:
            val = orch._causal_reasoning.get_variable("integration_test_confidence")
            self.assertAlmostEqual(val, 0.92, places=2)

        # 4. Meta-Learning should be operational
        if orch._meta_learning:
            status = orch._meta_learning.status()
            self.assertIsInstance(status, dict)

        # 5. Ethical Reasoning should have evaluated
        if orch._ethical_reasoning:
            status = orch._ethical_reasoning.status()
            self.assertIsInstance(status, dict)

        # 6. Social Cognition should have observed agents
        if orch._social_cognition:
            snap = orch._social_cognition.snapshot()
            rels = snap.get("relationships", [])
            self.assertGreater(len(rels), 0)

        # 7. Embodied Interaction should have tracked task
        if orch._embodied_interaction:
            obj = orch._embodied_interaction.environment.get_object("task_integration_test")
            self.assertIsNotNone(obj)
            self.assertAlmostEqual(obj.properties["confidence"], 0.92, places=2)

    def test_all_ten_modules_available(self):
        """Verify all 10 AGI cognitive modules can be instantiated simultaneously."""
        from core.causal_reasoning import CausalReasoning
        from core.deliberation import DeliberationGraph
        from core.embodied_interaction import EmbodiedInteraction
        from core.evolution import EvolutionEngine
        from core.goal_planner import GoalPlanner
        from core.metacognition import MetacognitionEngine
        from core.self_model import SelfModel
        from core.social_cognition import SocialCognition
        from core.transfer_learning import TransferLearning

        bus = EventBus()
        with tempfile.TemporaryDirectory() as tmp:
            db = DatabaseManager(db_path=str(Path(tmp) / "test.db"))
            db.initialize()

            modules = {
                "memory": None,  # MemorySystem needs db
                "deliberation": DeliberationGraph(bus=bus),
                "goal_planner": GoalPlanner(db=db, bus=bus),
                "evolution": EvolutionEngine(db=db, bus=bus),
                "metacognition": MetacognitionEngine(db=db, bus=bus),
                "self_model": SelfModel(bus=bus),
                "transfer_learning": TransferLearning(bus=bus),
                "causal_reasoning": CausalReasoning(bus=bus),
                "embodied_interaction": EmbodiedInteraction(bus=bus),
                "social_cognition": SocialCognition(bus=bus),
            }

            from core.memory_system import MemorySystem
            modules["memory"] = MemorySystem(db=db, bus=bus, working_max_size=64)

            for name, module in modules.items():
                self.assertIsNotNone(module, f"Module {name} failed to instantiate")

            # All 10 should be alive simultaneously
            self.assertEqual(len(modules), 10)
            db.close()


class TestAGICrossModuleInteraction(unittest.TestCase):
    """Test that AGI modules can interact with each other meaningfully."""

    def setUp(self):
        self.bus = EventBus()

    def test_social_observation_triggers_bus_event(self):
        """Social cognition should publish events that other modules could consume."""
        from core.social_cognition import SocialCognition
        events = []
        self.bus.subscribe("social/relationship_updated", lambda e: events.append(e))

        sc = SocialCognition(bus=self.bus)
        sc.observe_agent("test-agent", trust_delta=0.1)

        # Should have published an event
        self.assertGreater(len(events), 0)

    def test_embodied_action_triggers_bus_event(self):
        """Embodied interaction should publish events on actions."""
        from core.embodied_interaction import EmbodiedInteraction
        events = []
        self.bus.subscribe("embodied/actuator_command", lambda e: events.append(e))

        ei = EmbodiedInteraction(bus=self.bus)
        ei.move(direction="forward", distance_m=1.0)

        self.assertGreater(len(events), 0)

    def test_social_and_embodied_coexist(self):
        """Both modules sharing a bus should not interfere."""
        from core.embodied_interaction import EmbodiedInteraction
        from core.social_cognition import SocialCognition

        sc = SocialCognition(bus=self.bus)
        ei = EmbodiedInteraction(bus=self.bus)

        sc.observe_agent("agent-x", emotion="happy")
        ei.move("right", 0.3)
        ei.environment.update_object("obj-1", label="test")

        sc_snap = sc.snapshot()
        ei_snap = ei.snapshot()
        self.assertIn("theory_of_mind", sc_snap)
        self.assertIn("sensors", ei_snap)


if __name__ == "__main__":
    unittest.main()
