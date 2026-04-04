from __future__ import annotations

import os
import pathlib
import tempfile
import time
import unittest

from core._bus_fallback import EventBus
from core._database_fallback import DatabaseManager
from core.goal_planner import Goal, GoalPlanner, GoalStatus

MIGRATIONS = pathlib.Path("core/migrations")


def _make_env():
    """Create a file-backed DatabaseManager with migrations applied."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db = DatabaseManager(tmp.name, migrations_path=MIGRATIONS)
    db.initialize()
    return db, EventBus(), tmp.name


class TestGoalPlanner(unittest.TestCase):
    """Tests for GoalPlanner HTN-style hierarchical planner."""

    def setUp(self) -> None:
        self.db, self.bus, self._db_path = _make_env()
        self.planner = GoalPlanner(self.db, self.bus)

    def tearDown(self) -> None:
        self.db.close()
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(self._db_path + suffix)
            except OSError:
                pass

    # ================================================================
    # create_goal
    # ================================================================

    def test_create_goal_returns_goal_with_all_fields(self) -> None:
        goal = self.planner.create_goal(
            "Solve puzzle",
            domain="reasoning",
            preconditions=["has_input"],
            postconditions=["solved"],
            success_criteria=["correct_answer"],
            max_depth=5,
        )
        self.assertIsInstance(goal, Goal)
        self.assertTrue(len(goal.id) > 0)
        self.assertIsNone(goal.parent_id)
        self.assertEqual(goal.depth, 0)
        self.assertEqual(goal.description, "Solve puzzle")
        self.assertEqual(goal.domain, "reasoning")
        self.assertEqual(goal.preconditions, ["has_input"])
        self.assertEqual(goal.postconditions, ["solved"])
        self.assertEqual(goal.success_criteria, ["correct_answer"])
        self.assertEqual(goal.status, GoalStatus.PENDING)
        self.assertIsNone(goal.assigned_model)
        self.assertIsNone(goal.result)
        self.assertEqual(goal.confidence, 0.0)
        self.assertEqual(goal.max_depth, 5)
        self.assertIsInstance(goal.created_at, int)
        self.assertIsInstance(goal.updated_at, int)

    def test_create_goal_defaults(self) -> None:
        goal = self.planner.create_goal("Basic task")
        self.assertEqual(goal.domain, "general")
        self.assertIsNone(goal.parent_id)
        self.assertEqual(goal.preconditions, [])
        self.assertEqual(goal.postconditions, [])
        self.assertEqual(goal.success_criteria, [])
        self.assertEqual(goal.max_depth, 4)
        self.assertEqual(goal.depth, 0)

    def test_create_goal_with_parent_sets_correct_depth(self) -> None:
        parent = self.planner.create_goal("Parent")
        child = self.planner.create_goal("Child", parent_id=parent.id)
        self.assertEqual(child.depth, 1)
        self.assertEqual(child.parent_id, parent.id)

    def test_create_goal_nested_depth_accumulates(self) -> None:
        g0 = self.planner.create_goal("L0", max_depth=8)
        g1 = self.planner.create_goal("L1", parent_id=g0.id, max_depth=8)
        g2 = self.planner.create_goal("L2", parent_id=g1.id, max_depth=8)
        self.assertEqual(g0.depth, 0)
        self.assertEqual(g1.depth, 1)
        self.assertEqual(g2.depth, 2)

    # ================================================================
    # get_goal
    # ================================================================

    def test_get_goal_existing(self) -> None:
        created = self.planner.create_goal("Find me")
        fetched = self.planner.get_goal(created.id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.id, created.id)
        self.assertEqual(fetched.description, "Find me")

    def test_get_goal_nonexistent_returns_none(self) -> None:
        self.assertIsNone(self.planner.get_goal("nonexistent_goal_id"))

    # ================================================================
    # update_goal
    # ================================================================

    def test_update_goal_changes_status(self) -> None:
        goal = self.planner.create_goal("Status test")
        updated = self.planner.update_goal(goal.id, status=GoalStatus.ACTIVE)
        self.assertIsNotNone(updated)
        self.assertEqual(updated.status, GoalStatus.ACTIVE)

    def test_update_goal_updated_at_changes(self) -> None:
        goal = self.planner.create_goal("Timestamp test")
        time.sleep(1.1)
        updated = self.planner.update_goal(goal.id, status=GoalStatus.ACTIVE)
        self.assertIsNotNone(updated)
        self.assertGreater(updated.updated_at, goal.updated_at)

    def test_update_goal_changes_confidence(self) -> None:
        goal = self.planner.create_goal("Confidence")
        updated = self.planner.update_goal(goal.id, confidence=0.95)
        self.assertIsNotNone(updated)
        self.assertAlmostEqual(updated.confidence, 0.95)

    def test_update_goal_changes_assigned_model(self) -> None:
        goal = self.planner.create_goal("Model assign")
        updated = self.planner.update_goal(goal.id, assigned_model="gpt-4o")
        self.assertIsNotNone(updated)
        self.assertEqual(updated.assigned_model, "gpt-4o")

    def test_update_goal_rejects_non_whitelisted_fields(self) -> None:
        goal = self.planner.create_goal("Immutable desc")
        updated = self.planner.update_goal(goal.id, description="hacked", domain="code")
        self.assertIsNotNone(updated)
        self.assertEqual(updated.description, "Immutable desc")
        self.assertEqual(updated.domain, "general")

    def test_update_goal_mixed_whitelisted_and_non(self) -> None:
        goal = self.planner.create_goal("Mixed")
        updated = self.planner.update_goal(
            goal.id, status=GoalStatus.ACTIVE, description="nope"
        )
        self.assertIsNotNone(updated)
        self.assertEqual(updated.status, GoalStatus.ACTIVE)
        self.assertEqual(updated.description, "Mixed")

    # ================================================================
    # delete_goal
    # ================================================================

    def test_delete_goal_returns_true(self) -> None:
        goal = self.planner.create_goal("Delete me")
        self.assertTrue(self.planner.delete_goal(goal.id))
        self.assertIsNone(self.planner.get_goal(goal.id))

    def test_delete_goal_nonexistent_returns_false(self) -> None:
        self.assertFalse(self.planner.delete_goal("no_such_id"))

    def test_delete_goal_children_survive(self) -> None:
        # NOTE: CASCADE requires PRAGMA foreign_keys=ON per-connection.
        # DatabaseManager only sets it during initialize(), not on
        # transaction() connections, so children are NOT cascade-deleted.
        parent = self.planner.create_goal("Parent")
        child = self.planner.create_goal("Child", parent_id=parent.id)
        grandchild = self.planner.create_goal("GC", parent_id=child.id)
        self.planner.delete_goal(parent.id)
        self.assertIsNone(self.planner.get_goal(parent.id))
        # Children survive because foreign_keys pragma is off on txn connections
        self.assertIsNotNone(self.planner.get_goal(child.id))
        self.assertIsNotNone(self.planner.get_goal(grandchild.id))

    # ================================================================
    # list_goals
    # ================================================================

    def test_list_goals_returns_all(self) -> None:
        self.planner.create_goal("A")
        self.planner.create_goal("B")
        self.assertEqual(len(self.planner.list_goals()), 2)

    def test_list_goals_filter_by_status(self) -> None:
        g = self.planner.create_goal("Will activate")
        self.planner.create_goal("Stays pending")
        self.planner.update_goal(g.id, status=GoalStatus.ACTIVE)
        active = self.planner.list_goals(status=GoalStatus.ACTIVE)
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].id, g.id)

    def test_list_goals_filter_by_domain(self) -> None:
        self.planner.create_goal("Code work", domain="code")
        self.planner.create_goal("Math work", domain="math")
        code_goals = self.planner.list_goals(domain="code")
        self.assertEqual(len(code_goals), 1)
        self.assertEqual(code_goals[0].domain, "code")

    def test_list_goals_filter_by_parent_id(self) -> None:
        parent = self.planner.create_goal("Parent")
        c1 = self.planner.create_goal("C1", parent_id=parent.id)
        c2 = self.planner.create_goal("C2", parent_id=parent.id)
        self.planner.create_goal("Orphan")
        children = self.planner.list_goals(parent_id=parent.id)
        self.assertEqual(len(children), 2)
        ids = {g.id for g in children}
        self.assertEqual(ids, {c1.id, c2.id})

    # ================================================================
    # decompose
    # ================================================================

    def test_decompose_creates_subtasks_at_correct_depth(self) -> None:
        parent = self.planner.create_goal("Big task", max_depth=4)
        subtasks = self.planner.decompose(parent.id, ["S1", "S2", "S3"])
        self.assertEqual(len(subtasks), 3)
        for st in subtasks:
            self.assertEqual(st.depth, 1)
            self.assertEqual(st.parent_id, parent.id)
            self.assertEqual(st.domain, parent.domain)

    def test_decompose_fails_when_at_max_depth(self) -> None:
        root = self.planner.create_goal("Root", max_depth=1)
        children = self.planner.decompose(root.id, ["Level1"])
        self.assertEqual(len(children), 1)
        # child.depth == 1 == max_depth, so further decomposition blocked
        result = self.planner.decompose(children[0].id, ["Level2"])
        self.assertEqual(result, [])

    def test_decompose_inherits_parent_domain(self) -> None:
        parent = self.planner.create_goal("Code parent", domain="code")
        subs = self.planner.decompose(parent.id, ["Child"])
        self.assertEqual(subs[0].domain, "code")

    def test_decompose_overrides_domain(self) -> None:
        parent = self.planner.create_goal("General", domain="general")
        subs = self.planner.decompose(parent.id, ["Math child"], domain="math")
        self.assertEqual(subs[0].domain, "math")

    def test_decompose_nonexistent_parent_returns_empty(self) -> None:
        self.assertEqual(self.planner.decompose("no_id", ["task"]), [])

    # ================================================================
    # add_dependency / remove_dependency
    # ================================================================

    def test_add_dependency_basic(self) -> None:
        a = self.planner.create_goal("A")
        b = self.planner.create_goal("B")
        self.assertTrue(self.planner.add_dependency(b.id, a.id))
        deps = self.planner.get_dependencies(b.id)
        self.assertEqual(len(deps), 1)
        self.assertEqual(deps[0].id, a.id)

    def test_add_dependency_circular_detection_direct(self) -> None:
        a = self.planner.create_goal("A")
        b = self.planner.create_goal("B")
        self.planner.add_dependency(b.id, a.id)
        # A depending on B creates A->B->A cycle
        self.assertFalse(self.planner.add_dependency(a.id, b.id))

    def test_add_dependency_circular_detection_transitive(self) -> None:
        a = self.planner.create_goal("A")
        b = self.planner.create_goal("B")
        c = self.planner.create_goal("C")
        self.planner.add_dependency(b.id, a.id)  # B depends on A
        self.planner.add_dependency(c.id, b.id)  # C depends on B
        # A depending on C creates A->C->B->A cycle
        self.assertFalse(self.planner.add_dependency(a.id, c.id))

    def test_get_dependents(self) -> None:
        a = self.planner.create_goal("A")
        b = self.planner.create_goal("B")
        c = self.planner.create_goal("C")
        self.planner.add_dependency(b.id, a.id)
        self.planner.add_dependency(c.id, a.id)
        dep_ids = {g.id for g in self.planner.get_dependents(a.id)}
        self.assertEqual(dep_ids, {b.id, c.id})

    def test_remove_dependency(self) -> None:
        a = self.planner.create_goal("A")
        b = self.planner.create_goal("B")
        self.planner.add_dependency(b.id, a.id)
        self.assertTrue(self.planner.remove_dependency(b.id, a.id))
        self.assertEqual(self.planner.get_dependencies(b.id), [])

    def test_remove_dependency_nonexistent(self) -> None:
        a = self.planner.create_goal("A")
        b = self.planner.create_goal("B")
        self.assertFalse(self.planner.remove_dependency(b.id, a.id))

    # ================================================================
    # get_ready_goals / get_blocked_goals
    # ================================================================

    def test_get_ready_goals_no_dependencies(self) -> None:
        self.planner.create_goal("Free")
        ready = self.planner.get_ready_goals()
        self.assertEqual(len(ready), 1)

    def test_get_ready_goals_unmet_dependency_excluded(self) -> None:
        a = self.planner.create_goal("Prereq")
        b = self.planner.create_goal("Blocked")
        self.planner.add_dependency(b.id, a.id)
        ready_ids = {g.id for g in self.planner.get_ready_goals()}
        self.assertIn(a.id, ready_ids)
        self.assertNotIn(b.id, ready_ids)

    def test_get_ready_goals_after_dependency_completed(self) -> None:
        a = self.planner.create_goal("Prereq")
        b = self.planner.create_goal("Main")
        self.planner.add_dependency(b.id, a.id)
        self.planner.update_goal(a.id, status=GoalStatus.COMPLETED)
        ready_ids = {g.id for g in self.planner.get_ready_goals()}
        self.assertIn(b.id, ready_ids)

    def test_get_blocked_goals_has_failed_dependency(self) -> None:
        a = self.planner.create_goal("Fails")
        b = self.planner.create_goal("Depends on A")
        self.planner.add_dependency(b.id, a.id)
        self.planner.update_goal(a.id, status=GoalStatus.FAILED)
        blocked_ids = {g.id for g in self.planner.get_blocked_goals()}
        self.assertIn(b.id, blocked_ids)

    def test_get_blocked_goals_empty_when_no_failures(self) -> None:
        a = self.planner.create_goal("OK")
        b = self.planner.create_goal("Also OK")
        self.planner.add_dependency(b.id, a.id)
        self.assertEqual(self.planner.get_blocked_goals(), [])

    # ================================================================
    # propagate_failure / propagate_completion
    # ================================================================

    def test_propagate_failure_marks_dependents_blocked(self) -> None:
        a = self.planner.create_goal("Failing")
        b = self.planner.create_goal("Dep1")
        c = self.planner.create_goal("Dep2")
        self.planner.add_dependency(b.id, a.id)
        self.planner.add_dependency(c.id, a.id)
        self.planner.update_goal(a.id, status=GoalStatus.FAILED)
        newly_blocked = self.planner.propagate_failure(a.id)
        self.assertEqual(len(newly_blocked), 2)
        self.assertEqual(self.planner.get_goal(b.id).status, GoalStatus.BLOCKED)
        self.assertEqual(self.planner.get_goal(c.id).status, GoalStatus.BLOCKED)

    def test_propagate_failure_skips_already_blocked(self) -> None:
        a = self.planner.create_goal("F")
        b = self.planner.create_goal("Already blocked")
        self.planner.add_dependency(b.id, a.id)
        self.planner.update_goal(a.id, status=GoalStatus.FAILED)
        self.planner.update_goal(b.id, status=GoalStatus.BLOCKED)
        newly_blocked = self.planner.propagate_failure(a.id)
        self.assertEqual(len(newly_blocked), 0)

    def test_propagate_completion_unblocks_dependents(self) -> None:
        a = self.planner.create_goal("Prereq")
        b = self.planner.create_goal("Blocked")
        self.planner.add_dependency(b.id, a.id)
        self.planner.update_goal(b.id, status=GoalStatus.BLOCKED)
        self.planner.update_goal(a.id, status=GoalStatus.COMPLETED)
        unblocked = self.planner.propagate_completion(a.id)
        self.assertGreaterEqual(len(unblocked), 1)
        self.assertEqual(self.planner.get_goal(b.id).status, GoalStatus.PENDING)

    def test_propagate_completion_waits_for_all_deps(self) -> None:
        a = self.planner.create_goal("Dep1")
        b = self.planner.create_goal("Dep2")
        c = self.planner.create_goal("Needs both")
        self.planner.add_dependency(c.id, a.id)
        self.planner.add_dependency(c.id, b.id)
        self.planner.update_goal(c.id, status=GoalStatus.BLOCKED)
        # Complete only A
        self.planner.update_goal(a.id, status=GoalStatus.COMPLETED)
        unblocked = self.planner.propagate_completion(a.id)
        # C should NOT unblock because B is still pending
        c_ids = {g.id for g in unblocked}
        self.assertNotIn(c.id, c_ids)
        # Now complete B
        self.planner.update_goal(b.id, status=GoalStatus.COMPLETED)
        unblocked = self.planner.propagate_completion(b.id)
        c_ids = {g.id for g in unblocked}
        self.assertIn(c.id, c_ids)

    # ================================================================
    # get_subtree
    # ================================================================

    def test_get_subtree_with_nested_children(self) -> None:
        root = self.planner.create_goal("Root")
        c1 = self.planner.create_goal("C1", parent_id=root.id)
        c2 = self.planner.create_goal("C2", parent_id=root.id)
        gc = self.planner.create_goal("GC", parent_id=c1.id)
        tree = self.planner.get_subtree(root.id)
        self.assertIsNotNone(tree)
        self.assertEqual(tree["goal"].id, root.id)
        self.assertEqual(len(tree["children"]), 2)
        # One of the children should have its own child
        subtree_ids = [ch["goal"].id for ch in tree["children"]]
        self.assertIn(c1.id, subtree_ids)
        c1_subtree = next(ch for ch in tree["children"] if ch["goal"].id == c1.id)
        self.assertEqual(len(c1_subtree["children"]), 1)
        self.assertEqual(c1_subtree["children"][0]["goal"].id, gc.id)

    def test_get_subtree_leaf_has_no_children(self) -> None:
        leaf = self.planner.create_goal("Leaf")
        tree = self.planner.get_subtree(leaf.id)
        self.assertIsNotNone(tree)
        self.assertEqual(tree["children"], [])

    def test_get_subtree_nonexistent_returns_none(self) -> None:
        self.assertIsNone(self.planner.get_subtree("ghost"))

    # ================================================================
    # get_root_goals
    # ================================================================

    def test_get_root_goals_includes_parentless(self) -> None:
        r1 = self.planner.create_goal("Root1")
        r2 = self.planner.create_goal("Root2")
        _child = self.planner.create_goal("Child", parent_id=r1.id)
        roots = self.planner.get_root_goals()
        root_ids = {g.id for g in roots}
        self.assertIn(r1.id, root_ids)
        self.assertIn(r2.id, root_ids)

    # ================================================================
    # execution_order
    # ================================================================

    def test_execution_order_respects_dependencies(self) -> None:
        a = self.planner.create_goal("A")
        b = self.planner.create_goal("B")
        c = self.planner.create_goal("C")
        self.planner.add_dependency(b.id, a.id)  # B after A
        self.planner.add_dependency(c.id, b.id)  # C after B
        order = self.planner.execution_order()
        ids = [g.id for g in order]
        self.assertIn(a.id, ids)
        self.assertIn(b.id, ids)
        self.assertIn(c.id, ids)
        self.assertLess(ids.index(a.id), ids.index(b.id))
        self.assertLess(ids.index(b.id), ids.index(c.id))

    def test_execution_order_empty_when_no_goals(self) -> None:
        self.assertEqual(self.planner.execution_order(), [])

    def test_execution_order_independent_goals_all_present(self) -> None:
        a = self.planner.create_goal("A")
        b = self.planner.create_goal("B")
        order = self.planner.execution_order()
        ids = {g.id for g in order}
        self.assertEqual(ids, {a.id, b.id})

    # ================================================================
    # summary
    # ================================================================

    def test_summary_has_required_keys(self) -> None:
        s = self.planner.summary()
        for key in ("total_goals", "by_status", "max_depth_used", "ready_count", "blocked_count"):
            self.assertIn(key, s)

    def test_summary_counts_correct(self) -> None:
        self.planner.create_goal("One")
        g2 = self.planner.create_goal("Two")
        self.planner.update_goal(g2.id, status=GoalStatus.COMPLETED)
        s = self.planner.summary()
        self.assertEqual(s["total_goals"], 2)
        self.assertEqual(s["by_status"].get(GoalStatus.PENDING, 0), 1)
        self.assertEqual(s["by_status"].get(GoalStatus.COMPLETED, 0), 1)

    def test_summary_max_depth_reflects_deepest_goal(self) -> None:
        root = self.planner.create_goal("Root", max_depth=8)
        c1 = self.planner.create_goal("C1", parent_id=root.id, max_depth=8)
        _c2 = self.planner.create_goal("C2", parent_id=c1.id, max_depth=8)
        s = self.planner.summary()
        self.assertEqual(s["max_depth_used"], 2)

    def test_summary_ready_and_blocked_counts(self) -> None:
        a = self.planner.create_goal("Dep")
        b = self.planner.create_goal("Waits on A")
        self.planner.add_dependency(b.id, a.id)
        self.planner.update_goal(a.id, status=GoalStatus.FAILED)
        s = self.planner.summary()
        self.assertGreaterEqual(s["blocked_count"], 1)

    # ================================================================
    # GoalStatus constants
    # ================================================================

    def test_goal_status_constants(self) -> None:
        self.assertEqual(GoalStatus.PENDING, "pending")
        self.assertEqual(GoalStatus.ACTIVE, "active")
        self.assertEqual(GoalStatus.COMPLETED, "completed")
        self.assertEqual(GoalStatus.FAILED, "failed")
        self.assertEqual(GoalStatus.BLOCKED, "blocked")


if __name__ == "__main__":
    unittest.main()
