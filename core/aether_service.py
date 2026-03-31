from __future__ import annotations

import asyncio
import logging
import threading
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
        self.thread: threading.Thread | None = None
        self.error: str | None = None
        self.available = (self.root / "core" / "event_bus.py").exists()
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
        if self.thread is not None:
            return True

        def runner() -> None:
            asyncio.run(self.adapter.boot())

        self.thread = threading.Thread(target=runner, daemon=True, name="OpenChimera-AETHER")
        self.thread.start()
        LOGGER.info("Starting AETHER kernel as OpenChimera core runtime.")
        return True