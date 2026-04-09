"""Tests for the openchimera namespace package re-exports.

Ensures all public API modules are importable from both ``core.*`` and
``openchimera.*`` and that the re-exported symbols are identical.
"""
from __future__ import annotations

import unittest


class TestOpenChimeraNamespace(unittest.TestCase):
    """Every public sub-module under ``openchimera`` should import cleanly."""

    def test_version_available(self):
        import openchimera
        self.assertIsInstance(openchimera.__version__, str)
        self.assertNotEqual(openchimera.__version__, "")

    def test_kernel_reexport(self):
        from openchimera.kernel import Kernel
        from core.kernel import Kernel as CoreKernel
        self.assertIs(Kernel, CoreKernel)

    def test_provider_reexport(self):
        from openchimera.provider import OpenChimeraProvider
        from core.provider import OpenChimeraProvider as CoreProvider
        self.assertIs(OpenChimeraProvider, CoreProvider)

    def test_query_engine_reexport(self):
        from openchimera.query_engine import QueryEngine
        from core.query_engine import QueryEngine as CoreQE
        self.assertIs(QueryEngine, CoreQE)

    def test_memory_reexport(self):
        from openchimera.memory import MemorySystem
        from core.memory_system import MemorySystem as CoreMem
        self.assertIs(MemorySystem, CoreMem)

    def test_config_reexport(self):
        from openchimera.config import ROOT, load_runtime_profile
        from core.config import ROOT as CoreROOT
        from core.config import load_runtime_profile as core_lrp
        self.assertIs(ROOT, CoreROOT)
        self.assertIs(load_runtime_profile, core_lrp)

    def test_quantum_engine_reexport(self):
        from openchimera.quantum_engine import (
            QuantumEngine, ConsensusResult, ConsensusFailure,
        )
        from core.quantum_engine import (
            QuantumEngine as CoreQE,
            ConsensusResult as CoreCR,
            ConsensusFailure as CoreCF,
        )
        self.assertIs(QuantumEngine, CoreQE)
        self.assertIs(ConsensusResult, CoreCR)
        self.assertIs(ConsensusFailure, CoreCF)

    def test_agent_pool_reexport(self):
        from openchimera.agent_pool import (
            AgentPool, AgentSpec, AgentRole, AgentStatus, create_pool,
        )
        from core.agent_pool import (
            AgentPool as CoreAP,
            AgentSpec as CoreAS,
            AgentRole as CoreAR,
            AgentStatus as CoreASt,
            create_pool as core_cp,
        )
        self.assertIs(AgentPool, CoreAP)
        self.assertIs(AgentSpec, CoreAS)
        self.assertIs(AgentRole, CoreAR)
        self.assertIs(AgentStatus, CoreASt)
        self.assertIs(create_pool, core_cp)

    def test_orchestrator_reexport(self):
        from openchimera.orchestrator import (
            MultiAgentOrchestrator, OrchestratorResult,
        )
        from core.multi_agent_orchestrator import (
            MultiAgentOrchestrator as CoreMAO,
            OrchestratorResult as CoreOR,
        )
        self.assertIs(MultiAgentOrchestrator, CoreMAO)
        self.assertIs(OrchestratorResult, CoreOR)

    def test_session_memory_reexport(self):
        from openchimera.session_memory import SessionMemory
        from core.session_memory import SessionMemory as CoreSM
        self.assertIs(SessionMemory, CoreSM)

    def test_chimera_bridge_reexport(self):
        from openchimera.chimera_bridge import ChimeraLangBridge
        from core.chimera_bridge import ChimeraLangBridge as CoreCLB
        self.assertIs(ChimeraLangBridge, CoreCLB)

    def test_api_server_reexport(self):
        from openchimera.api_server import OpenChimeraAPIServer, RequestValidationFailure
        from core.api_server import OpenChimeraAPIServer as CoreAPI
        from core.api_server import RequestValidationFailure as CoreRVF
        self.assertIs(OpenChimeraAPIServer, CoreAPI)
        self.assertIs(RequestValidationFailure, CoreRVF)

    def test_cli_reexport(self):
        from openchimera.cli import main
        from run import main as core_main
        self.assertIs(main, core_main)

    # ------------------------------------------------------------------
    # AGI namespace re-exports (15 new modules)
    # ------------------------------------------------------------------

    def test_goal_planner_reexport(self):
        from openchimera.goal_planner import GoalPlanner
        from core.goal_planner import GoalPlanner as CoreGoalPlanner
        self.assertIs(GoalPlanner, CoreGoalPlanner)

    def test_deliberation_reexport(self):
        from openchimera.deliberation import DeliberationGraph, DeliberationEngine
        from core.deliberation import DeliberationGraph as CoreDG
        from core.deliberation_engine import DeliberationEngine as CoreDE
        self.assertIs(DeliberationGraph, CoreDG)
        self.assertIs(DeliberationEngine, CoreDE)

    def test_causal_reasoning_reexport(self):
        from openchimera.causal_reasoning import CausalReasoning
        from core.causal_reasoning import CausalReasoning as CoreCR
        self.assertIs(CausalReasoning, CoreCR)

    def test_meta_learning_reexport(self):
        from openchimera.meta_learning import MetaLearning
        from core.meta_learning import MetaLearning as CoreML
        self.assertIs(MetaLearning, CoreML)

    def test_metacognition_reexport(self):
        from openchimera.metacognition import MetacognitionEngine
        from core.metacognition import MetacognitionEngine as CoreMCE
        self.assertIs(MetacognitionEngine, CoreMCE)

    def test_self_model_reexport(self):
        from openchimera.self_model import SelfModel
        from core.self_model import SelfModel as CoreSM
        self.assertIs(SelfModel, CoreSM)

    def test_transfer_learning_reexport(self):
        from openchimera.transfer_learning import TransferLearning
        from core.transfer_learning import TransferLearning as CoreTL
        self.assertIs(TransferLearning, CoreTL)

    def test_ethical_reasoning_reexport(self):
        from openchimera.ethical_reasoning import EthicalReasoning
        from core.ethical_reasoning import EthicalReasoning as CoreER
        self.assertIs(EthicalReasoning, CoreER)

    def test_social_cognition_reexport(self):
        from openchimera.social_cognition import SocialCognition
        from core.social_cognition import SocialCognition as CoreSC
        self.assertIs(SocialCognition, CoreSC)

    def test_embodied_interaction_reexport(self):
        from openchimera.embodied_interaction import EmbodiedInteraction
        from core.embodied_interaction import EmbodiedInteraction as CoreEI
        self.assertIs(EmbodiedInteraction, CoreEI)

    def test_evolution_reexport(self):
        from openchimera.evolution import EvolutionEngine
        from core.evolution import EvolutionEngine as CoreEE
        self.assertIs(EvolutionEngine, CoreEE)

    def test_safety_layer_reexport(self):
        from openchimera.safety_layer import SafetyLayer
        from core.safety_layer import SafetyLayer as CoreSL
        self.assertIs(SafetyLayer, CoreSL)

    def test_plan_mode_reexport(self):
        from openchimera.plan_mode import PlanMode
        from core.plan_mode import PlanMode as CorePM
        self.assertIs(PlanMode, CorePM)

    def test_world_model_reexport(self):
        from openchimera.world_model import SystemWorldModel
        from core.world_model import SystemWorldModel as CoreWM
        self.assertIs(SystemWorldModel, CoreWM)

    def test_knowledge_base_reexport(self):
        from openchimera.knowledge_base import KnowledgeBase
        from core.knowledge_base import KnowledgeBase as CoreKB
        self.assertIs(KnowledgeBase, CoreKB)


if __name__ == "__main__":
    unittest.main()
