from __future__ import annotations

import unittest
from unittest.mock import MagicMock
from unittest.mock import patch

from core.control_plane import OperatorControlPlane


class _StatusService:
    def __init__(self, payload: dict[str, object]):
        self._payload = payload

    def status(self) -> dict[str, object]:
        return dict(self._payload)


class _Onboarding:
    def __init__(self, payload: dict[str, object]):
        self._payload = payload

    def status(self) -> dict[str, object]:
        return dict(self._payload)


class OperatorControlPlaneTests(unittest.TestCase):
    def _build_control_plane(self) -> OperatorControlPlane:
        llm_manager = MagicMock()
        llm_manager.get_status.return_value = {
            "healthy_count": 1,
            "total_count": 2,
            "runtime": {"models": {"phi": {"model_path_exists": True}}},
        }
        rag = MagicMock()
        rag.get_status.return_value = {"documents": 49}
        router = _StatusService({"healthy_models": 1, "known_models": 2})
        harness_port = MagicMock()
        harness_port.available = True
        minimind = _StatusService({"available": True, "running": False})
        minimind.available = True
        autonomy = _StatusService({"running": True, "jobs": {}})
        model_registry = MagicMock()
        model_registry.status.return_value = {
            "providers": [{"id": "openai"}],
            "discovery": {"learned_rankings_available": True},
            "recommendations": {
                "learned_free_rankings": [
                    {"id": "openrouter/top", "query_type": "general", "rank": 1, "score": 9.0, "confidence": 0.9, "degraded": False},
                    {"id": "openrouter/weak", "query_type": "general", "rank": 2, "score": 1.0, "confidence": 0.5, "degraded": True},
                ]
            },
        }
        model_roles = _StatusService({"roles": {"main_loop_model": {"model": "phi"}}})
        onboarding = _Onboarding({"completed": False, "blockers": ["Configure cloud provider"], "suggested_cloud_models": [], "suggested_local_models": [{"id": "phi"}]})
        bus = MagicMock()
        bus.recent_events.return_value = [{"topic": "system/test"}]
        aegis = _StatusService({"available": True})
        ascension = _StatusService({"available": True})

        return OperatorControlPlane(
            base_url_getter=lambda: "http://127.0.0.1:8000",
            profile_getter=lambda: {"providers": {"preferred_cloud_provider": "openai", "prefer_free_models": True}, "autonomy": {"alerts": {"dispatch_topic": "system/autonomy/alert"}}},
            llm_manager=llm_manager,
            rag=rag,
            router=router,
            harness_port=harness_port,
            minimind=minimind,
            autonomy=autonomy,
            model_registry=model_registry,
            model_roles=model_roles,
            onboarding=onboarding,
            integration_status_builder=lambda: {"remediation": ["Fix bridge"], "lineage_only": ["legacy-concept"]},
            subsystem_status_builder=lambda: {"counts": {"total": 1}, "subsystems": [{"id": "aegis"}]},
            channel_status_builder=lambda: {"counts": {"total": 1, "errors": 1}},
            channel_history_builder=lambda topic=None, status=None, limit=20: {"history": [{"topic": topic or "system/autonomy/alert"}] if status != "error" else [{"topic": "system/autonomy/alert", "results": [{"status": "error"}]}]},
            bus=bus,
            aegis=aegis,
            ascension=ascension,
        )

    def test_readiness_reports_ready_when_generation_path_exists(self) -> None:
        control_plane = self._build_control_plane()

        payload = control_plane.readiness_status(system_status={"provider_online": True}, auth_required=True)

        self.assertTrue(payload["ready"])
        self.assertTrue(payload["checks"]["generation_path"])
        self.assertTrue(payload["auth_required"])

    def test_status_snapshot_surfaces_blockers_and_delivery_failures(self) -> None:
        control_plane = self._build_control_plane()

        with patch(
            "core.control_plane.build_deployment_status",
            return_value={
                "mode": "docker",
                "containerized": True,
                "transport": {"tls_enabled": True},
                "logging": {"structured_enabled": True},
            },
        ):
            snapshot = control_plane.status_snapshot(system_status={"provider_online": True}, job_queue_status={"counts": {"total": 1}, "jobs": [{"job_id": "job-1"}]})

        self.assertIn("Configure cloud provider", snapshot["issues"])
        self.assertIn("Fix bridge", snapshot["issues"])
        self.assertEqual(snapshot["jobs"]["counts"]["total"], 1)
        self.assertEqual(snapshot["channels"]["status"]["counts"]["errors"], 1)
        self.assertEqual(snapshot["deployment"]["mode"], "docker")
        self.assertTrue(snapshot["deployment"]["transport"]["tls_enabled"])

    def test_health_degrades_without_any_generation_path(self) -> None:
        control_plane = self._build_control_plane()
        control_plane.llm_manager.get_status.return_value = {
            "healthy_count": 0,
            "total_count": 0,
            "runtime": {"models": {}},
        }
        control_plane.minimind.available = False

        payload = control_plane.health()

        self.assertEqual(payload["status"], "degraded")
        self.assertFalse(payload["components"]["local_llm"])
        self.assertFalse(payload["components"]["minimind"])


if __name__ == "__main__":
    unittest.main()