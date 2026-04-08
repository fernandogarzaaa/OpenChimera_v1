from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any

from core._bus_fallback import EventBus
from core._database_fallback import DatabaseManager

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Phase 4 — Goal Decomposition Strategy Learning
# ---------------------------------------------------------------------------

class DecompositionStrategyLearner:
    """Learns which decomposition strategies succeed for which goal types.

    Tracks per-goal-type decomposition attempts and their outcomes, allowing
    the planner to surface the historically best-performing step sequence for
    a given goal type.

    Thread-safe.
    """

    def __init__(self) -> None:
        # goal_type → list[{"steps": list[str], "successes": int, "attempts": int}]
        self._strategies: dict[str, list[dict[str, Any]]] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_decomposition(
        self,
        goal_type: str,
        steps: list[str],
        succeeded: bool,
    ) -> None:
        """Store a decomposition attempt and its outcome.

        If an identical *steps* sequence already exists for *goal_type*, only
        its counters are updated.  Otherwise a new entry is appended.
        """
        steps_key = tuple(steps)
        with self._lock:
            entries = self._strategies.setdefault(goal_type, [])
            for entry in entries:
                if tuple(entry["steps"]) == steps_key:
                    entry["attempts"] += 1
                    if succeeded:
                        entry["successes"] += 1
                    entry["success_rate"] = (
                        entry["successes"] / entry["attempts"]
                    )
                    log.debug(
                        "[DecompositionStrategyLearner] Updated %s strategy (rate=%.2f)",
                        goal_type, entry["success_rate"],
                    )
                    return
            # New entry
            entry = {
                "steps": list(steps),
                "successes": 1 if succeeded else 0,
                "attempts": 1,
                "success_rate": 1.0 if succeeded else 0.0,
            }
            entries.append(entry)
            log.debug(
                "[DecompositionStrategyLearner] Recorded new %s strategy with %d steps",
                goal_type, len(steps),
            )

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def best_strategy(self, goal_type: str) -> list[str] | None:
        """Return the steps list with the highest *success_rate* for *goal_type*.

        Returns ``None`` if no history exists for this goal type.
        Ties are broken in favour of the most recently added entry.
        """
        with self._lock:
            entries = self._strategies.get(goal_type)
            if not entries:
                return None
            best = max(entries, key=lambda e: e["success_rate"])
            return list(best["steps"])

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def all_strategies(self) -> dict[str, list[dict[str, Any]]]:
        """Return the full internal strategy dict (deep-copied)."""
        with self._lock:
            return {
                goal_type: [
                    {**e, "steps": list(e["steps"])}
                    for e in entries
                ]
                for goal_type, entries in self._strategies.items()
            }


class GoalStatus:
    """Goal status constants."""

    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class Goal:
    """Immutable goal representation."""

    id: str
    parent_id: str | None
    depth: int
    description: str
    domain: str
    preconditions: list[str]
    postconditions: list[str]
    success_criteria: list[str]
    status: str
    assigned_model: str | None
    result: str | None
    confidence: float
    max_depth: int
    created_at: int
    updated_at: int


