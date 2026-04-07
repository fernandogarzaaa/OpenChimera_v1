"""SwarmAgent — an individual agent entity within a swarm."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, List, Literal, Optional


AgentStatus = Literal["idle", "active", "done", "failed"]

log = logging.getLogger(__name__)

# Type alias for the optional real-LLM callback injected at runtime.
# Signature: (messages, model, max_tokens, temperature) -> dict
LLMCallback = Optional[Callable[..., dict[str, Any]]]


def _build_agent_prompt(role: str, description: str, capabilities: List[str], task: str, context: dict) -> list[dict[str, str]]:
    """Build a structured message list for the agent's LLM invocation."""
    system_content = (
        f"You are {role}. {description}\n"
        f"Capabilities: {', '.join(capabilities) if capabilities else 'general'}.\n"
        "Respond concisely and directly to the task. "
        "Do not repeat the task description in your answer."
    )
    messages: list[dict[str, str]] = [{"role": "system", "content": system_content}]

    # Inject any shared context from the orchestrator
    if context:
        ctx_lines = [f"{k}: {str(v)[:200]}" for k, v in context.items() if v]
        if ctx_lines:
            messages.append({"role": "system", "content": "Context:\n" + "\n".join(ctx_lines)})

    messages.append({"role": "user", "content": task})
    return messages


@dataclass
class SwarmAgent:
    """Represents a single swarm agent with identity, role, and execute capability.

    When *llm_callback* is provided it is used to run a real LLM completion
    for the agent's task.  Without it the agent falls back to the original
    deterministic offline stub so that all existing tests remain unaffected.

    The callback must accept the keyword arguments that
    ``OpenChimeraProvider.chat_completion`` accepts::

        callback(messages=[...], model="openchimera-local", max_tokens=512, temperature=0.7, stream=False)

    and return an OpenAI-compatible completion dict.
    """

    agent_id: str
    role: str
    description: str
    capabilities: List[str] = field(default_factory=list)
    status: AgentStatus = "idle"
    llm_callback: LLMCallback = field(default=None, repr=False, compare=False)

    async def execute(self, task: str, context: dict | None = None) -> str:
        """Execute the agent's task.

        If an LLM callback has been bound, the task is sent to the real model
        using a role-specific system prompt.  Otherwise, the deterministic
        offline stub is used (preserves backward-compatibility).
        """
        self.status = "active"
        ctx = context or {}

        try:
            if self.llm_callback is not None:
                result = await self._execute_with_llm(task, ctx)
            else:
                result = await self._execute_offline(task)
        except Exception as exc:
            log.warning("[SwarmAgent:%s] execute failed: %s", self.agent_id, exc)
            self.status = "failed"
            return f"[{self.role}] error: {exc}"

        self.status = "done"
        return result

    async def _execute_with_llm(self, task: str, context: dict) -> str:
        """Run the task through the bound LLM callback."""
        messages = _build_agent_prompt(
            role=self.role,
            description=self.description,
            capabilities=self.capabilities,
            task=task,
            context=context,
        )
        loop = asyncio.get_event_loop()
        # The callback is synchronous; run it in the executor to stay non-blocking
        completion = await loop.run_in_executor(
            None,
            lambda: self.llm_callback(  # type: ignore[misc]
                messages=messages,
                model="openchimera-local",
                max_tokens=512,
                temperature=0.7,
                stream=False,
            ),
        )
        content = str(
            completion.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        ).strip()
        return content or f"{self.role} completed: {task[:50]}"

    async def _execute_offline(self, task: str) -> str:
        """Deterministic offline stub — yields control then returns a fixed string."""
        await asyncio.sleep(0)
        return f"{self.role} completed: {task[:50]}"

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "role": self.role,
            "description": self.description,
            "capabilities": list(self.capabilities),
            "status": self.status,
            "llm_bound": self.llm_callback is not None,
        }
