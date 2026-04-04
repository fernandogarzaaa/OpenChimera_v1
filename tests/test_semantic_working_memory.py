from __future__ import annotations

import pathlib
import tempfile
import unittest

from core._bus_fallback import EventBus
from core._database_fallback import DatabaseManager
from core.memory.semantic import SemanticMemory
from core.memory.working import WorkingMemory

MIGRATIONS = pathlib.Path("core/migrations")


def _make_env() -> tuple[DatabaseManager, EventBus]:
    bus = EventBus()
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db = DatabaseManager(tmp.name, migrations_path=MIGRATIONS)
    db.initialize()
    return db, bus


class TestSemanticMemory(unittest.TestCase):
    """Tests for SemanticMemory knowledge-graph layer."""

    def setUp(self) -> None:
        self.db, self.bus = _make_env()
        self.mem = SemanticMemory(self.db, self.bus)

    # ---- add_triple / get_triples round-trip ----

    def test_add_and_get_triple_round_trip(self) -> None:
        self.mem.add_triple("Alice", "knows", "Bob")
        triples = self.mem.get_triples(subject="Alice")
        self.assertEqual(len(triples), 1)
        self.assertEqual(triples[0]["subject"], "Alice")
        self.assertEqual(triples[0]["predicate"], "knows")
        self.assertEqual(triples[0]["object"], "Bob")

    def test_get_triples_filter_by_subject(self) -> None:
        self.mem.add_triple("Alice", "knows", "Bob")
        self.mem.add_triple("Carol", "knows", "Dave")
        triples = self.mem.get_triples(subject="Alice")
        self.assertEqual(len(triples), 1)
        self.assertEqual(triples[0]["subject"], "Alice")

    def test_get_triples_filter_by_predicate(self) -> None:
        self.mem.add_triple("Alice", "knows", "Bob")
        self.mem.add_triple("Alice", "likes", "Carol")
        triples = self.mem.get_triples(predicate="likes")
        self.assertEqual(len(triples), 1)
        self.assertEqual(triples[0]["predicate"], "likes")

    def test_get_triples_filter_by_object(self) -> None:
        self.mem.add_triple("Alice", "knows", "Bob")
        self.mem.add_triple("Carol", "knows", "Bob")
        triples = self.mem.get_triples(object_="Bob")
        self.assertEqual(len(triples), 2)
        subjects = {t["subject"] for t in triples}
        self.assertEqual(subjects, {"Alice", "Carol"})

    def test_get_triples_min_confidence_filter(self) -> None:
        self.mem.add_triple("Alice", "knows", "Bob", confidence=0.9)
        self.mem.add_triple("Alice", "knows", "Carol", confidence=0.3)
        triples = self.mem.get_triples(min_confidence=0.5)
        self.assertEqual(len(triples), 1)
        self.assertEqual(triples[0]["object"], "Bob")

    # ---- remove_triple ----

    def test_remove_triple_removes_correctly(self) -> None:
        self.mem.add_triple("Alice", "knows", "Bob")
        result = self.mem.remove_triple("Alice", "knows", "Bob")
        self.assertTrue(result)
        triples = self.mem.get_triples(subject="Alice")
        self.assertEqual(len(triples), 0)

    def test_remove_triple_nonexistent_returns_true(self) -> None:
        # SQLite DELETE on no rows is not an error; method returns True
        result = self.mem.remove_triple("X", "Y", "Z")
        self.assertTrue(result)

    # ---- add_assertion ----

    def test_add_assertion_returns_dict_with_id(self) -> None:
        self.mem.add_triple("Alice", "knows", "Bob")
        assertion = self.mem.add_assertion(
            "Alice", "knows", "Bob", asserted_by="test"
        )
        self.assertIn("id", assertion)
        self.assertIsInstance(assertion["id"], str)
        self.assertTrue(len(assertion["id"]) > 0)

    def test_add_assertion_fields(self) -> None:
        self.mem.add_triple("Alice", "knows", "Bob")
        assertion = self.mem.add_assertion(
            "Alice", "knows", "Bob", asserted_by="observer"
        )
        self.assertEqual(assertion["subject"], "Alice")
        self.assertEqual(assertion["predicate"], "knows")
        self.assertEqual(assertion["object"], "Bob")
        self.assertEqual(assertion["asserted_by"], "observer")
        self.assertIsNone(assertion["valid_until"])

    # ---- get_active_assertions ----

    def test_get_active_assertions_returns_added(self) -> None:
        self.mem.add_triple("Alice", "knows", "Bob")
        self.mem.add_assertion("Alice", "knows", "Bob", asserted_by="test")
        active = self.mem.get_active_assertions()
        self.assertGreaterEqual(len(active), 1)
        self.assertEqual(active[0]["subject"], "Alice")

    def test_get_active_assertions_filtered(self) -> None:
        self.mem.add_triple("Alice", "knows", "Bob")
        self.mem.add_triple("Carol", "likes", "Dave")
        self.mem.add_assertion("Alice", "knows", "Bob", asserted_by="a")
        self.mem.add_assertion("Carol", "likes", "Dave", asserted_by="b")
        active = self.mem.get_active_assertions(subject="Carol")
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["predicate"], "likes")

    # ---- retract_assertion ----

    def test_retract_assertion_soft_deletes(self) -> None:
        self.mem.add_triple("Alice", "knows", "Bob")
        assertion = self.mem.add_assertion(
            "Alice", "knows", "Bob", asserted_by="test"
        )
        retracted = self.mem.retract_assertion(assertion["id"])
        self.assertTrue(retracted)
        # After retraction valid_until is set, so it's no longer "active"
        active = self.mem.get_active_assertions(subject="Alice")
        self.assertEqual(len(active), 0)

    # ---- subgraph ----

    def test_subgraph_returns_connected_entities(self) -> None:
        self.mem.add_triple("A", "r1", "B")
        self.mem.add_triple("B", "r2", "C")
        sg = self.mem.subgraph("A", depth=2)
        node_ids = {n["id"] for n in sg["nodes"]}
        self.assertIn("A", node_ids)
        self.assertIn("B", node_ids)
        self.assertIn("C", node_ids)

    def test_subgraph_depth_one_limits_breadth(self) -> None:
        self.mem.add_triple("A", "r1", "B")
        self.mem.add_triple("B", "r2", "C")
        self.mem.add_triple("C", "r3", "D")
        sg = self.mem.subgraph("A", depth=1)
        node_ids = {n["id"] for n in sg["nodes"]}
        self.assertIn("A", node_ids)
        self.assertIn("B", node_ids)
        # C is 2 hops away; should NOT appear at depth=1
        self.assertNotIn("C", node_ids)

    def test_subgraph_empty_for_unknown_entity(self) -> None:
        sg = self.mem.subgraph("nonexistent")
        self.assertEqual(len(sg["nodes"]), 0)
        self.assertEqual(len(sg["edges"]), 0)

    # ---- shortest_path ----

    def test_shortest_path_finds_path(self) -> None:
        self.mem.add_triple("A", "r1", "B")
        self.mem.add_triple("B", "r2", "C")
        path = self.mem.shortest_path("A", "C")
        self.assertIsNotNone(path)
        self.assertEqual(path, ["A", "B", "C"])

    def test_shortest_path_returns_none_for_disconnected(self) -> None:
        self.mem.add_triple("A", "r1", "B")
        self.mem.add_triple("X", "r2", "Y")
        path = self.mem.shortest_path("A", "Y")
        self.assertIsNone(path)

    def test_shortest_path_returns_none_for_unknown_node(self) -> None:
        path = self.mem.shortest_path("X", "Y")
        self.assertIsNone(path)

    # ---- multiple triples form knowledge graph ----

    def test_multiple_triples_form_knowledge_graph(self) -> None:
        self.mem.add_triple("Python", "is_a", "Language")
        self.mem.add_triple("Language", "used_in", "Programming")
        self.mem.add_triple("Python", "created_by", "Guido")
        all_triples = self.mem.get_triples()
        self.assertEqual(len(all_triples), 3)
        subjects = {t["subject"] for t in all_triples}
        self.assertIn("Python", subjects)
        self.assertIn("Language", subjects)


