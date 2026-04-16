"""Evo stub — SwarmBot (OpenChimera bundled implementation)."""
import logging
import time

log = logging.getLogger(__name__)


class SwarmBot:
    def start_autonomous_loop(self) -> None:
        log.info("[EVO] SwarmBot autonomous loop running (stub mode)")
        while True:
            time.sleep(3600)
