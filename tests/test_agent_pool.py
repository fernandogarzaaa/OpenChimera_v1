"""Tests for core.agent_pool — portable typed multi-agent framework.

Covers:
  1.  AgentRole enum members
  2.  AgentSpec frozen dataclass
  3.  AgentStatus enum
  4.  Built-in strategy functions produce correct shape
  5.  make_agent_callable with built-in strategy
  6.  make_agent_callable with external function
  7.  AgentPool register / unregister
  8.  AgentPool disable / enable
  9.  AgentPool.as_callables with domain filter
  10. AgentPool.as_callables with role filter
  11. AgentPool.as_callables with tag filter
  12. AgentPool.list_agents metadata
  13. AgentPool duplicate registration raises ValueError
  14. create_pool from explicit agents_config
  15. create_pool from profile dict
  16. create_pool from OPENCHIMERA_AGENTS env var
  17. create_pool falls back to DEFAULT_AGENTS
  18. create_pool handles invalid env var gracefully
  19. count / active_count reflect disabling
  20. get_spec returns correct spec
"""
from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from core.agent_pool import (
    DEFAULT_AGENTS,
    AgentPool,
    AgentRole,
    AgentSpec,
    AgentStatus,
    create_pool,
    make_agent_callable,
    _reasoner_strategy,
    _creative_strategy,
    _critic_strategy,
    _factchecker_strategy,
    _synthesizer_strategy,
    _explorer_strategy,
    _specialist_strategy,
)


# ---------------------------------------------------------------------------
# 1. AgentRole enum
# ---------------------------------------------------------------------------

class TestAgentRole(unittest.TestCase):
    def test_all_roles_exist(self):
        roles = [r.value for r in AgentRole]
        self.assertIn("reasoner", roles)
        self.assertIn("creative", roles)
        self.assertIn("critic", roles)
        self.assertIn("factchecker", roles)
        self.assertIn("synthesizer", roles)
        self.assertIn("specialist", roles)
        self.assertIn("explorer", roles)

    def test_string_identity(self):
        self.assertEqual(AgentRole.REASONER, "reasoner")
        self.assertEqual(AgentRole.CRITIC, "critic")


# ---------------------------------------------------------------------------
# 2. AgentSpec frozen dataclass
# ---------------------------------------------------------------------------

class TestAgentSpec(unittest.TestCase):
    def test_default_values(self):
        spec = AgentSpec(agent_id="a1", role=AgentRole.REASONER)
        self.assertEqual(spec.domain, "general")
        self.assertAlmostEqual(spec.temperature, 0.5)
        self.assertEqual(spec.system_prompt, "")
        self.assertEqual(spec.max_tokens, 512)
        self.assertEqual(spec.tags, ())

    def test_frozen(self):
        spec = AgentSpec(agent_id="a1", role=AgentRole.CRITIC)
        with self.assertRaises(AttributeError):
            spec.domain = "finance"  # type: ignore[misc]

    def test_custom_values(self):
        spec = AgentSpec(
            agent_id="x", role=AgentRole.SPECIALIST,
            domain="medical", temperature=0.9,
            system_prompt="Be precise.", max_tokens=1024,
            tags=("icu", "cardiology"),
        )
        self.assertEqual(spec.domain, "medical")
        self.assertAlmostEqual(spec.temperature, 0.9)
        self.assertEqual(spec.tags, ("icu", "cardiology"))


# ---------------------------------------------------------------------------
# 3. AgentStatus enum
# ---------------------------------------------------------------------------

class TestAgentStatus(unittest.TestCase):
    def test_values(self):
        self.assertEqual(AgentStatus.IDLE.value, "idle")
        self.assertEqual(AgentStatus.BUSY.value, "busy")
        self.assertEqual(AgentStatus.DISABLED.value, "disabled")


# ---------------------------------------------------------------------------
# 4. Built-in strategy functions
# ---------------------------------------------------------------------------

