from __future__ import annotations

import asyncio
import os
import pathlib
import struct
import tempfile
import unittest
from typing import Any

from core._bus_fallback import EventBus
from core._database_fallback import DatabaseManager
from core.memory_system import MemorySystem
from core.memory.episodic import EpisodicMemory
from core.memory.working import WorkingMemory
from core.memory.semantic import SemanticMemory


def run(coro):
    return asyncio.run(coro)


def _make_env():
    """Create a fresh DB using a temp file so all connections share state."""
    bus = EventBus()
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db = DatabaseManager(tmp.name)
    db.initialize()
    return db, bus, tmp.name


def _cleanup(path):
    try:
        os.unlink(path)
    except OSError:
        pass


# ── MemorySystem tests ────────────────────────────────────────────────


class TestMemorySystemInit(unittest.TestCase):
    def setUp(self):
        self.db, self.bus, self._tmp = _make_env()
        self.ms = MemorySystem(self.db, self.bus)

    def tearDown(self):
        _cleanup(self._tmp)

    def test_working_property_type(self):
        self.assertIsInstance(self.ms.working, WorkingMemory)

    def test_episodic_property_type(self):
        self.assertIsInstance(self.ms.episodic, EpisodicMemory)

    def test_semantic_property_type(self):
        self.assertIsInstance(self.ms.semantic, SemanticMemory)

    def test_custom_working_max_size(self):
        ms2 = MemorySystem(self.db, self.bus, working_max_size=4)
        for i in range(6):
            ms2.cache_put(f"k{i}", i)
        self.assertLessEqual(len(ms2.working), 4)


class TestMemorySystemCache(unittest.TestCase):
    def setUp(self):
        self.db, self.bus, self._tmp = _make_env()
        self.ms = MemorySystem(self.db, self.bus)

    def tearDown(self):
        _cleanup(self._tmp)

    def test_cache_put_get_roundtrip(self):
        self.ms.cache_put("alpha", {"v": 42})
        self.assertEqual(self.ms.cache_get("alpha"), {"v": 42})

    def test_cache_get_missing_returns_none(self):
        self.assertIsNone(self.ms.cache_get("nonexistent"))

    def test_cache_overwrite(self):
        self.ms.cache_put("key", 1)
        self.ms.cache_put("key", 2)
        self.assertEqual(self.ms.cache_get("key"), 2)


class TestMemorySystemEpisodic(unittest.TestCase):
    def setUp(self):
        self.db, self.bus, self._tmp = _make_env()
        self.ms = MemorySystem(self.db, self.bus)

    def tearDown(self):
        _cleanup(self._tmp)

    def _record(self, **kw):
        defaults = dict(
            session_id="sess-1",
            goal="solve task",
            outcome="success",
            confidence_initial=0.5,
            confidence_final=0.9,
            models_used=["gpt-4"],
            reasoning_chain=["step1", "step2"],
        )
        defaults.update(kw)
        return self.ms.record_episode(**defaults)

    def test_record_episode_returns_dict_with_episode_id(self):
        ep = self._record()
        self.assertIsInstance(ep, dict)
        self.assertIn("id", ep)

    def test_record_episode_stores_fields(self):
        ep = self._record(goal="test goal", outcome="failure", failure_reason="oops")
        self.assertEqual(ep["goal"], "test goal")
        self.assertEqual(ep["outcome"], "failure")
        self.assertEqual(ep["failure_reason"], "oops")

    def test_find_similar_episodes_matching(self):
        emb = struct.pack("3f", 1.0, 0.0, 0.0)
        self._record(embedding=emb)
        results = self.ms.find_similar_episodes(emb, limit=5)
        self.assertGreaterEqual(len(results), 1)
        self.assertIn("similarity", results[0])
        self.assertGreater(results[0]["similarity"], 0.9)

    def test_find_similar_episodes_no_embeddings(self):
        self._record()  # no embedding
        emb = struct.pack("3f", 1.0, 0.0, 0.0)
        results = self.ms.find_similar_episodes(emb)
        self.assertEqual(results, [])


