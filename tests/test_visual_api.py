"""
Tests for Phase 3: Visual Interface API (Canvas, Module Status, System Metrics).
"""
from __future__ import annotations

import unittest

from core.visual_api import get_canvas_state, get_module_status, get_system_metrics


class TestCanvasState(unittest.TestCase):
    def test_returns_nodes_and_edges(self):
        state = get_canvas_state()
        self.assertIn("nodes", state)
        self.assertIn("edges", state)
        self.assertIn("timestamp", state)

    def test_nodes_have_required_fields(self):
        state = get_canvas_state()
        for node in state["nodes"]:
            self.assertIn("id", node)
            self.assertIn("label", node)
            self.assertIn("type", node)
            self.assertIn("x", node)
            self.assertIn("y", node)
            self.assertIn("active", node)

    def test_edges_have_required_fields(self):
        state = get_canvas_state()
        for edge in state["edges"]:
            self.assertIn("id", edge)
            self.assertIn("from", edge)
            self.assertIn("to", edge)
            self.assertIn("strength", edge)
            self.assertIn("type", edge)

    def test_edge_node_references_valid(self):
        state = get_canvas_state()
        node_ids = {n["id"] for n in state["nodes"]}
        for edge in state["edges"]:
            self.assertIn(edge["from"], node_ids, f"Edge from '{edge['from']}' references unknown node")
            self.assertIn(edge["to"], node_ids, f"Edge to '{edge['to']}' references unknown node")

    def test_node_types_valid(self):
        valid_types = {"agent", "memory", "goal", "tool", "event"}
        state = get_canvas_state()
        for node in state["nodes"]:
            self.assertIn(node["type"], valid_types)

    def test_edge_strengths_in_range(self):
        state = get_canvas_state()
        for edge in state["edges"]:
            self.assertGreaterEqual(edge["strength"], 0.0)
            self.assertLessEqual(edge["strength"], 1.0)

    def test_has_agi_modules_represented(self):
        state = get_canvas_state()
        labels = " ".join(n["label"] for n in state["nodes"]).lower()
        # At least some key AGI modules should be present
        self.assertTrue(
            any(term in labels for term in ["deliberation", "memory", "goal", "quantum", "evolution"])
        )

    def test_timestamp_is_int(self):
        state = get_canvas_state()
        self.assertIsInstance(state["timestamp"], int)


class TestModuleStatus(unittest.TestCase):
    def test_returns_list(self):
        statuses = get_module_status()
        self.assertIsInstance(statuses, list)
        self.assertGreater(len(statuses), 0)

    def test_status_has_required_fields(self):
        statuses = get_module_status()
        for s in statuses:
            self.assertIn("name", s)
            self.assertIn("status", s)
            self.assertIn("latency_ms", s)

    def test_status_values_valid(self):
        valid_statuses = {"healthy", "degraded", "offline", "unknown"}
        statuses = get_module_status()
        for s in statuses:
            self.assertIn(s["status"], valid_statuses)

    def test_all_agi_modules_present(self):
        expected = {
            "memory", "deliberation", "goal_planner", "evolution", "metacognition",
            "self_model", "transfer_learning", "causal_reasoning", "embodied_interaction", "social_cognition",
        }
        statuses = get_module_status()
        names = {s["name"] for s in statuses}
        for module in expected:
            self.assertIn(module, names, f"Module '{module}' missing from status")

    def test_latency_positive(self):
        statuses = get_module_status()
        for s in statuses:
            self.assertGreater(s["latency_ms"], 0)


class TestSystemMetrics(unittest.TestCase):
    def test_returns_dict(self):
        metrics = get_system_metrics()
        self.assertIsInstance(metrics, dict)

    def test_has_required_fields(self):
        metrics = get_system_metrics()
        self.assertIn("cpu_pct", metrics)
        self.assertIn("memory_pct", metrics)
        self.assertIn("active_sessions", metrics)
        self.assertIn("tasks_queued", metrics)

    def test_cpu_pct_in_range(self):
        metrics = get_system_metrics()
        self.assertGreaterEqual(metrics["cpu_pct"], 0.0)
        self.assertLessEqual(metrics["cpu_pct"], 100.0)

    def test_memory_pct_in_range(self):
        metrics = get_system_metrics()
        self.assertGreaterEqual(metrics["memory_pct"], 0.0)
        self.assertLessEqual(metrics["memory_pct"], 100.0)

    def test_task_counts_non_negative(self):
        metrics = get_system_metrics()
        self.assertGreaterEqual(metrics["tasks_queued"], 0)
        self.assertGreaterEqual(metrics["active_sessions"], 0)


if __name__ == "__main__":
    unittest.main()