class TestStrategies(unittest.TestCase):
    def _run_strategy(self, fn, role: AgentRole):
        spec = AgentSpec(agent_id="test", role=role, domain="test")
        result = fn("some task", spec, {})
        self.assertIn("answer", result)
        self.assertIn("confidence", result)
        self.assertIn("domain", result)
        self.assertIsInstance(result["answer"], str)
        self.assertTrue(0 <= result["confidence"] <= 1.0)
        return result

    def test_reasoner(self):
        r = self._run_strategy(_reasoner_strategy, AgentRole.REASONER)
        self.assertIn("reasoner", r["answer"])

    def test_creative(self):
        r = self._run_strategy(_creative_strategy, AgentRole.CREATIVE)
        self.assertIn("creative", r["answer"])

    def test_critic(self):
        r = self._run_strategy(_critic_strategy, AgentRole.CRITIC)
        self.assertIn("critic", r["answer"])

    def test_factchecker(self):
        r = self._run_strategy(_factchecker_strategy, AgentRole.FACTCHECKER)
        self.assertIn("factchecker", r["answer"])

    def test_synthesizer(self):
        r = self._run_strategy(_synthesizer_strategy, AgentRole.SYNTHESIZER)
        self.assertIn("synthesizer", r["answer"])

    def test_explorer(self):
        r = self._run_strategy(_explorer_strategy, AgentRole.EXPLORER)
        self.assertIn("explorer", r["answer"])

    def test_specialist(self):
        r = self._run_strategy(_specialist_strategy, AgentRole.SPECIALIST)
        self.assertIn("specialist", r["answer"])


# ---------------------------------------------------------------------------
# 5–6. make_agent_callable
# ---------------------------------------------------------------------------

class TestMakeAgentCallable(unittest.TestCase):
    def test_builtin_strategy(self):
        spec = AgentSpec(agent_id="r1", role=AgentRole.REASONER)
        fn = make_agent_callable(spec)
        result = fn("task-1", {})
        self.assertIsInstance(result, dict)
        self.assertIn("answer", result)

    def test_external_function(self):
        spec = AgentSpec(agent_id="ext", role=AgentRole.SPECIALIST)

        def custom(task, ctx):
            return {"answer": f"custom:{task}", "confidence": 0.99}

        fn = make_agent_callable(spec, external_fn=custom)
        result = fn("hello", {})
        self.assertEqual(result["answer"], "custom:hello")

    def test_qualname_set(self):
        spec = AgentSpec(agent_id="qa-test", role=AgentRole.CRITIC)
        fn = make_agent_callable(spec)
        self.assertIn("qa-test", fn.__qualname__)


# ---------------------------------------------------------------------------
# 7–8. AgentPool register / unregister / disable / enable
# ---------------------------------------------------------------------------

class TestAgentPoolLifecycle(unittest.TestCase):
    def test_register_and_count(self):
        pool = AgentPool()
        pool.register(AgentSpec("a1", AgentRole.REASONER))
        pool.register(AgentSpec("a2", AgentRole.CRITIC))
        self.assertEqual(pool.count(), 2)
        self.assertEqual(pool.active_count(), 2)

    def test_unregister(self):
        pool = AgentPool()
        pool.register(AgentSpec("a1", AgentRole.REASONER))
        pool.unregister("a1")
        self.assertEqual(pool.count(), 0)

    def test_unregister_nonexistent_is_safe(self):
        pool = AgentPool()
        pool.unregister("ghost")  # Should not raise

    def test_disable_and_enable(self):
        pool = AgentPool()
        pool.register(AgentSpec("a1", AgentRole.REASONER))
        pool.disable("a1")
        self.assertEqual(pool.active_count(), 0)
        # Disabled agent excluded from callables
        self.assertEqual(len(pool.as_callables()), 0)
        pool.enable("a1")
        self.assertEqual(pool.active_count(), 1)
        self.assertEqual(len(pool.as_callables()), 1)

    def test_duplicate_registration_raises(self):
        pool = AgentPool()
        pool.register(AgentSpec("dup", AgentRole.CRITIC))
        with self.assertRaises(ValueError):
            pool.register(AgentSpec("dup", AgentRole.REASONER))


# ---------------------------------------------------------------------------
# 9–11. as_callables filters
# ---------------------------------------------------------------------------

class TestAgentPoolFilters(unittest.TestCase):
    def setUp(self):
        self.pool = AgentPool()
        self.pool.register(AgentSpec("med-1", AgentRole.SPECIALIST, domain="medical"))
        self.pool.register(AgentSpec("fin-1", AgentRole.REASONER, domain="finance"))
        self.pool.register(AgentSpec("gen-1", AgentRole.CRITIC, domain="general"))
        self.pool.register(AgentSpec(
            "tag-1", AgentRole.SYNTHESIZER, tags=("icu", "priority"),
        ))

    def test_domain_filter(self):
        callables = self.pool.as_callables(domain="medical")
        self.assertIn("med-1", callables)
        # "general" domain agents are always included
        self.assertIn("gen-1", callables)
        # finance excluded
        self.assertNotIn("fin-1", callables)

    def test_role_filter(self):
        callables = self.pool.as_callables(roles=[AgentRole.CRITIC])
        self.assertIn("gen-1", callables)
        self.assertNotIn("med-1", callables)
        self.assertNotIn("fin-1", callables)

    def test_tag_filter(self):
        callables = self.pool.as_callables(tags=["icu"])
        self.assertIn("tag-1", callables)

    def test_no_filter_returns_all(self):
        callables = self.pool.as_callables()
        self.assertEqual(len(callables), 4)


