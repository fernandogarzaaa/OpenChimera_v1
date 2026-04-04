from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from core.autonomy_plane import AutonomyPlane


def _make_plane(**overrides: Any) -> AutonomyPlane:
    defaults: dict[str, Any] = {
        "profile_getter": lambda: {},
        "autonomy": MagicMock(),
        "job_queue": MagicMock(),
        "channels": MagicMock(),
        "bus": MagicMock(),
        "provider_activation_getter": lambda: {"status": "ok"},
        "job_queue_status_getter": lambda **kwargs: {"jobs": []},
        "daily_briefing_getter": lambda: {"briefing": "ok"},
        "create_operator_job_callback": MagicMock(return_value={"status": "queued", "job_id": "job-abc"}),
        "run_autonomy_job_callback": MagicMock(return_value={"status": "ok"}),
    }
    defaults.update(overrides)
    return AutonomyPlane(**defaults)


class AutonomyPlaneInstantiationTests(unittest.TestCase):
    def test_instantiation(self) -> None:
        plane = _make_plane()
        self.assertIsNotNone(plane)

    def test_profile_returns_copy_of_getter_result(self) -> None:
        profile = {"key": "value"}
        plane = _make_plane(profile_getter=lambda: profile)
        result = plane.profile
        self.assertEqual(result, {"key": "value"})
        result["mutated"] = True
        self.assertNotIn("mutated", plane.profile)

    def test_profile_handles_none_from_getter(self) -> None:
        plane = _make_plane(profile_getter=lambda: None)  # type: ignore[arg-type]
        self.assertEqual(plane.profile, {})


