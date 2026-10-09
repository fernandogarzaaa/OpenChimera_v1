# CHIMERA_HARNESS: hook_pipeline_tests
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from pydantic import BaseModel, ConfigDict

from core.tool_runtime import RuntimeToolRegistry, RuntimeToolSpec, ToolMetadata, ToolRegistry
from services.hook_pipeline import HookPipeline, HookResult


class StrictToolInput(BaseModel):
    """Strict schema used to verify hook mutation before validation."""

    model_config = ConfigDict(strict=True)

    count: int


class TestHookPipeline(unittest.TestCase):
    """Validates the standalone hook middleware behavior."""

    def test_execute_pre_applies_mutations_in_order(self):
        pipeline = HookPipeline()

        def add_one(tool_name: str, tool_input: dict[str, int]) -> HookResult:
            return HookResult(action="mutate", mutated_input={"value": tool_input["value"] + 1})

        def double(tool_name: str, tool_input: dict[str, int]) -> HookResult:
            return HookResult(action="mutate", mutated_input={"value": tool_input["value"] * 2})

        pipeline.register_pre_tool(add_one)
        pipeline.register_pre_tool(double)

        result = pipeline.execute_pre("calc", {"value": 3})

        self.assertEqual(result.action, "mutate")
        self.assertEqual(result.mutated_input, {"value": 8})

    def test_execute_pre_blocks_later_hooks(self):
        pipeline = HookPipeline()
        calls: list[str] = []

        def block(tool_name: str, tool_input: dict[str, object]) -> HookResult:
            calls.append("block")
            return HookResult(action="block", reason="blocked")

        def never_runs(tool_name: str, tool_input: dict[str, object]) -> HookResult:
            calls.append("mutate")
            return HookResult(action="mutate", mutated_input={"mutated": True})

        pipeline.register_pre_tool(block)
        pipeline.register_pre_tool(never_runs)

        result = pipeline.execute_pre("dangerous", {"value": 1})

        self.assertEqual(result.action, "block")
        self.assertEqual(result.reason, "blocked")
        self.assertEqual(calls, ["block"])


class TestToolRegistryHooks(unittest.TestCase):
    """Verifies hook integration for ToolMetadata-based execution."""

    def test_pre_hook_can_block_metadata_tool(self):
        pipeline = HookPipeline()
        pipeline.register_pre_tool(
            lambda tool_name, tool_input: HookResult(action="block", reason="disabled")
        )

        handler = MagicMock(return_value={"ok": True})
        registry = ToolRegistry(hook_pipeline=pipeline)
        registry.register(ToolMetadata(name="safe.tool", description="test", handler=handler))

        result = registry.execute("safe.tool", {"value": 1})

        self.assertFalse(result.success)
        self.assertIn("disabled", str(result.error))
        handler.assert_not_called()

    def test_post_hook_can_mutate_metadata_tool_result(self):
        pipeline = HookPipeline()

        def rewrite_result(
            tool_name: str,
            tool_input: dict[str, object],
            tool_result: dict[str, object],
        ) -> HookResult:
            return HookResult(
                action="mutate",
                mutated_input={
                    "output": {"status": "hooked"},
                    "metadata": {"hooked": True},
                },
            )

        pipeline.register_post_tool(rewrite_result)

        registry = ToolRegistry(hook_pipeline=pipeline)
        registry.register(
            ToolMetadata(name="echo", description="test", handler=lambda arguments: {"status": "original"})
        )

        result = registry.execute("echo", {"value": 1})

        self.assertTrue(result.success)
        self.assertEqual(result.output, {"status": "hooked"})
        self.assertEqual(result.metadata, {"hooked": True})


class TestRuntimeToolRegistryHooks(unittest.TestCase):
    """Verifies hook integration for validated runtime tool execution."""

    def _make_runtime_registry(self, pipeline: HookPipeline) -> RuntimeToolRegistry:
        cap_reg = MagicMock()
        cap_reg.list_kind.return_value = [
            {
                "id": "strict.tool",
                "kind": "tool",
                "name": "strict.tool",
                "description": "strict",
                "category": "test",
            }
        ]
        return RuntimeToolRegistry(
            capability_registry=cap_reg,
            bus=MagicMock(),
            hook_pipeline=pipeline,
            specs=[
                RuntimeToolSpec(
                    tool_id="strict.tool",
                    name="Strict Tool",
                    description="strict schema tool",
                    schema=StrictToolInput,
                    executor=lambda arguments: {"count": arguments["count"]},
                    category="test",
                )
            ],
        )

    def test_pre_hook_can_mutate_runtime_tool_input_before_validation(self):
        pipeline = HookPipeline()

        def coerce_count(tool_name: str, tool_input: dict[str, object]) -> HookResult:
            return HookResult(
                action="mutate",
                mutated_input={"count": int(str(tool_input["count"]))},
            )

        pipeline.register_pre_tool(coerce_count)
        registry = self._make_runtime_registry(pipeline)

        result = registry.execute("strict.tool", {"count": "3"})

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"], {"count": 3})
        self.assertEqual(result["arguments"], {"count": 3})

    def test_post_hook_can_mutate_runtime_tool_result(self):
        pipeline = HookPipeline()
        pipeline.register_post_tool(
            lambda tool_name, tool_input, tool_result: HookResult(
                action="mutate",
                mutated_input={"result": {"status": "mutated"}},
            )
        )
        registry = self._make_runtime_registry(pipeline)

        result = registry.execute("strict.tool", {"count": 2})

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["result"], {"status": "mutated"})


if __name__ == "__main__":
    unittest.main()
