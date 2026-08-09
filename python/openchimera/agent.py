"""Agent orchestrator with full tool execution loop."""

from __future__ import annotations

import uuid
from typing import Any

from openchimera.providers.manager import ProviderManager
from openchimera.tools.registry import ToolRegistry


class AgentOrchestrator:
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

        prov = self.providers.get(provider) if provider else self.providers.get_default()
        if not prov:
            return {
                "session_id": session_id,
                "text": "No provider available. Run `openchimera onboard` to configure providers.",
                "provider": "none",
                "model": "none",
                "tools": [],
            }

        messages = [{"role": "user", "content": text}]
        tool_schemas = []

        if execute_tools:
            for t in self.tools.list_tools():
                schema = t.get("schema", {})
                tool_schemas.append({
                    "type": "function",
                    "function": {
                        "name": t["id"],
                        "description": t["description"],
                        "parameters": schema,
                    },
                })

        result = await prov.chat(
            messages,
            model=model,
            tools=tool_schemas if tool_schemas else None,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        tools_executed = []
        for tc in result.get("tool_calls", []):
            if isinstance(tc, dict):
                fn = tc.get("function", {})
                tid = fn.get("name") or tc.get("name", "")
                args = fn.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}
                tool_result = await self.tools.execute(tid, args)
                tools_executed.append({"tool": tid, "result": tool_result})

        return {
            "session_id": session_id,
            "text": result.get("text", ""),
            "provider": prov.name,
            "model": model or prov.default_model,
            "tools": [t["tool"] for t in tools_executed],
            "tool_results": tools_executed,
            "usage": result.get("usage"),
        }


import json  # noqa: E402
