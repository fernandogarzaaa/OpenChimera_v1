"""Agent orchestrator."""

import uuid
from typing import Any

from openchimera.providers.manager import ProviderManager
from openchimera.tools.registry import ToolRegistry


class AgentOrchestrator:
    def __init__(self, providers: ProviderManager, tools: ToolRegistry) -> None:
        self.providers = providers
        self.tools = tools
        self._agents: dict[str, dict[str, Any]] = {}

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
            "prompt_preview": prompt[:80],
            "created_at": None,
            "completed_at": None,
            "result_preview": None,
        }
        self._agents[agent_id] = agent
        return agent

    async def query(self, text: str, provider: str | None, model: str | None, execute_tools: bool) -> dict[str, Any]:
        prov = self.providers.get(provider) if provider else self.providers.get_default()
        if not prov:
            return {"session_id": str(uuid.uuid4()), "text": "No provider available", "provider": "none", "model": "none", "tools": []}
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
        result = await prov.chat(messages, model=model, tools=tool_schemas if tool_schemas else None)
        tools_executed = []
        for tc in result.get("tool_calls", []):
            if isinstance(tc, dict):
                fn = tc.get("function", {})
                tid = fn.get("name") or tc.get("name", "")
                args = fn.get("arguments", {})
                if isinstance(args, str):
                    import json
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}
                await self.tools.execute(tid, args)
                tools_executed.append(tid)
        return {
            "session_id": str(uuid.uuid4()),
            "text": result.get("text", ""),
            "provider": prov.name,
            "model": model or prov.default_model,
            "tools": tools_executed,
        }