class TestMemorySystemSemantic(unittest.TestCase):
    def setUp(self):
        self.db, self.bus, self._tmp = _make_env()
        self.ms = MemorySystem(self.db, self.bus)

    def tearDown(self):
        _cleanup(self._tmp)

    def test_add_and_query_knowledge(self):
        self.ms.add_knowledge("Python", "is_a", "Language")
        triples = self.ms.query_knowledge(subject="Python")
        self.assertGreaterEqual(len(triples), 1)
        t = triples[0]
        self.assertEqual(t["subject"], "Python")
        self.assertEqual(t["predicate"], "is_a")
        self.assertEqual(t["object"], "Language")

    def test_query_knowledge_by_predicate(self):
        self.ms.add_knowledge("A", "rel", "B")
        self.ms.add_knowledge("C", "other", "D")
        results = self.ms.query_knowledge(predicate="rel")
        self.assertTrue(all(r["predicate"] == "rel" for r in results))

    def test_query_knowledge_empty(self):
        results = self.ms.query_knowledge(subject="ghost")
        self.assertEqual(results, [])

    def test_explore_entity_with_triples(self):
        self.ms.add_knowledge("Node1", "conn", "Node2")
        self.ms.add_knowledge("Node2", "conn", "Node3")
        graph = self.ms.explore_entity("Node1", depth=2)
        self.assertIn("nodes", graph)
        self.assertIn("edges", graph)
        node_ids = {n["id"] for n in graph["nodes"]}
        self.assertIn("Node1", node_ids)

    def test_explore_entity_unknown(self):
        graph = self.ms.explore_entity("unknown_entity")
        self.assertIn("nodes", graph)


class TestMemorySystemStoreAndLink(unittest.TestCase):
    def setUp(self):
        self.db, self.bus, self._tmp = _make_env()
        self.ms = MemorySystem(self.db, self.bus)
        self.events: list[dict] = []
        self.bus.subscribe("memory.linked", lambda e: self.events.append(e))

    def tearDown(self):
        _cleanup(self._tmp)

    def _base_kwargs(self):
        return dict(
            session_id="sess-link",
            goal="link test",
            outcome="success",
            confidence_initial=0.6,
            confidence_final=0.95,
            models_used=["model-a"],
            reasoning_chain=["r1"],
        )

    def test_store_and_link_with_triples(self):
        triples = [("X", "rel", "Y"), ("Y", "rel", "Z")]
        result = self.ms.store_and_link(
            **self._base_kwargs(), knowledge_triples=triples
        )
        self.assertIn("episode", result)
        self.assertEqual(result["triples_added"], 2)
        self.assertIn("id", result["episode"])

    def test_store_and_link_publishes_bus_event(self):
        self.ms.store_and_link(
            **self._base_kwargs(),
            knowledge_triples=[("A", "b", "C")],
        )
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.events[0]["triples_added"], 1)

    def test_store_and_link_without_triples(self):
        result = self.ms.store_and_link(**self._base_kwargs())
        self.assertEqual(result["triples_added"], 0)
        self.assertIn("id", result["episode"])


class TestMemorySystemSummary(unittest.TestCase):
    def setUp(self):
        self.db, self.bus, self._tmp = _make_env()
        self.ms = MemorySystem(self.db, self.bus)

    def tearDown(self):
        _cleanup(self._tmp)

    def test_summary_keys(self):
        s = self.ms.summary()
        for key in (
            "working_size",
            "working_snapshot",
            "episodic_recent",
            "semantic_assertions",
            "knowledge_triples_sample",
        ):
            self.assertIn(key, s, f"Missing summary key: {key}")

    def test_summary_working_size_reflects_cache(self):
        self.ms.cache_put("x", 1)
        self.ms.cache_put("y", 2)
        s = self.ms.summary()
        self.assertEqual(s["working_size"], 2)


# ── EpisodicMemory direct tests ──────────────────────────────────────


