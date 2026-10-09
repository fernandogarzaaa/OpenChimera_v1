"""Agent orchestrator with full tool execution loop."""

from __future__ import annotations

import uuid
from typing import Any

from openchimera.providers.manager import ProviderManager
from openchimera.tools.registry import ToolRegistry


class AgentOrchestrator:
    MAX_TOOL_ROUNDS = 4

    def __init__(self, providers: ProviderManager, tools: ToolRegistry) -> None:
        self.providers = providers
        self.tools = tools
        self._agents: dict[str, dict[str, Any]] = {}
        self._session_counter = 0

    def list_agents(self) -> list[dict[str, Any]]:
        return list(self._agents.values())

    async def spawn_agent(self, name: str, prompt: str) -> dict[str, Any]:
        agent_id = f"agent-{uuid.uuid4().hex[:8]}"
        agent = {
            "id": agent_id,
            "name": name,
            "status": "queued",
            "provider": self.providers.settings.providers.default,
            "model": self.providers.get_default().default_model,
            "prompt_preview": prompt[:120],
            "created_at": None,
            "completed_at": None,
            "result_preview": None,
        }
        self._agents[agent_id] = agent
        return agent

    async def query(
        self,
        text: str,
        provider: str | None,
        model: str | None,
        execute_tools: bool,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        self._session_counter += 1
        session_id = f"sess-{uuid.uuid4().hex[:8]}"

        try:
            prov = self.providers.get(provider) if provider else self.providers.get_default()
        except RuntimeError:
            prov = None
        if not prov:
            return {
                "session_id": session_id,
                "text": "No provider available. Run `openchimera onboard` to configure providers.",
                "provider": "none",
                "model": "none",
                "tools": [],
            }

        messages: list[dict[str, Any]] = [{"role": "user", "content": text}]
        tool_schemas: list[dict[str, Any]] = []
        # OpenAI-style function names must match ^[a-zA-Z0-9_-]{1,64}$, so the
        # dotted registry ids (``file.read``) are sent as ``file__read`` and
        # mapped back when the model calls them.
        name_map: dict[str, str] = {}

        if execute_tools:
            for t in self.tools.list_tools():
                schema = t.get("schema") or {"type": "object", "properties": {}}
                wire_name = _wire_tool_name(t["id"])
                name_map[wire_name] = t["id"]
                tool_schemas.append({
                    "type": "function",
                    "function": {
                        "name": wire_name,
                        "description": t["description"],
                        "parameters": schema,
                    },
                })

        tools_executed: list[dict[str, Any]] = []
        usage: Any = None
        result: dict[str, Any] = {}
        # Tool-result follow-up turns use the OpenAI message format, which only
        # OpenAI-compatible providers accept; others keep single-shot behaviour.
        can_loop = bool(tool_schemas) and _speaks_openai_tool_messages(prov)
        max_rounds = self.MAX_TOOL_ROUNDS if can_loop else 1

        for _round in range(max_rounds):
            result = await prov.chat(
                messages,
                model=model,
                tools=tool_schemas if tool_schemas else None,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            usage = result.get("usage", usage)
            calls = [tc for tc in result.get("tool_calls", []) or [] if isinstance(tc, dict)]
            if not calls:
                break

            round_outputs: list[tuple[str, str, str, Any]] = []
            for idx, tc in enumerate(calls):
                fn = tc.get("function", {}) or {}
                wire = fn.get("name") or tc.get("name", "")
                tid = name_map.get(wire, wire)
                args = fn.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args) if args.strip() else {}
                    except Exception:
                        args = {}
                if not isinstance(args, dict):
                    args = {}
                tool_result = await self.tools.execute(tid, args)
                tools_executed.append({"tool": tid, "arguments": args, "result": tool_result})
                round_outputs.append((tc.get("id") or f"call_{_round}_{idx}", wire, json.dumps(args), tool_result))

            if not can_loop:
                break
            messages.append({
                "role": "assistant",
                "content": result.get("text") or None,
                "tool_calls": [
                    {"id": call_id, "type": "function", "function": {"name": wire, "arguments": args_json}}
                    for call_id, wire, args_json, _res in round_outputs
                ],
            })
            for call_id, _wire, _args, tool_result in round_outputs:
                messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": _truncate(json.dumps(tool_result, default=str)),
                })

        return {
            "session_id": session_id,
            "text": result.get("text", ""),
            "provider": prov.name,
            "model": model or prov.default_model,
            "tools": [t["tool"] for t in tools_executed],
            "tool_results": tools_executed,
            "usage": usage,
        }


def _wire_tool_name(tool_id: str) -> str:
    return tool_id.replace(".", "__")[:64]


def _truncate(text: str, limit: int = 8000) -> str:
    return text if len(text) <= limit else text[:limit] + "...[truncated]"


def _speaks_openai_tool_messages(provider: Any) -> bool:
    from openchimera.providers.manager import OpenAICompatibleProvider

    return isinstance(provider, OpenAICompatibleProvider)


import json  # noqa: E402
