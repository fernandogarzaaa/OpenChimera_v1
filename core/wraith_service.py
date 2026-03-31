from __future__ import annotations

import logging
import threading

from core.config import get_wraith_root
from core.integration import import_module_from_file


LOGGER = logging.getLogger(__name__)


class WraithService:
    def __init__(self):
        self.root = get_wraith_root()
        self.thread: threading.Thread | None = None
        self.error: str | None = None
        self.available = (self.root / "orchestrator" / "god_node.py").exists()
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
        if self.thread is not None:
            return True

        self.thread = threading.Thread(
            target=self.orchestrator.run,
            daemon=True,
            name="OpenChimera-WRAITH",
        )
        self.thread.start()
        LOGGER.info("Starting WRAITH circadian background orchestrator.")
        return True