class TestEpisodicMemoryDirect(unittest.TestCase):
    def setUp(self):
        self.db, self.bus, self._tmp = _make_env()
        self.ep = EpisodicMemory(db=self.db, bus=self.bus)
        self.events: list[dict] = []
        self.bus.subscribe(
            "memory.episode.recorded", lambda e: self.events.append(e)
        )

    def tearDown(self):
        _cleanup(self._tmp)

    def _record(self, **kw):
        defaults = dict(
            session_id="s1",
            goal="goal",
            outcome="success",
            confidence_initial=0.5,
            confidence_final=0.8,
            models_used=["m1"],
            reasoning_chain=["chain"],
        )
        defaults.update(kw)
        return self.ep.record_episode(**defaults)

    def test_record_and_get_roundtrip(self):
        ep = self._record()
        eid = ep["id"]
        fetched = self.ep.get_episode(eid)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["id"], eid)

    def test_record_publishes_event(self):
        self._record()
        self.assertEqual(len(self.events), 1)
        self.assertIn("episode_id", self.events[0])

    def test_list_episodes_returns_recorded(self):
        self._record()
        self._record()
        eps = self.ep.list_episodes()
        self.assertGreaterEqual(len(eps), 2)

    def test_list_episodes_filter_by_session(self):
        self._record(session_id="sA")
        self._record(session_id="sB")
        eps = self.ep.list_episodes(session_id="sA")
        self.assertTrue(all(e["session_id"] == "sA" for e in eps))

    def test_list_episodes_filter_by_domain(self):
        self._record(domain="code")
        self._record(domain="math")
        eps = self.ep.list_episodes(domain="code")
        self.assertTrue(all(e["domain"] == "code" for e in eps))

    def test_list_episodes_filter_by_outcome(self):
        self._record(outcome="success")
        self._record(outcome="failure", failure_reason="err")
        eps = self.ep.list_episodes(outcome="failure")
        self.assertTrue(all(e["outcome"] == "failure" for e in eps))

    def test_get_episode_missing_returns_none(self):
        self.assertIsNone(self.ep.get_episode("nonexistent"))


class TestEpisodicMemoryPostmortem(unittest.TestCase):
    def setUp(self):
        self.db, self.bus, self._tmp = _make_env()
        self.ep = EpisodicMemory(db=self.db, bus=self.bus)
        self.pm_events: list[dict] = []
        self.bus.subscribe(
            "memory.postmortem.recorded", lambda e: self.pm_events.append(e)
        )

    def tearDown(self):
        _cleanup(self._tmp)

    def _record_episode(self):
        return self.ep.record_episode(
            session_id="pm-sess",
            goal="fail task",
            outcome="failure",
            confidence_initial=0.7,
            confidence_final=0.1,
            models_used=["m1"],
            reasoning_chain=["tried"],
            failure_reason="bad logic",
        )

    def test_record_postmortem_and_get(self):
        ep = self._record_episode()
        eid = ep["id"]
        pm = self.ep.record_postmortem(
            episode_id=eid,
            failure_mode="logic_error",
            contributing_models=["m1"],
            prevention_hypothesis="add validation",
        )
        self.assertIn("id", pm)
        pms = self.ep.get_postmortems(eid)
        self.assertEqual(len(pms), 1)
        self.assertEqual(pms[0]["failure_mode"], "logic_error")

    def test_postmortem_publishes_event(self):
        ep = self._record_episode()
        self.ep.record_postmortem(
            episode_id=ep["id"],
            failure_mode="timeout",
            contributing_models=["m2"],
            prevention_hypothesis="increase timeout",
        )
        self.assertEqual(len(self.pm_events), 1)
        self.assertEqual(self.pm_events[0]["failure_mode"], "timeout")

    def test_get_postmortems_empty_for_no_postmortems(self):
        ep = self._record_episode()
        pms = self.ep.get_postmortems(ep["id"])
        self.assertEqual(pms, [])


class TestEpisodicMemoryCurated(unittest.TestCase):
    def setUp(self):
        self.db, self.bus, self._tmp = _make_env()
        self.ep = EpisodicMemory(db=self.db, bus=self.bus)

    def tearDown(self):
        _cleanup(self._tmp)

    def test_mark_curated(self):
        ep = self.ep.record_episode(
            session_id="cur",
            goal="g",
            outcome="success",
            confidence_initial=0.5,
            confidence_final=0.9,
            models_used=["m"],
            reasoning_chain=["c"],
        )
        result = self.ep.mark_curated(ep["id"])
        self.assertTrue(result)
        fetched = self.ep.get_episode(ep["id"])
        self.assertEqual(fetched.get("curated"), 1)

    def test_mark_curated_idempotent(self):
        ep = self.ep.record_episode(
            session_id="cur2",
            goal="g2",
            outcome="success",
            confidence_initial=0.5,
            confidence_final=0.9,
            models_used=["m"],
            reasoning_chain=["c"],
        )
        self.ep.mark_curated(ep["id"])
        result = self.ep.mark_curated(ep["id"])
        self.assertTrue(result)


