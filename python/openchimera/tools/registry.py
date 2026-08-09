"""Full tool registry with computer use, godmode, code execution, and more."""

from __future__ import annotations

import base64
import io
import json
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from openchimera.config import Settings


class ToolRegistry:
    """Central registry for all OpenChimera tools."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings
        self._tools: dict[str, dict[str, Any]] = self._build_registry()
        self._browser_ctx: Any = None
        self._screenshot_counter = 0

    def _build_registry(self) -> dict[str, dict[str, Any]]:
        return {
            # ── Web & Browser ──
            "browser.fetch": {
                "name": "browser.fetch",
                "description": "Fetch a URL and return main text content",
                "category": "web",
                "requires_admin": False,
                "schema": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]},
            },
            "browser.navigate": {
                "name": "browser.navigate",
                "description": "Navigate a browser to a URL and return page content (requires playwright)",
                "category": "web",
                "requires_admin": False,
                "schema": {"type": "object", "properties": {"url": {"type": "string"}, "wait_for": {"type": "string"}}, "required": ["url"]},
            },
            "browser.screenshot": {
                "name": "browser.screenshot",
                "description": "Take a screenshot of a webpage",
                "category": "web",
                "requires_admin": False,
                "schema": {"type": "object", "properties": {"url": {"type": "string"}, "full_page": {"type": "boolean"}}, "required": ["url"]},
            },
            "browser.click": {
                "name": "browser.click",
                "description": "Click an element on the current page by selector",
                "category": "web",
                "requires_admin": False,
                "schema": {"type": "object", "properties": {"selector": {"type": "string"}}, "required": ["selector"]},
            },
            "browser.type": {
                "name": "browser.type",
                "description": "Type text into an input field by selector",
                "category": "web",
                "requires_admin": False,
                "schema": {"type": "object", "properties": {"selector": {"type": "string"}, "text": {"type": "string"}}, "required": ["selector", "text"]},
            },
            # ── System & Shell ──
            "shell.exec": {
                "name": "shell.exec",
                "description": "Execute a shell command",
                "category": "system",
                "requires_admin": True,
                "schema": {"type": "object", "properties": {"command": {"type": "string"}, "timeout": {"type": "integer"}}, "required": ["command"]},
            },
            "file.read": {
                "name": "file.read",
                "description": "Read a local file",
                "category": "filesystem",
                "requires_admin": False,
                "schema": {"type": "object", "properties": {"path": {"type": "string"}, "offset": {"type": "integer"}, "limit": {"type": "integer"}}, "required": ["path"]},
            },
            "file.write": {
                "name": "file.write",
                "description": "Write content to a local file",
                "category": "filesystem",
                "requires_admin": True,
                "schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]},
            },
            "file.list": {
                "name": "file.list",
                "description": "List files in a directory",
                "category": "filesystem",
                "requires_admin": False,
                "schema": {"type": "object", "properties": {"path": {"type": "string"}, "recursive": {"type": "boolean"}}, "required": ["path"]},
            },
            # ── Code Execution ──
            "code.execute": {
                "name": "code.execute",
                "description": "Execute Python code in a sandboxed environment",
                "category": "code",
                "requires_admin": True,
                "schema": {"type": "object", "properties": {"code": {"type": "string"}, "language": {"type": "string", "enum": ["python", "bash", "javascript"]}}, "required": ["code"]},
            },
            # ── Computer Use ──
            "computer.screenshot": {
                "name": "computer.screenshot",
                "description": "Take a screenshot of the desktop (requires pyautogui + PIL)",
                "category": "computer",
                "requires_admin": False,
                "schema": {"type": "object", "properties": {"region": {"type": "string", "description": "x,y,width,height"}}, "required": []},
            },
            "computer.click": {
                "name": "computer.click",
                "description": "Click at screen coordinates (x, y)",
                "category": "computer",
                "requires_admin": True,
                "schema": {"type": "object", "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}, "button": {"type": "string", "enum": ["left", "right"]}}, "required": ["x", "y"]},
            },
            "computer.type": {
                "name": "computer.type",
                "description": "Type text at the current cursor position",
                "category": "computer",
                "requires_admin": True,
                "schema": {"type": "object", "properties": {"text": {"type": "string"}, "interval": {"type": "number"}}, "required": ["text"]},
            },
            # ── GitHub ──
            "github.search_code": {
                "name": "github.search_code",
                "description": "Search code across GitHub repositories",
                "category": "integration",
                "requires_admin": False,
                "schema": {"type": "object", "properties": {"query": {"type": "string"}, "language": {"type": "string"}}, "required": ["query"]},
            },
            "github.read_repo": {
                "name": "github.read_repo",
                "description": "Read file contents from a GitHub repository",
                "category": "integration",
                "requires_admin": False,
                "schema": {"type": "object", "properties": {"owner": {"type": "string"}, "repo": {"type": "string"}, "path": {"type": "string"}, "ref": {"type": "string"}}, "required": ["owner", "repo", "path"]},
            },
            # ── RAG ──
            "rag.query": {
                "name": "rag.query",
                "description": "Query the RAG vector store for relevant documents",
                "category": "retrieval",
                "requires_admin": False,
                "schema": {"type": "object", "properties": {"query": {"type": "string"}, "top_k": {"type": "integer"}}, "required": ["query"]},
            },
            "rag.add_documents": {
                "name": "rag.add_documents",
                "description": "Add documents to the RAG vector store",
                "category": "retrieval",
                "requires_admin": True,
                "schema": {"type": "object", "properties": {"texts": {"type": "array", "items": {"type": "string"}}, "metadatas": {"type": "array"}}, "required": ["texts"]},
            },
            # ── Cognitive Stack ──
            "godmode.activate": {
                "name": "godmode.activate",
                "description": "Activate the unified cognitive stack (AXIOM + EVE + ADAM). Use for memory recall, claim verification, UX validation, or cognitive evolution.",
                "category": "cognitive",
                "requires_admin": False,
                "schema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["recall", "verify", "predict_ux", "read_genome", "store_memory"], "description": "Cognitive action to perform"},
                        "query": {"type": "string", "description": "Query for recall/verify/store actions"},
                        "content": {"type": "string", "description": "Content to store in memory"},
                        "kind": {"type": "string", "enum": ["decision", "code", "conversation", "fix"], "description": "Memory kind for store action"},
                    },
                    "required": ["action"],
                },
            },
            "axiom.recall": {
                "name": "axiom.recall",
                "description": "Recall memory from AXIOM cognitive memory system",
                "category": "cognitive",
                "requires_admin": False,
                "schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
            },
            "axiom.remember": {
                "name": "axiom.remember",
                "description": "Store a memory in AXIOM",
                "category": "cognitive",
                "requires_admin": False,
                "schema": {"type": "object", "properties": {"text": {"type": "string"}, "kind": {"type": "string"}, "scope": {"type": "string"}}, "required": ["text", "kind"]},
            },
            "adam.read_genome": {
                "name": "adam.read_genome",
                "description": "Read ADAM genome state (cognitive substrate)",
                "category": "cognitive",
                "requires_admin": False,
                "schema": {"type": "object", "properties": {}},
            },
            "eve.predict_ux": {
                "name": "eve.predict_ux",
                "description": "Predict UX with EVE simulated-human validation",
                "category": "cognitive",
                "requires_admin": False,
                "schema": {"type": "object", "properties": {"feature": {"type": "string"}}, "required": ["feature"]},
            },
            # ── Web Search ──
            "web.search": {
                "name": "web.search",
                "description": "Search the web for current information",
                "category": "web",
                "requires_admin": False,
                "schema": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["query"]},
            },
            # ── MCP ──
            "mcp.list_tools": {
                "name": "mcp.list_tools",
                "description": "List available tools from an MCP server",
                "category": "mcp",
                "requires_admin": False,
                "schema": {"type": "object", "properties": {"server_name": {"type": "string"}}, "required": ["server_name"]},
            },
            "mcp.call_tool": {
                "name": "mcp.call_tool",
                "description": "Call a tool on an MCP server",
                "category": "mcp",
                "requires_admin": False,
                "schema": {"type": "object", "properties": {"server_name": {"type": "string"}, "tool_name": {"type": "string"}, "arguments": {"type": "object"}}, "required": ["server_name", "tool_name"]},
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
        handler_name = f"_handle_{tool_id.replace('.', '_')}"
        handler = getattr(self, handler_name, None)
        if handler:
            try:
                return await handler(arguments)
            except Exception as e:
                return {"error": str(e), "tool_id": tool_id}
        return {"error": f"Execution not implemented for {tool_id}"}

    # ── Web handlers ──

    async def _handle_browser_fetch(self, args: dict[str, Any]) -> dict[str, Any]:
        import httpx
        url = args["url"]
        try:
            async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                r = await client.get(url, headers={"User-Agent": "OpenChimera/2.0"})
                content_type = r.headers.get("content-type", "")
                if "application/json" in content_type:
                    return {"status": r.status_code, "json": r.json(), "url": url}
                return {"status": r.status_code, "content": r.text[:8000], "url": url}
        except Exception as e:
            return {"error": str(e), "url": url}

    async def _handle_browser_navigate(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            from playwright.async_api import async_playwright
            url = args["url"]
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page(viewport={"width": 1280, "height": 720})
                await page.goto(url, wait_until="domcontentloaded")
                wait_for = args.get("wait_for")
                if wait_for:
                    await page.wait_for_selector(wait_for, timeout=5000)
                title = await page.title()
                content = await page.content()
                await browser.close()
                return {"title": title, "content": content[:10000], "url": url}
        except ImportError:
            return {"error": "playwright not installed. Run: pip install playwright && playwright install chromium"}
        except Exception as e:
            return {"error": str(e), "url": args.get("url")}

    async def _handle_browser_screenshot(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            from playwright.async_api import async_playwright
            url = args["url"]
            full_page = args.get("full_page", False)
            self._screenshot_counter += 1
            out_path = Path("data/screenshots")
            out_path.mkdir(parents=True, exist_ok=True)
            filename = f"screenshot_{self._screenshot_counter}_{int(time.time())}.png"
            filepath = out_path / filename

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page(viewport={"width": 1280, "height": 720})
                await page.goto(url, wait_until="networkidle")
                await page.screenshot(path=str(filepath), full_page=full_page)
                await browser.close()

            with open(filepath, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            return {"screenshot_b64": b64, "path": str(filepath), "url": url}
        except ImportError:
            return {"error": "playwright not installed"}
        except Exception as e:
            return {"error": str(e)}

    async def _handle_browser_click(self, args: dict[str, Any]) -> dict[str, Any]:
        return {"note": "Browser click requires active page session. Use browser.navigate first."}

    async def _handle_browser_type(self, args: dict[str, Any]) -> dict[str, Any]:
        return {"note": "Browser type requires active page session. Use browser.navigate first."}

    # ── System handlers ──

    async def _handle_shell_exec(self, args: dict[str, Any]) -> dict[str, Any]:
        cmd = args["command"]
        timeout = args.get("timeout", 30)
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=timeout,
            )
            return {
                "returncode": result.returncode,
                "stdout": result.stdout[:10000],
                "stderr": result.stderr[:5000],
            }
        except subprocess.TimeoutExpired:
            return {"error": f"Command timed out after {timeout}s", "returncode": -1}
        except Exception as e:
            return {"error": str(e)}

    async def _handle_file_read(self, args: dict[str, Any]) -> dict[str, Any]:
        path = Path(args["path"])
        if not path.exists():
            return {"error": "File not found"}
        try:
            offset = args.get("offset", 0)
            limit = args.get("limit", 5000)
            text = path.read_text(encoding="utf-8", errors="replace")
            snippet = text[offset:offset + limit] if limit else text[offset:]
            return {
                "content": snippet,
                "total_size": len(text),
                "path": str(path),
                "truncated": len(snippet) < len(text) - offset,
            }
        except Exception as e:
            return {"error": str(e)}

    async def _handle_file_write(self, args: dict[str, Any]) -> dict[str, Any]:
        path = Path(args["path"])
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(args["content"], encoding="utf-8")
            return {"success": True, "path": str(path), "bytes_written": len(args["content"].encode("utf-8"))}
        except Exception as e:
            return {"error": str(e)}

    async def _handle_file_list(self, args: dict[str, Any]) -> dict[str, Any]:
        path = Path(args["path"])
        recursive = args.get("recursive", False)
        if not path.exists():
            return {"error": "Path not found"}
        try:
            if recursive:
                items = [{"name": p.name, "type": "dir" if p.is_dir() else "file", "path": str(p.relative_to(path))} for p in path.rglob("*")]
            else:
                items = [{"name": p.name, "type": "dir" if p.is_dir() else "file"} for p in path.iterdir()]
            return {"path": str(path), "items": items}
        except Exception as e:
            return {"error": str(e)}

    # ── Code execution ──

    async def _handle_code_execute(self, args: dict[str, Any]) -> dict[str, Any]:
        code = args["code"]
        language = args.get("language", "python")
        if language == "python":
            return await self._exec_python(code)
        elif language == "bash":
            return await self._handle_shell_exec({"command": code, "timeout": 30})
        return {"error": f"Language '{language}' not supported"}

    async def _exec_python(self, code: str) -> dict[str, Any]:
        """Execute Python in a restricted sandbox."""
        import ast
        try:
            tree = ast.parse(code)
            # Basic security: block dangerous imports
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in {"os", "sys", "subprocess", "ctypes", "socket"}:
                            return {"error": f"Import of '{alias.name}' is blocked in sandbox"}
                elif isinstance(node, ast.ImportFrom):
                    if node.module in {"os", "sys", "subprocess", "ctypes", "socket"}:
                        return {"error": f"Import from '{node.module}' is blocked in sandbox"}
        except SyntaxError as e:
            return {"error": f"Syntax error: {e}"}

        stdout_buffer = io.StringIO()
        stderr_buffer = io.StringIO()
        try:
            import contextlib
            with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(stderr_buffer):
                exec(compile(tree, "<sandbox>", "exec"), {"__builtins__": __builtins__})
            return {
                "stdout": stdout_buffer.getvalue()[:10000],
                "stderr": stderr_buffer.getvalue()[:5000],
                "returncode": 0,
            }
        except Exception as e:
            return {
                "error": str(e),
                "stdout": stdout_buffer.getvalue()[:10000],
                "stderr": stderr_buffer.getvalue()[:5000],
                "returncode": 1,
            }

    # ── Computer use ──

    async def _handle_computer_screenshot(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            import pyautogui
            from PIL import Image
            screenshot = pyautogui.screenshot()
            region = args.get("region")
            if region:
                parts = [int(x.strip()) for x in region.split(",")]
                if len(parts) == 4:
                    screenshot = screenshot.crop((parts[0], parts[1], parts[0] + parts[2], parts[1] + parts[3]))
            buf = io.BytesIO()
            screenshot.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode()
            return {"screenshot_b64": b64, "size": screenshot.size}
        except ImportError:
            return {"error": "pyautogui and Pillow not installed. Run: pip install pyautogui pillow"}
        except Exception as e:
            return {"error": str(e)}

    async def _handle_computer_click(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            import pyautogui
            x, y = args["x"], args["y"]
            button = args.get("button", "left")
            pyautogui.click(x, y, button=button)
            return {"success": True, "x": x, "y": y, "button": button}
        except ImportError:
            return {"error": "pyautogui not installed"}
        except Exception as e:
            return {"error": str(e)}

    async def _handle_computer_type(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            import pyautogui
            text = args["text"]
            interval = args.get("interval", 0.01)
            pyautogui.typewrite(text, interval=interval)
            return {"success": True, "chars_typed": len(text)}
        except ImportError:
            return {"error": "pyautogui not installed"}
        except Exception as e:
            return {"error": str(e)}

    # ── GitHub ──

    async def _handle_github_search_code(self, args: dict[str, Any]) -> dict[str, Any]:
        import httpx
        query = args["query"]
        lang = args.get("language", "")
        q = f"{query} language:{lang}" if lang else query
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.get(
                    "https://api.github.com/search/code",
                    params={"q": q, "per_page": 10},
                    headers={"Accept": "application/vnd.github.v3+json", "User-Agent": "OpenChimera/2.0"},
                )
                data = r.json()
                items = data.get("items", [])[:10]
                return {
                    "count": data.get("total_count", 0),
                    "items": [{"repo": i["repository"]["full_name"], "path": i["path"], "url": i["html_url"]} for i in items],
                }
        except Exception as e:
            return {"error": str(e)}

    async def _handle_github_read_repo(self, args: dict[str, Any]) -> dict[str, Any]:
        import httpx
        owner, repo = args["owner"], args["repo"]
        path = args.get("path", "")
        ref = args.get("ref", "main")
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
                r = await client.get(url, params={"ref": ref}, headers={"Accept": "application/vnd.github.v3+json", "User-Agent": "OpenChimera/2.0"})
                data = r.json()
                if isinstance(data, dict) and "content" in data:
                    import base64
                    content = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
                    return {"content": content, "path": path, "sha": data.get("sha")}
                return {"items": [{"name": i.get("name"), "type": i.get("type"), "path": i.get("path")} for i in data] if isinstance(data, list) else data}
        except Exception as e:
            return {"error": str(e)}

    # ── RAG ──

    async def _handle_rag_query(self, args: dict[str, Any]) -> dict[str, Any]:
        from openchimera.rag.engine import get_engine
        engine = get_engine()
        results = engine.query(args["query"], top_k=args.get("top_k", 5))
        return {"results": results, "query": args["query"]}

    async def _handle_rag_add_documents(self, args: dict[str, Any]) -> dict[str, Any]:
        from openchimera.rag.engine import get_engine
        engine = get_engine()
        texts = args["texts"]
        metadatas = args.get("metadatas")
        engine.add_documents(texts, metadatas)
        return {"added": len(texts), "status": "indexed"}

    # ── Cognitive / Godmode ──

    async def _handle_godmode_activate(self, args: dict[str, Any]) -> dict[str, Any]:
        """Activate godmode cognitive stack as a tool."""
        action = args["action"]
        from openchimera.cognitive.bridge import get_bridge
        bridge = get_bridge()

        if action == "recall":
            return await bridge.axiom_recall(args.get("query", ""))
        elif action == "verify":
            return await bridge.axiom_verify(args.get("query", ""))
        elif action == "predict_ux":
            return await bridge.eve_predict(args.get("query", ""))
        elif action == "read_genome":
            return await bridge.adam_read_genome()
        elif action == "store_memory":
            return await bridge.axiom_remember(
                text=args.get("content", ""),
                kind=args.get("kind", "conversation"),
            )
        return {"error": f"Unknown godmode action: {action}"}

    async def _handle_axiom_recall(self, args: dict[str, Any]) -> dict[str, Any]:
        from openchimera.cognitive.bridge import get_bridge
        return await get_bridge().axiom_recall(args.get("query", ""))

    async def _handle_axiom_remember(self, args: dict[str, Any]) -> dict[str, Any]:
        from openchimera.cognitive.bridge import get_bridge
        return await get_bridge().axiom_remember(
            text=args.get("text", ""),
            kind=args.get("kind", "conversation"),
            scope=args.get("scope", "personal"),
        )

    async def _handle_adam_read_genome(self, args: dict[str, Any]) -> dict[str, Any]:
        from openchimera.cognitive.bridge import get_bridge
        return await get_bridge().adam_read_genome()

    async def _handle_eve_predict_ux(self, args: dict[str, Any]) -> dict[str, Any]:
        from openchimera.cognitive.bridge import get_bridge
        return await get_bridge().eve_predict(args.get("feature", ""))

    # ── Web Search ──

    async def _handle_web_search(self, args: dict[str, Any]) -> dict[str, Any]:
        import httpx
        query = args["query"]
        limit = args.get("limit", 5)
        try:
            # DuckDuckGo HTML scraping as fallback search
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                r = await client.get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": query},
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                )
                from html.parser import HTMLParser

                class ResultParser(HTMLParser):
                    def __init__(self):
                        super().__init__()
                        self.results = []
                        self.in_result = False
                        self.current = {}
                        self._tag_stack = []

                    def handle_starttag(self, tag, attrs):
                        attrs_dict = dict(attrs)
                        if tag == "a" and "result__a" in attrs_dict.get("class", ""):
                            self.in_result = True
                            self.current = {"title": "", "url": attrs_dict.get("href", "")}
                        self._tag_stack.append(tag)

                    def handle_endtag(self, tag):
                        if self._tag_stack:
                            self._tag_stack.pop()
                        if tag == "a" and self.in_result and self.current:
                            self.results.append(self.current)
                            self.current = {}
                            self.in_result = False

                    def handle_data(self, data):
                        if self.in_result and self.current is not None:
                            self.current["title"] = self.current.get("title", "") + data.strip()

                parser = ResultParser()
                parser.feed(r.text)
                return {
                    "query": query,
                    "results": [{"title": r.get("title", ""), "url": r.get("url", "")} for r in parser.results[:limit]],
                }
        except Exception as e:
            return {"error": str(e), "query": query}

    # ── MCP ──

    async def _handle_mcp_list_tools(self, args: dict[str, Any]) -> dict[str, Any]:
        from openchimera.mcp.client import MCPClient
        client = MCPClient(command="echo", args=["mcp"])  # placeholder
        return {"note": "MCP server connection required. Configure in data/mcp_registry.json", "server": args.get("server_name")}

    async def _handle_mcp_call_tool(self, args: dict[str, Any]) -> dict[str, Any]:
        return {"note": "MCP tool call requires configured MCP server", "server": args.get("server_name"), "tool": args.get("tool_name")}
