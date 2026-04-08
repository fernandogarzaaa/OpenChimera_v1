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


if __name__ == "__main__":
    unittest.main()
