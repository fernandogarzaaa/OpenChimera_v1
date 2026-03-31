from __future__ import annotations

import asyncio
import logging
import threading
import time
from pathlib import Path

from core.config import get_aether_root
from core.integration import import_module_from_file


LOGGER = logging.getLogger(__name__)


class AetherKernelAdapter:
    def __init__(self, root: Path):
        core_root = root / "core"
        event_bus_module = import_module_from_file(
            "openchimera_aether_event_bus", core_root / "event_bus.py", repo_root=root
        )
        plugin_manager_module = import_module_from_file(
            "openchimera_aether_plugin_manager", core_root / "plugin_manager.py", repo_root=root
        )

        evolution_path = core_root / "evolution_engine.py"
        evolution_module = None
        if evolution_path.exists():
            try:
                evolution_module = import_module_from_file(
                    "openchimera_aether_evolution_engine", evolution_path, repo_root=root
                )
            except Exception as exc:
                LOGGER.warning("AETHER evolution engine unavailable; continuing without immune loop: %s", exc)

        event_bus_cls = getattr(event_bus_module, "EventBus")
        plugin_manager_cls = getattr(plugin_manager_module, "PluginManager")
        self.bus = getattr(event_bus_module, "bus", None) or event_bus_cls()
        self.plugin_manager = plugin_manager_cls()
        self.evolution_engine = None
        self.evolution_thread: threading.Thread | None = None

        if evolution_module is not None and hasattr(evolution_module, "EvolutionEngine"):
            self.evolution_engine = evolution_module.EvolutionEngine()

    def start_immune_system(self) -> None:
        if self.evolution_engine is None or self.evolution_thread is not None:
            return

        self.evolution_thread = threading.Thread(
            target=self.evolution_engine.run,
            daemon=True,
            name="OpenChimera-AetherEvolution",
        )
        self.evolution_thread.start()

    async def boot(self) -> None:
        self.plugin_manager.load_plugins()
        self.start_immune_system()

        maybe_coro = self.bus.start()
        if asyncio.iscoroutine(maybe_coro):
            await maybe_coro

        if hasattr(self.bus, "publish_nowait"):
            self.bus.publish_nowait("system/startup", {"source": "openchimera", "runtime": "aether"})

        while True:
            await asyncio.sleep(3600)


class AetherService:
    def __init__(self):
        self.root = get_aether_root()
        self.entrypoint = self.root / "core" / "event_bus.py"
        self.thread: threading.Thread | None = None
        self.error: str | None = None
        self.start_attempts = 0
        self.last_started_at = 0.0
        self.last_exited_at = 0.0
        self.available = self.entrypoint.exists()
        self.adapter: AetherKernelAdapter | None = None

        if self.available:
            try:
                self.adapter = AetherKernelAdapter(self.root)
            except Exception as exc:
                self.available = False
                self.error = str(exc)
                LOGGER.exception("Failed to initialize AETHER adapter.")

    def start(self) -> bool:
        if not self.available or self.adapter is None:
            return False
        if self.is_running():
            return True

        self.start_attempts += 1
        self.last_started_at = time.time()
        self.error = None

        def runner() -> None:
            try:
                asyncio.run(self.adapter.boot())
            except Exception as exc:
                self.error = str(exc)
                LOGGER.exception("AETHER runtime exited unexpectedly.")
            finally:
                self.last_exited_at = time.time()

        self.thread = threading.Thread(target=runner, daemon=True, name="OpenChimera-AETHER")
        self.thread.start()
        LOGGER.info("Starting AETHER kernel as OpenChimera core runtime.")
        return True

    def is_running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def status(self) -> dict[str, object]:
        return {
            "name": "aether",
            "available": self.available,
            "running": self.is_running(),
            "root": str(self.root),
            "entrypoint": str(self.entrypoint),
            "start_attempts": self.start_attempts,
            "last_started_at": self.last_started_at,
            "last_exited_at": self.last_exited_at,
            "last_error": self.error,
        }