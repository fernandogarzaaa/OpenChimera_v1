"""Production Beta Readiness Test Suite for OpenChimera.

Uses :class:`sandbox.sandbox_simulation.SandboxSimulation` to drive the
five-phase new-user journey and asserts that every critical check passes.

Each test class maps to one simulation phase so failures are easy to
pinpoint. An additional integration class runs the complete simulation
end-to-end and validates the :class:`~sandbox.sandbox_simulation.BetaReadinessReport`.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from sandbox.sandbox_simulation import SandboxSimulation, _run_check


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sim() -> SandboxSimulation:
    """Return a fresh SandboxSimulation using a shared temp dir managed by
    the simulation itself (owned_tmp=True)."""
    return SandboxSimulation()


def _assert_phase(phase_result, *, fail_msg_prefix: str = "") -> None:
    """Assert all checks in *phase_result* passed, raising AssertionError
    with a human-readable failure summary if any did not."""
    failures = [c for c in phase_result.checks if not c.passed]
    if failures:
        details = "\n".join(
            f"  [{c.name}] {c.message}" + (f"\n    {c.error[:300]}" if c.error else "")
            for c in failures
        )
        raise AssertionError(
            f"{fail_msg_prefix or phase_result.name} — {len(failures)} check(s) failed:\n{details}"
        )


# ---------------------------------------------------------------------------
# Phase 1: Environment Setup
# ---------------------------------------------------------------------------


class TestBetaReadiness_Phase1_EnvironmentSetup(unittest.TestCase):
    """Simulate first-time environment setup for a brand-new user."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._sim = _sim()
        cls._phase = cls._sim._phase1_environment_setup()

    def _check(self, name: str) -> None:
        result = next((c for c in self._phase.checks if c.name == name), None)
        self.assertIsNotNone(result, f"check '{name}' not found in phase1")
        self.assertTrue(result.passed, f"[{name}] FAILED: {result.message}\n{result.error}")

    def test_core_package_importable(self):
        self._check("core_package_importable")

    def test_bootstrap_workspace_runs(self):
        self._check("bootstrap_workspace_runs")

    def test_database_initializes(self):
        self._check("database_initializes")

    def test_eventbus_pubsub(self):
        self._check("eventbus_pubsub")

    def test_config_loads_defaults(self):
        self._check("config_loads_defaults")

    def test_runtime_profile_normalizes(self):
        self._check("runtime_profile_normalizes")

    def test_credential_store_fresh_db(self):
        self._check("credential_store_fresh_db")


# ---------------------------------------------------------------------------
# Phase 2: Functions Discovery
# ---------------------------------------------------------------------------


