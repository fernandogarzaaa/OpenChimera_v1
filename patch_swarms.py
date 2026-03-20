import os

def patch_swarm_v2():
    path = r'D:\openclaw\swarm_v2.py'
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()

    if 'token_optimizer_bridge' not in content:
        content = content.replace(
            'from typing import Any, Callable, Dict, Optional',
            'from typing import Any, Callable, Dict, Optional\nfrom token_optimizer_bridge import optimize_context'
        )

        content = content.replace(
            'current_context = context or {}',
            'current_context = optimize_context(context or {}, token_threshold=4000)'
        )

        content = content.replace(
            'current_context = {"compressed_output": output, "compression_ratio": 0.2}',
            'current_context = {"last_agent_output": output}\n            current_context = optimize_context(current_context, token_threshold=4000)'
        )

        content = content.replace(
            'async def _execute_parallel(self, task: str, context: dict) -> dict:\n',
            'async def _execute_parallel(self, task: str, context: dict) -> dict:\n        context = optimize_context(context or {}, token_threshold=4000)\n'
        )

        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        print("Patched swarm_v2.py")
    else:
        print("swarm_v2.py already patched")

def patch_swarm_v3():
    path = r'D:\openclaw\swarm_v3.py'
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()

    if 'token_optimizer_bridge' not in content:
        content = content.replace(
            'from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union',
            'from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union\nfrom token_optimizer_bridge import optimize_context'
        )

        content = content.replace(
            'async def _execute_sequential(self, tasks: List[Task], context: Dict[str, Any]) -> Dict[str, Any]:\n        """Execute tasks in sequence, passing context forward"""\n        results = {}\n        current_context = context.copy()',
            'async def _execute_sequential(self, tasks: List[Task], context: Dict[str, Any]) -> Dict[str, Any]:\n        """Execute tasks in sequence, passing context forward"""\n        results = {}\n        current_context = context.copy()\n        current_context = optimize_context(current_context, token_threshold=4000)'
        )
        
        content = content.replace(
            'current_context[f"result_{task.task_id}"] = result["result"]',
            'current_context[f"result_{task.task_id}"] = result["result"]\n            current_context = optimize_context(current_context, token_threshold=4000)'
        )

        content = content.replace(
            'async def _execute_parallel(self, tasks: List[Task], context: Dict[str, Any]) -> Dict[str, Any]:\n        """Execute tasks in parallel"""',
            'async def _execute_parallel(self, tasks: List[Task], context: Dict[str, Any]) -> Dict[str, Any]:\n        """Execute tasks in parallel"""\n        context = optimize_context(context, token_threshold=4000)'
        )

        content = content.replace(
            'async def execute(self, task: Task, context: Dict[str, Any]) -> Any:\n        """Execute task with this agent"""',
            'async def execute(self, task: Task, context: Dict[str, Any]) -> Any:\n        """Execute task with this agent"""\n        context = optimize_context(context, token_threshold=4000)'
        )

        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        print("Patched swarm_v3.py")
    else:
        print("swarm_v3.py already patched")

if __name__ == "__main__":
    patch_swarm_v2()
    patch_swarm_v3()
