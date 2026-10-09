# CHIMERA_HARNESS: hook_pipeline
"""Hook middleware for intercepting OpenChimera tool execution."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Callable, Literal, TypeAlias

log = logging.getLogger(__name__)

HookAction = Literal["pass", "block", "mutate"]
PreToolHook: TypeAlias = Callable[[str, dict[str, Any]], "HookResult | None"]
PostToolHook: TypeAlias = Callable[[str, dict[str, Any], dict[str, Any]], "HookResult | None"]


@dataclass(frozen=True)
class HookResult:
    """Represents a hook decision for a tool dispatch step."""

    action: HookAction = "pass"
    mutated_input: dict[str, Any] | None = None
    reason: str | None = None


class HookPipeline:
    """Coordinates pre-tool and post-tool middleware for OpenChimera."""

    def __init__(self) -> None:
        self._pre_hooks: list[PreToolHook] = []
        self._post_hooks: list[PostToolHook] = []
        self._lock = threading.RLock()

    def register_pre_tool(self, hook_fn: PreToolHook) -> None:
        """Register a hook that can inspect, block, or mutate tool input."""

        with self._lock:
            self._pre_hooks.append(hook_fn)

    def register_post_tool(self, hook_fn: PostToolHook) -> None:
        """Register a hook that can inspect or mutate the result envelope."""

        with self._lock:
            self._post_hooks.append(hook_fn)

    def execute_pre(self, tool_name: str, tool_input: dict[str, Any] | None) -> HookResult:
        """Run pre-tool hooks in order, applying mutations cumulatively."""

        current_input = dict(tool_input or {})
        mutated = False
        last_reason: str | None = None

        for hook_fn in self._snapshot_pre_hooks():
            try:
                hook_result = self._normalize_result(hook_fn(tool_name, dict(current_input)))
            except Exception as exc:
                reason = f"pre-hook {self._describe_hook(hook_fn)} failed: {exc}"
                log.warning("[HookPipeline] %s", reason)
                return HookResult(action="block", reason=reason)

            if hook_result is None or hook_result.action == "pass":
                if hook_result is not None and hook_result.reason:
                    last_reason = hook_result.reason
                continue
            if hook_result.action == "block":
                return HookResult(action="block", reason=hook_result.reason)
            if hook_result.mutated_input is not None:
                current_input = dict(hook_result.mutated_input)
            mutated = True
            if hook_result.reason:
                last_reason = hook_result.reason

        if mutated:
            return HookResult(action="mutate", mutated_input=current_input, reason=last_reason)
        return HookResult(action="pass", reason=last_reason)

    def execute_post(
        self,
        tool_name: str,
        tool_input: dict[str, Any] | None,
        tool_result: dict[str, Any] | None,
    ) -> HookResult:
        """Run post-tool hooks in order, applying result mutations cumulatively."""

        current_input = dict(tool_input or {})
        current_result = dict(tool_result or {})
        mutated = False
        last_reason: str | None = None

        for hook_fn in self._snapshot_post_hooks():
            try:
                hook_result = self._normalize_result(
                    hook_fn(tool_name, dict(current_input), dict(current_result))
                )
            except Exception as exc:
                log.warning(
                    "[HookPipeline] post-hook %s failed: %s",
                    self._describe_hook(hook_fn),
                    exc,
                )
                continue

            if hook_result is None or hook_result.action == "pass":
                if hook_result is not None and hook_result.reason:
                    last_reason = hook_result.reason
                continue
            if hook_result.action == "block":
                log.warning(
                    "[HookPipeline] post-hook %s attempted to block tool %s; ignoring",
                    self._describe_hook(hook_fn),
                    tool_name,
                )
                continue
            if hook_result.mutated_input is not None:
                current_result = dict(hook_result.mutated_input)
            mutated = True
            if hook_result.reason:
                last_reason = hook_result.reason

        if mutated:
            return HookResult(action="mutate", mutated_input=current_result, reason=last_reason)
        return HookResult(action="pass", reason=last_reason)

    def _snapshot_pre_hooks(self) -> tuple[PreToolHook, ...]:
        with self._lock:
            return tuple(self._pre_hooks)

    def _snapshot_post_hooks(self) -> tuple[PostToolHook, ...]:
        with self._lock:
            return tuple(self._post_hooks)

    def _normalize_result(self, hook_result: HookResult | None) -> HookResult | None:
        if hook_result is None:
            return None
        if not isinstance(hook_result, HookResult):
            raise TypeError("Hook functions must return HookResult or None")
        return hook_result

    def _describe_hook(self, hook_fn: Callable[..., Any]) -> str:
        return getattr(hook_fn, "__name__", hook_fn.__class__.__name__)
