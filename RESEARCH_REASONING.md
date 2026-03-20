# RESEARCH_REASONING.md - ToT Implementation for Project Evo

## Tree-of-Thought (ToT) Reasoning for Coding Agents

### Overview
ToT generalizes Chain-of-Thought by allowing agents to explore multiple reasoning paths. In the context of code generation (Project Evo), this enables the orchestrator to look ahead, evaluate the viability of a refactor or fix *before* committing to it, and backtrack if a path hits a dead end (e.g., circular dependencies or failing tests).

### ToT Mechanics
1. **Thought Decomposition**: The coding task is split into "reasoning blocks" (e.g., Analyze → Propose Architecture → Write Test → Implement → Validate).
2. **State Evaluation (Critic Model)**: A lightweight secondary agent evaluates candidates. Metrics:
    - *Syntax validity* (linting)
    - *Type consistency* (static analysis)
    - *Dependency health*
3. **Search Strategy**: 
    - **Breadth-First Search (BFS)**: Ideal for exploring multiple valid approaches to a feature.
    - **A* Search**: Use a heuristic (e.g., "number of unresolved imports") to prioritize the most promising branches.

---

### Prototype: ToT Orchestrator (Python Strategy)

This structure provides a framework for an agent orchestrator to manage search branches.

```python
import abc
import heapq
from typing import List, Any

class CodeState:
    """Representation of the workspace at a specific point in the ToT."""
    def __init__(self, code_diff: str, context: dict, score: float):
        self.code_diff = code_diff
        self.context = context
        self.score = score  # Heuristic score for priority queue

    def __lt__(self, other):
        return self.score > other.score # Max-heap for best-first search

class ToTPlanner:
    def __init__(self, model_agent):
        self.agent = model_agent
        self.queue = []

    def propose_thoughts(self, current_state: CodeState) -> List[CodeState]:
        """Ask LLM for N possible next steps."""
        proposals = self.agent.generate_next_steps(current_state)
        return [CodeState(p['diff'], p['context'], p['eval_score']) for p in proposals]

    def solve(self, initial_state: CodeState, max_depth=3):
        heapq.heappush(self.queue, initial_state)
        
        while self.queue:
            current = heapq.heappop(self.queue)
            
            # Evaluate path
            if self.is_goal(current):
                return current
            
            # Branching
            thoughts = self.propose_thoughts(current)
            for t in thoughts:
                heapq.heappush(self.queue, t)
        
        return None

    def is_goal(self, state: CodeState) -> bool:
        # Check against success criteria (e.g., tests passed)
        return False
```

### Findings
- **Integration**: Project Evo's orchestrator should treat its `agent_pool` as the thought generator and a `testing_suite` as the evaluation engine.
- **Challenges**:
    - **Token Overhead**: Generating multiple branches is expensive. 
    - **State Forking**: Branching in a filesystem requires local git staging or temporary virtual environments.
- **Recommendation**: Begin implementation by using `git worktree` or temporary branch switching as the mechanism for "state forking" in the orchestrator.
