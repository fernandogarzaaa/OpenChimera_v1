from __future__ import annotations

import enum
import logging
import threading
import time
from typing import Any

from core.api_server import OpenChimeraAPIServer
from core.aether_service import AetherService
from core.bus import EventBus
from core.causal_reasoning import CausalReasoning
from core.config import build_identity_snapshot, get_watch_files
from core.consensus_plane import ConsensusPlane
from core.embodied_interaction import EmbodiedInteraction
from core.ethical_reasoning import EthicalReasoning
from core.evo_service import EvoService
from core.fim_daemon import FIMDaemon
from core.meta_learning import MetaLearning
from core.personality import Personality
from core.provider import OpenChimeraProvider
from core.self_model import SelfModel
from core.social_cognition import SocialCognition
from core.transfer_learning import TransferLearning
from core.wraith_service import WraithService


LOGGER = logging.getLogger(__name__)


class BootStatus(enum.Enum):
    """Kernel boot status levels."""
    FULL = "FULL"           # All subsystems initialized successfully
    DEGRADED = "DEGRADED"   # Some subsystems failed but kernel is operational
    FAILED = "FAILED"       # Critical subsystems failed, kernel is not operational


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

        # --- AGI cognitive modules ---
        self.self_model = SelfModel(bus=self.bus)
        self.transfer_learning = TransferLearning(bus=self.bus)
        self.causal_reasoning = CausalReasoning(bus=self.bus)
        self.meta_learning = MetaLearning(bus=self.bus)
        self.ethical_reasoning = EthicalReasoning(bus=self.bus)
        # Capabilities #9 & #10 — Embodied Interaction and Social Cognition
        self.embodied_interaction = EmbodiedInteraction(bus=self.bus)
        self.social_cognition = SocialCognition(bus=self.bus)
        # GodSwarm — multi-agent orchestration (lazy init so boot doesn't block)
        self._god_swarm: "Any | None" = None

        self.api_server = OpenChimeraAPIServer(self.provider, system_status_provider=self.status_snapshot)
        self._fim_thread: threading.Thread | None = None
        self._supervisor_thread: threading.Thread | None = None
        self._running = False

    def boot(self, run_forever: bool = True) -> dict:
        LOGGER.info("Booting OpenChimera...")
        self._running = True

        try:
            self.provider.start()
        except Exception as exc:
            LOGGER.error("Provider failed to start: %s", exc, exc_info=True)
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
                _fallback_model = self.identity_snapshot.get("local_model_fallback", "phi-3.5-mini")

                def _local_llm_agent(task: str, context: dict) -> str:
                    ranked = _llm_mgr.get_ranked_models(query_type="general")
                    model = ranked[0] if ranked else _fallback_model
                    result = _llm_mgr.chat_completion(
                        messages=[{"role": "user", "content": task}],
                        model=model,
                        query_type="general",
                        max_tokens=256,
                        timeout=15.0,
                    )
                    return str(result.get("content") or result.get("choices", [{}])[0].get("message", {}).get("content", ""))
                self.consensus_plane.register_agent("local-llm", _local_llm_agent)
        except Exception as exc:
            LOGGER.warning("Failed to wire local-llm consensus agent: %s", exc, exc_info=False)

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
        except Exception as exc:
            LOGGER.warning("Failed to wire minimind consensus agent: %s", exc, exc_info=False)

        # --- Wire AGI cognitive modules to bus events ---
        self._wire_cognitive_modules()

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

        # Emit boot status event
        boot_status_report = self.boot_report()
        self.bus.publish_nowait("system/boot_status", boot_status_report)
        LOGGER.info(
            "Boot status: %s (%d subsystems ok, %d degraded, %d failed)",
            boot_status_report["status"],
            sum(1 for s in boot_status_report["subsystems"].values() if s == "ok"),
            sum(1 for s in boot_status_report["subsystems"].values() if s == "degraded"),
            sum(1 for s in boot_status_report["subsystems"].values() if s == "failed"),
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
        self._running = False
        self.api_server.stop()
        self.provider.stop()
        self.bus.publish_nowait("system/shutdown", {"status": "offline"})

    # ------------------------------------------------------------------
    # Cognitive module wiring
    # ------------------------------------------------------------------

    def _wire_cognitive_modules(self) -> None:
        """Subscribe AGI modules to relevant bus events."""
        try:
            self.bus.subscribe("consensus/complete", self._on_consensus_complete)
            self.bus.subscribe("evolution/cycle", self._on_evolution_cycle)
        except Exception as exc:
            LOGGER.warning("AGI bus wiring incomplete: %s", exc)

        # Wire GodSwarm to the bus — non-blocking lazy initialisation
        try:
            from swarms.god_swarm import GodSwarm
            self._god_swarm = GodSwarm(bus=self.bus)
            self._god_swarm.wire_to_kernel(self)
            LOGGER.info("GodSwarm wired to kernel (%d agents).", len(GodSwarm.ALL_AGENT_IDS))
        except Exception as exc:
            LOGGER.warning("GodSwarm wiring skipped: %s", exc)

    def _on_consensus_complete(self, event: dict) -> None:
        """React to consensus results: update self-model and causal graph."""
        try:
            domain = event.get("domain", "general")
            confidence = float(event.get("confidence", 0.5))
            self.self_model.record_capability(domain, "consensus_confidence", confidence)
            self.causal_reasoning.set_variable(f"{domain}_confidence", confidence)
        except Exception as exc:
            LOGGER.debug("cognitive reaction to consensus failed: %s", exc)

    def _on_evolution_cycle(self, event: dict) -> None:
        """React to evolution cycles: record in meta-learning."""
        try:
            domain = event.get("domain", "general")
            success = bool(event.get("success", False))
            self.meta_learning.record_outcome(
                strategy_id=event.get("strategy_id", "default"),
                domain=domain,
                success=success,
                confidence=float(event.get("confidence", 0.5)),
                latency_ms=float(event.get("latency_ms", 0.0)),
            )
        except Exception as exc:
            LOGGER.debug("cognitive reaction to evolution failed: %s", exc)

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
        agi_status: dict = {}
        
        # Improved error handling with structured logging
        subsystem_health = {}
        
        try:
            agi_status["self_model"] = self.self_model.self_assessment()
            subsystem_health["self_model"] = "ok"
        except Exception as exc:
            LOGGER.warning("self_model subsystem unavailable: %s", exc, exc_info=False)
            agi_status["self_model"] = {"error": "unavailable"}
            subsystem_health["self_model"] = "failed"
            
        try:
            agi_status["transfer_learning"] = {
                "domains": self.transfer_learning.list_domains(),
                "patterns": len(self.transfer_learning.list_patterns()),
            }
            subsystem_health["transfer_learning"] = "ok"
        except Exception as exc:
            LOGGER.warning("transfer_learning subsystem unavailable: %s", exc, exc_info=False)
            agi_status["transfer_learning"] = {"error": "unavailable"}
            subsystem_health["transfer_learning"] = "failed"
            
        try:
            agi_status["meta_learning"] = self.meta_learning.status()
            subsystem_health["meta_learning"] = "ok"
        except Exception as exc:
            LOGGER.warning("meta_learning subsystem unavailable: %s", exc, exc_info=False)
            agi_status["meta_learning"] = {"error": "unavailable"}
            subsystem_health["meta_learning"] = "failed"
            
        try:
            agi_status["ethical_reasoning"] = self.ethical_reasoning.status()
            subsystem_health["ethical_reasoning"] = "ok"
        except Exception as exc:
            LOGGER.warning("ethical_reasoning subsystem unavailable: %s", exc, exc_info=False)
            agi_status["ethical_reasoning"] = {"error": "unavailable"}
            subsystem_health["ethical_reasoning"] = "failed"
            
        try:
            agi_status["social_cognition"] = self.social_cognition.snapshot()
            subsystem_health["social_cognition"] = "ok"
        except Exception as exc:
            LOGGER.warning("social_cognition subsystem unavailable: %s", exc, exc_info=False)
            agi_status["social_cognition"] = {"error": "unavailable"}
            subsystem_health["social_cognition"] = "failed"
            
        try:
            agi_status["embodied_interaction"] = self.embodied_interaction.snapshot()
            subsystem_health["embodied_interaction"] = "ok"
        except Exception as exc:
            LOGGER.warning("embodied_interaction subsystem unavailable: %s", exc, exc_info=False)
            agi_status["embodied_interaction"] = {"error": "unavailable"}
            subsystem_health["embodied_interaction"] = "failed"
            
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
            "agi": agi_status,
            "subsystem_health": subsystem_health,
        }

    def boot_report(self) -> dict[str, Any]:
        """Generate a boot status report showing which subsystems initialized successfully.
        
        Returns:
            dict with:
                - subsystems: dict mapping subsystem name to status ("ok"|"degraded"|"failed")
                - status: overall BootStatus ("FULL"|"DEGRADED"|"FAILED")
                - timestamp: boot report generation time
        """
        report = {
            "timestamp": time.time(),
            "subsystems": {},
            "status": BootStatus.FULL.value,
        }
        
        # Check core services
        report["subsystems"]["aether"] = "ok" if self.aether.status().get("running") else "degraded"
        report["subsystems"]["wraith"] = "ok" if self.wraith.status().get("running") else "degraded"
        report["subsystems"]["evo"] = "ok" if self.evo.status().get("running") else "degraded"
        report["subsystems"]["provider"] = "ok" if self.provider.status().get("online") else "failed"
        report["subsystems"]["api_server"] = "ok" if self.api_server else "failed"
        
        # Check AGI modules
        for module_name in ["self_model", "transfer_learning", "meta_learning", 
                           "ethical_reasoning", "social_cognition", "embodied_interaction"]:
            try:
                module = getattr(self, module_name, None)
                if module is None:
                    report["subsystems"][module_name] = "failed"
                else:
                    # Try to call a status method to verify it's working
                    if hasattr(module, "status"):
                        module.status()
                    elif hasattr(module, "snapshot"):
                        module.snapshot()
                    elif hasattr(module, "self_assessment"):
                        module.self_assessment()
                    report["subsystems"][module_name] = "ok"
            except Exception as exc:
                LOGGER.debug("Boot check failed for %s: %s", module_name, exc)
                report["subsystems"][module_name] = "degraded"
        
        # Determine overall status
        failed_count = sum(1 for s in report["subsystems"].values() if s == "failed")
        degraded_count = sum(1 for s in report["subsystems"].values() if s == "degraded")
        
        if failed_count > 0 and "provider" in [k for k, v in report["subsystems"].items() if v == "failed"]:
            report["status"] = BootStatus.FAILED.value
        elif failed_count > 0 or degraded_count > 2:
            report["status"] = BootStatus.DEGRADED.value
        else:
            report["status"] = BootStatus.FULL.value
        
        return report

    def _swarm_status(self) -> dict:
        """Return lightweight swarm surface info."""
        try:
            from swarms.god_swarm import GodSwarm
            base = {
                "core_agents": GodSwarm.CORE_AGENT_IDS,
                "supporting_agents": GodSwarm.SUPPORTING_AGENT_IDS,
                "total_agents": len(GodSwarm.ALL_AGENT_IDS),
                "ready": True,
            }
            if self._god_swarm is not None:
                base["live"] = self._god_swarm.status()
            return base
        except Exception as exc:
            return {"ready": False, "error": str(exc)}


Kernel = OpenChimeraKernel


if __name__ == "__main__":
    from core.config import get_log_level, get_structured_log_path
    from core.logging_utils import configure_runtime_logging

    configure_runtime_logging(level=get_log_level(), structured_log_path=get_structured_log_path())
    OpenChimeraKernel().boot()