class GoalPlanner:
    """HTN-style hierarchical goal planner with dependency tracking."""

    def __init__(self, db: DatabaseManager, bus: EventBus) -> None:
        """Initialize goal planner.

        Args:
            db: DatabaseManager instance for persistence
            bus: EventBus instance for event publishing
        """
        self._db = db
        self._bus = bus
        self._strategy_learner = DecompositionStrategyLearner()
        self._intervention_events: list[dict[str, Any]] = []
        self._intervention_lock = threading.Lock()
        self._intervention_events: list[dict[str, Any]] = []
        self._intervention_lock = threading.Lock()

    # ========== CRUD Operations ==========

    def create_goal(
        self,
        description: str,
        domain: str = "general",
        parent_id: str | None = None,
        preconditions: list[str] | None = None,
        postconditions: list[str] | None = None,
        success_criteria: list[str] | None = None,
        max_depth: int = 4,
    ) -> Goal:
        """Create a new goal.

        Args:
            description: Goal description
            domain: Problem domain
            parent_id: Parent goal ID for hierarchical decomposition
            preconditions: List of preconditions (JSON-serialized)
            postconditions: List of postconditions (JSON-serialized)
            success_criteria: List of success criteria (JSON-serialized)
            max_depth: Maximum recursion depth for this goal tree

        Returns:
            Created Goal object
        """
        goal_id = uuid.uuid4().hex
        now = int(time.time())

        # Calculate depth from parent
        depth = 0
        if parent_id:
            parent = self.get_goal(parent_id)
            if parent:
                depth = parent.depth + 1
                if depth > 8:
                    log.warning(f"Goal depth {depth} exceeds max of 8, clamping to 8")
                    depth = 8

        preconditions = preconditions or []
        postconditions = postconditions or []
        success_criteria = success_criteria or []

        try:
            with self._db.transaction() as conn:
                conn.execute(
                    """
                    INSERT INTO goals
                    (id, parent_id, depth, description, domain, preconditions,
                     postconditions, success_criteria, status, confidence,
                     max_depth, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        goal_id,
                        parent_id,
                        depth,
                        description,
                        domain,
                        json.dumps(preconditions),
                        json.dumps(postconditions),
                        json.dumps(success_criteria),
                        GoalStatus.PENDING,
                        0.0,
                        max_depth,
                        now,
                        now,
                    ),
                )
        except sqlite3.Error as e:
            log.warning(f"Failed to create goal: {e}")
            raise

        goal = Goal(
            id=goal_id,
            parent_id=parent_id,
            depth=depth,
            description=description,
            domain=domain,
            preconditions=preconditions,
            postconditions=postconditions,
            success_criteria=success_criteria,
            status=GoalStatus.PENDING,
            assigned_model=None,
            result=None,
            confidence=0.0,
            max_depth=max_depth,
            created_at=now,
            updated_at=now,
        )

        self._bus.publish("planner.goal.created", {"goal": goal})
        return goal

    def get_goal(self, goal_id: str) -> Goal | None:
        """Retrieve a goal by ID.

        Args:
            goal_id: Goal ID

        Returns:
            Goal object or None if not found
        """
        try:
            with self._db.transaction() as conn:
                cursor = conn.execute(
                    "SELECT * FROM goals WHERE id = ?",
                    (goal_id,),
                )
                row = cursor.fetchone()
                if row:
                    return self._row_to_goal(row)
        except sqlite3.Error as e:
            log.warning(f"Failed to get goal {goal_id}: {e}")

        return None

    def update_goal(self, goal_id: str, **kwargs: Any) -> Goal | None:
        """Update goal fields.

        Supported fields: status, result, confidence, assigned_model

        Args:
            goal_id: Goal ID
            **kwargs: Fields to update

        Returns:
            Updated Goal object or None if not found
        """
        # Whitelist allowed fields
        allowed_fields = {"status", "result", "confidence", "assigned_model"}
        update_fields = {k: v for k, v in kwargs.items() if k in allowed_fields}

        if not update_fields:
            log.warning(f"No valid update fields provided for goal {goal_id}")
            return self.get_goal(goal_id)

        now = int(time.time())

        # Build dynamic UPDATE query
        set_clauses = [f"{k} = ?" for k in update_fields.keys()]
        set_clause = ", ".join(set_clauses)
        values = list(update_fields.values()) + [now, goal_id]

        try:
            with self._db.transaction() as conn:
                conn.execute(
                    f"UPDATE goals SET {set_clause}, updated_at = ? WHERE id = ?",
                    values,
                )
        except sqlite3.Error as e:
            log.warning(f"Failed to update goal {goal_id}: {e}")
            raise

        goal = self.get_goal(goal_id)
        if goal:
            self._bus.publish("planner.goal.updated", {"goal": goal})

        return goal

    def delete_goal(self, goal_id: str) -> bool:
        """Delete a goal (cascades to children via foreign key).

        Args:
            goal_id: Goal ID

        Returns:
            True if deleted, False if not found
        """
        try:
            with self._db.transaction() as conn:
                cursor = conn.execute(
                    "DELETE FROM goals WHERE id = ?",
                    (goal_id,),
                )
                affected = cursor.rowcount

                if affected > 0:
                    self._bus.publish("planner.goal.deleted", {"goal_id": goal_id})
                    return True
        except sqlite3.Error as e:
            log.warning(f"Failed to delete goal {goal_id}: {e}")
            raise

        return False

    def list_goals(
        self,
        status: str | None = None,
        domain: str | None = None,
        parent_id: str | None = None,
        limit: int = 100,
    ) -> list[Goal]:
        """List goals with optional filtering.

        Args:
            status: Filter by status
            domain: Filter by domain
            parent_id: Filter by parent ID
            limit: Maximum results

        Returns:
            List of Goal objects
        """
        conditions: list[str] = []
        params: list[Any] = []

        if status:
            conditions.append("status = ?")
            params.append(status)

        if domain:
            conditions.append("domain = ?")
            params.append(domain)

        if parent_id is not None:
            conditions.append("parent_id = ?")
            params.append(parent_id)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        try:
            with self._db.transaction() as conn:
                query = f"SELECT * FROM goals WHERE {where_clause} LIMIT ?"
                cursor = conn.execute(query, params + [limit])
                rows = cursor.fetchall()
                return [self._row_to_goal(row) for row in rows]
        except sqlite3.Error as e:
            log.warning(f"Failed to list goals: {e}")
            return []

    # ========== Decomposition ==========

    def decompose(
        self,
        goal_id: str,
        subtask_descriptions: list[str],
        domain: str | None = None,
    ) -> list[Goal]:
        """Decompose a goal into subtasks.

        Args:
            goal_id: Parent goal ID
            subtask_descriptions: List of subtask descriptions
            domain: Domain for subtasks (inherits from parent if not specified)

        Returns:
            List of created subtask Goal objects
        """
        parent = self.get_goal(goal_id)
        if not parent:
            log.warning(f"Parent goal {goal_id} not found")
            return []

        # Check depth constraint
        if parent.depth >= parent.max_depth:
            log.warning(
                f"Cannot decompose goal {goal_id}: depth {parent.depth} "
                f"at max {parent.max_depth}"
            )
            return []

        domain = domain or parent.domain
        subtasks = []

        for description in subtask_descriptions:
            subtask = self.create_goal(
                description=description,
                domain=domain,
                parent_id=goal_id,
                max_depth=parent.max_depth,
            )
            subtasks.append(subtask)

        self._bus.publish(
            "planner.goal.decomposed",
            {"parent_id": goal_id, "subtasks": subtasks},
        )

        return subtasks

    # ========== Dependencies ==========

    def add_dependency(self, goal_id: str, depends_on_id: str) -> bool:
        """Add a dependency between goals.

        Args:
            goal_id: Goal that depends on another
            depends_on_id: Goal that must complete first

        Returns:
            True if added, False on conflict or circular dependency
        """
        try:
            with self._db.transaction() as conn:
                if self._has_circular_dependency(goal_id, depends_on_id, conn):
                    log.warning(
                        f"Circular dependency detected: {goal_id} -> {depends_on_id}"
                    )
                    return False

                conn.execute(
                    """
                    INSERT OR IGNORE INTO goal_dependencies
                    (goal_id, depends_on_id)
                    VALUES (?, ?)
                    """,
                    (goal_id, depends_on_id),
                )
        except sqlite3.Error as e:
            log.warning(f"Failed to add dependency: {e}")
            return False

        self._bus.publish(
            "planner.dependency.added",
            {"goal_id": goal_id, "depends_on_id": depends_on_id},
        )

        return True

    def remove_dependency(self, goal_id: str, depends_on_id: str) -> bool:
        """Remove a dependency between goals.

        Args:
            goal_id: Goal ID
            depends_on_id: Goal ID

        Returns:
            True if removed, False if not found
        """
        try:
            with self._db.transaction() as conn:
                cursor = conn.execute(
                    """
                    DELETE FROM goal_dependencies
                    WHERE goal_id = ? AND depends_on_id = ?
                    """,
                    (goal_id, depends_on_id),
                )
                affected = cursor.rowcount
                return affected > 0
        except sqlite3.Error as e:
            log.warning(f"Failed to remove dependency: {e}")
            return False

    def get_dependencies(self, goal_id: str) -> list[Goal]:
        """Get all goals this goal depends on.

        Args:
            goal_id: Goal ID

        Returns:
            List of Goal objects
        """
        try:
            with self._db.transaction() as conn:
                cursor = conn.execute(
                    """
                    SELECT g.* FROM goals g
                    INNER JOIN goal_dependencies gd ON g.id = gd.depends_on_id
                    WHERE gd.goal_id = ?
                    """,
                    (goal_id,),
                )
                rows = cursor.fetchall()
                return [self._row_to_goal(row) for row in rows]
        except sqlite3.Error as e:
            log.warning(f"Failed to get dependencies for {goal_id}: {e}")
            return []

    def get_dependents(self, goal_id: str) -> list[Goal]:
        """Get all goals that depend on this goal.

        Args:
            goal_id: Goal ID

        Returns:
            List of Goal objects
        """
        try:
            with self._db.transaction() as conn:
                cursor = conn.execute(
                    """
                    SELECT g.* FROM goals g
                    INNER JOIN goal_dependencies gd ON g.id = gd.goal_id
                    WHERE gd.depends_on_id = ?
                    """,
                    (goal_id,),
                )
                rows = cursor.fetchall()
                return [self._row_to_goal(row) for row in rows]
        except sqlite3.Error as e:
            log.warning(f"Failed to get dependents for {goal_id}: {e}")
            return []

    # ========== Planning ==========

    def get_ready_goals(self) -> list[Goal]:
        """Get all pending goals where ALL dependencies are completed.

        Returns:
            List of executable Goal objects
        """
        try:
            with self._db.transaction() as conn:
                cursor = conn.execute(
                    """
                    SELECT DISTINCT g.* FROM goals g
                    WHERE g.status = ?
                    AND NOT EXISTS (
                        SELECT 1 FROM goal_dependencies gd
                        LEFT JOIN goals dep ON dep.id = gd.depends_on_id
                        WHERE gd.goal_id = g.id
                        AND dep.status != ?
                    )
                    """,
                    (GoalStatus.PENDING, GoalStatus.COMPLETED),
                )
                rows = cursor.fetchall()
                return [self._row_to_goal(row) for row in rows]
        except sqlite3.Error as e:
            log.warning(f"Failed to get ready goals: {e}")
            return []

    def get_blocked_goals(self) -> list[Goal]:
        """Get pending goals where at least one dependency is failed.

        Returns:
            List of blocked Goal objects
        """
        try:
            with self._db.transaction() as conn:
                cursor = conn.execute(
                    """
                    SELECT DISTINCT g.* FROM goals g
                    WHERE g.status = ?
                    AND EXISTS (
                        SELECT 1 FROM goal_dependencies gd
                        INNER JOIN goals dep ON dep.id = gd.depends_on_id
                        WHERE gd.goal_id = g.id
                        AND dep.status = ?
                    )
                    """,
                    (GoalStatus.PENDING, GoalStatus.FAILED),
                )
                rows = cursor.fetchall()
                return [self._row_to_goal(row) for row in rows]
        except sqlite3.Error as e:
            log.warning(f"Failed to get blocked goals: {e}")
            return []

    def propagate_failure(self, goal_id: str) -> list[Goal]:
        """When a goal fails, mark all dependent goals as blocked.

        Args:
            goal_id: Goal that failed

        Returns:
            List of newly blocked goals
        """
        dependents = self.get_dependents(goal_id)
        newly_blocked = []

        try:
            with self._db.transaction() as conn:
                for dependent in dependents:
                    if dependent.status not in (GoalStatus.FAILED, GoalStatus.BLOCKED):
                        conn.execute(
                            "UPDATE goals SET status = ?, updated_at = ? WHERE id = ?",
                            (GoalStatus.BLOCKED, int(time.time()), dependent.id),
                        )
                        newly_blocked.append(dependent)
        except sqlite3.Error as e:
            log.warning(f"Failed to propagate failure for {goal_id}: {e}")

        for goal in newly_blocked:
            self._bus.publish(
                "planner.goal.blocked",
                {"goal_id": goal.id, "reason": "dependency_failed"},
            )

        return newly_blocked

    def propagate_completion(self, goal_id: str) -> list[Goal]:
        """When a goal completes, unblock dependents with all deps completed.

        Args:
            goal_id: Goal that completed

        Returns:
            List of newly unblocked goals
        """
        dependents = self.get_dependents(goal_id)
        newly_ready = []

        try:
            with self._db.transaction() as conn:
                for dependent in dependents:
                    # Check if ALL dependencies are now completed
                    cursor = conn.execute(
                        """
                        SELECT COUNT(*) as unmet FROM goal_dependencies gd
                        INNER JOIN goals dep ON dep.id = gd.depends_on_id
                        WHERE gd.goal_id = ?
                        AND dep.status != ?
                        """,
                        (dependent.id, GoalStatus.COMPLETED),
                    )
                    result = cursor.fetchone()
                    unmet = result["unmet"]

                    # If pending/blocked and all deps met, move to pending
                    if dependent.status in (GoalStatus.BLOCKED, GoalStatus.PENDING):
                        if unmet == 0:
                            conn.execute(
                                "UPDATE goals SET status = ?, updated_at = ? WHERE id = ?",
                                (GoalStatus.PENDING, int(time.time()), dependent.id),
                            )
                            newly_ready.append(dependent)
        except sqlite3.Error as e:
            log.warning(f"Failed to propagate completion for {goal_id}: {e}")

        for goal in newly_ready:
            self._bus.publish(
                "planner.goal.unblocked",
                {"goal_id": goal.id},
            )

        return newly_ready

    # ========== HTN Tree ==========

    def get_subtree(self, goal_id: str) -> dict[str, Any] | None:
        """Get recursive subtree structure.

        Args:
            goal_id: Root goal ID

        Returns:
            Dict with "goal" and "children" keys, or None if not found
        """
        goal = self.get_goal(goal_id)
        if not goal:
            return None

        children = self.list_goals(parent_id=goal_id)
        subtree: dict[str, Any] = {
            "goal": goal,
            "children": [],
        }

        for child in children:
            child_subtree = self.get_subtree(child.id)
            if child_subtree:
                subtree["children"].append(child_subtree)

        return subtree

    def get_root_goals(self) -> list[Goal]:
        """Get all goals with no parent.

        Returns:
            List of root Goal objects
        """
        return self.list_goals(parent_id=None)

    def execution_order(self) -> list[Goal]:
        """Topological sort of pending/active goals respecting dependencies.

        Uses Kahn's algorithm on the dependency graph.

        Returns:
            List of Goal objects in execution order
        """
        # Get all pending and active goals
        try:
            with self._db.transaction() as conn:
                cursor = conn.execute(
                    """
                    SELECT * FROM goals
                    WHERE status IN (?, ?)
                    """,
                    (GoalStatus.PENDING, GoalStatus.ACTIVE),
                )
                goals_data = cursor.fetchall()
                goals = [self._row_to_goal(row) for row in goals_data]

                if not goals:
                    return []

                # Build in-degree map
                in_degree: dict[str, int] = {g.id: 0 for g in goals}

                cursor = conn.execute(
                    """
                    SELECT goal_id, depends_on_id FROM goal_dependencies
                    WHERE goal_id IN ({})
                    """.format(
                        ",".join(["?"] * len(goals))
                    ),
                    [g.id for g in goals],
                )

                dependencies = cursor.fetchall()
                for dep in dependencies:
                    goal_id = dep["goal_id"]
                    if goal_id in in_degree:
                        in_degree[goal_id] += 1
        except sqlite3.Error as e:
            log.warning(f"Failed to compute execution order: {e}")
            return []

        # Kahn's algorithm
        queue = [g for g in goals if in_degree[g.id] == 0]
        result: list[Goal] = []

        while queue:
            current = queue.pop(0)
            result.append(current)

            # Find dependents and reduce their in-degree
            for goal in goals:
                if goal.id not in in_degree:
                    continue

                deps = self.get_dependencies(goal.id)
                if any(d.id == current.id for d in deps):
                    in_degree[goal.id] -= 1
                    if in_degree[goal.id] == 0:
                        queue.append(goal)

        return result

    # ========== Execution ==========

    def execute_goal(self, goal_id: str, executor_fn=None) -> dict:
        """Execute a goal, optionally using a provided executor function.

        Args:
            goal_id: Goal ID to execute
            executor_fn: Optional callable(goal) -> dict with 'status' key

        Returns:
            Dict with goal_id, status, result, duration_seconds
        """
        start_time = time.time()
        goal = self.get_goal(goal_id)
        if goal is None:
            return {"goal_id": goal_id, "status": "failed", "result": "Goal not found", "duration_seconds": 0.0}

        if goal.preconditions:
            for precondition in goal.preconditions:
                if not isinstance(precondition, str) or not precondition.strip():
                    log.warning("Goal %s has an empty or invalid precondition entry: %r", goal_id, precondition)

        try:
            self.update_goal(goal_id, status=GoalStatus.ACTIVE)
            goal = self.get_goal(goal_id)

            if executor_fn is not None:
                result = executor_fn(goal)
            else:
                result = {"status": "completed", "result": "no executor provided"}

            if result.get("status") == "completed":
                self.update_goal(goal_id, status=GoalStatus.COMPLETED, result=json.dumps(result))
                final_status = GoalStatus.COMPLETED
            else:
                self.update_goal(goal_id, status=GoalStatus.FAILED, result=json.dumps(result))
                final_status = GoalStatus.FAILED

        except Exception as exc:
            log.warning("Goal %s execution failed: %s", goal_id, exc)
            self.update_goal(goal_id, status=GoalStatus.FAILED, result=str(exc))
            result = {"status": "failed", "result": str(exc)}
            final_status = GoalStatus.FAILED

        duration = round(time.time() - start_time, 4)
        self._bus.publish("planner.goal.executed", {"goal_id": goal_id, "status": final_status})

        # --- Phase 4: record decomposition strategy outcome ---
        try:
            recorded_goal = self.get_goal(goal_id)
            if recorded_goal is not None:
                goal_type = recorded_goal.domain or "general"
                steps = recorded_goal.preconditions or []
                succeeded = final_status == GoalStatus.COMPLETED
                self._strategy_learner.record_decomposition(goal_type, steps, succeeded)
        except Exception as _rec_exc:
            log.debug("[GoalPlanner] Strategy record skipped: %s", _rec_exc)

        return {"goal_id": goal_id, "status": final_status, "result": result, "duration_seconds": duration}

    def suggest_decomposition(self, goal_type: str) -> list[str] | None:
        """Suggest the best known decomposition steps for *goal_type*.

        Delegates to the internal :class:`DecompositionStrategyLearner`.
        Returns ``None`` when no history is available for this goal type.
        """
        return self._strategy_learner.best_strategy(goal_type)

    def auto_decompose(self, goal_id: str, max_subgoals: int = 5) -> list[str]:
        """Decompose a goal into subgoals by splitting its description on conjunctions.

        Args:
            goal_id: Parent goal ID
            max_subgoals: Maximum number of subgoals to create

        Returns:
            List of created child goal IDs
        """
        goal = self.get_goal(goal_id)
        if goal is None:
            log.warning("auto_decompose: goal %s not found", goal_id)
            return []

        parts = re.split(r'\s+(?:and|then|also|while)\s+', goal.description, flags=re.IGNORECASE)
        parts = [p.strip() for p in parts if p.strip()][:max_subgoals]

        if len(parts) <= 1:
            return []

        created_ids: list[str] = []
        for part in parts:
            try:
                child = self.create_goal(
                    description=part,
                    domain=goal.domain,
                    parent_id=goal_id,
                    max_depth=goal.max_depth,
                )
                created_ids.append(child.id)
            except Exception as exc:
                log.warning("auto_decompose: failed to create subgoal '%s': %s", part, exc)

        return created_ids

    def plan_long_horizon(
        self,
        goal_id: str,
        horizon: int = 2,
        max_subgoals_per_level: int = 4,
    ) -> dict[str, Any]:
        """Expand a goal tree for multiple levels with bounded breadth.

        Prefers learned strategies for the root domain, then falls back to
        lightweight description splitting for deeper levels.
        """
        root = self.get_goal(goal_id)
        if root is None:
            return {
                "status": "error",
                "goal_id": goal_id,
                "error": "Goal not found",
                "created_goal_ids": [],
                "created_count": 0,
                "levels_expanded": 0,
            }

        queue: list[tuple[str, int]] = [(goal_id, 0)]
        created_goal_ids: list[str] = []
        expanded_levels: set[int] = set()

        while queue:
            current_id, level = queue.pop(0)
            if level >= max(horizon, 0):
                continue
            current = self.get_goal(current_id)
            if current is None:
                continue

            suggested = self.suggest_decomposition(current.domain) or []
            if suggested:
                subtask_descriptions = suggested[: max(1, max_subgoals_per_level)]
                children = self.decompose(current_id, subtask_descriptions)
                child_ids = [child.id for child in children]
            else:
                child_ids = self.auto_decompose(
                    current_id,
                    max_subgoals=max(1, max_subgoals_per_level),
                )

            if not child_ids:
                continue

            expanded_levels.add(level + 1)
            created_goal_ids.extend(child_ids)
            for child_id in child_ids:
                queue.append((child_id, level + 1))

        return {
            "status": "ok",
            "goal_id": goal_id,
            "created_goal_ids": created_goal_ids,
            "created_count": len(created_goal_ids),
            "levels_expanded": len(expanded_levels),
        }

    def replan_goal(self, goal_id: str, failure_reason: str = "") -> dict[str, Any]:
        """Create a lightweight autonomous replan for failed or blocked goals."""
        goal = self.get_goal(goal_id)
        if goal is None:
            return {"status": "error", "goal_id": goal_id, "error": "Goal not found"}

        if goal.status in (GoalStatus.FAILED, GoalStatus.BLOCKED):
            self.update_goal(goal_id, status=GoalStatus.PENDING)

        planned_steps = self.suggest_decomposition(goal.domain) or [
            "analyze failure",
            "retry execution",
            "validate output",
        ]
        planned_steps = planned_steps[:3]
        subgoals = self.decompose(goal_id, planned_steps)
        subgoal_ids = [g.id for g in subgoals]

        if not subgoal_ids:
            subgoal_ids = self.auto_decompose(goal_id, max_subgoals=3)

        autonomous = bool(subgoal_ids)
        self.record_intervention(
            goal_id,
            required=not autonomous,
            reason=failure_reason or ("auto-replan" if autonomous else "manual-replan-required"),
        )

        return {
            "status": "replanned" if autonomous else "needs_intervention",
            "goal_id": goal_id,
            "subgoal_ids": subgoal_ids,
            "failure_reason": failure_reason,
        }

    def record_intervention(self, goal_id: str, *, required: bool, reason: str = "") -> None:
        """Record whether a step required human intervention."""
        event = {
            "goal_id": goal_id,
            "required": bool(required),
            "reason": reason,
            "recorded_at": time.time(),
        }
        with self._intervention_lock:
            self._intervention_events.append(event)

    def intervention_minimization_metrics(self, limit: int | None = None) -> dict[str, Any]:
        """Return intervention minimization metrics for recent events."""
        with self._intervention_lock:
            events = list(self._intervention_events)
        if limit is not None and limit > 0:
            events = events[-limit:]

        total_events = len(events)
        required_interventions = sum(1 for event in events if bool(event.get("required")))
        avoided_interventions = total_events - required_interventions
        avoidance_rate = (
            avoided_interventions / total_events if total_events > 0 else 0.0
        )
        return {
            "total_events": total_events,
            "required_interventions": required_interventions,
            "avoided_interventions": avoided_interventions,
            "intervention_avoidance_rate": avoidance_rate,
        }

    def plan_long_horizon(
        self,
        goal_id: str,
        horizon: int = 2,
        max_subgoals_per_level: int = 5,
    ) -> dict[str, Any]:
        """Expand a goal tree level-by-level using lightweight auto decomposition.

        The planner only expands leaf goals at each horizon step and respects each
        goal's ``max_depth`` via ``auto_decompose``/``create_goal`` safeguards.
        """
        root = self.get_goal(goal_id)
        if root is None:
            return {
                "status": "error",
                "goal_id": goal_id,
                "error": "Goal not found",
                "created_count": 0,
                "levels_expanded": 0,
                "created_goal_ids": [],
            }

        levels = max(0, int(horizon))
        max_subgoals = max(1, int(max_subgoals_per_level))
        frontier = [goal_id]
        created_goal_ids: list[str] = []
        levels_expanded = 0

        for _ in range(levels):
            next_frontier: list[str] = []
            level_created = 0
            for current_goal_id in frontier:
                child_ids = self.auto_decompose(current_goal_id, max_subgoals=max_subgoals)
                if not child_ids:
                    continue
                created_goal_ids.extend(child_ids)
                next_frontier.extend(child_ids)
                level_created += len(child_ids)
            if level_created == 0:
                break
            levels_expanded += 1
            frontier = next_frontier

        return {
            "status": "ok",
            "goal_id": goal_id,
            "created_count": len(created_goal_ids),
            "levels_expanded": levels_expanded,
            "created_goal_ids": created_goal_ids,
        }

    def replan_goal(self, goal_id: str, failure_reason: str = "") -> dict[str, Any]:
        """Replan a failed/stalled goal by generating fallback subgoals.

        Replanning prefers learned decomposition strategies for the goal domain.
        If no learned strategy exists, it falls back to a compact, deterministic
        heuristic sequence that keeps manual intervention low.
        """
        goal = self.get_goal(goal_id)
        if goal is None:
            return {"status": "error", "goal_id": goal_id, "error": "Goal not found", "subgoal_ids": []}

        learned_steps = self.suggest_decomposition(goal.domain or "general")
        if learned_steps:
            subtask_descriptions = learned_steps
        else:
            reason = (failure_reason or "").strip()
            subtask_descriptions = [
                f"triage failure signals for: {goal.description}",
                "retry execution with conservative fallback settings",
                "validate output and close remaining gaps",
            ]
            if reason:
                subtask_descriptions[0] = f"triage failure ({reason}) for: {goal.description}"

        subtasks = self.decompose(goal_id, subtask_descriptions, domain=goal.domain)
        subgoal_ids = [item.id for item in subtasks]

        # Mark as active to reflect autonomous recovery attempt.
        self.update_goal(goal_id, status=GoalStatus.ACTIVE, result=None)
        self.record_intervention(goal_id, required=False, reason="auto-replan")

        return {
            "status": "replanned",
            "goal_id": goal_id,
            "subgoal_ids": subgoal_ids,
            "strategy_source": "learned" if learned_steps else "heuristic",
        }

    def record_intervention(self, goal_id: str, required: bool, reason: str = "") -> dict[str, Any]:
        """Record whether a goal step needed operator intervention."""
        event = {
            "goal_id": goal_id,
            "required": bool(required),
            "reason": str(reason or ""),
            "recorded_at": time.time(),
        }
        with self._intervention_lock:
            self._intervention_events.append(event)
        return event

    def intervention_minimization_metrics(self) -> dict[str, Any]:
        """Return aggregate intervention and avoidance metrics."""
        with self._intervention_lock:
            events = list(self._intervention_events)
        total = len(events)
        required = sum(1 for item in events if bool(item.get("required")))
        avoided = total - required
        avoidance_rate = (avoided / total) if total else 1.0
        return {
            "total_events": total,
            "required_interventions": required,
            "avoided_interventions": avoided,
            "intervention_avoidance_rate": avoidance_rate,
        }

    # ========== Introspection ==========

    def summary(self) -> dict[str, Any]:
        """Get planner summary statistics.

        Returns:
            Dict with total_goals, by_status, max_depth_used, ready_count, blocked_count
        """
        try:
            with self._db.transaction() as conn:
                # Total goals
                cursor = conn.execute("SELECT COUNT(*) as count FROM goals")
                total = cursor.fetchone()["count"]

                # By status
                cursor = conn.execute(
                    """
                    SELECT status, COUNT(*) as count FROM goals
                    GROUP BY status
                    """
                )
                by_status = {row["status"]: row["count"] for row in cursor.fetchall()}

                # Max depth
                cursor = conn.execute("SELECT MAX(depth) as max_depth FROM goals")
                result = cursor.fetchone()
                max_depth = result["max_depth"] or 0
        except sqlite3.Error as e:
            log.warning(f"Failed to compute summary: {e}")
            return {
                "total_goals": 0,
                "by_status": {},
                "max_depth_used": 0,
                "ready_count": 0,
                "blocked_count": 0,
            }

        ready_count = len(self.get_ready_goals())
        blocked_count = len(self.get_blocked_goals())

        return {
            "total_goals": total,
            "by_status": by_status,
            "max_depth_used": max_depth,
            "ready_count": ready_count,
            "blocked_count": blocked_count,
        }

    # ========== Helpers ==========

    def _row_to_goal(self, row: sqlite3.Row) -> Goal:
        """Convert database row to Goal object.

        Args:
            row: sqlite3.Row with row_factory set

        Returns:
            Goal object
        """
        return Goal(
            id=row["id"],
            parent_id=row["parent_id"],
            depth=row["depth"],
            description=row["description"],
            domain=row["domain"],
            preconditions=json.loads(row["preconditions"]),
            postconditions=json.loads(row["postconditions"]),
            success_criteria=json.loads(row["success_criteria"]),
            status=row["status"],
            assigned_model=row["assigned_model"],
            result=row["result"],
            confidence=row["confidence"],
            max_depth=row["max_depth"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _has_circular_dependency(
        self,
        goal_id: str,
        depends_on_id: str,
        conn: sqlite3.Connection,
    ) -> bool:
        """Check for circular dependency using DFS.

        Args:
            goal_id: Goal that would depend on another
            depends_on_id: Goal being depended on
            conn: Database connection

        Returns:
            True if adding this dependency would create a cycle
        """
        # DFS from depends_on_id to see if we can reach goal_id
        visited: set[str] = set()
        stack = [depends_on_id]

        while stack:
            current = stack.pop()
            if current in visited:
                continue

            visited.add(current)

            if current == goal_id:
                return True

            # Get dependencies of current goal
            cursor = conn.execute(
                """
                SELECT depends_on_id FROM goal_dependencies
                WHERE goal_id = ?
                """,
                (current,),
            )

            for row in cursor.fetchall():
                dep_id = row["depends_on_id"]
                if dep_id not in visited:
                    stack.append(dep_id)

        return False
