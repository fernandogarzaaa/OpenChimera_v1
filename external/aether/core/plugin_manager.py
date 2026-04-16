"""AETHER stub — PluginManager (OpenChimera bundled implementation)."""
import logging

log = logging.getLogger(__name__)


class PluginManager:
    def load_plugins(self) -> None:
        log.info("[AETHER] PluginManager initialized (stub mode)")
