from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import run


ROOT = Path(__file__).resolve().parents[1]


class OpenChimeraCLITests(unittest.TestCase):
    def test_bootstrap_command_emits_json(self) -> None:
        with patch.object(run, "bootstrap_workspace", return_value={"status": "ok", "workspace_root": "D:/OpenChimera", "created_directories": [], "created_files": [], "normalized_files": []}):
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = run.main(["bootstrap", "--json"])

        self.assertEqual(exit_code, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["status"], "ok")

    def test_status_command_uses_kernel_snapshot(self) -> None:
        fake_provider = SimpleNamespace(
            provider_activation_status=MagicMock(
                return_value={
                    "prefer_free_models": True,
                    "fallback_learning": {
                        "learned_rankings_available": True,
                        "top_ranked_models": [
                            {
                                "id": "openrouter/top-choice",
                                "query_type": "general",
                                "rank": 1,
                            }
                        ],
                        "degraded_models": ["openrouter/weak-choice"],
                    },
                }
            )
        )
        fake_snapshot = {
            "provider_online": True,
            "aether": {"status": "offline"},
            "wraith": {"status": "offline"},
            "evo": {"status": "offline"},
            "aegis": {"status": "offline"},
            "ascension": {"status": "offline"},
        }
        with patch.object(run, "_build_provider", return_value=fake_provider), patch.object(run, "_build_status_snapshot", return_value=fake_snapshot):
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = run.main(["status", "--json"])

        self.assertEqual(exit_code, 0)
        payload = json.loads(output.getvalue())
        self.assertTrue(payload["provider_online"])
        self.assertTrue(payload["provider_activation"]["fallback_learning"]["learned_rankings_available"])

    def test_status_command_renders_runtime_state_labels(self) -> None:
        fake_provider = SimpleNamespace(provider_activation_status=MagicMock(return_value={"prefer_free_models": False, "fallback_learning": {}}))
        fake_snapshot = {
            "provider_online": True,
            "aether": {"available": True, "running": False},
            "wraith": {"available": False, "running": False},
            "evo": {"available": True, "running": True},
            "aegis": {"available": True, "running": False},
            "ascension": {"available": False, "running": False},
        }
        with patch.object(run, "_build_provider", return_value=fake_provider), patch.object(run, "_build_status_snapshot", return_value=fake_snapshot):
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = run.main(["status"])

        self.assertEqual(exit_code, 0)
        rendered = output.getvalue()
        self.assertIn("AETHER: available", rendered)
        self.assertIn("WRAITH: missing", rendered)
        self.assertIn("Evo: running", rendered)

    def test_doctor_payload_warns_when_aether_immune_loop_is_degraded(self) -> None:
        fake_provider = SimpleNamespace(
            llm_manager=SimpleNamespace(
                get_runtime_status=MagicMock(
                    return_value={
                        "llama_server_exists": True,
                        "models": {},
                        "discovery": {"search_roots": ["D:/models"], "discovered_files": []},
                    }
                )
            )
        )
        fake_identity = {
            "root": "D:/OpenChimera",
            "integration_roots": {
                "harness_repo": "D:/repos/upstream-harness-repo",
                "legacy_harness_snapshot": "D:/OpenChimera/data/harness-snapshots",
                "minimind": "D:/openclaw/research/minimind",
            },
        }
        with patch.object(run, "bootstrap_workspace", return_value={"status": "ok"}), patch.object(
            run, "load_runtime_profile", return_value={"providers": {"enabled": ["local-llama-cpp"], "preferred_cloud_provider": ""}}
        ), patch.object(run, "build_identity_snapshot", return_value=fake_identity), patch.object(
            run, "_build_provider", return_value=fake_provider
        ), patch.object(
            run, "AetherService", return_value=SimpleNamespace(status=lambda: {"available": True, "immune_loop_available": False, "immune_loop_error": "No module named 'psutil'"})
        ), patch.object(run, "get_runtime_profile_path", return_value=Path("D:/OpenChimera/config/runtime_profile.json")), patch.object(
            run, "get_runtime_profile_override_path", return_value=Path("D:/OpenChimera/config/runtime_profile.local.json")
        ), patch.object(run, "get_harness_repo_root", return_value=Path("D:/repos/upstream-harness-repo")), patch.object(
            run, "get_legacy_harness_snapshot_root", return_value=Path("D:/OpenChimera/data/harness-snapshots")
        ), patch.object(run, "get_minimind_root", return_value=Path("D:/openclaw/research/minimind")), patch.object(
            run, "is_supported_harness_repo_root", return_value=True
        ), patch.object(run, "is_api_auth_enabled", return_value=False), patch.object(run, "get_api_auth_header", return_value="Authorization"), patch.object(
            run, "get_api_auth_token", return_value=""
        ), patch.object(run, "get_api_admin_token", return_value=""):
            payload = run._doctor_payload()

        self.assertFalse(payload["checks"]["aether_immune_loop_available"])
        self.assertTrue(any("AETHER immune loop is unavailable" in warning for warning in payload["warnings"]))
        self.assertEqual(payload["local_model_discovery"]["search_roots"], ["D:/models"])

    def test_doctor_payload_warns_when_public_bind_has_no_auth(self) -> None:
        fake_provider = SimpleNamespace(llm_manager=SimpleNamespace(get_runtime_status=MagicMock(return_value={"llama_server_exists": True, "models": {}, "discovery": {"search_roots": [], "discovered_files": []}})))
        fake_identity = {"root": "D:/OpenChimera", "integration_roots": {"harness_repo": "D:/repos/upstream-harness-repo", "legacy_harness_snapshot": "D:/OpenChimera/data/harness-snapshots", "minimind": "D:/openclaw/research/minimind"}}
        safe_config = {
            "network": {"public_bind": True},
            "auth": {"enabled": False},
        }
        with patch.object(run, "bootstrap_workspace", return_value={"status": "ok"}), patch.object(run, "load_runtime_profile", return_value={"providers": {}}), patch.object(run, "build_identity_snapshot", return_value=fake_identity), patch.object(run, "build_runtime_configuration_status", return_value=safe_config), patch.object(run, "_build_provider", return_value=fake_provider), patch.object(run, "AetherService", return_value=SimpleNamespace(status=lambda: {"available": False, "immune_loop_available": False, "immune_loop_error": None})), patch.object(run, "get_runtime_profile_path", return_value=Path("D:/OpenChimera/config/runtime_profile.json")), patch.object(run, "get_runtime_profile_override_path", return_value=Path("D:/OpenChimera/config/runtime_profile.local.json")), patch.object(run, "get_harness_repo_root", return_value=Path("D:/repos/upstream-harness-repo")), patch.object(run, "get_legacy_harness_snapshot_root", return_value=Path("D:/OpenChimera/data/harness-snapshots")), patch.object(run, "get_minimind_root", return_value=Path("D:/openclaw/research/minimind")), patch.object(run, "is_supported_harness_repo_root", return_value=True), patch.object(run, "is_api_auth_enabled", return_value=False), patch.object(run, "get_api_auth_header", return_value="Authorization"), patch.object(run, "get_api_auth_token", return_value=""), patch.object(run, "get_api_admin_token", return_value=""):
            payload = run._doctor_payload()

        self.assertFalse(payload["checks"]["external_bind_protected"])
        self.assertTrue(any("bind beyond localhost without API auth" in warning for warning in payload["warnings"]))

    def test_config_command_emits_sanitized_snapshot(self) -> None:
        payload = {
            "provider_url": "http://127.0.0.1:7870",
            "network": {"public_bind": False},
            "auth": {"enabled": True},
            "profile_sources": {"local_override_exists": True},
            "deployment": {"transport": {"tls_enabled": True}, "logging": {"structured_enabled": True}},
        }
        with patch.object(run, "build_runtime_configuration_status", return_value=payload):
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = run.main(["config", "--json"])

        self.assertEqual(exit_code, 0)
        rendered = json.loads(output.getvalue())
        self.assertEqual(rendered["provider_url"], "http://127.0.0.1:7870")

    def test_doctor_command_prints_local_model_search_roots_when_assets_missing(self) -> None:
        payload = {
            "status": "warning",
            "provider_url": "http://127.0.0.1:7870",
            "auth": {"enabled": False},
            "checks": {
                "runtime_profile_exists": True,
                "local_model_assets_available": False,
            },
            "warnings": ["No local GGUF model assets were found in the configured or discovered search roots."],
            "local_model_discovery": {
                "search_roots": ["D:/OpenChimera/models", "D:/models"],
                "discovered_files": [],
            },
        }
        with patch.object(run, "_doctor_payload", return_value=payload):
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = run.main(["doctor"])

        self.assertEqual(exit_code, 0)
        rendered = output.getvalue()
        self.assertIn("Local model search roots:", rendered)
        self.assertIn("D:/OpenChimera/models", rendered)

    def test_validate_command_reports_release_validation_summary(self) -> None:
        validation_result = {
            "command": [sys.executable, "-m", "unittest"],
            "pattern": "test_*.py",
            "passed": True,
            "returncode": 0,
            "stdout": "Ran 3 tests in 0.123s\n\nOK\n",
            "stderr": "",
            "streamed": True,
        }
        with patch.object(run, "_doctor_payload", return_value={"status": "ok", "warnings": []}), patch.object(
            run,
            "_run_validation_tests",
            return_value=validation_result,
        ) as validation_mock:
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = run.main(["validate"])

        self.assertEqual(exit_code, 0)
        validation_mock.assert_called_once_with(test_pattern="test_*.py", stream_output=True)
        rendered = output.getvalue()
        self.assertIn("OpenChimera validate: ok", rendered)
        self.assertIn("Tests passed: True", rendered)
        self.assertIn("Validation gate: passed", rendered)

    def test_validate_command_returns_nonzero_when_tests_fail(self) -> None:
        validation_result = {
            "command": [sys.executable, "-m", "unittest"],
            "pattern": "test_cli.py",
            "passed": False,
            "returncode": 1,
            "stdout": "FAILED (failures=1)\n",
            "stderr": "traceback",
            "streamed": True,
        }
        with patch.object(run, "_doctor_payload", return_value={"status": "ok", "warnings": []}), patch.object(
            run,
            "_run_validation_tests",
            return_value=validation_result,
        ):
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = run.main(["validate", "--pattern", "test_cli.py"])

        self.assertEqual(exit_code, 1)
        rendered = output.getvalue()
        self.assertIn("OpenChimera validate: error", rendered)
        self.assertIn("Test pattern: test_cli.py", rendered)
        self.assertIn("Validation gate: failed", rendered)

    def test_validate_command_emits_json_with_captured_test_output(self) -> None:
        validation_result = {
            "command": [sys.executable, "-m", "unittest"],
            "pattern": "test_cli.py",
            "passed": False,
            "returncode": 1,
            "stdout": "FAILED (failures=1)\n",
            "stderr": "traceback",
            "streamed": False,
        }
        with patch.object(run, "_doctor_payload", return_value={"status": "ok", "warnings": []}), patch.object(
            run,
            "_run_validation_tests",
            return_value=validation_result,
        ) as validation_mock:
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = run.main(["validate", "--json", "--pattern", "test_cli.py"])

        self.assertEqual(exit_code, 1)
        validation_mock.assert_called_once_with(test_pattern="test_cli.py", stream_output=False)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["tests"]["stderr"], "traceback")
        self.assertFalse(payload["tests"]["streamed"])

    def test_briefing_command_reports_fallback_leaders(self) -> None:
        fake_provider = SimpleNamespace(
            daily_briefing=MagicMock(
                return_value={
                    "summary": "OpenChimera runtime has 1 healthy local model and 1 learned free fallback leader.",
                    "priorities": ["Learned free fallback leader: openrouter/top-choice for general queries."],
                    "fallback_learning": {
                        "top_ranked_models": [
                            {
                                "id": "openrouter/top-choice",
                                "query_type": "general",
                                "rank": 1,
                            }
                        ],
                        "degraded_models": ["openrouter/weak-choice"],
                    },
                }
            )
        )
        with patch.object(run, "_build_provider", return_value=fake_provider):
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = run.main(["briefing"])

        self.assertEqual(exit_code, 0)
        rendered = output.getvalue()
        self.assertIn("Fallback leaders: openrouter/top-choice (general #1)", rendered)
        self.assertIn("Degraded free fallbacks: openrouter/weak-choice", rendered)

    def test_channels_command_reports_status_and_dispatches_topic(self) -> None:
        fake_provider = SimpleNamespace(
            upsert_channel_subscription=MagicMock(
                return_value={
                    "id": "ops-webhook",
                    "channel": "webhook",
                    "topics": ["system/autonomy/alert"],
                }
            ),
            delete_channel_subscription=MagicMock(return_value={"deleted": True, "subscription_id": "ops-webhook"}),
            validate_channel_subscription=MagicMock(return_value={"subscription_id": "ops-webhook", "status": "delivered", "status_code": 200}),
            channel_status=MagicMock(
                return_value={
                    "counts": {"total": 1, "enabled": 1, "validated": 1, "healthy": 1, "errors": 0},
                    "subscriptions": [
                        {"id": "ops-webhook", "channel": "webhook", "topics": ["system/autonomy/alert"], "endpoint": "http://example.invalid/webhook", "last_validation": {"status": "delivered"}},
                    ],
                    "last_delivery": {"topic": "system/autonomy/alert", "delivery_count": 1},
                }
            ),
            dispatch_channel=MagicMock(
                return_value={
                    "topic": "system/autonomy/alert",
                    "payload": {"message": "attention"},
                    "delivery": {"delivery_count": 1},
                }
            ),
            channel_delivery_history=MagicMock(
                return_value={
                    "history": [
                        {"topic": "system/autonomy/alert", "delivery_count": 1, "delivered_count": 1, "error_count": 0}
                    ]
                }
            ),
        )
        with patch.object(run, "_build_provider", return_value=fake_provider):
            set_output = io.StringIO()
            with redirect_stdout(set_output):
                set_exit = run.main([
                    "channels",
                    "--set-subscription-json",
                    '{"id":"ops-webhook","channel":"webhook","endpoint":"http://example.invalid/webhook","topics":["system/autonomy/alert"]}',
                ])

            status_output = io.StringIO()
            with redirect_stdout(status_output):
                status_exit = run.main(["channels"])

            history_output = io.StringIO()
            with redirect_stdout(history_output):
                history_exit = run.main(["channels", "--history", "--topic", "system/autonomy/alert", "--status", "delivered"])

            dispatch_output = io.StringIO()
            with redirect_stdout(dispatch_output):
                dispatch_exit = run.main(["channels", "--dispatch-topic", "system/autonomy/alert", "--message", "attention"])

            validate_output = io.StringIO()
            with redirect_stdout(validate_output):
                validate_exit = run.main(["channels", "--validate-subscription", "ops-webhook"])

            delete_output = io.StringIO()
            with redirect_stdout(delete_output):
                delete_exit = run.main(["channels", "--delete-subscription", "ops-webhook"])

        self.assertEqual(set_exit, 0)
        fake_provider.upsert_channel_subscription.assert_called_once()
        self.assertIn("Stored subscription: ops-webhook", set_output.getvalue())
        self.assertEqual(status_exit, 0)
        self.assertIn("OpenChimera channels", status_output.getvalue())
        self.assertIn("ops-webhook", status_output.getvalue())
        self.assertEqual(history_exit, 0)
        fake_provider.channel_delivery_history.assert_called_once_with(topic="system/autonomy/alert", status="delivered", limit=20)
        self.assertIn("OpenChimera channel delivery history", history_output.getvalue())
        self.assertEqual(dispatch_exit, 0)
        fake_provider.dispatch_channel.assert_called_once_with("system/autonomy/alert", payload={"message": "attention"})
        self.assertIn("Dispatched topic: system/autonomy/alert", dispatch_output.getvalue())
        self.assertEqual(validate_exit, 0)
        fake_provider.validate_channel_subscription.assert_called_once_with(subscription_id="ops-webhook")
        self.assertIn("Validated subscription: ops-webhook", validate_output.getvalue())
        self.assertEqual(delete_exit, 0)
        fake_provider.delete_channel_subscription.assert_called_once_with("ops-webhook")
        self.assertIn("Deleted subscription: ops-webhook", delete_output.getvalue())
        self.assertIn("validation=delivered", status_output.getvalue())

    def test_channels_command_supports_filesystem_channel_flags(self) -> None:
        fake_provider = SimpleNamespace(
            upsert_channel_subscription=MagicMock(
                return_value={
                    "id": "ops-local-feed",
                    "channel": "filesystem",
                    "topics": ["system/autonomy/alert", "system/briefing/daily"],
                }
            )
        )
        with patch.object(run, "_build_provider", return_value=fake_provider):
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = run.main(
                    [
                        "channels",
                        "--channel",
                        "filesystem",
                        "--file-path",
                        "data/channels/operator-feed.jsonl",
                        "--subscription-id",
                        "ops-local-feed",
                        "--topics-csv",
                        "system/autonomy/alert,system/briefing/daily",
                    ]
                )

        self.assertEqual(exit_code, 0)
        fake_provider.upsert_channel_subscription.assert_called_once_with(
            {
                "id": "ops-local-feed",
                "channel": "filesystem",
                "enabled": True,
                "file_path": "data/channels/operator-feed.jsonl",
                "topics": ["system/autonomy/alert", "system/briefing/daily"],
            }
        )
        self.assertIn("Stored subscription: ops-local-feed", output.getvalue())

    def test_channels_command_supports_guided_channel_setup_flags(self) -> None:
        fake_provider = SimpleNamespace(
            upsert_channel_subscription=MagicMock(
                return_value={
                    "id": "ops-webhook",
                    "channel": "webhook",
                    "topics": ["system/autonomy/alert", "system/briefing/daily"],
                }
            )
        )
        with patch.object(run, "_build_provider", return_value=fake_provider):
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = run.main(
                    [
                        "channels",
                        "--channel",
                        "webhook",
                        "--endpoint",
                        "http://example.invalid/webhook",
                        "--subscription-id",
                        "ops-webhook",
                        "--topics-csv",
                        "system/autonomy/alert,system/briefing/daily",
                    ]
                )

        self.assertEqual(exit_code, 0)
        fake_provider.upsert_channel_subscription.assert_called_once_with(
            {
                "id": "ops-webhook",
                "channel": "webhook",
                "enabled": True,
                "endpoint": "http://example.invalid/webhook",
                "topics": ["system/autonomy/alert", "system/briefing/daily"],
            }
        )
        self.assertIn("Stored subscription: ops-webhook", output.getvalue())

    def test_autonomy_command_reports_diagnostics(self) -> None:
        fake_provider = SimpleNamespace(
            autonomy_diagnostics=MagicMock(
                return_value={
                    "scheduler": {
                        "jobs": {
                            "run_self_audit": {"enabled": True, "last_status": "never"},
                        }
                    },
                    "job_queue": {"counts": {"total": 2, "queued": 1, "running": 0, "completed": 1, "failed": 0, "cancelled": 0}},
                    "artifacts": {
                        "self_audit": {
                            "status": "warning",
                            "findings": [
                                {"id": "generation-path-offline", "summary": "No healthy local generation path is currently online."}
                            ],
                        },
                        "degradation_chains": {
                            "chains": [{"id": "generation-path-offline"}],
                        },
                    },
                }
            )
        )
        with patch.object(run, "_build_provider", return_value=fake_provider):
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = run.main(["autonomy"])

        self.assertEqual(exit_code, 0)
        rendered = output.getvalue()
        self.assertIn("OpenChimera autonomy diagnostics", rendered)
        self.assertIn("Jobs needing attention: run_self_audit", rendered)
        self.assertIn("generation-path-offline", rendered)

    def test_autonomy_command_can_queue_preview_repair(self) -> None:
        fake_provider = SimpleNamespace(
            preview_self_repair=MagicMock(return_value={"status": "queued", "job_id": "job-1"})
        )
        with patch.object(run, "_build_provider", return_value=fake_provider):
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = run.main(["autonomy", "--preview-repair", "--target-project", "D:/OpenChimera", "--enqueue", "--max-attempts", "2"])

        self.assertEqual(exit_code, 0)
        fake_provider.preview_self_repair.assert_called_once_with(
            target_project="D:/OpenChimera",
            enqueue=True,
            max_attempts=2,
        )
        self.assertIn("Queued job: job-1", output.getvalue())

    def test_autonomy_command_reports_artifact_history(self) -> None:
        fake_provider = SimpleNamespace(
            autonomy_artifact_history=MagicMock(
                return_value={
                    "history": [
                        {"artifact_name": "self_audit", "summary": "3 self-audit findings", "status": "warning"},
                    ]
                }
            )
        )
        with patch.object(run, "_build_provider", return_value=fake_provider):
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = run.main(["autonomy", "--history", "--artifact", "self_audit", "--limit", "5"])

        self.assertEqual(exit_code, 0)
        fake_provider.autonomy_artifact_history.assert_called_once_with(artifact_name="self_audit", limit=5)
        self.assertIn("self_audit: 3 self-audit findings [warning]", output.getvalue())

    def test_autonomy_command_can_read_and_dispatch_operator_digest(self) -> None:
        fake_provider = SimpleNamespace(
            operator_digest=MagicMock(
                return_value={
                    "artifact_name": "operator_digest",
                    "summary": {"recent_alert_count": 1, "failed_job_count": 1, "failed_channel_delivery_count": 0},
                }
            ),
            dispatch_operator_digest=MagicMock(
                return_value={
                    "status": "ok",
                    "dispatch_topic": "system/briefing/daily",
                    "target": "D:/OpenChimera/data/autonomy/operator_digest.json",
                }
            ),
        )
        with patch.object(run, "_build_provider", return_value=fake_provider):
            digest_output = io.StringIO()
            with redirect_stdout(digest_output):
                digest_exit = run.main(["autonomy", "--operator-digest"])

            dispatch_output = io.StringIO()
            with redirect_stdout(dispatch_output):
                dispatch_exit = run.main(["autonomy", "--dispatch-digest", "--history-limit", "3", "--dispatch-topic", "system/briefing/daily"])

        self.assertEqual(digest_exit, 0)
        fake_provider.operator_digest.assert_called_once_with()
        self.assertIn("OpenChimera operator digest", digest_output.getvalue())
        self.assertEqual(dispatch_exit, 0)
        fake_provider.dispatch_operator_digest.assert_called_once_with(
            enqueue=False,
            max_attempts=3,
            history_limit=3,
            dispatch_topic="system/briefing/daily",
        )
        self.assertIn("Dispatch topic: system/briefing/daily", dispatch_output.getvalue())

    def test_jobs_command_can_show_one_job(self) -> None:
        fake_provider = SimpleNamespace(
            get_operator_job=MagicMock(return_value={"job_id": "job-1", "job_class": "autonomy.preview_repair", "status": "completed"})
        )
        with patch.object(run, "_build_provider", return_value=fake_provider):
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = run.main(["jobs", "--id", "job-1"])

        self.assertEqual(exit_code, 0)
        fake_provider.get_operator_job.assert_called_once_with("job-1")
        self.assertIn('"job_class": "autonomy.preview_repair"', output.getvalue())

    def test_jobs_command_reports_queue_state(self) -> None:
        fake_provider = SimpleNamespace(
            job_queue_status=MagicMock(
                return_value={
                    "counts": {"total": 2, "queued": 1, "running": 0, "completed": 1, "failed": 0, "cancelled": 0},
                    "jobs": [
                        {"job_id": "job-1", "job_type": "autonomy.preview_repair", "job_class": "autonomy.preview_repair", "status": "queued"},
                    ],
                }
            )
        )
        with patch.object(run, "_build_provider", return_value=fake_provider):
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = run.main(["jobs"])

        self.assertEqual(exit_code, 0)
        rendered = output.getvalue()
        self.assertIn("OpenChimera job queue", rendered)
        self.assertIn("job-1: autonomy.preview_repair class=autonomy.preview_repair status=queued", rendered)

    def test_jobs_command_can_cancel_job(self) -> None:
        fake_provider = SimpleNamespace(
            cancel_operator_job=MagicMock(return_value={"status": "cancelled", "job_id": "job-1"})
        )
        with patch.object(run, "_build_provider", return_value=fake_provider):
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = run.main(["jobs", "--cancel", "job-1"])

        self.assertEqual(exit_code, 0)
        fake_provider.cancel_operator_job.assert_called_once_with("job-1")
        self.assertIn('"status": "cancelled"', output.getvalue())

    def test_onboard_command_reports_blockers(self) -> None:
        fake_provider = SimpleNamespace(
            onboarding_status=MagicMock(
                return_value={
                    "completed": False,
                    "blockers": ["Configure a provider credential."],
                    "next_actions": ["Run openchimera doctor."],
                }
            )
        )
        with patch.object(run, "_build_provider", return_value=fake_provider):
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = run.main(["onboard"])

        self.assertEqual(exit_code, 0)
        rendered = output.getvalue()
        self.assertIn("Configure a provider credential.", rendered)
        self.assertIn("Run openchimera doctor.", rendered)

    def test_onboard_command_can_register_local_model_asset(self) -> None:
        fake_provider = SimpleNamespace(
            apply_onboarding=MagicMock(
                return_value={
                    "completed": False,
                    "blockers": ["No push channel configured for operator notifications."],
                    "next_actions": ["Configure a webhook, Slack, Discord, or Telegram channel for operator notifications."],
                }
            )
        )
        with patch.object(run, "_build_provider", return_value=fake_provider):
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = run.main([
                    "onboard",
                    "--register-local-model-path",
                    "D:/models/qwen2.5-7b-instruct-q4_k_m.gguf",
                    "--register-local-model-id",
                    "qwen2.5-7b",
                ])

        self.assertEqual(exit_code, 0)
        fake_provider.apply_onboarding.assert_called_once_with(
            {
                "local_model_asset_path": "D:/models/qwen2.5-7b-instruct-q4_k_m.gguf",
                "local_model_asset_id": "qwen2.5-7b",
            }
        )
        self.assertIn("Registered local model asset: D:/models/qwen2.5-7b-instruct-q4_k_m.gguf", output.getvalue())

    def test_query_and_plugins_commands_use_new_operator_surfaces(self) -> None:
        fake_provider = SimpleNamespace(
            run_query=MagicMock(
                return_value={
                    "session_id": "qs-1",
                    "query_type": "general",
                    "response": {"choices": [{"message": {"content": "ok"}}]},
                }
            ),
            plugin_status=MagicMock(return_value={"plugins": [{"id": "openchimera-core", "installed": False}]}),
            mcp_status=MagicMock(return_value={"counts": {"total": 1}, "servers": [{"id": "context_hub", "status": "healthy"}]}),
        )
        with patch.object(run, "_build_provider", return_value=fake_provider):
            query_output = io.StringIO()
            with redirect_stdout(query_output):
                query_exit = run.main(["query", "--text", "hello"])

            plugins_output = io.StringIO()
            with redirect_stdout(plugins_output):
                plugins_exit = run.main(["plugins"])

            mcp_output = io.StringIO()
            with redirect_stdout(mcp_output):
                mcp_exit = run.main(["mcp"])

        self.assertEqual(query_exit, 0)
        self.assertIn("Session: qs-1", query_output.getvalue())
        self.assertEqual(plugins_exit, 0)
        self.assertIn("openchimera-core", plugins_output.getvalue())
        self.assertEqual(mcp_exit, 0)
        self.assertIn("context_hub", mcp_output.getvalue())

    def test_mcp_command_can_manage_registry_and_descriptors(self) -> None:
        with patch.object(
            run,
            "upsert_mcp_registry_entry",
            return_value={"id": "context_gateway_remote", "transport": "http", "status": "registered", "url": "http://localhost:9100/mcp"},
        ) as upsert_mock, patch.object(
            run,
            "delete_mcp_registry_entry",
            return_value={"id": "context_gateway_remote", "deleted": True},
        ) as delete_mock, patch.object(
            run,
            "list_mcp_registry_with_health",
            return_value=[{"id": "context_gateway_remote", "transport": "http", "status": "registered"}],
        ):
            register_output = io.StringIO()
            with redirect_stdout(register_output):
                register_exit = run.main(["mcp", "--register", "context_gateway_remote", "--transport", "http", "--url", "http://localhost:9100/mcp"])

            registry_output = io.StringIO()
            with redirect_stdout(registry_output):
                registry_exit = run.main(["mcp", "--registry"])

            remove_output = io.StringIO()
            with redirect_stdout(remove_output):
                remove_exit = run.main(["mcp", "--unregister", "context_gateway_remote"])

        self.assertEqual(register_exit, 0)
        upsert_mock.assert_called_once()
        self.assertIn("Registered MCP connector: context_gateway_remote", register_output.getvalue())
        self.assertEqual(registry_exit, 0)
        self.assertIn("context_gateway_remote", registry_output.getvalue())
        self.assertEqual(remove_exit, 0)
        delete_mock.assert_called_once_with("context_gateway_remote")

    def test_mcp_command_can_probe_registry_entries(self) -> None:
        with patch.object(
            run,
            "probe_all_mcp_registry_entries",
            return_value={"counts": {"total": 1}, "servers": [{"id": "context_gateway_remote", "status": "healthy"}]},
        ) as probe_all_mock, patch.object(
            run,
            "probe_mcp_registry_entry",
            return_value={"id": "context_gateway_remote", "status": "healthy"},
        ) as probe_one_mock:
            all_output = io.StringIO()
            with redirect_stdout(all_output):
                all_exit = run.main(["mcp", "--probe"])

            one_output = io.StringIO()
            with redirect_stdout(one_output):
                one_exit = run.main(["mcp", "--probe", "--id", "context_gateway_remote"])

        self.assertEqual(all_exit, 0)
        probe_all_mock.assert_called_once()
        self.assertIn("Probed MCP connectors: 1", all_output.getvalue())
        self.assertEqual(one_exit, 0)
        probe_one_mock.assert_called_once_with("context_gateway_remote", timeout_seconds=3.0)
        self.assertIn("Probed MCP connector: context_gateway_remote", one_output.getvalue())

    def test_mcp_command_can_render_resources_and_prompts(self) -> None:
        fake_server = MagicMock()
        fake_server.resource_descriptors.return_value = [
            {"uri": "openchimera://status/mcp", "description": "Discovered MCP servers and current health summary."}
        ]
        fake_server.prompt_descriptors.return_value = [
            {"name": "openchimera.system_overview", "description": "Generate a concise operator prompt for reviewing the current runtime."}
        ]
        with patch("core.mcp_server.OpenChimeraMCPServer", return_value=fake_server):
            resources_output = io.StringIO()
            with redirect_stdout(resources_output):
                resources_exit = run.main(["mcp", "--resources"])

            prompts_output = io.StringIO()
            with redirect_stdout(prompts_output):
                prompts_exit = run.main(["mcp", "--prompts"])

        self.assertEqual(resources_exit, 0)
        self.assertIn("openchimera://status/mcp", resources_output.getvalue())
        self.assertEqual(prompts_exit, 0)
        self.assertIn("openchimera.system_overview", prompts_output.getvalue())

    def test_mcp_registry_subprocess_does_not_fall_through_to_serve(self) -> None:
        env = os.environ.copy()
        env.setdefault("PYTHONIOENCODING", "utf-8")
        result = subprocess.run(
            [sys.executable, "run.py", "mcp", "--registry"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=20,
            env=env,
        )

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("Registered MCP connectors:", result.stdout)
        self.assertNotIn("Starting OpenChimera", result.stdout)
        self.assertNotIn("Booting OpenChimera", result.stdout)


if __name__ == "__main__":
    unittest.main()