class AutonomyPlaneDiagnosticsTests(unittest.TestCase):
    def test_diagnostics_missing_artifact_path(self) -> None:
        autonomy = MagicMock()
        autonomy.status.return_value = {
            "artifacts": {"self_audit": "/tmp/__nonexistent_openchimera_xyz__.json"},
        }
        autonomy.artifact_history.return_value = []
        plane = _make_plane(autonomy=autonomy)
        result = plane.diagnostics()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["artifacts"]["self_audit"]["status"], "missing")

    def test_diagnostics_invalid_json_artifact(self) -> None:
        autonomy = MagicMock()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not valid json {{{{")
            artifact_path = f.name
        try:
            autonomy.status.return_value = {"artifacts": {"self_audit": artifact_path}}
            autonomy.artifact_history.return_value = []
            plane = _make_plane(autonomy=autonomy)
            result = plane.diagnostics()
            self.assertEqual(result["artifacts"]["self_audit"]["status"], "error")
            self.assertIn("error", result["artifacts"]["self_audit"])
        finally:
            Path(artifact_path).unlink(missing_ok=True)

    def test_diagnostics_valid_artifact_parsed(self) -> None:
        autonomy = MagicMock()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"findings": ["a", "b"]}, f)
            artifact_path = f.name
        try:
            autonomy.status.return_value = {"artifacts": {"self_audit": artifact_path}}
            autonomy.artifact_history.return_value = []
            plane = _make_plane(autonomy=autonomy)
            result = plane.diagnostics()
            self.assertEqual(result["artifacts"]["self_audit"]["findings"], ["a", "b"])
        finally:
            Path(artifact_path).unlink(missing_ok=True)

    def test_diagnostics_no_artifacts(self) -> None:
        autonomy = MagicMock()
        autonomy.status.return_value = {"artifacts": {}}
        autonomy.artifact_history.return_value = []
        plane = _make_plane(autonomy=autonomy)
        result = plane.diagnostics()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["artifacts"], {})


class AutonomyPlaneArtifactTests(unittest.TestCase):
    def test_artifact_history_proxies_to_autonomy(self) -> None:
        autonomy = MagicMock()
        autonomy.artifact_history.return_value = [{"name": "test"}]
        plane = _make_plane(autonomy=autonomy)
        result = plane.artifact_history("self_audit", limit=5)
        autonomy.artifact_history.assert_called_once_with(artifact_name="self_audit", limit=5)
        self.assertEqual(result, [{"name": "test"}])

    def test_artifact_history_none_name(self) -> None:
        autonomy = MagicMock()
        autonomy.artifact_history.return_value = []
        plane = _make_plane(autonomy=autonomy)
        plane.artifact_history(None, limit=10)
        autonomy.artifact_history.assert_called_once_with(artifact_name=None, limit=10)

    def test_artifact_reads_from_autonomy(self) -> None:
        autonomy = MagicMock()
        autonomy.read_artifact.return_value = {"findings": []}
        plane = _make_plane(autonomy=autonomy)
        result = plane.artifact("self_audit")
        autonomy.read_artifact.assert_called_once_with("self_audit")
        self.assertEqual(result["findings"], [])

    def test_operator_digest_calls_artifact(self) -> None:
        autonomy = MagicMock()
        autonomy.read_artifact.return_value = {"digest": "summary"}
        plane = _make_plane(autonomy=autonomy)
        result = plane.operator_digest()
        autonomy.read_artifact.assert_called_with("operator_digest")
        self.assertEqual(result["digest"], "summary")


class AutonomyPlaneDispatchTests(unittest.TestCase):
    def test_dispatch_operator_digest_direct_run(self) -> None:
        run_cb = MagicMock(return_value={"status": "ok"})
        plane = _make_plane(run_autonomy_job_callback=run_cb)
        result = plane.dispatch_operator_digest(enqueue=False)
        run_cb.assert_called_once()
        self.assertEqual(result["status"], "ok")

    def test_dispatch_operator_digest_enqueue(self) -> None:
        create_cb = MagicMock(return_value={"status": "queued", "job_id": "job-x"})
        plane = _make_plane(create_operator_job_callback=create_cb)
        result = plane.dispatch_operator_digest(enqueue=True, max_attempts=2)
        create_cb.assert_called_once()
        self.assertEqual(result["status"], "queued")

    def test_dispatch_operator_digest_with_history_limit(self) -> None:
        run_cb = MagicMock(return_value={"status": "ok"})
        plane = _make_plane(run_autonomy_job_callback=run_cb)
        plane.dispatch_operator_digest(history_limit=10)
        call_kwargs = run_cb.call_args
        payload = call_kwargs[1].get("payload") or call_kwargs[0][1] if len(call_kwargs[0]) > 1 else {}
        # history_limit passed through payload when it's not None
        self.assertIsNotNone(call_kwargs)

    def test_dispatch_operator_digest_with_topic(self) -> None:
        run_cb = MagicMock(return_value={"status": "ok"})
        plane = _make_plane(run_autonomy_job_callback=run_cb)
        plane.dispatch_operator_digest(dispatch_topic="my/custom/topic")
        run_cb.assert_called_once()

    def test_preview_self_repair_direct(self) -> None:
        run_cb = MagicMock(return_value={"status": "ok"})
        plane = _make_plane(run_autonomy_job_callback=run_cb)
        result = plane.preview_self_repair()
        run_cb.assert_called_once()
        self.assertEqual(result["status"], "ok")

    def test_preview_self_repair_with_target_project(self) -> None:
        run_cb = MagicMock(return_value={"status": "ok"})
        plane = _make_plane(run_autonomy_job_callback=run_cb)
        plane.preview_self_repair(target_project="myproj")
        call_args = run_cb.call_args
        self.assertIsNotNone(call_args)

    def test_preview_self_repair_enqueue(self) -> None:
        create_cb = MagicMock(return_value={"status": "queued", "job_id": "job-y"})
        plane = _make_plane(create_operator_job_callback=create_cb)
        result = plane.preview_self_repair(enqueue=True, target_project="proj")
        create_cb.assert_called_once()
        self.assertEqual(result["status"], "queued")


class AutonomyPlaneJobEventTests(unittest.TestCase):
    def test_handle_job_event_dispatches_channels(self) -> None:
        channels = MagicMock()
        autonomy = MagicMock()
        autonomy.read_artifact.return_value = {}
        plane = _make_plane(channels=channels, autonomy=autonomy)
        plane.handle_job_event({"job": "run_self_audit", "status": "completed"})
        channels.dispatch.assert_called()

    def test_handle_job_event_non_dict_is_ignored(self) -> None:
        channels = MagicMock()
        plane = _make_plane(channels=channels)
        plane.handle_job_event("not-a-dict")
        channels.dispatch.assert_not_called()

    def test_handle_job_event_dispatches_alert_when_above_threshold(self) -> None:
        channels = MagicMock()
        autonomy = MagicMock()
        autonomy.read_artifact.return_value = {
            "chains": [{"severity": "critical", "desc": "oops"}],
            "generated_at": int(time.time()),
        }
        profile = {"autonomy": {"alerts": {"enabled": True, "minimum_severity": "info"}}}
        plane = _make_plane(
            channels=channels,
            autonomy=autonomy,
            profile_getter=lambda: profile,
        )
        plane.handle_job_event({"job": "check_degradation_chains", "status": "completed"})
        # Should dispatch at least twice: once for job topic, once for alert topic
        self.assertGreaterEqual(channels.dispatch.call_count, 2)


class AutonomyPlaneAlertTests(unittest.TestCase):
    def test_build_alert_disabled_returns_none(self) -> None:
        plane = _make_plane(
            profile_getter=lambda: {"autonomy": {"alerts": {"enabled": False}}}
        )
        result = plane.build_autonomy_alert({"job": "run_self_audit"})
        self.assertIsNone(result)

    def test_build_alert_empty_job_name_returns_none(self) -> None:
        plane = _make_plane()
        result = plane.build_autonomy_alert({"job": ""})
        self.assertIsNone(result)

    def test_build_alert_unknown_job_returns_none(self) -> None:
        plane = _make_plane()
        result = plane.build_autonomy_alert({"job": "unknown_job_xyz_does_not_map"})
        self.assertIsNone(result)

    def test_build_alert_below_threshold_returns_none(self) -> None:
        autonomy = MagicMock()
        autonomy.read_artifact.return_value = {"chains": []}
        plane = _make_plane(
            autonomy=autonomy,
            profile_getter=lambda: {"autonomy": {"alerts": {"enabled": True, "minimum_severity": "critical"}}},
        )
        result = plane.build_autonomy_alert({"job": "check_degradation_chains"})
        self.assertIsNone(result)

    def test_build_alert_degradation_chains_critical(self) -> None:
        autonomy = MagicMock()
        autonomy.read_artifact.return_value = {
            "chains": [{"severity": "critical", "desc": "oops"}],
            "generated_at": int(time.time()),
        }
        plane = _make_plane(
            autonomy=autonomy,
            profile_getter=lambda: {"autonomy": {"alerts": {"enabled": True, "minimum_severity": "info"}}},
        )
        result = plane.build_autonomy_alert({"job": "check_degradation_chains"})
        self.assertIsNotNone(result)
        self.assertEqual(result["severity"], "critical")
        self.assertEqual(result["job"], "check_degradation_chains")

    def test_build_alert_degradation_chains_no_chains_info_severity(self) -> None:
        autonomy = MagicMock()
        autonomy.read_artifact.return_value = {
            "chains": [],
            "generated_at": int(time.time()),
        }
        plane = _make_plane(
            autonomy=autonomy,
            profile_getter=lambda: {"autonomy": {"alerts": {"enabled": True, "minimum_severity": "info"}}},
        )
        result = plane.build_autonomy_alert({"job": "check_degradation_chains"})
        self.assertIsNotNone(result)
        self.assertEqual(result["severity"], "info")

    def test_build_alert_degradation_chains_non_critical_items_high(self) -> None:
        autonomy = MagicMock()
        autonomy.read_artifact.return_value = {
            "chains": [{"severity": "warning"}],
            "generated_at": int(time.time()),
        }
        plane = _make_plane(
            autonomy=autonomy,
            profile_getter=lambda: {"autonomy": {"alerts": {"enabled": True, "minimum_severity": "info"}}},
        )
        result = plane.build_autonomy_alert({"job": "check_degradation_chains"})
        self.assertIsNotNone(result)
        self.assertEqual(result["severity"], "high")

    def test_build_alert_self_audit_critical_finding(self) -> None:
        autonomy = MagicMock()
        autonomy.read_artifact.return_value = {
            "findings": [{"severity": "critical", "description": "bad thing"}],
            "generated_at": int(time.time()),
        }
        plane = _make_plane(
            autonomy=autonomy,
            profile_getter=lambda: {"autonomy": {"alerts": {"enabled": True, "minimum_severity": "info"}}},
        )
        result = plane.build_autonomy_alert({"job": "run_self_audit"})
        self.assertIsNotNone(result)
        self.assertEqual(result["severity"], "critical")

    def test_build_alert_self_audit_warning_status(self) -> None:
        autonomy = MagicMock()
        autonomy.read_artifact.return_value = {
            "findings": [],
            "status": "warning",
            "generated_at": int(time.time()),
        }
        plane = _make_plane(
            autonomy=autonomy,
            profile_getter=lambda: {"autonomy": {"alerts": {"enabled": True, "minimum_severity": "info"}}},
        )
        result = plane.build_autonomy_alert({"job": "run_self_audit"})
        self.assertIsNotNone(result)
        self.assertEqual(result["severity"], "high")

    def test_build_alert_preview_self_repair_with_focus_areas(self) -> None:
        autonomy = MagicMock()
        autonomy.read_artifact.return_value = {
            "focus_areas": ["auth", "db", "llm"],
            "generated_at": int(time.time()),
        }
        plane = _make_plane(
            autonomy=autonomy,
            profile_getter=lambda: {"autonomy": {"alerts": {"enabled": True, "minimum_severity": "info"}}},
        )
        result = plane.build_autonomy_alert({"job": "preview_self_repair"})
        self.assertIsNotNone(result)
        self.assertEqual(result["severity"], "high")

    def test_build_alert_preview_self_repair_no_focus_areas(self) -> None:
        autonomy = MagicMock()
        autonomy.read_artifact.return_value = {
            "focus_areas": [],
            "generated_at": int(time.time()),
        }
        plane = _make_plane(
            autonomy=autonomy,
            profile_getter=lambda: {"autonomy": {"alerts": {"enabled": True, "minimum_severity": "info"}}},
        )
        result = plane.build_autonomy_alert({"job": "preview_self_repair"})
        # info severity is below default "high" minimum
        # with default profile {} → min_severity="high" → info < high → None
        # But we set minimum_severity info above, so result is not None
        self.assertIsNotNone(result)
        self.assertEqual(result["severity"], "info")

    def test_build_alert_artifact_not_dict_returns_none(self) -> None:
        autonomy = MagicMock()
        autonomy.read_artifact.return_value = "not-a-dict"
        plane = _make_plane(autonomy=autonomy)
        result = plane.build_autonomy_alert({"job": "run_self_audit"})
        self.assertIsNone(result)

    def test_severity_rank_all_levels(self) -> None:
        plane = _make_plane()
        self.assertEqual(plane.severity_rank("info"), 1)
        self.assertEqual(plane.severity_rank("warning"), 2)
        self.assertEqual(plane.severity_rank("high"), 3)
        self.assertEqual(plane.severity_rank("critical"), 4)
        self.assertEqual(plane.severity_rank("unknown"), 1)
        self.assertEqual(plane.severity_rank("CRITICAL"), 4)


class AutonomyPlaneJobExecutionTests(unittest.TestCase):
    def test_execute_operator_job_autonomy_type(self) -> None:
        autonomy = MagicMock()
        autonomy.run_job.return_value = {"status": "ok"}
        plane = _make_plane(autonomy=autonomy)
        result = plane.execute_operator_job({"job_type": "autonomy", "payload": {"job": "run_self_audit"}})
        autonomy.run_job.assert_called_once_with("run_self_audit", payload={})
        self.assertEqual(result["status"], "ok")

    def test_execute_operator_job_autonomy_dot_prefix(self) -> None:
        autonomy = MagicMock()
        autonomy.run_job.return_value = {"status": "ok"}
        plane = _make_plane(autonomy=autonomy)
        result = plane.execute_operator_job({"job_type": "autonomy.audit", "payload": {"job": "run_self_audit"}})
        self.assertEqual(result["status"], "ok")

    def test_execute_operator_job_missing_name_returns_error(self) -> None:
        plane = _make_plane()
        result = plane.execute_operator_job({"job_type": "autonomy", "payload": {}})
        self.assertEqual(result["status"], "error")
        self.assertIn("Missing", result["error"])

    def test_execute_operator_job_unsupported_type_returns_error(self) -> None:
        plane = _make_plane()
        result = plane.execute_operator_job({"job_type": "completely_unknown", "payload": {}})
        self.assertEqual(result["status"], "error")
        self.assertIn("Unsupported", result["error"])

    def test_classify_operator_job_non_autonomy_passthrough(self) -> None:
        plane = _make_plane()
        result = plane.classify_operator_job("myjob.type", {})
        self.assertEqual(result, ("myjob.type", "myjob.type", "myjob type"))

    def test_classify_operator_job_known_mapping(self) -> None:
        plane = _make_plane()
        result = plane.classify_operator_job("autonomy", {"job": "run_self_audit"})
        self.assertEqual(result[0], "autonomy.audit")

    def test_classify_operator_job_unknown_job_name(self) -> None:
        plane = _make_plane()
        result = plane.classify_operator_job("autonomy", {"job": "something_new"})
        self.assertEqual(result[0], "autonomy")

    def test_create_operator_job_enqueues(self) -> None:
        job_queue = MagicMock()
        job_queue.enqueue.return_value = {"status": "queued", "job_id": "job-abc"}
        plane = _make_plane(job_queue=job_queue)
        result = plane.create_operator_job("autonomy", {"job": "run_self_audit"})
        job_queue.enqueue.assert_called_once()
        self.assertEqual(result["job_id"], "job-abc")


if __name__ == "__main__":
    unittest.main()
