from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import MagicMock, patch, call


from core.kernel import OpenChimeraKernel


def _make_kernel(**identity_overrides):
    """Build a kernel with all external services mocked."""
    fake_provider = MagicMock()
    identity = {"supervision": {"enabled": True, "interval_seconds": 0.01, "restart_cooldown_seconds": 0}, **identity_overrides}

    patches = {
        "core.kernel.build_identity_snapshot": {"return_value": identity},
        "core.kernel.get_watch_files": {"return_value": []},
        "core.kernel.Personality": {},
        "core.kernel.FIMDaemon": {},
        "core.kernel.AetherService": {},
        "core.kernel.WraithService": {},
        "core.kernel.EvoService": {},
        "core.kernel.OpenChimeraProvider": {"return_value": fake_provider},
        "core.kernel.OpenChimeraAPIServer": {},
    }
    active: list = []
    for target, kwargs in patches.items():
        p = patch(target, **kwargs)
        active.append(p.start())
    return active, identity, fake_provider


class KernelStartupTests(unittest.TestCase):
    def test_boot_fails_fast_when_api_server_does_not_start(self) -> None:
        fake_provider = MagicMock()
        fake_provider.start = MagicMock()
        fake_provider.stop = MagicMock()

        with (
            patch("core.kernel.build_identity_snapshot", return_value={"supervision": {}}),
            patch("core.kernel.get_watch_files", return_value=[]),
            patch("core.kernel.Personality"),
            patch("core.kernel.FIMDaemon"),
            patch("core.kernel.AetherService"),
            patch("core.kernel.WraithService"),
            patch("core.kernel.EvoService"),
            patch("core.kernel.OpenChimeraProvider", return_value=fake_provider),
            patch("core.kernel.OpenChimeraAPIServer") as api_server_cls,
        ):
            api_server_cls.return_value.start.return_value = False
            kernel = OpenChimeraKernel()

            with self.assertRaises(RuntimeError):
                kernel.boot(run_forever=False)

        fake_provider.start.assert_called_once()
        fake_provider.stop.assert_called_once()

    def test_boot_succeeds_and_returns_status(self) -> None:
        fake_provider = MagicMock()
        fake_provider.status.return_value = {
            "online": True, "api_online": True,
            "aegis": {}, "ascension": {}, "deployment": {},
            "onboarding": {}, "integrations": {},
        }
        fake_aether = MagicMock()
        fake_aether.start.return_value = True
        fake_aether.status.return_value = {"running": True, "available": True}
        fake_wraith = MagicMock()
        fake_wraith.start.return_value = True
        fake_wraith.status.return_value = {"running": True, "available": True}
        fake_evo = MagicMock()
        fake_evo.start.return_value = True
        fake_evo.status.return_value = {"running": True, "available": True}

        with (
            patch("core.kernel.build_identity_snapshot", return_value={"supervision": {"enabled": False}}),
            patch("core.kernel.get_watch_files", return_value=[]),
            patch("core.kernel.Personality"),
            patch("core.kernel.FIMDaemon"),
            patch("core.kernel.AetherService", return_value=fake_aether),
            patch("core.kernel.WraithService", return_value=fake_wraith),
            patch("core.kernel.EvoService", return_value=fake_evo),
            patch("core.kernel.OpenChimeraProvider", return_value=fake_provider),
            patch("core.kernel.OpenChimeraAPIServer") as api_server_cls,
        ):
            api_server_cls.return_value.start.return_value = True
            kernel = OpenChimeraKernel()
            status = kernel.boot(run_forever=False)

        self.assertIn("aether", status)
        self.assertIn("provider_online", status)
        self.assertTrue(status["provider_online"])

    def test_boot_starts_local_runtime_when_aether_unavailable(self) -> None:
        fake_provider = MagicMock()
        fake_provider.status.return_value = {
            "online": True, "api_online": True,
            "aegis": {}, "ascension": {}, "deployment": {},
            "onboarding": {}, "integrations": {},
        }
        fake_aether = MagicMock()
        fake_aether.start.return_value = False  # aether unavailable
        fake_aether.status.return_value = {"running": False}

        published = []

        def fake_publish_nowait(topic, payload):
            published.append(topic)

        with (
            patch("core.kernel.build_identity_snapshot", return_value={"supervision": {"enabled": False}}),
            patch("core.kernel.get_watch_files", return_value=[]),
            patch("core.kernel.Personality"),
            patch("core.kernel.FIMDaemon"),
            patch("core.kernel.AetherService", return_value=fake_aether),
            patch("core.kernel.WraithService"),
            patch("core.kernel.EvoService"),
            patch("core.kernel.OpenChimeraProvider", return_value=fake_provider),
            patch("core.kernel.OpenChimeraAPIServer") as api_server_cls,
        ):
            api_server_cls.return_value.start.return_value = True
            kernel = OpenChimeraKernel()
            kernel.bus.publish_nowait = fake_publish_nowait
            kernel.boot(run_forever=False)

        self.assertIn("system/startup", published)

    def test_shutdown_stops_provider_and_api(self) -> None:
        fake_provider = MagicMock()
        fake_api = MagicMock()

        with (
            patch("core.kernel.build_identity_snapshot", return_value={"supervision": {}}),
            patch("core.kernel.get_watch_files", return_value=[]),
            patch("core.kernel.Personality"),
            patch("core.kernel.FIMDaemon"),
            patch("core.kernel.AetherService"),
            patch("core.kernel.WraithService"),
            patch("core.kernel.EvoService"),
            patch("core.kernel.OpenChimeraProvider", return_value=fake_provider),
            patch("core.kernel.OpenChimeraAPIServer", return_value=fake_api),
        ):
            kernel = OpenChimeraKernel()
            kernel.shutdown()

        fake_api.stop.assert_called_once()
        fake_provider.stop.assert_called_once()

    def test_status_snapshot_returns_expected_keys(self) -> None:
        fake_provider = MagicMock()
        fake_provider.status.return_value = {
            "online": True, "api_online": True,
            "aegis": {"running": True}, "ascension": {},
            "deployment": {}, "onboarding": {"suggested_local_models": []},
            "integrations": {},
        }
        fake_aether = MagicMock()
        fake_aether.status.return_value = {"running": True}
        fake_wraith = MagicMock()
        fake_wraith.status.return_value = {"running": False}
        fake_evo = MagicMock()
        fake_evo.status.return_value = {"running": False}

        with (
            patch("core.kernel.build_identity_snapshot", return_value={"supervision": {}}),
            patch("core.kernel.get_watch_files", return_value=[]),
            patch("core.kernel.Personality"),
            patch("core.kernel.FIMDaemon"),
            patch("core.kernel.AetherService", return_value=fake_aether),
            patch("core.kernel.WraithService", return_value=fake_wraith),
            patch("core.kernel.EvoService", return_value=fake_evo),
            patch("core.kernel.OpenChimeraProvider", return_value=fake_provider),
            patch("core.kernel.OpenChimeraAPIServer"),
        ):
            kernel = OpenChimeraKernel()
            snap = kernel.status_snapshot()

        for key in ("aether", "wraith", "evo", "aegis", "ascension", "provider_online", "supervision", "watch_files"):
            self.assertIn(key, snap)

    def test_fim_daemon_not_started_when_no_watch_files(self) -> None:
        fake_provider = MagicMock()
        fake_provider.status.return_value = {
            "online": True, "api_online": True,
            "aegis": {}, "ascension": {}, "deployment": {},
            "onboarding": {}, "integrations": {},
        }

        with (
            patch("core.kernel.build_identity_snapshot", return_value={"supervision": {"enabled": False}}),
            patch("core.kernel.get_watch_files", return_value=[]),
            patch("core.kernel.Personality"),
            patch("core.kernel.FIMDaemon"),
            patch("core.kernel.AetherService"),
            patch("core.kernel.WraithService"),
            patch("core.kernel.EvoService"),
            patch("core.kernel.OpenChimeraProvider", return_value=fake_provider),
            patch("core.kernel.OpenChimeraAPIServer") as api_cls,
        ):
            api_cls.return_value.start.return_value = True
            kernel = OpenChimeraKernel()
            kernel.boot(run_forever=False)
            self.assertIsNone(kernel._fim_thread)

    def test_supervise_runtimes_restarts_stopped_service(self) -> None:
        """_supervise_runtimes should call service.start() if service is available but not running."""
        fake_service = MagicMock()
        fake_service.status.return_value = {"available": True, "running": False, "last_started_at": None}
        fake_service.start.return_value = True

        with (
            patch("core.kernel.build_identity_snapshot", return_value={"supervision": {"enabled": True, "interval_seconds": 10}}),
            patch("core.kernel.get_watch_files", return_value=[]),
            patch("core.kernel.Personality"),
            patch("core.kernel.FIMDaemon"),
            patch("core.kernel.AetherService", return_value=fake_service),
            patch("core.kernel.WraithService"),
            patch("core.kernel.EvoService"),
            patch("core.kernel.OpenChimeraProvider"),
            patch("core.kernel.OpenChimeraAPIServer"),
        ):
            kernel = OpenChimeraKernel()
            kernel._running = True

            # Run one iteration of the supervisor loop
            # Patch time.sleep to exit after one cycle
            call_count = [0]
            real_sleep = time.sleep

            def one_shot_sleep(secs):
                call_count[0] += 1
                kernel._running = False  # stop loop after first sleep

            with patch("core.kernel.time.sleep", side_effect=one_shot_sleep):
                kernel._supervise_runtimes()

        fake_service.start.assert_called()

    def test_provider_start_exception_propagates(self) -> None:
        fake_provider = MagicMock()
        fake_provider.start.side_effect = RuntimeError("provider boot failure")

        with (
            patch("core.kernel.build_identity_snapshot", return_value={"supervision": {}}),
            patch("core.kernel.get_watch_files", return_value=[]),
            patch("core.kernel.Personality"),
            patch("core.kernel.FIMDaemon"),
            patch("core.kernel.AetherService"),
            patch("core.kernel.WraithService"),
            patch("core.kernel.EvoService"),
            patch("core.kernel.OpenChimeraProvider", return_value=fake_provider),
            patch("core.kernel.OpenChimeraAPIServer"),
        ):
            kernel = OpenChimeraKernel()
            with self.assertRaises(RuntimeError, msg="provider boot failure"):
                kernel.boot(run_forever=False)
        self.assertFalse(kernel._running)

    def test_kernel_alias_is_openchimera_kernel(self) -> None:
        from core.kernel import Kernel
        self.assertIs(Kernel, OpenChimeraKernel)


if __name__ == "__main__":
    unittest.main()