class TestWorkingMemory(unittest.TestCase):
    """Tests for the WorkingMemory LRU cache."""

    def setUp(self) -> None:
        self.wm = WorkingMemory(max_size=5)

    # ---- put / get round-trip ----

    def test_put_and_get_round_trip(self) -> None:
        self.wm.put("key1", "value1")
        self.assertEqual(self.wm.get("key1"), "value1")

    def test_get_nonexistent_returns_none(self) -> None:
        self.assertIsNone(self.wm.get("missing"))

    def test_put_multiple_get_all(self) -> None:
        for i in range(5):
            self.wm.put(f"k{i}", i)
        for i in range(5):
            self.assertEqual(self.wm.get(f"k{i}"), i)

    # ---- LRU eviction ----

    def test_lru_eviction_oldest_removed(self) -> None:
        for i in range(6):
            self.wm.put(f"k{i}", i)
        # k0 was the oldest and should be evicted
        self.assertIsNone(self.wm.get("k0"))
        # k1 through k5 should survive
        for i in range(1, 6):
            self.assertIsNotNone(self.wm.get(f"k{i}"))

    def test_lru_respects_max_size(self) -> None:
        for i in range(20):
            self.wm.put(f"k{i}", i)
        self.assertEqual(len(self.wm), 5)

    def test_get_refreshes_lru_order(self) -> None:
        """After get(), the accessed item should NOT be the next evicted."""
        for i in range(5):
            self.wm.put(f"k{i}", i)
        # Access k0 so it's refreshed
        self.wm.get("k0")
        # Add a 6th item to trigger eviction – k1 should be oldest now
        self.wm.put("k5", 5)
        self.assertIsNone(self.wm.get("k1"))
        # k0 should still exist because we refreshed it
        self.assertEqual(self.wm.get("k0"), 0)

    # ---- evict ----

    def test_evict_existing_returns_true(self) -> None:
        self.wm.put("k", 42)
        self.assertTrue(self.wm.evict("k"))
        self.assertIsNone(self.wm.get("k"))

    def test_evict_nonexistent_returns_false(self) -> None:
        self.assertFalse(self.wm.evict("nope"))

    # ---- clear ----

    def test_clear_empties_everything(self) -> None:
        for i in range(5):
            self.wm.put(f"k{i}", i)
        self.wm.clear()
        self.assertEqual(len(self.wm), 0)
        for i in range(5):
            self.assertIsNone(self.wm.get(f"k{i}"))

    # ---- snapshot ----

    def test_snapshot_returns_current_contents(self) -> None:
        self.wm.put("a", 1)
        self.wm.put("b", 2)
        snap = self.wm.snapshot()
        self.assertEqual(snap, {"a": 1, "b": 2})

    def test_snapshot_is_copy(self) -> None:
        self.wm.put("a", 1)
        snap = self.wm.snapshot()
        snap["a"] = 999
        self.assertEqual(self.wm.get("a"), 1)

    # ---- __len__ ----

    def test_len_returns_correct_count(self) -> None:
        self.assertEqual(len(self.wm), 0)
        self.wm.put("a", 1)
        self.assertEqual(len(self.wm), 1)
        self.wm.put("b", 2)
        self.assertEqual(len(self.wm), 2)

    def test_len_after_evict(self) -> None:
        self.wm.put("a", 1)
        self.wm.put("b", 2)
        self.wm.evict("a")
        self.assertEqual(len(self.wm), 1)

    # ---- overwrite same key ----

    def test_put_same_key_overwrites(self) -> None:
        self.wm.put("k", "old")
        self.wm.put("k", "new")
        self.assertEqual(self.wm.get("k"), "new")
        self.assertEqual(len(self.wm), 1)


if __name__ == "__main__":
    unittest.main()
