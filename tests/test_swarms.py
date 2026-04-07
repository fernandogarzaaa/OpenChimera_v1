"""tests/test_swarms.py — offline tests for the swarms runtime.

All tests run without network access or a live LLM.
"""
from __future__ import annotations

import asyncio
import pytest

from swarms.agent import SwarmAgent
from swarms.orchestrator import SwarmOrchestrator
from swarms.god_swarm import GodSwarm
from swarms.result import SwarmResult
from swarms.registry import SwarmRegistry


# ---------------------------------------------------------------------------
# Helper factory
# ---------------------------------------------------------------------------

def make_agent(
    agent_id: str = "test-agent",
    role: str = "TestRole",
    description: str = "Test agent",
    capabilities: list[str] | None = None,
) -> SwarmAgent:
    return SwarmAgent(
        agent_id=agent_id,
        role=role,
        description=description,
        capabilities=capabilities or ["cap-a", "cap-b"],
    )


# ===========================================================================
# Tests 1–2: SwarmAgent creation and attributes
# ===========================================================================

class TestSwarmAgent:
    def test_creation_and_attributes(self):
        agent = make_agent()
        assert agent.agent_id == "test-agent"
        assert agent.role == "TestRole"
        assert agent.description == "Test agent"
        assert agent.capabilities == ["cap-a", "cap-b"]
        assert agent.status == "idle"

    def test_execute_returns_expected_string(self):
        agent = make_agent(role="Analyst", agent_id="analyst-1")
        task = "Analyse the system topology for bottlenecks"
        result = asyncio.run(agent.execute(task, {}))
        # Must start with "<role> completed: <task[:50]>"
        assert result == f"Analyst completed: {task[:50]}"

    def test_execute_sets_status_to_done(self):
        agent = make_agent()
        asyncio.run(agent.execute("some task", {}))
        assert agent.status == "done"

    def test_to_dict_shape(self):
        agent = make_agent()
        d = agent.to_dict()
        assert d["agent_id"] == "test-agent"
        assert d["role"] == "TestRole"
        assert "capabilities" in d
        assert "status" in d


# ===========================================================================
# Tests 3–5: SwarmOrchestrator registration and dispatch
# ===========================================================================

class TestSwarmOrchestrator:
    def test_register_and_list(self):
        orch = SwarmOrchestrator()
        a1 = make_agent("a1", "Alpha")
        a2 = make_agent("a2", "Beta")
        orch.register(a1)
        orch.register(a2)
        ids = orch.agent_ids()
        assert "a1" in ids
        assert "a2" in ids
        assert len(orch.list_agents()) == 2

    def test_dispatch_single_agent(self):
        orch = SwarmOrchestrator()
        agent = make_agent("solo", "Solo")
        orch.register(agent)
        result = orch.dispatch("Do the single thing", agent_ids=["solo"])
        assert isinstance(result, SwarmResult)
        assert result.error is None
        assert "Solo" in result.consensus_answer
        assert result.confidence == 1.0

    def test_dispatch_multiple_agents_quantum_consensus(self):
        """Multi-agent dispatch should succeed and return SwarmResult."""
        orch = SwarmOrchestrator()
        for i in range(3):
            orch.register(make_agent(f"agent-{i}", f"Role{i}"))
        result = orch.dispatch("Coordinate multi-agent task", use_consensus=True)
        assert isinstance(result, SwarmResult)
        assert len(result.selected_agents) == 3
        assert result.consensus_answer != ""

    def test_dispatch_no_agents_returns_error(self):
        orch = SwarmOrchestrator()
        result = orch.dispatch("task", agent_ids=["nonexistent"])
        assert result.error is not None

    def test_orchestrator_status(self):
        orch = SwarmOrchestrator()
        orch.register(make_agent())
        status = orch.status()
        assert status["registered_agents"] == 1
        assert "test-agent" in status["agent_ids"]


# ===========================================================================
# Tests 6–7: GodSwarm
# ===========================================================================