class TestEpisodicMemoryFindSimilar(unittest.TestCase):
    def setUp(self):
        self.db, self.bus, self._tmp = _make_env()
        self.ep = EpisodicMemory(db=self.db, bus=self.bus)

    def tearDown(self):
        _cleanup(self._tmp)

    def _record(self, emb, **kw):
        defaults = dict(
            session_id="sim",
            goal="g",
            outcome="success",
            confidence_initial=0.5,
            confidence_final=0.8,
            models_used=["m"],
            reasoning_chain=["c"],
            embedding=emb,
        )
        defaults.update(kw)
        return self.ep.record_episode(**defaults)

    def test_find_similar_identical_embedding(self):
        emb = struct.pack("3f", 1.0, 0.0, 0.0)
        self._record(emb)
        results = self.ep.find_similar(emb, limit=5)
        self.assertEqual(len(results), 1)
        self.assertIn("similarity", results[0])
        self.assertAlmostEqual(results[0]["similarity"], 1.0, places=4)

    def test_find_similar_orthogonal_embedding(self):
        emb_a = struct.pack("3f", 1.0, 0.0, 0.0)
        emb_b = struct.pack("3f", 0.0, 1.0, 0.0)
        self._record(emb_a)
        results = self.ep.find_similar(emb_b, limit=5)
        self.assertEqual(len(results), 1)
        self.assertAlmostEqual(results[0]["similarity"], 0.0, places=4)

    def test_find_similar_ordering(self):
        emb_query = struct.pack("3f", 1.0, 0.0, 0.0)
        emb_close = struct.pack("3f", 0.9, 0.1, 0.0)
        emb_far = struct.pack("3f", 0.0, 0.0, 1.0)
        self._record(emb_close, session_id="close")
        self._record(emb_far, session_id="far")
        results = self.ep.find_similar(emb_query, limit=5)
        self.assertEqual(len(results), 2)
        self.assertGreater(results[0]["similarity"], results[1]["similarity"])

    def test_find_similar_respects_limit(self):
        for i in range(5):
            emb = struct.pack("3f", float(i), 1.0, 0.0)
            self._record(emb, session_id=f"s{i}")
        query = struct.pack("3f", 1.0, 1.0, 0.0)
        results = self.ep.find_similar(query, limit=2)
        self.assertLessEqual(len(results), 2)

    def test_find_similar_empty_db(self):
        emb = struct.pack("3f", 1.0, 0.0, 0.0)
        results = self.ep.find_similar(emb)
        self.assertEqual(results, [])


# ── Bus event capture pattern ─────────────────────────────────────────


class TestBusEventCapture(unittest.TestCase):
    def setUp(self):
        self.db, self.bus, self._tmp = _make_env()
        self.ms = MemorySystem(self.db, self.bus)

    def tearDown(self):
        _cleanup(self._tmp)

    def test_episode_recorded_event_captured(self):
        events: list[dict] = []
        self.bus.subscribe("memory.episode.recorded", lambda e: events.append(e))
        self.ms.record_episode(
            session_id="ev",
            goal="g",
            outcome="success",
            confidence_initial=0.5,
            confidence_final=0.9,
            models_used=["m"],
            reasoning_chain=["c"],
        )
        self.assertEqual(len(events), 1)
        self.assertIn("episode_id", events[0])
        self.assertEqual(events[0]["outcome"], "success")

    def test_triple_added_event_captured(self):
        events: list[dict] = []
        self.bus.subscribe("memory.triple.added", lambda e: events.append(e))
        self.ms.add_knowledge("A", "knows", "B")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["subject"], "A")


if __name__ == "__main__":
    unittest.main()
