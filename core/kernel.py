from __future__ import annotations

import logging
import threading
import time

from core.api_server import OpenChimeraAPIServer
from core.aether_service import AetherService
from core.bus import EventBus
from core.config import build_identity_snapshot, get_watch_files
from core.consensus_plane import ConsensusPlane
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
        self.consensus_plane = ConsensusPlane(profile=self.identity_snapshot, bus=self.bus)
        self.api_server = OpenChimeraAPIServer(self.provider, system_status_provider=self.status_snapshot)
        self._fim_thread: threading.Thread | None = None
        self._supervisor_thread: threading.Thread | None = None
        self._running = False

    def boot(self, run_forever: bool = True) -> dict:
        LOGGER.info("Booting OpenChimera...")
        self._running = True

        try:
            self.provider.start()
        except Exception:
            self._running = False
            raise

        api_online = self.api_server.start()
        if not api_online:
            self.provider.stop()
            self._running = False
            raise RuntimeError("OpenChimera API server failed to start")

        if self.aether.start():
            self.bus.publish_nowait("system/runtime", self.aether.status())
        else:
            self._start_local_runtime()

        if self.wraith.start():
            self.bus.publish_nowait("system/wraith", self.wraith.status())
        if self.evo.start():
            self.bus.publish_nowait("system/evo", self.evo.status())

        # Wire consensus agents after core services are started
        try:
            _llm_mgr = getattr(self.provider, "llm_manager", None)
            if _llm_mgr is not None:
                def _local_llm_agent(task: str, context: dict) -> str:
                    ranked = _llm_mgr.get_ranked_models(query_type="general")
                    model = ranked[0] if ranked else "phi-3.5-mini"
                    result = _llm_mgr.chat_completion(
                        messages=[{"role": "user", "content": task}],
                        model=model,
                        query_type="general",
                        max_tokens=256,
                        timeout=15.0,
                    )
                    return str(result.get("content") or result.get("choices", [{}])[0].get("message", {}).get("content", ""))
                self.consensus_plane.register_agent("local-llm", _local_llm_agent)
        except Exception:
            pass

        try:
            _minimind = getattr(self.provider, "minimind", None)
            if _minimind is not None:
                def _minimind_agent(task: str, context: dict) -> str:
                    result = _minimind.reasoning_completion(
                        messages=[{"role": "user", "content": task}],
                        temperature=0.4,
                        max_tokens=256,
                        timeout=30.0,
                    )
                    return str(result.get("content", ""))
                self.consensus_plane.register_agent("minimind", _minimind_agent)
        except Exception:
            pass

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
            "deployment": provider_status.get("deployment", {}),
            "onboarding": provider_status.get("onboarding", {}),
            "integrations": provider_status.get("integrations", {}),
            "supervision": {
                "enabled": bool(self.supervision_config.get("enabled", True)),
                "interval_seconds": float(self.supervision_config.get("interval_seconds", 15)),
                "restart_cooldown_seconds": float(self.supervision_config.get("restart_cooldown_seconds", 30)),
                "running": self._supervisor_thread is not None and self._supervisor_thread.is_alive(),
            },
            "watch_files": self.watch_files,
            "swarm_agents": self._swarm_status(),
        }

    def _swarm_status(self) -> dict:
        """Return lightweight swarm surface info without instantiating GodSwarm."""
        try:
            from swarms.god_swarm import GodSwarm
            return {
                "core_agents": GodSwarm.CORE_AGENT_IDS,
                "supporting_agents": GodSwarm.SUPPORTING_AGENT_IDS,
                "total_agents": len(GodSwarm.ALL_AGENT_IDS),
                "ready": True,
            }
        except Exception as exc:
            return {"ready": False, "error": str(exc)}


Kernel = OpenChimeraKernel


if __name__ == "__main__":
    from core.config import get_log_level, get_structured_log_path
    from core.logging_utils import configure_runtime_logging

    configure_runtime_logging(level=get_log_level(), structured_log_path=get_structured_log_path())
    OpenChimeraKernel().boot()
