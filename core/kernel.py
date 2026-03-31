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
        self.bus = EventBus()
        self.personality = Personality(identity_snapshot=self.identity_snapshot)
        self.fim_daemon = FIMDaemon(self.bus, self.watch_files)
        self.aether = AetherService()
        self.wraith = WraithService()
        self.evo = EvoService()
        self.provider = OpenChimeraProvider(self.bus, self.personality)
        self.api_server = OpenChimeraAPIServer(self.provider)
        self._fim_thread: threading.Thread | None = None

    def boot(self, run_forever: bool = True) -> dict:
        LOGGER.info("Booting OpenChimera...")

        self.provider.start()
        api_online = self.api_server.start()

        if self.aether.start():
            self.bus.publish_nowait("system/runtime", {"runtime": "aether", "status": "online"})
        else:
            self._start_local_runtime()

        if self.wraith.start():
            self.bus.publish_nowait("system/wraith", {"status": "online"})
        if self.evo.start():
            self.bus.publish_nowait("system/evo", {"status": "online"})

        self._start_fim_daemon()

        provider_status = self.provider.status()
        provider_status["api_online"] = api_online
        self.bus.publish_nowait("system/provider", provider_status)

        status = self.status_snapshot(provider_status)
        LOGGER.info(
            "OpenChimera online. aether=%s wraith=%s evo=%s provider=%s",
            status["aether"],
            status["wraith"],
            status["evo"],
            status["provider_online"],
        )

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

    def status_snapshot(self, provider_status: dict | None = None) -> dict:
        provider_status = provider_status or self.provider.status()
        return {
            "aether": self.aether.available,
            "wraith": self.wraith.available,
            "evo": self.evo.available,
            "provider_online": provider_status.get("online", False) and provider_status.get("api_online", True),
            "watch_files": self.watch_files,
        }


Kernel = OpenChimeraKernel


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    OpenChimeraKernel().boot()