class TestGodSwarm:
    def test_initialization_all_10_agents_registered(self):
        gs = GodSwarm()
        ids = gs.agent_ids()
        expected = [
            "omniscient", "architect", "demiurge", "chronos", "arbiter", "scribe",
            "oracle", "alchemist", "reaper", "librarian",
        ]
        for eid in expected:
            assert eid in ids, f"Missing agent: {eid}"
        assert len(ids) == 10

    def test_analyze_and_dispatch_returns_swarm_result(self):
        gs = GodSwarm()
        result = gs.analyze_and_dispatch("Build a resilient caching layer")
        assert isinstance(result, SwarmResult)
        assert result.error is None
        assert result.objective == "Build a resilient caching layer"
        assert len(result.selected_agents) == 10
        assert result.consensus_answer != ""

    def test_god_swarm_status_includes_core_and_supporting(self):
        gs = GodSwarm()
        status = gs.status()
        assert "core_agents" in status
        assert "supporting_agents" in status
        assert len(status["core_agents"]) == 6
        assert len(status["supporting_agents"]) == 4


# ===========================================================================
# Tests 8–9: SwarmRegistry pattern matching
# ===========================================================================

class TestSwarmRegistry:
    def test_coding_pattern(self):
        reg = SwarmRegistry()
        assert reg.resolve("code a new feature for the dashboard") == "coding_swarm"
        assert reg.resolve("implement the OAuth flow") == "coding_swarm"
        assert reg.resolve("develop a caching module") == "coding_swarm"

    def test_security_pattern(self):
        reg = SwarmRegistry()
        assert reg.resolve("security audit of the auth module") == "security_swarm"
        assert reg.resolve("find vulnerabilities in the API") == "security_swarm"

    def test_architect_pattern(self):
        reg = SwarmRegistry()
        assert reg.resolve("design a scalable arch for microservices") == "architect_swarm"
        assert reg.resolve("scale the system to 10M users") == "architect_swarm"

    def test_debug_pattern(self):
        reg = SwarmRegistry()
        assert reg.resolve("debug the login error") == "debug_swarm"
        assert reg.resolve("fix the crash in the payment flow") == "debug_swarm"

    def test_default_fallback(self):
        reg = SwarmRegistry()
        assert reg.resolve("help me think about my life choices") == "god_swarm"

    def test_list_patterns_returns_four_defaults(self):
        reg = SwarmRegistry()
        patterns = reg.list_patterns()
        assert len(patterns) == 4

    def test_register_custom_pattern(self):
        reg = SwarmRegistry()
        reg.register_pattern(r"translate|i18n|localiz", "i18n_swarm", "Internationalisation")
        assert reg.resolve("translate the UI strings to French") == "i18n_swarm"


# ===========================================================================
# Test 10: SwarmResult immutability (frozen dataclass)
# ===========================================================================

class TestSwarmResult:
    def test_frozen_dataclass(self):
        result = SwarmResult(
            objective="Test",
            selected_agents=["a1"],
            outputs=[{"agent_id": "a1", "output": "done"}],
            consensus_answer="done",
            confidence=0.9,
            latency_ms=12.5,
        )
        with pytest.raises((AttributeError, TypeError)):
            result.objective = "Modified"  # type: ignore[misc]

    def test_succeeded_without_error(self):
        result = SwarmResult(
            objective="Test",
            selected_agents=[],
            outputs=[],
            consensus_answer="ok",
            confidence=1.0,
            latency_ms=1.0,
        )
        assert result.succeeded() is True

    def test_succeeded_with_error(self):
        result = SwarmResult(
            objective="Test",
            selected_agents=[],
            outputs=[],
            consensus_answer="",
            confidence=0.0,
            latency_ms=0.0,
            error="Something failed",
        )
        assert result.succeeded() is False

    def test_summary_keys(self):
        result = SwarmResult(
            objective="Test objective",
            selected_agents=["a1", "a2"],
            outputs=[],
            consensus_answer="consensus",
            confidence=0.85,
            latency_ms=42.0,
        )
        summary = result.summary()
        assert "objective" in summary
        assert "confidence" in summary
        assert "latency_ms" in summary
        assert "answer_preview" in summary


# ===========================================================================
# Test 11: Full god_swarm flow with varied objectives
# ===========================================================================

class TestFullGodSwarmFlow:
    def test_coding_objective_full_flow(self):
        gs = GodSwarm()
        reg = SwarmRegistry()
        objective = "Implement a new REST endpoint for user profile updates"
        swarm_name = reg.resolve(objective)
        assert swarm_name == "coding_swarm"
        result = gs.analyze_and_dispatch(objective)
        assert result.succeeded()
        assert result.confidence > 0.0

    def test_security_objective_full_flow(self):
        gs = GodSwarm()
        result = gs.analyze_and_dispatch("Audit the authentication system for security vulnerabilities")
        assert result.succeeded()
        assert len(result.outputs) == 10  # all 10 agents participated


