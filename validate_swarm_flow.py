import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from swarm_v2 import ProcessMode, SwarmOrchestrator


async def analyst(task, context, previous_results):
    return {
        "step": "analyst",
        "message": f"Analyst: received context {context}",
        "task": task,
    }


async def coder(task, context, previous_results):
    return {
        "step": "coder",
        "message": f"Coder: received context {context}",
        "task": task,
    }


async def reviewer(task, context, previous_results):
    return {
        "step": "reviewer",
        "message": f"Reviewer: received context {context}",
        "task": task,
    }


async def main():
    swarm = SwarmOrchestrator("validate-swarm-flow", ProcessMode.SEQUENTIAL)

    swarm.register_agent("analyst", "Analyst", analyst)
    swarm.register_agent("coder", "Coder", coder)
    swarm.register_agent("reviewer", "Reviewer", reviewer)

    swarm.set_handoff("analyst", "coder")
    swarm.set_handoff("coder", "reviewer")

    final_results = await swarm.execute_task("validate handoff flow", {})
    print(json.dumps(final_results, indent=2))


if __name__ == "__main__":
    asyncio.run(main())