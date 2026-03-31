from __future__ import annotations

import logging
import threading
import time

from core.api_server import OpenChimeraAPIServer
from core.aether_service import AetherService
from core.bus import EventBus
from core.config import build_identity_snapshot, get_watch_files
from core.evo_service import EvoService
from core.fim_daemon import FIMDaemon
from core.personality import Personality
from core.provider import OpenChimeraProvider
from core.wraith_service import WraithService


LOGGER = logging.getLogger(__name__)


class OpenChimeraKernel:
    def __init__(self):
        self.identity_snapshot = build_identity_snapshot()
        self.watch_files = get_watch_files()
        self.supervision_config = self.identity_snapshot.get("supervision", {})
        self.bus = EventBus()
        self.personality = Personality(identity_snapshot=self.identity_snapshot)
        self.fim_daemon = FIMDaemon(self.bus, self.watch_files)
        self.aether = AetherService()
        self.wraith = WraithService()
        self.evo = EvoService()
        self.provider = OpenChimeraProvider(self.bus, self.personality)
        self.api_server = OpenChimeraAPIServer(self.provider, system_status_provider=self.status_snapshot)
        self._fim_thread: threading.Thread | None = None
        self._supervisor_thread: threading.Thread | None = None
        self._running = False

    def boot(self, run_forever: bool = True) -> dict:
        LOGGER.info("Booting OpenChimera...")
        self._running = True

        self.provider.start()
        api_online = self.api_server.start()

        if self.aether.start():
            self.bus.publish_nowait("system/runtime", self.aether.status())
        else:
            self._start_local_runtime()

        if self.wraith.start():
            self.bus.publish_nowait("system/wraith", self.wraith.status())
        if self.evo.start():
            self.bus.publish_nowait("system/evo", self.evo.status())

        self._start_fim_daemon()
        self._start_runtime_supervisor()

        provider_status = self.provider.status()
        provider_status["api_online"] = api_online
        self.bus.publish_nowait("system/provider", provider_status)

        status = self.status_snapshot(provider_status)
        onboarding = status.get("onboarding", {})
        suggested_local_models = onboarding.get("suggested_local_models", [])
        LOGGER.info(
            "OpenChimera online. aether=%s wraith=%s evo=%s provider=%s aegis=%s ascension=%s",
            status["aether"].get("running"),
            status["wraith"].get("running"),
            status["evo"].get("running"),
            status["provider_online"],
            status.get("aegis", {}).get("running"),
            status.get("ascension", {}).get("running"),
        )
        if suggested_local_models:
            LOGGER.info(
                "Onboarding hardware recommendations: %s",
                ", ".join(str(item.get("id")) for item in suggested_local_models),
            )
        else:
            LOGGER.info("Onboarding hardware recommendations: no suitable local model detected; cloud fallback recommended.")

        if run_forever:
            while True:
                time.sleep(1)
        return status

    def _start_local_runtime(self) -> None:
        LOGGER.info("AETHER unavailable; starting local OpenChimera runtime fallback.")
        self.bus.publish_nowait(
            "system/startup",
            {
                "runtime": "openchimera-local",
                "watch_files": self.watch_files,
                "identity": self.identity_snapshot,
            },
        )

    def shutdown(self) -> None:
        self._running = False
        self.api_server.stop()
        self.provider.stop()
        self.bus.publish_nowait("system/shutdown", {"status": "offline"})

    def _start_fim_daemon(self) -> None:
        if self._fim_thread is not None or not self.watch_files:
            return

        self._fim_thread = threading.Thread(
            target=self.fim_daemon.run,
            daemon=True,
            name="OpenChimera-FIM",
        )
        self._fim_thread.start()

    def _start_runtime_supervisor(self) -> None:
        if not self.supervision_config.get("enabled", True):
            return
        if self._supervisor_thread is not None:
            return

        self._supervisor_thread = threading.Thread(
            target=self._supervise_runtimes,
            daemon=True,
            name="OpenChimera-Supervisor",
        )
        self._supervisor_thread.start()

    def _supervise_runtimes(self) -> None:
        interval = float(self.supervision_config.get("interval_seconds", 15))
        cooldown = float(self.supervision_config.get("restart_cooldown_seconds", 30))
        while self._running:
            for service_name, service in (("aether", self.aether), ("wraith", self.wraith), ("evo", self.evo)):
                status = service.status()
                if not status.get("available") or status.get("running"):
                    continue
                last_started_at = float(status.get("last_started_at") or 0.0)
                if last_started_at and (time.time() - last_started_at) < cooldown:
                    continue
                restarted = service.start()
                if restarted:
                    self.bus.publish_nowait(
                        "system/supervisor",
                        {"service": service_name, "action": "restart", "status": service.status()},
                    )
            time.sleep(interval)

    def status_snapshot(self, provider_status: dict | None = None) -> dict:
        provider_status = provider_status or self.provider.status()
        return {
            "aether": self.aether.status(),
            "wraith": self.wraith.status(),
            "evo": self.evo.status(),
            "aegis": provider_status.get("aegis", {}),
            "ascension": provider_status.get("ascension", {}),
            "provider_online": provider_status.get("online", False) and provider_status.get("api_online", True),
            "onboarding": provider_status.get("onboarding", {}),
            "integrations": provider_status.get("integrations", {}),
            "supervision": {
                "enabled": bool(self.supervision_config.get("enabled", True)),
                "interval_seconds": float(self.supervision_config.get("interval_seconds", 15)),
                "restart_cooldown_seconds": float(self.supervision_config.get("restart_cooldown_seconds", 30)),
                "running": self._supervisor_thread is not None and self._supervisor_thread.is_alive(),
            },
            "watch_files": self.watch_files,
        }


Kernel = OpenChimeraKernel


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    OpenChimeraKernel().boot()
