"""
Project Evo — SwarmBot entry point for OpenChimera.

Delegates to the full project-evo SDK (sdk.swarm_orchestrator) when available.
The SDK is resolved relative to this file's location:
    external/evo/../../.. -> openchimera root -> ../project-evo
i.e. D:\\project-evo (sibling of the openchimera repo root).

Falls back to stub mode if the SDK cannot be loaded, so the service still
marks itself as available and the thread starts without crashing.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys

# ---------------------------------------------------------------------------
# SDK path resolution
# ---------------------------------------------------------------------------
# external/evo/ -> external/ -> openchimera/ -> D:\ -> project-evo
_EVO_PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "project-evo")
)
if os.path.isdir(_EVO_PROJECT_ROOT) and _EVO_PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _EVO_PROJECT_ROOT)


class SwarmBot:
    """Autonomous evolution swarm entry point."""

    def __init__(self):
        self.logger = logging.getLogger("SwarmBot")
        logging.basicConfig(level=logging.INFO)
        self._orchestrator = None
        self._stub_mode = False

        try:
            from sdk.swarm_orchestrator import SwarmOrchestrator  # noqa: PLC0415
            self._orchestrator = SwarmOrchestrator()
            self.logger.info("Project Evo SDK loaded from: %s", _EVO_PROJECT_ROOT)
        except Exception as exc:
            self.logger.warning(
                "Project Evo SDK unavailable (%s) — running in stub mode.", exc
            )
            self._stub_mode = True

    def start_autonomous_loop(self) -> None:
        """Start the autonomous evolution loop."""
        self.logger.info("Initializing Autonomous Evolution Swarm...")
        if self._orchestrator is not None:
            asyncio.run(self._orchestrator.run_parallel_evolution("."))
        else:
            self.logger.warning(
                "Orchestrator not available (stub mode); evolution loop skipped."
            )
        self.logger.info("Evolution loop completed.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()

    if args.run:
        bot = SwarmBot()
        bot.start_autonomous_loop()
    else:
        print("Usage: python swarm_bot.py --run")
