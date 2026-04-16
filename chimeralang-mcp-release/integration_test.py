"""Integration test — call every one of the 12 MCP tools and verify output."""
import asyncio
import json
import sys

from chimeralang_mcp import server as srv


async def run() -> None:
    # Collect registered tools via the list_tools handler
    list_handler = srv.server.request_handlers
    # The MCP server stores handlers internally; the @list_tools decorator
    # registers under ListToolsRequest. Simpler: just call our function.
    # We can access the original functions through the module globals.
    # `list_tools` is not kept as a module-level name after decoration; call
    # the handler registered with the server.

    # Retrieve via server.list_tools() coroutine — the decorator keeps the
    # underlying fn in the registered handler map.
    from mcp.types import ListToolsRequest
    handler = srv.server.request_handlers[ListToolsRequest]
    # The handler wraps our coroutine; its signature expects a request object.
    # Easiest path: reach into closure / walk tools by invoking call_tool
    # directly with known names.

    tool_names = [
        "chimera_run",
        "chimera_confident",
        "chimera_explore",
        "chimera_gate",
        "chimera_detect",
        "chimera_constrain",
        "chimera_typecheck",
        "chimera_prove",
        "chimera_audit",
        "chimera_compress",
        "chimera_optimize",
        "chimera_fracture",
    ]

    # Get underlying call_tool coroutine (wraps the @server.call_tool handler)
    from mcp.types import CallToolRequest
    call_handler = srv.server.request_handlers[CallToolRequest]

    async def call(name: str, args: dict) -> dict:
        # Synthesize a CallToolRequest
        req = CallToolRequest(
            method="tools/call",
            params={"name": name, "arguments": args},
        )
        result = await call_handler(req)
        # ServerResult wraps CallToolResult
        inner = result.root if hasattr(result, "root") else result
        return inner

    test_cases = {
        "chimera_run": {
            "source": 'val x: Confident<Text> = confident("paris", 0.97)\nemit x\n',
        },
        "chimera_confident": {"value": "paris", "confidence": 0.97, "label": "capital"},
        "chimera_explore":   {"value": "maybe dark matter", "confidence": 0.3},
        "chimera_gate": {
            "candidates": [
                {"value": "paris", "confidence": 0.9},
                {"value": "paris", "confidence": 0.85},
                {"value": "london", "confidence": 0.4},
            ],
            "strategy": "weighted_vote",
            "threshold": 0.7,
        },
        "chimera_detect": {
            "value": 42.0,
            "confidence": 0.9,
            "strategy": "range",
            "params": {"valid_range": [0, 100]},
        },
        "chimera_constrain": {
            "tool_name": "search",
            "output": "The capital of France is Paris.",
            "input_confidence": 0.9,
            "min_confidence": 0.5,
            "detect_strategy": "confidence_threshold",
            "detect_threshold": 0.5,
        },
        "chimera_typecheck": {
            "source": 'val x: Confident<Text> = confident("hello", 0.96)\n',
        },
        "chimera_prove": {
            "source": 'val x: Confident<Text> = confident("proof", 0.99)\nemit x\n',
        },
        "chimera_audit": {},
        "chimera_compress": {
            "messages": [
                {"role": "user", "content": "Tell me about compression. " * 500},
                {"role": "assistant", "content": "Compression reduces size. " * 500},
                {"role": "user", "content": "How does it work? " * 500},
            ],
            "query": "compression",
            "max_tokens": 500,
        },
        "chimera_optimize": {
            "text": (
                "class TokenFracture:\n"
                "    def __init__(self, budget):\n"
                "        self.budget = budget\n"
                "    def compress(self, messages):\n"
                "        return truncate(messages)\n"
                "\n"
                "CONSTANT_MAX = 100\n"
                "The TokenFracture system uses aggressive optimization. "
                "Compression ratios are adjustable. Memory budgets should be respected.\n"
            ) * 20,
            "target_ratio": 0.1,
        },
        "chimera_fracture": {
            "messages": [
                {"role": "user", "content": "Explain token compression. " * 200},
                {"role": "assistant", "content": "Token compression works via proportional truncation. " * 200},
            ],
            "documents": [
                "class Foo: def bar(self): pass\n" * 50,
                "The UniverseService handles cosmic events. " * 50,
            ],
            "query": "token compression",
            "token_budget": 800,
            "optimize_ratio": 0.1,
        },
    }

    passed = 0
    failed = 0
    failures: list[str] = []

    for name in tool_names:
        args = test_cases[name]
        try:
            result = await call(name, args)
            # result is CallToolResult
            is_error = getattr(result, "isError", False)
            text = result.content[0].text if result.content else ""
            payload = json.loads(text) if text else {}

            if is_error:
                failed += 1
                failures.append(f"{name}: isError=True — {payload}")
                print(f"[FAIL] {name}: {payload}")
                continue

            # Tool-specific validation
            ok = True
            reason = ""
            if name == "chimera_run":
                ok = "emitted" in payload and isinstance(payload["emitted"], list)
                reason = "expected emitted[]"
            elif name == "chimera_confident":
                ok = payload.get("passed") is True and payload.get("confidence") == 0.97
                reason = "expected passed=True"
            elif name == "chimera_explore":
                ok = payload.get("type") == "ExploreValue"
                reason = "expected type=ExploreValue"
            elif name == "chimera_gate":
                ok = payload.get("value") == "paris" and payload.get("passed") is True
                reason = "expected winner=paris passed=True"
            elif name == "chimera_detect":
                ok = payload.get("passed") is True and payload.get("flag_count") == 0
                reason = "expected passed=True, no flags"
            elif name == "chimera_constrain":
                ok = "tool_name" in payload and payload["tool_name"] == "search"
                reason = "expected tool_name=search"
            elif name == "chimera_typecheck":
                ok = "ok" in payload
                reason = "expected 'ok' key"
            elif name == "chimera_prove":
                ok = "proof" in payload and payload["proof"].get("root_hash")
                reason = "expected proof.root_hash"
            elif name == "chimera_audit":
                ok = "recent_calls" in payload
                reason = "expected recent_calls"
            elif name == "chimera_compress":
                ok = (
                    "compressed_messages" in payload
                    and "stats" in payload
                    and payload["stats"]["compressed_tokens"] <= payload["stats"]["target_max_tokens"] + 50
                )
                reason = "expected compressed under budget"
            elif name == "chimera_optimize":
                ok = (
                    "optimized_text" in payload
                    and payload["original_chars"] > payload["optimized_chars"]
                    and payload["reduction_percent"] > 50
                )
                reason = "expected reduction > 50%"
            elif name == "chimera_fracture":
                ok = (
                    "compressed_messages" in payload
                    and "optimized_documents" in payload
                    and len(payload["optimized_documents"]) == 2
                    and "quality_passed" in payload
                    and "compression_stats" in payload
                )
                reason = "expected full fracture shape"

            if ok:
                passed += 1
                print(f"[PASS] {name}")
            else:
                failed += 1
                failures.append(f"{name}: {reason} — got {json.dumps(payload)[:200]}")
                print(f"[FAIL] {name}: {reason}")
                print(f"       payload: {json.dumps(payload)[:400]}")
        except Exception as e:
            failed += 1
            failures.append(f"{name}: exception {type(e).__name__}: {e}")
            print(f"[ERR]  {name}: {type(e).__name__}: {e}")

    print()
    print(f"Result: {passed}/{len(tool_names)} tools passed")
    if failures:
        print("Failures:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run())