class TestBetaReadiness_Phase2_FunctionsDiscovery(unittest.TestCase):
    """Simulate a new user discovering what capabilities are available."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._sim = _sim()
        cls._phase = cls._sim._phase2_functions_discovery()

    def _check(self, name: str) -> None:
        result = next((c for c in self._phase.checks if c.name == name), None)
        self.assertIsNotNone(result, f"check '{name}' not found in phase2")
        self.assertTrue(result.passed, f"[{name}] FAILED: {result.message}\n{result.error}")

    def test_capability_registry_snapshot(self):
        self._check("capability_registry_snapshot")

    def test_plugin_manager_lists_plugins(self):
        self._check("plugin_manager_lists_plugins")

    def test_command_registry_lists_commands(self):
        self._check("command_registry_lists_commands")

    def test_model_registry_refreshes(self):
        self._check("model_registry_refreshes")

    def test_onboarding_status_structure(self):
        self._check("onboarding_status_structure")

    def test_all_core_modules_importable(self):
        self._check("all_core_modules_importable")

    def test_tool_registry_initializes(self):
        self._check("tool_registry_initializes")

    def test_chimera_bridge_status(self):
        self._check("chimera_bridge_status")


# ---------------------------------------------------------------------------
# Phase 3: Capabilities Testing
# ---------------------------------------------------------------------------


class TestBetaReadiness_Phase3_CapabilitiesTesting(unittest.TestCase):
    """Simulate a new user exercising core OpenChimera capabilities."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._sim = _sim()
        cls._phase = cls._sim._phase3_capabilities_testing()

    def _check(self, name: str) -> None:
        result = next((c for c in self._phase.checks if c.name == name), None)
        self.assertIsNotNone(result, f"check '{name}' not found in phase3")
        self.assertTrue(result.passed, f"[{name}] FAILED: {result.message}\n{result.error}")

    def test_query_engine_initializes(self):
        self._check("query_engine_initializes")

    def test_query_engine_run_query(self):
        self._check("query_engine_run_query")

    def test_plan_mode_full_lifecycle(self):
        self._check("plan_mode_full_lifecycle")

    def test_session_memory_roundtrip(self):
        self._check("session_memory_roundtrip")

    def test_self_model_capability_tracking(self):
        self._check("self_model_capability_tracking")

    def test_causal_reasoning_graph(self):
        self._check("causal_reasoning_graph")

    def test_meta_learning_strategies(self):
        self._check("meta_learning_strategies")

    def test_ethical_reasoning_evaluation(self):
        self._check("ethical_reasoning_evaluation")

    def test_transfer_learning_patterns(self):
        self._check("transfer_learning_patterns")

    def test_knowledge_base_add_search(self):
        self._check("knowledge_base_add_search")

    def test_safety_layer_validates(self):
        self._check("safety_layer_validates")

    def test_multi_agent_orchestrator_status(self):
        self._check("multi_agent_orchestrator_status")

    def test_chimera_bridge_run_program(self):
        self._check("chimera_bridge_run_program")

    def test_health_monitor_tracks_subsystems(self):
        self._check("health_monitor_tracks_subsystems")


# ---------------------------------------------------------------------------
# Phase 4: Bug & Error Detection
# ---------------------------------------------------------------------------


class TestBetaReadiness_Phase4_BugErrorDetection(unittest.TestCase):
    """Verify edge cases, graceful degradation, and absence of production bugs."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._sim = _sim()
        cls._phase = cls._sim._phase4_bug_error_detection()

    def _check(self, name: str) -> None:
        result = next((c for c in self._phase.checks if c.name == name), None)
        self.assertIsNotNone(result, f"check '{name}' not found in phase4")
        self.assertTrue(result.passed, f"[{name}] FAILED: {result.message}\n{result.error}")

    def test_no_hardcoded_user_paths_in_core(self):
        self._check("no_hardcoded_user_paths_in_core")

    def test_query_engine_handles_empty_input(self):
        self._check("query_engine_handles_empty_input")

    def test_config_handles_missing_file(self):
        self._check("config_handles_missing_file")

    def test_safety_layer_handles_empty_string(self):
        self._check("safety_layer_handles_empty_string")

    def test_plan_mode_handles_no_steps(self):
        self._check("plan_mode_handles_no_steps")

    def test_knowledge_base_search_empty(self):
        self._check("knowledge_base_search_empty")

    def test_session_memory_load_nonexistent(self):
        self._check("session_memory_load_nonexistent")

    def test_tool_executor_permission_gating(self):
        self._check("tool_executor_permission_gating")

    def test_config_validation_catches_bad_failover(self):
        self._check("config_validation_catches_bad_failover")

    def test_model_registry_cpu_only_no_crash(self):
        self._check("model_registry_cpu_only_no_crash")


# ---------------------------------------------------------------------------
# Phase 5: Beta Readiness
# ---------------------------------------------------------------------------


class TestBetaReadiness_Phase5_BetaReadiness(unittest.TestCase):
    """Assert production beta readiness checks all pass."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._sim = _sim()
        cls._phase = cls._sim._phase5_beta_readiness()

    def _check(self, name: str) -> None:
        result = next((c for c in self._phase.checks if c.name == name), None)
        self.assertIsNotNone(result, f"check '{name}' not found in phase5")
        self.assertTrue(result.passed, f"[{name}] FAILED: {result.message}\n{result.error}")

    def test_kernel_instantiates_cleanly(self):
        self._check("kernel_instantiates_cleanly")

    def test_kernel_boot_report_structure(self):
        self._check("kernel_boot_report_structure")

    def test_provider_agi_completeness(self):
        self._check("provider_agi_completeness")

    def test_identity_session_lifecycle(self):
        self._check("identity_session_lifecycle")

    def test_safety_blocks_hack_content(self):
        self._check("safety_blocks_hack_content")

    def test_session_persistence_and_resume(self):
        self._check("session_persistence_and_resume")

    def test_full_agi_cognitive_pipeline(self):
        self._check("full_agi_cognitive_pipeline")

    def test_openchimera_namespace_re_exports(self):
        self._check("openchimera_namespace_re_exports")

    def test_query_engine_persists_sessions(self):
        self._check("query_engine_persists_sessions")

    def test_multi_agent_consensus_with_mock(self):
        self._check("multi_agent_consensus_with_mock")


