"""
AETHER PluginManager — OpenChimera external integration.

Provides a zero-argument-constructable PluginManager compatible with the
AetherKernelAdapter contract:
  - PluginManager() — no required constructor arguments
  - .load_plugins() — discovers and registers available plugins
"""
from __future__ import annotations

import importlib
import logging
import os
from pathlib import Path
from typing import Any


LOGGER = logging.getLogger("aether.plugin_manager")


class PluginManager:
    """
    Discovers and loads AETHER plugins.

    Plugins are Python modules located under the ``plugins/`` directory
    adjacent to this file (i.e. external/aether/plugins/).  Each module
    that exposes a ``register(manager)`` callable will have it invoked
    on load.

    The class is intentionally self-contained so it can be instantiated
    with no arguments by AetherService.
    """

    def __init__(self) -> None:
        self._plugins: dict[str, Any] = {}
        self._plugin_dir = Path(__file__).parent.parent / "plugins"
        self._loaded = False

    # ------------------------------------------------------------------
    # Core contract
    # ------------------------------------------------------------------

    def load_plugins(self) -> list[str]:
        """
        Discover and load plugins from the plugins directory.

        Returns a list of successfully loaded plugin names.
        Safe to call multiple times — subsequent calls are no-ops.
        """
        if self._loaded:
            LOGGER.debug("[PluginManager] Already loaded; skipping.")
            return list(self._plugins.keys())

        self._loaded = True
        loaded: list[str] = []

        if not self._plugin_dir.exists():
            LOGGER.info(
                "[PluginManager] Plugin directory not found (%s); no plugins loaded.",
                self._plugin_dir,
            )
            return loaded

        for entry in sorted(self._plugin_dir.iterdir()):
            if entry.suffix != ".py" or entry.name.startswith("_"):
                continue
            plugin_name = entry.stem
            try:
                spec = importlib.util.spec_from_file_location(
                    f"aether_plugin_{plugin_name}", entry
                )
                if spec is None or spec.loader is None:
                    continue
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)  # type: ignore[union-attr]

                if callable(getattr(module, "register", None)):
                    module.register(self)

                self._plugins[plugin_name] = module
                loaded.append(plugin_name)
                LOGGER.info("[PluginManager] Loaded plugin: %s", plugin_name)
            except Exception as exc:
                LOGGER.warning("[PluginManager] Failed to load plugin %r: %s", plugin_name, exc)

        LOGGER.info("[PluginManager] %d plugin(s) loaded.", len(loaded))
        return loaded

    # ------------------------------------------------------------------
    # Registry helpers
    # ------------------------------------------------------------------

    def register_plugin(self, name: str, module: Any) -> None:
        """Manually register an already-loaded plugin module."""
        self._plugins[name] = module

    def get_plugin(self, name: str) -> Any | None:
        return self._plugins.get(name)

    def list_plugins(self) -> list[str]:
        return list(self._plugins.keys())

    def status(self) -> dict[str, Any]:
        return {
            "loaded": self._loaded,
            "plugin_count": len(self._plugins),
            "plugins": list(self._plugins.keys()),
            "plugin_dir": str(self._plugin_dir),
        }
