from __future__ import annotations

import logging
import threading

from core.config import get_evo_root
from core.integration import import_module_from_file


LOGGER = logging.getLogger(__name__)


class EvoService:
    def __init__(self):
        self.root = get_evo_root()
        self.thread: threading.Thread | None = None
        self.error: str | None = None
        self.available = (self.root / "swarm_bot.py").exists()
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
        if self.thread is not None:
            return True

        self.thread = threading.Thread(
            target=self.bot.start_autonomous_loop,
            daemon=True,
            name="OpenChimera-EVO",
        )
        self.thread.start()
        LOGGER.info("Starting Project Evo autonomous swarm.")
        return True