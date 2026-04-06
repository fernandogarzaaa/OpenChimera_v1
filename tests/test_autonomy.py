from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.autonomy import AutonomyScheduler
from core.bus import EventBus


class _FakeMiniMind:
    def build_training_dataset(self, harness_port, identity_snapshot, force=True):
        return {"files": {"dataset": "ok"}, "counts": {"records": 1}}


class AutonomySchedulerTests(unittest.TestCase):
    def test_status_includes_discovery_job_and_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            profile = {
                "autonomy": {
                    "enabled": True,
                    "auto_start": False,
                    "jobs": {
                        "discover_free_models": {"enabled": True, "interval_seconds": 1234},
                    },
                },
                "model_inventory": {},
            }
            with patch("core.autonomy.ROOT", temp_root), patch("core.autonomy.load_runtime_profile", return_value=profile), patch("core.autonomy.get_legacy_workspace_root", return_value=temp_root / "legacy"):
                scheduler = AutonomyScheduler(EventBus(), harness_port=object(), minimind=_FakeMiniMind(), identity_snapshot={})

            status = scheduler.status()
            self.assertIn("discover_free_models", status["jobs"])
            self.assertEqual(status["jobs"]["discover_free_models"]["interval_seconds"], 1234)
            self.assertIn("discovered_models", status["artifacts"])
            self.assertIn("self_audit", status["artifacts"])
            self.assertIn("preview_self_repair", status["artifacts"])
            self.assertIn("operator_digest", status["artifacts"])
            self.assertIn("job_state", status["artifacts"])

    def test_job_state_persists_across_scheduler_rebuilds(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            profile = {"autonomy": {"enabled": True, "auto_start": False, "jobs": {}}, "model_inventory": {}}
            with patch("core.autonomy.ROOT", temp_root), patch("core.autonomy.load_runtime_profile", return_value=profile), patch("core.autonomy.get_legacy_workspace_root", return_value=temp_root / "legacy"):
                scheduler = AutonomyScheduler(EventBus(), harness_port=object(), minimind=_FakeMiniMind(), identity_snapshot={})
                scheduler.run_job("discover_free_models")

                rebuilt = AutonomyScheduler(EventBus(), harness_port=object(), minimind=_FakeMiniMind(), identity_snapshot={})

            self.assertEqual(rebuilt.status()["jobs"]["discover_free_models"]["last_status"], "ok")
            self.assertGreater(rebuilt.status()["jobs"]["discover_free_models"]["last_run_at"], 0)

    def test_discover_free_models_persists_normalized_results(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            profile = {
                "autonomy": {"enabled": True, "auto_start": False, "jobs": {}},
                "model_inventory": {
                    "discovery_sources": [
                        {"name": "openrouter-free", "provider": "openrouter", "url": "https://openrouter.ai/api/v1/models", "kind": "remote-openrouter", "enabled": True},
                        {"name": "ollama-local", "provider": "ollama", "url": "http://127.0.0.1:11434/api/tags", "kind": "local-ollama", "enabled": True},
                    ]
                },
            }

            class _Response:
                def __init__(self, body: str):
                    self._body = body.encode("utf-8")

                def read(self):
                    return self._body

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

            def fake_urlopen(req, timeout=0):
                url = req.full_url if hasattr(req, "full_url") else str(req)
                if "openrouter" in url:
                    return _Response(json.dumps({"data": [{"id": "openrouter/qwen-free", "name": "Qwen Free", "pricing": {"prompt": "0", "completion": "0"}, "context_length": 131072}, {"id": "openrouter/paid", "pricing": {"prompt": "1", "completion": "1"}}]}))
                return _Response(json.dumps({"models": [{"name": "llama3.2:latest"}]}))

            with patch("core.autonomy.ROOT", temp_root), patch("core.autonomy.load_runtime_profile", return_value=profile), patch("core.autonomy.get_legacy_workspace_root", return_value=temp_root / "legacy"), patch("core.autonomy.request.urlopen", side_effect=fake_urlopen):
                scheduler = AutonomyScheduler(EventBus(), harness_port=object(), minimind=_FakeMiniMind(), identity_snapshot={})
                result = scheduler.run_job("discover_free_models")

            self.assertEqual(result["status"], "ok")
            discovered_path = temp_root / "data" / "autonomy" / "discovered_models.json"
            payload = json.loads(discovered_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["model_count"], 2)
            self.assertTrue(any(item["id"] == "openrouter/qwen-free" for item in payload["models"]))
            self.assertTrue(any(item["id"] == "llama3.2:latest" for item in payload["models"]))

    def test_sync_scouted_models_merges_legacy_and_discovered_catalogs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            legacy_root = temp_root / "legacy"
            legacy_root.mkdir(parents=True)
            (legacy_root / "chimera_free_fallbacks.json").write_text(
                json.dumps([{"id": "openrouter/qwen-free", "provider": "openrouter"}, {"id": "legacy/model-a", "provider": "scouted"}]),
                encoding="utf-8",
            )
            autonomy_root = temp_root / "data" / "autonomy"
            autonomy_root.mkdir(parents=True)
            (autonomy_root / "discovered_models.json").write_text(
                json.dumps({"models": [{"id": "openrouter/qwen-free", "provider": "openrouter", "source": "autonomy-discovery"}, {"id": "ollama/llama3.2", "provider": "ollama", "source": "autonomy-discovery"}]}),
                encoding="utf-8",
            )

            profile = {"autonomy": {"enabled": True, "auto_start": False, "jobs": {}}, "model_inventory": {}}
            with patch("core.autonomy.ROOT", temp_root), patch("core.autonomy.load_runtime_profile", return_value=profile), patch("core.autonomy.get_legacy_workspace_root", return_value=legacy_root):
                scheduler = AutonomyScheduler(EventBus(), harness_port=object(), minimind=_FakeMiniMind(), identity_snapshot={})
                result = scheduler.run_job("sync_scouted_models")

            self.assertEqual(result["status"], "ok")
            scouted_path = autonomy_root / "scouted_models_registry.json"
            payload = json.loads(scouted_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["legacy_model_count"], 2)
            self.assertEqual(payload["discovered_model_count"], 2)
            self.assertEqual(payload["model_count"], 3)
            self.assertTrue(any(item["id"] == "ollama/llama3.2" for item in payload["models"]))

    def test_learn_fallback_rankings_summarizes_route_memory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            route_memory_path = temp_root / "data" / "local_llm_route_memory.json"
            route_memory_path.parent.mkdir(parents=True)
            route_memory_path.write_text(
                json.dumps(
                    {
                        "openrouter/qwen-free": {
                            "general": {
                                "successes": 4,
                                "failures": 1,
                                "low_quality_failures": 0,
                                "avg_latency_ms": 800,
                                "last_success_at": 1700000100,
                                "last_failure_at": 1700000000,
                            }
                        },
                        "openrouter/weak-free": {
                            "general": {
                                "successes": 0,
                                "failures": 3,
                                "low_quality_failures": 2,
                                "avg_latency_ms": 4800,
                                "last_success_at": 0,
                                "last_failure_at": 1700000200,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            profile = {"autonomy": {"enabled": True, "auto_start": False, "jobs": {}}, "model_inventory": {}}
            with patch("core.autonomy.ROOT", temp_root), patch("core.autonomy.load_runtime_profile", return_value=profile), patch("core.autonomy.get_legacy_workspace_root", return_value=temp_root / "legacy"), patch("core.autonomy.time.time", return_value=1700000300):
                scheduler = AutonomyScheduler(EventBus(), harness_port=object(), minimind=_FakeMiniMind(), identity_snapshot={})
                result = scheduler.run_job("learn_fallback_rankings")

            self.assertEqual(result["status"], "ok")
            learned_path = temp_root / "data" / "autonomy" / "learned_fallback_rankings.json"
            payload = json.loads(learned_path.read_text(encoding="utf-8"))
            self.assertIn("general", payload["query_types"])
            self.assertEqual(payload["query_types"]["general"][0]["model"], "openrouter/qwen-free")
            self.assertEqual(payload["query_types"]["general"][0]["rank"], 1)
            self.assertTrue(any(item["model"] == "openrouter/weak-free" for item in payload["degraded_models"]))

    def test_run_self_audit_persists_runtime_findings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            profile = {"autonomy": {"enabled": True, "auto_start": False, "jobs": {}}, "model_inventory": {}}
            with patch("core.autonomy.ROOT", temp_root), patch("core.autonomy.load_runtime_profile", return_value=profile), patch("core.autonomy.get_legacy_workspace_root", return_value=temp_root / "legacy"):
                scheduler = AutonomyScheduler(EventBus(), harness_port=object(), minimind=_FakeMiniMind(), identity_snapshot={})
                scheduler.bind_runtime_context(
                    health=lambda: {"healthy_models": 0, "components": {"minimind": False}},
                    provider_activation=lambda: {"prefer_free_models": True, "fallback_learning": {"degraded_models": ["openrouter/weak-free"], "learned_rankings_available": True}},
                    onboarding=lambda: {"blockers": []},
                    integrations=lambda: {"remediation": ["project_seraph bridge remains evidence-only"]},
                    subsystems=lambda: {"subsystems": [{"id": "aegis_swarm", "health": "offline"}]},
                    job_queue=lambda: {"counts": {"failed": 1}},
                )
                result = scheduler.run_job("run_self_audit")

            self.assertEqual(result["status"], "warning")
            audit_path = temp_root / "data" / "autonomy" / "self_audit.json"
            payload = json.loads(audit_path.read_text(encoding="utf-8"))
            self.assertTrue(any(item["id"] == "generation-path-offline" for item in payload["findings"]))
            self.assertTrue(any("Restore at least one healthy local or cloud generation path." == item for item in payload["recommendations"]))

    def test_degradation_report_ignores_lineage_only_missing_subsystems(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            profile = {"autonomy": {"enabled": True, "auto_start": False, "jobs": {}}, "model_inventory": {}}
            with patch("core.autonomy.ROOT", temp_root), patch("core.autonomy.load_runtime_profile", return_value=profile), patch("core.autonomy.get_legacy_workspace_root", return_value=temp_root / "legacy"):
                scheduler = AutonomyScheduler(EventBus(), harness_port=object(), minimind=_FakeMiniMind(), identity_snapshot={})
                scheduler.bind_runtime_context(
                    health=lambda: {"healthy_models": 1, "components": {"minimind": True}},
                    provider_activation=lambda: {"prefer_free_models": False, "fallback_learning": {}},
                    onboarding=lambda: {"blockers": []},
                    integrations=lambda: {"remediation": [], "lineage_only": ["tri_core_architecture"]},
                    subsystems=lambda: {
                        "subsystems": [
                            {"id": "tri_core_architecture", "health": "missing", "integrated_runtime": False},
                            {"id": "context_hub", "health": "running", "integrated_runtime": True},
                        ]
                    },
                    job_queue=lambda: {"counts": {"failed": 0}},
                )

                result = scheduler.run_job("check_degradation_chains")

            self.assertEqual(result["status"], "degraded")
            degradation_path = temp_root / "data" / "autonomy" / "degradation_chains.json"
            payload = json.loads(degradation_path.read_text(encoding="utf-8"))
            self.assertFalse(any(item["id"] == "subsystem-health-drift" for item in payload["chains"]))

    def test_preview_self_repair_uses_bound_aegis_preview(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            profile = {"autonomy": {"enabled": True, "auto_start": False, "jobs": {}}, "model_inventory": {}}
            seen: list[dict[str, object]] = []
            with patch("core.autonomy.ROOT", temp_root), patch("core.autonomy.load_runtime_profile", return_value=profile), patch("core.autonomy.get_legacy_workspace_root", return_value=temp_root / "legacy"):
                scheduler = AutonomyScheduler(EventBus(), harness_port=object(), minimind=_FakeMiniMind(), identity_snapshot={})
                scheduler.bind_runtime_context(
                    health=lambda: {"healthy_models": 1, "components": {"minimind": True}},
                    provider_activation=lambda: {"prefer_free_models": False, "fallback_learning": {"degraded_models": []}},
                    integrations=lambda: {"remediation": []},
                    subsystems=lambda: {"subsystems": []},
                    job_queue=lambda: {"counts": {"failed": 0}},
                    aegis_preview=lambda target_project=None, preview_context=None: seen.append({"target_project": target_project, "preview_context": preview_context or {}}) or {"status": "preview", "target": target_project},
                )
                result = scheduler.run_job("preview_self_repair", {"target_project": str(temp_root)})

            self.assertEqual(result["status"], "repair")
            self.assertEqual(seen[0]["target_project"], str(temp_root))
            self.assertIn("focus_areas", seen[0]["preview_context"])

    def test_artifact_history_records_written_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            profile = {"autonomy": {"enabled": True, "auto_start": False, "jobs": {}}, "model_inventory": {}}
            with patch("core.autonomy.ROOT", temp_root), patch("core.autonomy.load_runtime_profile", return_value=profile), patch("core.autonomy.get_legacy_workspace_root", return_value=temp_root / "legacy"):
                scheduler = AutonomyScheduler(EventBus(), harness_port=object(), minimind=_FakeMiniMind(), identity_snapshot={})
                scheduler.bind_runtime_context(
                    health=lambda: {"healthy_models": 0, "components": {"minimind": False}},
                    provider_activation=lambda: {"prefer_free_models": False, "fallback_learning": {}},
                    onboarding=lambda: {"blockers": []},
                    integrations=lambda: {"remediation": []},
                    subsystems=lambda: {"subsystems": []},
                    job_queue=lambda: {"counts": {"failed": 0}},
                )
                scheduler.run_job("run_self_audit")

                history = scheduler.artifact_history(artifact_name="self_audit", limit=5)
                artifact = scheduler.read_artifact("self_audit")

            self.assertEqual(history["count"], 1)
            self.assertEqual(history["history"][0]["artifact_name"], "self_audit")
            self.assertEqual(artifact["artifact_name"], "self_audit")

    def test_artifact_history_honors_retention_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            profile = {
                "autonomy": {
                    "enabled": True,
                    "auto_start": False,
                    "artifacts": {"retention": {"max_history_entries": 1, "max_age_days": 30}},
                    "jobs": {},
                },
                "model_inventory": {},
            }
            with patch("core.autonomy.ROOT", temp_root), patch("core.autonomy.load_runtime_profile", return_value=profile), patch("core.autonomy.get_legacy_workspace_root", return_value=temp_root / "legacy"):
                scheduler = AutonomyScheduler(EventBus(), harness_port=object(), minimind=_FakeMiniMind(), identity_snapshot={})
                scheduler.bind_runtime_context(
                    health=lambda: {"healthy_models": 0, "components": {"minimind": False}},
                    provider_activation=lambda: {"prefer_free_models": False, "fallback_learning": {}},
                    onboarding=lambda: {"blockers": []},
                    integrations=lambda: {"remediation": []},
                    subsystems=lambda: {"subsystems": []},
                    job_queue=lambda: {"counts": {"failed": 0}},
                )
                scheduler.run_job("run_self_audit")
                scheduler.run_job("check_degradation_chains")

                history = scheduler.artifact_history(limit=10)

            self.assertEqual(history["count"], 1)

    def test_dispatch_operator_digest_persists_artifact_and_uses_channel_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            profile = {
                "autonomy": {
                    "enabled": True,
                    "auto_start": False,
                    "digests": {"dispatch_topic": "system/briefing/daily", "history_limit": 3},
                    "jobs": {},
                },
                "model_inventory": {},
            }
            seen: list[dict[str, object]] = []
            with patch("core.autonomy.ROOT", temp_root), patch("core.autonomy.load_runtime_profile", return_value=profile), patch("core.autonomy.get_legacy_workspace_root", return_value=temp_root / "legacy"):
                scheduler = AutonomyScheduler(EventBus(), harness_port=object(), minimind=_FakeMiniMind(), identity_snapshot={})
                scheduler.bind_runtime_context(
                    health=lambda: {"healthy_models": 1, "components": {"minimind": True}},
                    provider_activation=lambda: {"prefer_free_models": False, "fallback_learning": {"top_ranked_models": []}},
                    onboarding=lambda: {"blockers": []},
                    integrations=lambda: {"remediation": []},
                    subsystems=lambda: {"subsystems": []},
                    job_queue=lambda status_filter=None, limit=None: {"jobs": [{"job_id": "job-1", "job_type": "autonomy.audit", "job_class": "autonomy.audit", "status": "failed"}] if status_filter == "failed" else [], "counts": {"failed": 1}},
                    daily_briefing=lambda: {"summary": "OpenChimera daily briefing", "priorities": []},
                    channel_history=lambda topic=None, status=None, limit=None: {"history": [{"topic": topic or "system/autonomy/alert", "payload_preview": {"summary": "Alert summary"}, "error_count": 1, "results": [{"status": status or "delivered"}]}], "count": 1},
                    channel_dispatch=lambda topic=None, payload=None: seen.append({"topic": topic, "payload": payload or {}}) or {"topic": topic, "delivery": {"delivery_count": 1}},
                )

                result = scheduler.run_job("dispatch_operator_digest")
                artifact = scheduler.read_artifact("operator_digest")

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["failed_job_count"], 1)
            self.assertEqual(seen[0]["topic"], "system/briefing/daily")
            self.assertIn("recent_alerts", seen[0]["payload"])
            self.assertEqual(artifact["summary"]["failed_job_count"], 1)

    def test_self_audit_surfaces_external_operator_blockers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            profile = {"autonomy": {"enabled": True, "auto_start": False, "jobs": {}}, "model_inventory": {}}
            with patch("core.autonomy.ROOT", temp_root), patch("core.autonomy.load_runtime_profile", return_value=profile), patch("core.autonomy.get_legacy_workspace_root", return_value=temp_root / "legacy"):
                scheduler = AutonomyScheduler(EventBus(), harness_port=object(), minimind=_FakeMiniMind(), identity_snapshot={})
                scheduler.bind_runtime_context(
                    health=lambda: {"healthy_models": 0, "components": {"minimind": True}},
                    provider_activation=lambda: {
                        "prefer_free_models": False,
                        "fallback_learning": {},
                        "discovery": {"local_model_assets_available": False, "local_search_roots": ["fake/models"]},
                    },
                    onboarding=lambda: {"blockers": ["No push channel configured for operator notifications."]},
                    integrations=lambda: {"remediation": []},
                    subsystems=lambda: {"subsystems": []},
                    job_queue=lambda: {"counts": {"failed": 0}},
                )
                result = scheduler.run_job("run_self_audit")
                payload = scheduler.read_artifact("self_audit")

            self.assertEqual(result["status"], "warning")
            self.assertEqual(payload["summary"]["external_blocker_count"], 2)
            finding_ids = [item["id"] for item in payload["findings"]]
            self.assertIn("local-model-assets-missing", finding_ids)
            self.assertIn("operator-channel-missing", finding_ids)


class TestProbeHuggingFaceModels(unittest.TestCase):

    def test_probe_huggingface_models_returns_text_gen_models(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            profile = {"autonomy": {"enabled": True, "auto_start": False, "jobs": {}}, "model_inventory": {}}

            class _Response:
                def __init__(self, body: str):
                    self._body = body.encode("utf-8")

                def read(self):
                    return self._body

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

            hf_models = [
                {"id": "meta-llama/Llama-3.2-3B-Instruct", "pipeline_tag": "text-generation", "inference": "warm", "likes": 500, "downloads": 10000},
                {"id": "bigscience/bloom-560m", "pipeline_tag": "text-generation", "inference": "hot", "likes": 100, "downloads": 5000},
                {"id": "gated/model-x", "pipeline_tag": "text-generation", "inference": "warm", "gated": True, "likes": 50, "downloads": 200},
            ]

            def fake_urlopen(req, timeout=0):
                return _Response(json.dumps(hf_models))

            with patch("core.autonomy.ROOT", temp_root), patch("core.autonomy.load_runtime_profile", return_value=profile), patch("core.autonomy.get_legacy_workspace_root", return_value=temp_root / "legacy"), patch("core.autonomy.request.urlopen", side_effect=fake_urlopen), patch.dict("os.environ", {}, clear=False):
                os.environ.pop("HF_TOKEN", None)
                scheduler = AutonomyScheduler(EventBus(), harness_port=object(), minimind=_FakeMiniMind(), identity_snapshot={})
                results = scheduler._probe_huggingface_models("https://huggingface.co/api/models", "huggingface")

            self.assertEqual(len(results), 2)
            self.assertTrue(all(item["id"].startswith("huggingface/") for item in results))
            self.assertTrue(any(item["id"] == "huggingface/meta-llama/Llama-3.2-3B-Instruct" for item in results))
            self.assertEqual(results[0]["cost"], 0)
            self.assertEqual(results[0]["provider"], "huggingface")

    def test_probe_huggingface_includes_gated_when_token_present(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            profile = {"autonomy": {"enabled": True, "auto_start": False, "jobs": {}}, "model_inventory": {}}

            class _Response:
                def __init__(self, body: str):
                    self._body = body.encode("utf-8")

                def read(self):
                    return self._body

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

            hf_models = [
                {"id": "gated/model-x", "pipeline_tag": "text-generation", "inference": "warm", "gated": True, "likes": 50, "downloads": 200},
            ]

            def fake_urlopen(req, timeout=0):
                return _Response(json.dumps(hf_models))

            with patch("core.autonomy.ROOT", temp_root), patch("core.autonomy.load_runtime_profile", return_value=profile), patch("core.autonomy.get_legacy_workspace_root", return_value=temp_root / "legacy"), patch("core.autonomy.request.urlopen", side_effect=fake_urlopen), patch.dict("os.environ", {"HF_TOKEN": "hf_test123"}):
                scheduler = AutonomyScheduler(EventBus(), harness_port=object(), minimind=_FakeMiniMind(), identity_snapshot={})
                results = scheduler._probe_huggingface_models("https://huggingface.co/api/models", "huggingface")

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["id"], "huggingface/gated/model-x")

    def test_discovery_sources_defaults_include_huggingface(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            profile = {"autonomy": {"enabled": True, "auto_start": False, "jobs": {}}, "model_inventory": {}}
            with patch("core.autonomy.ROOT", temp_root), patch("core.autonomy.load_runtime_profile", return_value=profile), patch("core.autonomy.get_legacy_workspace_root", return_value=temp_root / "legacy"):
                scheduler = AutonomyScheduler(EventBus(), harness_port=object(), minimind=_FakeMiniMind(), identity_snapshot={})
                sources = scheduler._discovery_sources()

            names = [s["name"] for s in sources]
            self.assertIn("huggingface-free", names)
            hf_source = next(s for s in sources if s["name"] == "huggingface-free")
            self.assertEqual(hf_source["kind"], "remote-huggingface")
            self.assertEqual(hf_source["provider"], "huggingface")

    def test_probe_dispatcher_routes_huggingface_kind(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            profile = {"autonomy": {"enabled": True, "auto_start": False, "jobs": {}}, "model_inventory": {}}
            with patch("core.autonomy.ROOT", temp_root), patch("core.autonomy.load_runtime_profile", return_value=profile), patch("core.autonomy.get_legacy_workspace_root", return_value=temp_root / "legacy"):
                scheduler = AutonomyScheduler(EventBus(), harness_port=object(), minimind=_FakeMiniMind(), identity_snapshot={})
                with patch.object(scheduler, "_probe_huggingface_models", return_value=[{"id": "hf/test"}]) as mock_hf:
                    result = scheduler._probe_discovery_source({"kind": "remote-huggingface", "url": "https://huggingface.co/api/models", "provider": "huggingface"})

            mock_hf.assert_called_once()
            self.assertEqual(result, [{"id": "hf/test"}])


class TestRecordLearning(unittest.TestCase):
    """Phase 7 — _record_learning feeds causal and transfer subsystems."""

    def _make_sched(self, tmp_root: Path):
        profile = {"autonomy": {"enabled": True, "auto_start": False, "jobs": {}}, "model_inventory": {}}
        with patch("core.autonomy.ROOT", tmp_root), \
             patch("core.autonomy.load_runtime_profile", return_value=profile), \
             patch("core.autonomy.get_legacy_workspace_root", return_value=tmp_root / "legacy"):
            return AutonomyScheduler(EventBus(), harness_port=object(), minimind=_FakeMiniMind(), identity_snapshot={})

    def test_record_learning_calls_causal_on_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            sched = self._make_sched(Path(tmp))
            from unittest.mock import MagicMock
            sched._causal = MagicMock()
            sched._transfer = MagicMock()
            sched._record_learning("discover_free_models", {"ok": True}, success=True)
            sched._causal.record_observation.assert_called_once()
            sched._transfer.register_pattern.assert_called_once()

    def test_record_learning_skips_transfer_on_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            sched = self._make_sched(Path(tmp))
            from unittest.mock import MagicMock
            sched._causal = MagicMock()
            sched._transfer = MagicMock()
            sched._record_learning("discover_free_models", {"err": "boom"}, success=False)
            sched._causal.record_observation.assert_called_once()
            sched._transfer.register_pattern.assert_not_called()

    def test_record_learning_tolerates_none_subsystems(self):
        with tempfile.TemporaryDirectory() as tmp:
            sched = self._make_sched(Path(tmp))
            sched._causal = None
            sched._transfer = None
            # Should not raise
            sched._record_learning("discover_free_models", {}, success=True)


if __name__ == "__main__":
    unittest.main()