# ===========================================================================
# Tests: Real LLM callback wiring in SwarmAgent and GodSwarm
# ===========================================================================

class TestSwarmAgentLLMCallback:
    def _make_llm_callback(self, response: str = "LLM answer"):
        """Return a fake chat_completion callback that mimics the provider API."""
        def _callback(messages, model="openchimera-local", max_tokens=512, temperature=0.7, stream=False):
            return {
                "choices": [{"message": {"content": response}}],
                "model": model,
            }
        return _callback

    def test_offline_stub_used_when_no_callback(self):
        agent = SwarmAgent(agent_id="a", role="Analyst", description="test")
        result = asyncio.run(agent.execute("test task", {}))
        assert result == "Analyst completed: test task"
        assert agent.status == "done"

    def test_llm_callback_invoked_when_bound(self):
        callback = self._make_llm_callback("Real LLM response here")
        agent = SwarmAgent(agent_id="b", role="Expert", description="test", llm_callback=callback)
        result = asyncio.run(agent.execute("answer this question", {}))
        assert result == "Real LLM response here"
        assert agent.status == "done"

    def test_llm_callback_failure_sets_failed_status_returns_error_string(self):
        def bad_callback(**kwargs):
            raise RuntimeError("model offline")
        agent = SwarmAgent(agent_id="c", role="Broken", description="test", llm_callback=bad_callback)
        result = asyncio.run(agent.execute("task", {}))
        assert agent.status == "failed"
        assert "error" in result.lower() or "broken" in result.lower()

    def test_to_dict_reflects_llm_bound_true(self):
        callback = self._make_llm_callback()
        agent = SwarmAgent(agent_id="d", role="R", description="t", llm_callback=callback)
        d = agent.to_dict()
        assert d["llm_bound"] is True

    def test_to_dict_reflects_llm_bound_false(self):
        agent = SwarmAgent(agent_id="e", role="R", description="t")
        d = agent.to_dict()
        assert d["llm_bound"] is False

    def test_context_injected_into_messages(self):
        """Verify that context dict is reflected in the messages sent to the callback."""
        captured = []
        def capturing_callback(messages, **kwargs):
            captured.extend(messages)
            return {"choices": [{"message": {"content": "ok"}}], "model": "test"}

        agent = SwarmAgent(agent_id="f", role="Scribe", description="test", llm_callback=capturing_callback)
        asyncio.run(agent.execute("summarise", context={"phase": "execute", "coord_id": "abc123"}))
        # Context entries should appear in system messages
        combined = " ".join(m.get("content", "") for m in captured)
        assert "phase" in combined or "coord_id" in combined


class TestGodSwarmKernelWiring:
    def _make_kernel_with_llm(self, response: str = "kernel LLM"):
        class FakeProvider:
            def chat_completion(self, messages, model, max_tokens, temperature, stream):
                return {"choices": [{"message": {"content": response}}], "model": model}

        class FakeKernel:
            provider = FakeProvider()

        return FakeKernel()

    def test_wire_to_kernel_binds_llm_to_all_agents(self):
        gs = GodSwarm()
        kernel = self._make_kernel_with_llm("swarm LLM response")
        gs.wire_to_kernel(kernel)
        for agent in gs.list_agents():
            assert agent.llm_callback is not None, f"Agent {agent.agent_id} missing callback"

    def test_wire_to_kernel_without_provider_uses_offline_stub(self):
        gs = GodSwarm()
        class KernelNoBus:
            pass
        gs.wire_to_kernel(KernelNoBus())
        for agent in gs.list_agents():
            assert agent.llm_callback is None, f"Agent {agent.agent_id} should have no callback"

    def test_spawn_agent_inherits_llm_callback(self):
        gs = GodSwarm()
        kernel = self._make_kernel_with_llm()
        gs.wire_to_kernel(kernel)
        record = gs.spawn_agent({"role": "Dynamic", "description": "spawned"})
        spawned = gs.get_agent(record["agent_id"])
        assert spawned is not None
        assert spawned.llm_callback is not None

    def test_status_reports_kernel_wired(self):
        gs = GodSwarm()
        kernel = self._make_kernel_with_llm()
        gs.wire_to_kernel(kernel)
        status = gs.status()
        assert status["kernel_wired"] is True
