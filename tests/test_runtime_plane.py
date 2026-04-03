from __future__ import annotations

import unittest
from unittest.mock import MagicMock
from unittest.mock import patch

from core.runtime_plane import RuntimePlane


class RuntimePlaneTests(unittest.TestCase):
    def test_status_includes_deployment_summary(self) -> None:
        plane = RuntimePlane(
            base_url_getter=lambda: "http://127.0.0.1:7870",
            profile_getter=lambda: {"local_runtime": {"context_length": 4096}},
            llm_manager=MagicMock(get_status=MagicMock(return_value={"models": {}, "healthy_count": 0, "total_count": 0}), get_runtime_status=MagicMock(return_value={})),
            rag=MagicMock(get_status=MagicMock(return_value={})),
            router=MagicMock(status=MagicMock(return_value={})),
            harness_port=MagicMock(status=MagicMock(return_value={})),
            minimind=MagicMock(status=MagicMock(return_value={})),
            autonomy=MagicMock(status=MagicMock(return_value={})),
            observability=MagicMock(snapshot=MagicMock(return_value={})),
            health_getter=lambda: {"status": "online"},
            autonomy_diagnostics_getter=lambda: {},
            aegis_status_getter=lambda: {},
            ascension_status_getter=lambda: {},
            model_registry_status_getter=lambda: {},
            browser_status_getter=lambda: {},
            media_status_getter=lambda: {},
            query_status_getter=lambda: {},
            model_role_status_getter=lambda: {},
            plugin_status_getter=lambda: {},
            subsystem_status_getter=lambda: {},
            onboarding_status_getter=lambda: {},
            integration_status_getter=lambda: {},
        )

        with patch(
            "core.runtime_plane.build_deployment_status",
            return_value={"mode": "local", "containerized": False, "transport": {"tls_enabled": False}},
        ):
            payload = plane.status()

        self.assertEqual(payload["deployment"]["mode"], "local")
        self.assertFalse(payload["deployment"]["containerized"])


if __name__ == "__main__":
    unittest.main()