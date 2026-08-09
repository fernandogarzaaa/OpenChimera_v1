"""Cognitive bridge — AXIOM / EVE / ADAM integration."""

import json
from typing import Any

from openchimera.config import Settings


class CognitiveBridge:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._gateway_url = "http://127.0.0.1:8788"

    def _gateway_available(self) -> bool:
        try:
            import httpx
            r = httpx.get(f"{self._gateway_url}/health", timeout=2)
            return r.status_code == 200
        except Exception:
            return False

    def axiom_status(self) -> dict[str, Any]:
        cfg = self.settings.cognitive.axiom
        if not cfg.enabled:
            return {"enabled": False}
        return {
            "enabled": True,
            "memories_stored": 0,
            "last_recall": None,
            "checkpoints_dir": cfg.checkpoints_dir,
            "gateway_connected": self._gateway_available(),
        }

    def eve_status(self) -> dict[str, Any]:
        cfg = self.settings.cognitive.eve
        if not cfg.enabled:
            return {"enabled": False}
        return {
            "enabled": True,
            "personas_available": cfg.personas,
            "last_session": None,
            "gateway_connected": self._gateway_available(),
        }

    def adam_status(self) -> dict[str, Any]:
        cfg = self.settings.cognitive.adam
        if not cfg.enabled:
            return {"enabled": False}
        genome = {}
        try:
            path = cfg.genome_path
            import os
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    genome = json.load(f)
        except Exception:
            pass
        return {
            "enabled": True,
            "genome_version": genome.get("version", "unknown"),
            "beliefs_count": 0,
            "skills_count": 0,
            "mutations_pending": 0,
            "gateway_connected": self._gateway_available(),
        }

    async def axiom_recall(self, query: str) -> dict[str, Any]:
        if not self._gateway_available():
            return {"error": "Cognitive gateway not available"}
        return {"query": query, "results": []}

    async def eve_predict(self, feature: str) -> dict[str, Any]:
        if not self._gateway_available():
            return {"error": "Cognitive gateway not available"}
        return {"feature": feature, "prediction": "N/A"}

    async def adam_read_genome(self) -> dict[str, Any]:
        if not self._gateway_available():
            return {"error": "Cognitive gateway not available"}
        return {"genome": {}}
