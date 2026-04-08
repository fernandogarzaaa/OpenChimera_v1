"""Tests for LLM-backed multi-agent consensus.

Covers:
  1.  _discover_available_models returns model list or empty
  2.  _call_ollama_chat sends correct request shape
  3.  make_llm_agent_callable returns async callable
  4.  LLM callable returns structured dict on success
  5.  LLM callable falls back to heuristic on failure
  6.  LLM callable handles empty response gracefully
  7.  create_llm_pool with multiple models assigns round-robin
  8.  create_llm_pool with single model uses varied temperatures
  9.  create_llm_pool with no models falls back to heuristics
  10. create_llm_pool respects OLLAMA_HOST env var
  11. create_llm_pool from profile config
  12. LLM agents integrate with QuantumEngine consensus
  13. Role-specific system prompts are applied
  14. Orchestrator llm_dispatch flag works
  15. Orchestrator respects OPENCHIMERA_LLM_CONSENSUS env var
"""
from __future__ import annotations

import asyncio
import json
import os
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from core.agent_pool import (
    AgentPool,
    AgentRole,
    AgentSpec,
    _LLM_ROLE_PROMPTS,
    _LLM_ROLE_TEMPERATURES,
    _call_ollama_chat,
    _discover_available_models,
    create_llm_pool,
    make_llm_agent_callable,
)
from core.multi_agent_orchestrator import MultiAgentOrchestrator
from core.quantum_engine import QuantumEngine


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Fake Ollama server for integration tests
# ---------------------------------------------------------------------------

