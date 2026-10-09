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
        from core.kernel import Kernel as CoreKernel
        from openchimera.kernel import Kernel
        self.assertIs(Kernel, CoreKernel)

    def test_provider_reexport(self):
        from core.provider import OpenChimeraProvider as CoreProvider
        from openchimera.provider import OpenChimeraProvider
        self.assertIs(OpenChimeraProvider, CoreProvider)

    def test_query_engine_reexport(self):
        from core.query_engine import QueryEngine as CoreQE
        from openchimera.query_engine import QueryEngine
        self.assertIs(QueryEngine, CoreQE)

    def test_memory_reexport(self):
        from core.memory_system import MemorySystem as CoreMem
        from openchimera.memory import MemorySystem
        self.assertIs(MemorySystem, CoreMem)

    def test_config_reexport(self):
        from core.config import ROOT as CoreROOT
        from core.config import load_runtime_profile as core_lrp
        from openchimera.config import ROOT, load_runtime_profile
        self.assertIs(ROOT, CoreROOT)
        self.assertIs(load_runtime_profile, core_lrp)

    def test_quantum_engine_reexport(self):
        from core.quantum_engine import (
            ConsensusFailure as CoreCF,
        )
        from core.quantum_engine import (
            ConsensusResult as CoreCR,
        )
        from core.quantum_engine import (
            QuantumEngine as CoreQE,
        )
        from openchimera.quantum_engine import (
            ConsensusFailure,
            ConsensusResult,
            QuantumEngine,
        )
        self.assertIs(QuantumEngine, CoreQE)
        self.assertIs(ConsensusResult, CoreCR)
        self.assertIs(ConsensusFailure, CoreCF)

    def test_agent_pool_reexport(self):
        from core.agent_pool import (
            AgentPool as CoreAP,
        )
        from core.agent_pool import (
            AgentRole as CoreAR,
        )
        from core.agent_pool import (
            AgentSpec as CoreAS,
        )
        from core.agent_pool import (
            AgentStatus as CoreASt,
        )
        from core.agent_pool import (
            create_pool as core_cp,
        )
        from openchimera.agent_pool import (
            AgentPool,
            AgentRole,
            AgentSpec,
            AgentStatus,
            create_pool,
        )
        self.assertIs(AgentPool, CoreAP)
        self.assertIs(AgentSpec, CoreAS)
        self.assertIs(AgentRole, CoreAR)
        self.assertIs(AgentStatus, CoreASt)
        self.assertIs(create_pool, core_cp)

    def test_orchestrator_reexport(self):
        from core.multi_agent_orchestrator import (
            MultiAgentOrchestrator as CoreMAO,
        )
        from core.multi_agent_orchestrator import (
            OrchestratorResult as CoreOR,
        )
        from openchimera.orchestrator import (
            MultiAgentOrchestrator,
            OrchestratorResult,
        )
        self.assertIs(MultiAgentOrchestrator, CoreMAO)
        self.assertIs(OrchestratorResult, CoreOR)

    def test_session_memory_reexport(self):
        from core.session_memory import SessionMemory as CoreSM
        from openchimera.session_memory import SessionMemory
        self.assertIs(SessionMemory, CoreSM)

    def test_chimera_bridge_reexport(self):
        from core.chimera_bridge import ChimeraLangBridge as CoreCLB
        from openchimera.chimera_bridge import ChimeraLangBridge
        self.assertIs(ChimeraLangBridge, CoreCLB)

    def test_api_server_reexport(self):
        from core.api_server import OpenChimeraAPIServer as CoreAPI
        from core.api_server import RequestValidationFailure as CoreRVF
        from openchimera.api_server import OpenChimeraAPIServer, RequestValidationFailure
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
        from core.goal_planner import GoalPlanner as CoreGoalPlanner
        from openchimera.goal_planner import GoalPlanner
        self.assertIs(GoalPlanner, CoreGoalPlanner)

    def test_deliberation_reexport(self):
        from core.deliberation import DeliberationGraph as CoreDG
        from core.deliberation_engine import DeliberationEngine as CoreDE
        from openchimera.deliberation import DeliberationEngine, DeliberationGraph
        self.assertIs(DeliberationGraph, CoreDG)
        self.assertIs(DeliberationEngine, CoreDE)

    def test_causal_reasoning_reexport(self):
        from core.causal_reasoning import CausalReasoning as CoreCR
        from openchimera.causal_reasoning import CausalReasoning
        self.assertIs(CausalReasoning, CoreCR)

    def test_meta_learning_reexport(self):
        from core.meta_learning import MetaLearning as CoreML
        from openchimera.meta_learning import MetaLearning
        self.assertIs(MetaLearning, CoreML)

    def test_metacognition_reexport(self):
        from core.metacognition import MetacognitionEngine as CoreMCE
        from openchimera.metacognition import MetacognitionEngine
        self.assertIs(MetacognitionEngine, CoreMCE)

    def test_self_model_reexport(self):
        from core.self_model import SelfModel as CoreSM
        from openchimera.self_model import SelfModel
        self.assertIs(SelfModel, CoreSM)

    def test_transfer_learning_reexport(self):
        from core.transfer_learning import TransferLearning as CoreTL
        from openchimera.transfer_learning import TransferLearning
        self.assertIs(TransferLearning, CoreTL)

    def test_ethical_reasoning_reexport(self):
        from core.ethical_reasoning import EthicalReasoning as CoreER
        from openchimera.ethical_reasoning import EthicalReasoning
        self.assertIs(EthicalReasoning, CoreER)

    def test_social_cognition_reexport(self):
        from core.social_cognition import SocialCognition as CoreSC
        from openchimera.social_cognition import SocialCognition
        self.assertIs(SocialCognition, CoreSC)

    def test_embodied_interaction_reexport(self):
        from core.embodied_interaction import EmbodiedInteraction as CoreEI
        from openchimera.embodied_interaction import EmbodiedInteraction
        self.assertIs(EmbodiedInteraction, CoreEI)

    def test_evolution_reexport(self):
        from core.evolution import EvolutionEngine as CoreEE
        from openchimera.evolution import EvolutionEngine
        self.assertIs(EvolutionEngine, CoreEE)

    def test_safety_layer_reexport(self):
        from core.safety_layer import SafetyLayer as CoreSL
        from openchimera.safety_layer import SafetyLayer
        self.assertIs(SafetyLayer, CoreSL)

    def test_plan_mode_reexport(self):
        from core.plan_mode import PlanMode as CorePM
        from openchimera.plan_mode import PlanMode
        self.assertIs(PlanMode, CorePM)

    def test_world_model_reexport(self):
        from core.world_model import SystemWorldModel as CoreWM
        from openchimera.world_model import SystemWorldModel
        self.assertIs(SystemWorldModel, CoreWM)

    def test_knowledge_base_reexport(self):
        from core.knowledge_base import KnowledgeBase as CoreKB
        from openchimera.knowledge_base import KnowledgeBase
        self.assertIs(KnowledgeBase, CoreKB)


if __name__ == "__main__":
    unittest.main()
