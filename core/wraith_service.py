from __future__ import annotations

import logging
import threading
import time

from core.config import get_wraith_root
from core.integration import import_module_from_file


LOGGER = logging.getLogger(__name__)


class WraithService:
    def __init__(self):
        self.root = get_wraith_root()
        self.entrypoint = self.root / "orchestrator" / "god_node.py"
        self.thread: threading.Thread | None = None
        self.error: str | None = None
        self.start_attempts = 0
        self.last_started_at = 0.0
        self.last_exited_at = 0.0
        self.available = self.entrypoint.exists()
        self.orchestrator = None

        if self.available:
            try:
                module = import_module_from_file(
                    "openchimera_wraith_god_node",
                    self.root / "orchestrator" / "god_node.py",
                    repo_root=self.root,
                )
                self.orchestrator = module.WraithOrchestrator()
            except Exception as exc:
                self.available = False
                self.error = str(exc)
                LOGGER.exception("Failed to initialize WRAITH orchestrator.")

    def start(self) -> bool:
        if not self.available or self.orchestrator is None:
            return False
        if self.is_running():
            return True

        self.start_attempts += 1
        self.last_started_at = time.time()
        self.error = None

        def runner() -> None:
            try:
                self.orchestrator.run()
            except Exception as exc:
                self.error = str(exc)
                LOGGER.exception("WRAITH runtime exited unexpectedly.")
            finally:
                self.last_exited_at = time.time()

        self.thread = threading.Thread(
            target=runner,
            daemon=True,
            name="OpenChimera-WRAITH",
        )
        self.thread.start()
        LOGGER.info("Starting WRAITH circadian background orchestrator.")
        return True

    def is_running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def status(self) -> dict[str, object]:
        return {
            "name": "wraith",
            "available": self.available,
            "running": self.is_running(),
            "root": str(self.root),
            "entrypoint": str(self.entrypoint),
            "start_attempts": self.start_attempts,
            "last_started_at": self.last_started_at,
            "last_exited_at": self.last_exited_at,
            "last_error": self.error,
        }