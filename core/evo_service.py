from __future__ import annotations

import logging
import threading
import time

from core.config import get_evo_root
from core.integration import import_module_from_file


LOGGER = logging.getLogger(__name__)


class EvoService:
    def __init__(self):
        self.root = get_evo_root()
        self.entrypoint = self.root / "swarm_bot.py"
        self.thread: threading.Thread | None = None
        self.error: str | None = None
        self.start_attempts = 0
        self.last_started_at = 0.0
        self.last_exited_at = 0.0
        self.available = self.entrypoint.exists()
        self.bot = None

        if self.available:
            try:
                module = import_module_from_file(
                    "openchimera_evo_swarm_bot",
                    self.root / "swarm_bot.py",
                    repo_root=self.root,
                )
                self.bot = module.SwarmBot()
            except Exception as exc:
                self.available = False
                self.error = str(exc)
                LOGGER.exception("Failed to initialize Project Evo swarm bot.")

    def start(self) -> bool:
        if not self.available or self.bot is None:
            return False
        if self.is_running():
            return True

        self.start_attempts += 1
        self.last_started_at = time.time()
        self.error = None

        def runner() -> None:
            try:
                self.bot.start_autonomous_loop()
            except Exception as exc:
                self.error = str(exc)
                LOGGER.exception("Project Evo runtime exited unexpectedly.")
            finally:
                self.last_exited_at = time.time()

        self.thread = threading.Thread(
            target=runner,
            daemon=True,
            name="OpenChimera-EVO",
        )
        self.thread.start()
        LOGGER.info("Starting Project Evo autonomous swarm.")
        return True

    def is_running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def status(self) -> dict[str, object]:
        return {
            "name": "evo",
            "available": self.available,
            "running": self.is_running(),
            "root": str(self.root),
            "entrypoint": str(self.entrypoint),
            "start_attempts": self.start_attempts,
            "last_started_at": self.last_started_at,
            "last_exited_at": self.last_exited_at,
            "last_error": self.error,
        }