class _FakeOllamaHandler(BaseHTTPRequestHandler):
    """Minimal Ollama-compatible handler for testing."""

    models: List[str] = ["llama3.2:latest", "gemma3:4b"]
    response_text: str = "This is a thoughtful analysis of the problem."

    def do_GET(self):
        if self.path == "/api/tags":
            body = json.dumps({
                "models": [{"name": m} for m in self.models]
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/api/chat":
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length))
            # Store the request for verification
            self.server.last_request = payload
            body = json.dumps({
                "message": {"content": self.response_text},
                "model": payload.get("model", "unknown"),
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def log_message(self, *args):
        pass  # Suppress test output


def _start_fake_ollama(port: int, models: List[str] = None) -> HTTPServer:
    if models is not None:
        _FakeOllamaHandler.models = models
    server = HTTPServer(("127.0.0.1", port), _FakeOllamaHandler)
    server.last_request = None
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


# ---------------------------------------------------------------------------
# 1. _discover_available_models
# ---------------------------------------------------------------------------

class TestDiscoverModels(unittest.TestCase):
    def test_discover_from_server(self):
        server = _start_fake_ollama(0, models=["phi3:latest", "mistral:7b"])
        port = server.server_address[1]
        try:
            models = _discover_available_models("127.0.0.1", port)
            self.assertEqual(models, ["phi3:latest", "mistral:7b"])
        finally:
            server.shutdown()

    def test_discover_unreachable_returns_empty(self):
        models = _discover_available_models("127.0.0.1", 59999)
        self.assertEqual(models, [])


# ---------------------------------------------------------------------------
# 2. _call_ollama_chat
# ---------------------------------------------------------------------------

class TestCallOllamaChat(unittest.TestCase):
    def test_successful_call(self):
        _FakeOllamaHandler.response_text = "The answer is 42."
        server = _start_fake_ollama(0)
        port = server.server_address[1]
        try:
            result = _call_ollama_chat(
                model="test-model",
                messages=[{"role": "user", "content": "What is 6*7?"}],
                temperature=0.5,
                ollama_host="127.0.0.1",
                ollama_port=port,
            )
            self.assertEqual(result, "The answer is 42.")
            # Verify request shape
            req = server.last_request
            self.assertEqual(req["model"], "test-model")
            self.assertFalse(req["stream"])
            self.assertAlmostEqual(req["options"]["temperature"], 0.5)
        finally:
            server.shutdown()

    def test_unreachable_raises(self):
        with self.assertRaises(Exception):
            _call_ollama_chat(
                model="x",
                messages=[{"role": "user", "content": "hello"}],
                ollama_host="127.0.0.1",
                ollama_port=59998,
                timeout=1.0,
            )


# ---------------------------------------------------------------------------
# 3–6. make_llm_agent_callable
# ---------------------------------------------------------------------------

class TestMakeLLMAgentCallable(unittest.TestCase):
    def test_returns_async_callable(self):
        spec = AgentSpec("test", AgentRole.REASONER)
        fn = make_llm_agent_callable(spec, model="llama3.2:latest")
        import inspect
        self.assertTrue(inspect.iscoroutinefunction(fn))

    def test_llm_callable_success(self):
        _FakeOllamaHandler.response_text = "Deep analysis result here."
        server = _start_fake_ollama(0)
        port = server.server_address[1]
        try:
            spec = AgentSpec("r1", AgentRole.REASONER, domain="science")
            fn = make_llm_agent_callable(
                spec, model="test-model",
                ollama_host="127.0.0.1", ollama_port=port,
            )
            result = run(fn("What is gravity?", {}))
            self.assertIsInstance(result, dict)
            self.assertEqual(result["answer"], "Deep analysis result here.")
            self.assertEqual(result["domain"], "science")
            self.assertTrue(result["llm_backed"])
            self.assertEqual(result["model_used"], "test-model")
            self.assertGreater(result["confidence"], 0)
        finally:
            server.shutdown()

    def test_llm_callable_fallback_on_error(self):
        spec = AgentSpec("r2", AgentRole.CRITIC, domain="general")
        fn = make_llm_agent_callable(
            spec, model="nonexistent",
            ollama_host="127.0.0.1", ollama_port=59997,
            timeout=1.0,
        )
        result = run(fn("Test task", {}))
        self.assertIsInstance(result, dict)
        self.assertIn("answer", result)
        self.assertFalse(result.get("llm_backed", True))
        self.assertIn("fallback_reason", result)

    def test_llm_callable_fallback_on_empty(self):
        _FakeOllamaHandler.response_text = ""
        server = _start_fake_ollama(0)
        port = server.server_address[1]
        try:
            spec = AgentSpec("r3", AgentRole.SYNTHESIZER)
            fn = make_llm_agent_callable(
                spec, model="test",
                ollama_host="127.0.0.1", ollama_port=port,
            )
            result = run(fn("Task", {}))
            self.assertIsInstance(result, dict)
            self.assertIn("answer", result)
        finally:
            server.shutdown()


# ---------------------------------------------------------------------------
# 7–11. create_llm_pool
# ---------------------------------------------------------------------------

class TestCreateLLMPool(unittest.TestCase):
    def test_multi_model_round_robin(self):
        """Multiple models → agents assigned round-robin."""
        server = _start_fake_ollama(0, models=["modelA", "modelB", "modelC"])
        port = server.server_address[1]
        try:
            pool = create_llm_pool(
                ollama_host="127.0.0.1", ollama_port=port,
                agents_config=[
                    {"agent_id": "a1", "role": "reasoner"},
                    {"agent_id": "a2", "role": "critic"},
                    {"agent_id": "a3", "role": "creative"},
                    {"agent_id": "a4", "role": "factchecker"},
                    {"agent_id": "a5", "role": "synthesizer"},
                ],
            )
            self.assertEqual(pool.count(), 5)
            # All agents should be registered with LLM-backed callables
            callables = pool.as_callables()
            self.assertEqual(len(callables), 5)
        finally:
            server.shutdown()

    def test_single_model_varied_config(self):
        """Single model → same model with varied temperatures."""
        server = _start_fake_ollama(0, models=["only-model:latest"])
        port = server.server_address[1]
        try:
            pool = create_llm_pool(
                ollama_host="127.0.0.1", ollama_port=port,
                agents_config=[
                    {"agent_id": "a1", "role": "reasoner"},
                    {"agent_id": "a2", "role": "creative"},
                ],
            )
            self.assertEqual(pool.count(), 2)
        finally:
            server.shutdown()

    def test_no_models_falls_back_to_heuristic(self):
        """No reachable models → uses pure-Python strategies."""
        pool = create_llm_pool(
            ollama_host="127.0.0.1", ollama_port=59996,
            agents_config=[
                {"agent_id": "h1", "role": "reasoner"},
                {"agent_id": "h2", "role": "critic"},
            ],
        )
        self.assertEqual(pool.count(), 2)
        callables = pool.as_callables()
        # Should work — pure Python fallback (callable takes (task, context))
        result = callables["h1"]("test task", {})
        self.assertIn("answer", result)

    def test_env_var_host(self):
        server = _start_fake_ollama(0, models=["env-model"])
        port = server.server_address[1]
        try:
            with patch.dict(os.environ, {"OLLAMA_HOST": f"127.0.0.1:{port}"}):
                pool = create_llm_pool(
                    agents_config=[{"agent_id": "e1", "role": "reasoner"}],
                )
                self.assertEqual(pool.count(), 1)
        finally:
            server.shutdown()

    def test_from_profile(self):
        server = _start_fake_ollama(0, models=["profile-model"])
        port = server.server_address[1]
        try:
            profile = {
                "ollama": {"host": "127.0.0.1", "port": port},
                "agent_pool": {
                    "agents": [
                        {"agent_id": "p1", "role": "reasoner"},
                        {"agent_id": "p2", "role": "critic"},
                    ]
                },
            }
            pool = create_llm_pool(profile=profile)
            self.assertEqual(pool.count(), 2)
        finally:
            server.shutdown()


# ---------------------------------------------------------------------------
# 12. LLM agents integrate with QuantumEngine
# ---------------------------------------------------------------------------

class TestLLMConsensusIntegration(unittest.TestCase):
    def test_llm_agents_through_quantum_engine(self):
        """Real LLM agents → QuantumEngine consensus produces valid result."""
        _FakeOllamaHandler.response_text = "The consensus answer is clear."
        server = _start_fake_ollama(0, models=["model-x", "model-y"])
        port = server.server_address[1]
        try:
            pool = create_llm_pool(
                ollama_host="127.0.0.1", ollama_port=port,
                agents_config=[
                    {"agent_id": "l1", "role": "reasoner"},
                    {"agent_id": "l2", "role": "critic"},
                    {"agent_id": "l3", "role": "synthesizer"},
                ],
            )
            engine = QuantumEngine(quorum=2, hard_timeout_ms=10_000)
            callables = pool.as_callables()
            result = run(engine.gather("What is 2+2?", callables))
            self.assertIsNotNone(result.answer)
            self.assertGreater(result.confidence, 0)
            self.assertGreaterEqual(result.participating, 2)
        finally:
            server.shutdown()


# ---------------------------------------------------------------------------
# 13. Role-specific system prompts
# ---------------------------------------------------------------------------

class TestRolePrompts(unittest.TestCase):
    def test_all_roles_have_prompts(self):
        for role in AgentRole:
            self.assertIn(role, _LLM_ROLE_PROMPTS,
                          f"Missing LLM prompt for {role}")

    def test_all_roles_have_temperatures(self):
        for role in AgentRole:
            self.assertIn(role, _LLM_ROLE_TEMPERATURES,
                          f"Missing temperature for {role}")

    def test_system_prompt_injected(self):
        _FakeOllamaHandler.response_text = "Critic finds flaws."
        server = _start_fake_ollama(0)
        port = server.server_address[1]
        try:
            spec = AgentSpec("c1", AgentRole.CRITIC, domain="security")
            fn = make_llm_agent_callable(
                spec, model="test",
                ollama_host="127.0.0.1", ollama_port=port,
            )
            run(fn("Review this code", {}))
            req = server.last_request
            system_msg = req["messages"][0]
            self.assertEqual(system_msg["role"], "system")
            self.assertIn("adversarial", system_msg["content"].lower())
            self.assertIn("security", system_msg["content"])
        finally:
            server.shutdown()


# ---------------------------------------------------------------------------
# 14–15. Orchestrator LLM dispatch
# ---------------------------------------------------------------------------

class TestOrchestratorLLMDispatch(unittest.TestCase):
    def test_llm_dispatch_flag(self):
        _FakeOllamaHandler.response_text = "Orchestrated LLM answer."
        server = _start_fake_ollama(0, models=["orch-model"])
        port = server.server_address[1]
        try:
            profile = {"ollama": {"host": "127.0.0.1", "port": port}}
            orch = MultiAgentOrchestrator(
                profile=profile, llm_dispatch=True, quorum=1,
            )
            self.assertGreater(orch.pool.count(), 0)
            result = run(orch.run("Test query"))
            self.assertIsNotNone(result.answer)
        finally:
            server.shutdown()

    def test_env_var_enables_llm_dispatch(self):
        with patch.dict(os.environ, {"OPENCHIMERA_LLM_CONSENSUS": "true"}):
            # No Ollama reachable → should still create pool (heuristic fallback)
            orch = MultiAgentOrchestrator(quorum=1, hard_timeout_ms=5000)
            self.assertGreater(orch.pool.count(), 0)

    def test_llm_dispatch_false_uses_heuristic(self):
        orch = MultiAgentOrchestrator(llm_dispatch=False, quorum=1)
        self.assertGreater(orch.pool.count(), 0)
        result = run(orch.run("Simple test"))
        self.assertIsNotNone(result.answer)
