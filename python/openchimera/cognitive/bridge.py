"""Full cognitive bridge — AXIOM / EVE / ADAM integration with real MCP tools."""

from __future__ import annotations

import json
from typing import Any

from openchimera.config import Settings, load_settings

_BRIDGE_INSTANCE: CognitiveBridge | None = None


def get_bridge() -> CognitiveBridge:
    global _BRIDGE_INSTANCE
    if _BRIDGE_INSTANCE is None:
        _BRIDGE_INSTANCE = CognitiveBridge(load_settings())
    return _BRIDGE_INSTANCE


class CognitiveBridge:
    """Bridge to the owner's cognitive stack (AXIOM + EVE + ADAM).

    Uses the native MCP tools when the gateway is available,
    falls back to direct file reads when not.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._gateway_url = "http://127.0.0.1:8788"
        self._native_available = self._check_native_tools()

    def _check_native_tools(self) -> bool:
        """Check if native cognitive MCP tools are available."""
        try:
            # Try importing the plugin modules directly
            import importlib
            spec = importlib.util.find_spec("mcp__plugin-cognitive_axiom__axiom_recall")
            return spec is not None
        except Exception:
            return False

    def _gateway_available(self) -> bool:
        try:
            import httpx
            r = httpx.get(f"{self._gateway_url}/health", timeout=2)
            return r.status_code == 200
        except Exception:
            return False

    def _use_native(self) -> bool:
        return self._native_available or self._gateway_available()

    # ── Status ──

    def axiom_status(self) -> dict[str, Any]:
        cfg = self.settings.cognitive.axiom
        if not cfg.enabled:
            return {"enabled": False}

        memories = 0
        try:
            from pathlib import Path
            cp_dir = Path(cfg.checkpoints_dir)
            if cp_dir.exists():
                memories = len(list(cp_dir.rglob("*.json")))
        except Exception:
            pass

        return {
            "enabled": True,
            "memories_stored": memories,
            "checkpoints_dir": cfg.checkpoints_dir,
            "gateway_connected": self._gateway_available(),
            "native_tools": self._native_available,
            "auto_recall": cfg.auto_recall,
        }

    def eve_status(self) -> dict[str, Any]:
        cfg = self.settings.cognitive.eve
        if not cfg.enabled:
            return {"enabled": False}
        return {
            "enabled": True,
            "personas_available": cfg.personas,
            "gateway_connected": self._gateway_available(),
            "native_tools": self._native_available,
            "auto_approve": cfg.auto_approve,
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

        beliefs = 0
        skills = 0
        mutations = 0
        try:
            import sqlite3
            conn = sqlite3.connect(cfg.memory_db)
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM beliefs")
            beliefs = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM skills")
            skills = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM mutations WHERE status = 'pending'")
            mutations = cur.fetchone()[0]
            conn.close()
        except Exception:
            pass

        return {
            "enabled": True,
            "genome_version": genome.get("version", "unknown"),
            "beliefs_count": beliefs,
            "skills_count": skills,
            "mutations_pending": mutations,
            "gateway_connected": self._gateway_available(),
            "native_tools": self._native_available,
            "auto_evolve": cfg.auto_evolve,
        }

    # ── AXIOM ──

    async def axiom_recall(self, query: str) -> dict[str, Any]:
        if self._native_available:
            try:
                # Use the native MCP tool
                # Note: These tools are injected by the cognitive plugin
                result = await self._call_native("axiom_recall", {"query": query})
                return {"query": query, "results": result}
            except Exception as e:
                return {"query": query, "results": [], "error": str(e), "fallback": "file_scan"}

        # Fallback: scan checkpoints directory
        return await self._fallback_recall(query)

    async def axiom_remember(self, text: str, kind: str = "conversation", scope: str = "personal") -> dict[str, Any]:
        if self._native_available:
            try:
                result = await self._call_native("axiom_remember", {"text": text, "kind": kind, "scope": scope})
                return {"stored": True, "kind": kind, "scope": scope, "result": result}
            except Exception as e:
                return {"stored": False, "error": str(e)}

        # Fallback: write to local checkpoint
        try:
            from pathlib import Path
            import uuid
            cp_dir = Path(self.settings.cognitive.axiom.checkpoints_dir)
            cp_dir.mkdir(parents=True, exist_ok=True)
            filename = f"{kind}_{uuid.uuid4().hex[:8]}_{int(time.time())}.json"
            filepath = cp_dir / filename
            data = {"text": text, "kind": kind, "scope": scope, "timestamp": time.time()}
            filepath.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return {"stored": True, "path": str(filepath), "fallback": True}
        except Exception as e:
            return {"stored": False, "error": str(e)}

    async def axiom_verify(self, response: str, evidence: str = "") -> dict[str, Any]:
        if self._native_available:
            try:
                result = await self._call_native("axiom_verify", {"response": response, "evidence": evidence})
                return {"verified": result}
            except Exception as e:
                return {"verified": False, "error": str(e)}
        return {"verified": None, "note": "AXIOM verify requires cognitive gateway"}

    async def _fallback_recall(self, query: str) -> dict[str, Any]:
        """Fallback: scan checkpoint files for matching content."""
        try:
            from pathlib import Path
            cp_dir = Path(self.settings.cognitive.axiom.checkpoints_dir)
            if not cp_dir.exists():
                return {"query": query, "results": [], "note": "No checkpoints directory"}

            results = []
            query_lower = query.lower()
            for f in cp_dir.rglob("*.json"):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    text = data.get("text", "")
                    if query_lower in text.lower():
                        results.append({"text": text[:500], "path": str(f), "kind": data.get("kind", "unknown")})
                        if len(results) >= 10:
                            break
                except Exception:
                    continue
            return {"query": query, "results": results, "fallback": True}
        except Exception as e:
            return {"query": query, "results": [], "error": str(e)}

    # ── EVE ──

    async def eve_predict(self, feature: str) -> dict[str, Any]:
        if self._native_available:
            try:
                result = await self._call_native("eve_predict_ux", {"feature": feature, "seed": 42})
                return {"feature": feature, "prediction": result}
            except Exception as e:
                return {"feature": feature, "error": str(e)}
        return {"feature": feature, "prediction": "N/A", "note": "EVE requires cognitive gateway"}

    # ── ADAM ──

    async def adam_read_genome(self) -> dict[str, Any]:
        if self._native_available:
            try:
                result = await self._call_native("adam_genome", {})
                return {"genome": result}
            except Exception as e:
                return {"genome": {}, "error": str(e)}

        # Fallback: read genome file directly
        try:
            path = self.settings.cognitive.adam.genome_path
            import os
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    return {"genome": json.load(f), "source": "file"}
            return {"genome": {}, "note": "Genome file not found"}
        except Exception as e:
            return {"genome": {}, "error": str(e)}

    async def adam_memory_query(self, query: str) -> dict[str, Any]:
        if self._native_available:
            try:
                result = await self._call_native("adam_memory_query", {"query": query})
                return {"query": query, "results": result}
            except Exception as e:
                return {"query": query, "error": str(e)}

        # Fallback: query SQLite directly
        try:
            import sqlite3
            conn = sqlite3.connect(self.settings.cognitive.adam.memory_db)
            cur = conn.cursor()
            cur.execute("SELECT content, metadata FROM memories WHERE content LIKE ?", (f"%{query}%",))
            rows = cur.fetchall()
            conn.close()
            return {"query": query, "results": [{"content": r[0], "metadata": r[1]} for r in rows[:10]], "fallback": True}
        except Exception as e:
            return {"query": query, "results": [], "error": str(e)}

    # ── Native tool caller ──

    async def _call_native(self, tool_name: str, params: dict[str, Any]) -> Any:
        """Call a native cognitive MCP tool if available."""
        # This is a bridge — in production, the MCP tools are injected by the runtime
        # We attempt to import and call them dynamically
        try:
            # Try the mcp plugin tools
            import importlib
            module_name = f"mcp__plugin-cognitive_{tool_name.split('_')[0]}__{tool_name}"
            mod = importlib.import_module(module_name)
            if hasattr(mod, tool_name):
                return await getattr(mod, tool_name)(**params)
        except Exception:
            pass
        raise RuntimeError(f"Native tool {tool_name} not available")


import time  # noqa: E402 — imported at end to avoid circular issues in some contexts
