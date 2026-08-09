"""Tool registry with built-in tools and MCP support."""

import json
from typing import Any

from openchimera.config import Settings


class ToolRegistry:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings
        self._tools: dict[str, dict[str, Any]] = {
            "browser.fetch": {
                "name": "browser.fetch",
                "description": "Fetch a URL and return main text content",
                "category": "web",
                "requires_admin": False,
                "schema": {
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                },
            },
            "shell.exec": {
                "name": "shell.exec",
                "description": "Execute a shell command",
                "category": "system",
                "requires_admin": True,
                "schema": {
                    "type": "object",
                    "properties": {"command": {"type": "string"}},
                    "required": ["command"],
                },
            },
            "file.read": {
                "name": "file.read",
                "description": "Read a local file",
                "category": "filesystem",
                "requires_admin": False,
                "schema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            },
            "github.search_code": {
                "name": "github.search_code",
                "description": "Search code across GitHub repositories",
                "category": "integration",
                "requires_admin": False,
                "schema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}, "language": {"type": "string"}},
                    "required": ["query"],
                },
            },
            "rag.query": {
                "name": "rag.query",
                "description": "Query the RAG vector store",
                "category": "retrieval",
                "requires_admin": False,
                "schema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}, "top_k": {"type": "integer"}},
                    "required": ["query"],
                },
            },
            "axiom.recall": {
                "name": "axiom.recall",
                "description": "Recall memory from AXIOM",
                "category": "cognitive",
                "requires_admin": False,
                "schema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            },
            "adam.genome": {
                "name": "adam.genome",
                "description": "Read ADAM genome state",
                "category": "cognitive",
                "requires_admin": False,
                "schema": {"type": "object", "properties": {}},
            },
            "eve.predict_ux": {
                "name": "eve.predict_ux",
                "description": "Predict UX with EVE",
                "category": "cognitive",
                "requires_admin": False,
                "schema": {
                    "type": "object",
                    "properties": {"feature": {"type": "string"}},
                    "required": ["feature"],
                },
            },
        }

    def list_tools(self) -> list[dict[str, Any]]:
        return [{"id": k, **v} for k, v in self._tools.items()]

    def get_tool(self, tool_id: str) -> dict[str, Any] | None:
        return self._tools.get(tool_id)

    async def execute(self, tool_id: str, arguments: dict[str, Any]) -> Any:
        tool = self._tools.get(tool_id)
        if not tool:
            return {"error": f"Tool {tool_id} not found"}
        handler = getattr(self, f"_handle_{tool_id.replace('.', '_')}", None)
        if handler:
            return await handler(arguments)
        return {"error": f"Execution not implemented for {tool_id}"}

    async def _handle_browser_fetch(self, args: dict[str, Any]) -> dict[str, Any]:
        import httpx
        url = args["url"]
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.get(url)
                return {"status": r.status_code, "content": r.text[:2000]}
        except Exception as e:
            return {"error": str(e)}

    async def _handle_shell_exec(self, args: dict[str, Any]) -> dict[str, Any]:
        import subprocess
        cmd = args["command"]
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
            return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
        except Exception as e:
            return {"error": str(e)}

    async def _handle_file_read(self, args: dict[str, Any]) -> dict[str, Any]:
        from pathlib import Path
        path = Path(args["path"])
        if not path.exists():
            return {"error": "File not found"}
        try:
            return {"content": path.read_text(encoding="utf-8")[:5000]}
        except Exception as e:
            return {"error": str(e)}

    async def _handle_github_search_code(self, args: dict[str, Any]) -> dict[str, Any]:
        import httpx
        query = args["query"]
        lang = args.get("language", "")
        q = f"{query} language:{lang}" if lang else query
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.get("https://api.github.com/search/code", params={"q": q}, headers={"Accept": "application/vnd.github.v3+json"})
                data = r.json()
                items = data.get("items", [])[:5]
                return {"count": data.get("total_count", 0), "items": [{"repo": i["repository"]["full_name"], "path": i["path"]} for i in items]}
        except Exception as e:
            return {"error": str(e)}

    async def _handle_rag_query(self, args: dict[str, Any]) -> dict[str, Any]:
        return {"results": [], "note": "RAG engine not initialized in this session"}

    async def _handle_axiom_recall(self, args: dict[str, Any]) -> dict[str, Any]:
        return {"note": "AXIOM recall requires cognitive gateway", "query": args.get("query")}

    async def _handle_adam_genome(self, args: dict[str, Any]) -> dict[str, Any]:
        return {"note": "ADAM genome read requires cognitive gateway"}

    async def _handle_eve_predict_ux(self, args: dict[str, Any]) -> dict[str, Any]:
        return {"note": "EVE UX prediction requires cognitive gateway", "feature": args.get("feature")}