# ---------------------------------------------------------------------------
# Integration: full simulation report
# ---------------------------------------------------------------------------


class TestBetaReadiness_Integration(unittest.TestCase):
    """Run the complete SandboxSimulation end-to-end and assert the report."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._report = SandboxSimulation().run()

    def test_report_has_five_phases(self):
        self.assertEqual(len(self._report.phases), 5)

    def test_report_score_is_in_range(self):
        score = self._report.score
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)

    def test_report_verdict_is_valid(self):
        valid_verdicts = {"PRODUCTION_READY", "BETA_READY", "ALPHA_QUALITY", "NOT_READY"}
        self.assertIn(self._report.verdict, valid_verdicts)

    def test_report_score_meets_beta_threshold(self):
        """Overall readiness score should be ≥ 80 (BETA_READY)."""
        self.assertGreaterEqual(
            self._report.score,
            80.0,
            msg=(
                f"Score {self._report.score}% is below the 80% beta threshold.\n"
                + "Failed checks:\n"
                + "\n".join(
                    f"  [{c.phase}/{c.name}] {c.message}"
                    for c in self._report.failed_checks
                )
            ),
        )

    def test_report_summary_shape(self):
        summary = self._report.summary()
        required_keys = {"score", "verdict", "pass_count", "fail_count", "total_checks", "phases"}
        missing = required_keys - set(summary.keys())
        self.assertFalse(missing, f"summary missing keys: {missing}")

    def test_report_phase_names(self):
        expected_phases = {
            "phase1_environment_setup",
            "phase2_functions_discovery",
            "phase3_capabilities_testing",
            "phase4_bug_error_detection",
            "phase5_beta_readiness",
        }
        actual = {p.name for p in self._report.phases}
        self.assertEqual(actual, expected_phases)

    def test_phase1_environment_setup_all_pass(self):
        phase = next(p for p in self._report.phases if p.name == "phase1_environment_setup")
        _assert_phase(phase)

    def test_phase2_functions_discovery_all_pass(self):
        phase = next(p for p in self._report.phases if p.name == "phase2_functions_discovery")
        _assert_phase(phase)

    def test_phase3_capabilities_testing_all_pass(self):
        phase = next(p for p in self._report.phases if p.name == "phase3_capabilities_testing")
        _assert_phase(phase)

    def test_phase4_bug_error_detection_all_pass(self):
        phase = next(p for p in self._report.phases if p.name == "phase4_bug_error_detection")
        _assert_phase(phase)

    def test_phase5_beta_readiness_all_pass(self):
        phase = next(p for p in self._report.phases if p.name == "phase5_beta_readiness")
        _assert_phase(phase)

    def test_report_generated_at_is_set(self):
        self.assertTrue(self._report.generated_at, "generated_at should be set")
        # Should be a valid ISO 8601 timestamp
        import datetime
        try:
            datetime.datetime.fromisoformat(self._report.generated_at)
        except ValueError as exc:
            self.fail(f"generated_at is not a valid ISO 8601 timestamp: {exc}")

    def test_report_total_duration_positive(self):
        self.assertGreater(self._report.total_duration_ms, 0)

    def test_pass_count_plus_fail_equals_total(self):
        self.assertEqual(
            self._report.pass_count + self._report.fail_count,
            len(self._report.all_checks),
        )