# ---------------------------------------------------------------------------
# 12. list_agents metadata
# ---------------------------------------------------------------------------

class TestAgentPoolMetadata(unittest.TestCase):
    def test_list_agents(self):
        pool = AgentPool()
        pool.register(AgentSpec("a1", AgentRole.REASONER, domain="math"))
        agents = pool.list_agents()
        self.assertEqual(len(agents), 1)
        agent = agents[0]
        self.assertEqual(agent["agent_id"], "a1")
        self.assertEqual(agent["role"], "reasoner")
        self.assertEqual(agent["domain"], "math")

    def test_get_spec(self):
        pool = AgentPool()
        spec = AgentSpec("lookup", AgentRole.EXPLORER)
        pool.register(spec)
        self.assertIs(pool.get_spec("lookup"), spec)
        self.assertIsNone(pool.get_spec("nonexistent"))


# ---------------------------------------------------------------------------
# 14–18. create_pool builder
# ---------------------------------------------------------------------------

class TestCreatePool(unittest.TestCase):
    def test_from_explicit_config(self):
        config = [
            {"agent_id": "x1", "role": "reasoner"},
            {"agent_id": "x2", "role": "critic", "domain": "law"},
        ]
        pool = create_pool(agents_config=config)
        self.assertEqual(pool.count(), 2)
        self.assertIsNotNone(pool.get_spec("x1"))
        self.assertEqual(pool.get_spec("x2").domain, "law")

    def test_from_profile(self):
        profile = {
            "agent_pool": {
                "agents": [
                    {"agent_id": "p1", "role": "synthesizer"},
                ]
            }
        }
        pool = create_pool(profile=profile)
        self.assertEqual(pool.count(), 1)
        self.assertEqual(pool.get_spec("p1").role, AgentRole.SYNTHESIZER)

    def test_from_env_var(self):
        env_json = json.dumps([
            {"agent_id": "env-agent", "role": "explorer"},
        ])
        with patch.dict(os.environ, {"OPENCHIMERA_AGENTS": env_json}):
            pool = create_pool()
        self.assertEqual(pool.count(), 1)
        self.assertEqual(pool.get_spec("env-agent").role, AgentRole.EXPLORER)

    def test_invalid_env_falls_back(self):
        with patch.dict(os.environ, {"OPENCHIMERA_AGENTS": "NOT-JSON"}):
            pool = create_pool()
        # Should fall back to DEFAULT_AGENTS
        self.assertEqual(pool.count(), len(DEFAULT_AGENTS))

    def test_default_fallback(self):
        # No profile, no env var → defaults
        with patch.dict(os.environ, {}, clear=True):
            # Remove OPENCHIMERA_AGENTS if it exists
            os.environ.pop("OPENCHIMERA_AGENTS", None)
            pool = create_pool()
        self.assertEqual(pool.count(), len(DEFAULT_AGENTS))

    def test_explicit_config_takes_priority(self):
        """Explicit agents_config wins over profile."""
        profile = {
            "agent_pool": {
                "agents": [{"agent_id": "profile-a", "role": "critic"}]
            }
        }
        config = [{"agent_id": "explicit-a", "role": "reasoner"}]
        pool = create_pool(profile=profile, agents_config=config)
        self.assertEqual(pool.count(), 1)
        self.assertIsNotNone(pool.get_spec("explicit-a"))
        self.assertIsNone(pool.get_spec("profile-a"))


# ---------------------------------------------------------------------------
# 19–20. count / active_count / get_spec
# ---------------------------------------------------------------------------

class TestPoolCounts(unittest.TestCase):
    def test_count_reflects_lifecycle(self):
        pool = AgentPool()
        self.assertEqual(pool.count(), 0)
        pool.register(AgentSpec("a", AgentRole.REASONER))
        self.assertEqual(pool.count(), 1)
        self.assertEqual(pool.active_count(), 1)
        pool.disable("a")
        self.assertEqual(pool.count(), 1)     # Still registered
        self.assertEqual(pool.active_count(), 0)  # But not active
        pool.unregister("a")
        self.assertEqual(pool.count(), 0)
        self.assertEqual(pool.active_count(), 0)


if __name__ == "__main__":
    unittest.main()
