"""
SWARM V3 - Quantum-Enhanced Multi-Agent Orchestration
======================================================
Integrates:
- LangGraph checkpoint patterns for state persistence
- crewAI task delegation logic
- Quantum optimization for agent selection
- Hierarchical/Parallel/Sequential execution modes

Usage:
    from swarm_v3 import SwarmV3, ExecutionMode, TaskDelegation
    
    swarm = SwarmV3("my-swarm", ExecutionMode.HIERARCHICAL)
    swarm.register_agent("researcher", research_handler)
    swarm.register_agent("writer", write_handler)
    
    result = await swarm.execute(task="Write a report on AI", context={})
"""
from __future__ import annotations

import asyncio
import json
import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union
from token_optimizer_bridge import optimize_context
from contextlib import asynccontextmanager


class ExecutionMode(Enum):
    """Execution modes inspired by LangGraph's graph types"""
    SEQUENTIAL = auto()      # Linear chain: A → B → C
    PARALLEL = auto()        # Fan-out: A → [B, C, D]
    HIERARCHICAL = auto()    # Tree structure with manager
    CONDITIONAL = auto()     # Dynamic routing based on state
    MAP_REDUCE = auto()      # Split task, process in parallel, aggregate


class TaskPriority(Enum):
    """Task priority levels from crewAI"""
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4


@dataclass
class Checkpoint:
    """
    LangGraph-style checkpoint for state persistence
    Allows resuming from any point in execution
    """
    checkpoint_id: str
    thread_id: str
    agent_id: Optional[str]
    state: Dict[str, Any]
    metadata: Dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.now)
    parent_checkpoint: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "thread_id": self.thread_id,
            "agent_id": self.agent_id,
            "state": self.state,
            "metadata": self.metadata,
            "timestamp": self.timestamp.isoformat(),
            "parent_checkpoint": self.parent_checkpoint
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Checkpoint":
        return cls(
            checkpoint_id=data["checkpoint_id"],
            thread_id=data["thread_id"],
            agent_id=data.get("agent_id"),
            state=data["state"],
            metadata=data["metadata"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            parent_checkpoint=data.get("parent_checkpoint")
        )


class CheckpointManager:
    """
    Manages checkpoints for state persistence
    Inspired by LangGraph's checkpointing system
    """
    def __init__(self, storage_path: Optional[Path] = None):
        self.storage_path = storage_path or Path("swarm_checkpoints")
        self.memory_checkpoints: Dict[str, List[Checkpoint]] = {}
        self._ensure_storage()
    
    def _ensure_storage(self):
        if self.storage_path:
            self.storage_path.mkdir(parents=True, exist_ok=True)
    
    def _generate_id(self, data: str) -> str:
        return hashlib.sha256(data.encode()).hexdigest()[:16]
    
    def save(self, checkpoint: Checkpoint) -> str:
        """Save checkpoint to memory and optionally disk"""
        thread_id = checkpoint.thread_id
        
        # Memory storage
        if thread_id not in self.memory_checkpoints:
            self.memory_checkpoints[thread_id] = []
        self.memory_checkpoints[thread_id].append(checkpoint)
        
        # Disk storage
        if self.storage_path:
            checkpoint_file = self.storage_path / f"{thread_id}_{checkpoint.checkpoint_id}.json"
            with open(checkpoint_file, 'w') as f:
                json.dump(checkpoint.to_dict(), f, indent=2)
        
        return checkpoint.checkpoint_id
    
    def load(self, thread_id: str, checkpoint_id: Optional[str] = None) -> Optional[Checkpoint]:
        """Load checkpoint by thread_id and optional checkpoint_id"""
        # Try memory first
        if thread_id in self.memory_checkpoints:
            checkpoints = self.memory_checkpoints[thread_id]
            if checkpoint_id:
                for cp in checkpoints:
                    if cp.checkpoint_id == checkpoint_id:
                        return cp
            elif checkpoints:
                return checkpoints[-1]  # Return latest
        
        # Try disk
        if self.storage_path:
            if checkpoint_id:
                checkpoint_file = self.storage_path / f"{thread_id}_{checkpoint_id}.json"
                if checkpoint_file.exists():
                    with open(checkpoint_file, 'r') as f:
                        return Checkpoint.from_dict(json.load(f))
            else:
                # Find latest checkpoint for thread
                pattern = f"{thread_id}_*.json"
                files = sorted(self.storage_path.glob(pattern))
                if files:
                    with open(files[-1], 'r') as f:
                        return Checkpoint.from_dict(json.load(f))
        
        return None
    
    def list_checkpoints(self, thread_id: str) -> List[Checkpoint]:
        """List all checkpoints for a thread"""
        return self.memory_checkpoints.get(thread_id, [])
    
    def get_state_diff(self, checkpoint1: Checkpoint, checkpoint2: Checkpoint) -> Dict[str, Any]:
        """Get difference between two checkpoint states"""
        diff = {}
        all_keys = set(checkpoint1.state.keys()) | set(checkpoint2.state.keys())
        for key in all_keys:
            val1 = checkpoint1.state.get(key)
            val2 = checkpoint2.state.get(key)
            if val1 != val2:
                diff[key] = {"from": val1, "to": val2}
        return diff


@dataclass
class Task:
    """
    crewAI-inspired task definition with delegation support
    """
    task_id: str
    description: str
    expected_output: str
    assigned_agent: Optional[str] = None
    priority: TaskPriority = TaskPriority.MEDIUM
    dependencies: List[str] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    tools: List[str] = field(default_factory=list)
    async_execution: bool = False
    callback: Optional[Callable] = None
    output_file: Optional[str] = None
    
    def __post_init__(self):
        if not self.task_id:
            self.task_id = self._generate_id()
    
    def _generate_id(self) -> str:
        data = f"{self.description}{datetime.now().isoformat()}"
        return hashlib.sha256(data.encode()).hexdigest()[:12]


@dataclass
class Agent:
    """
    Enhanced agent definition with crewAI-style role definition
    """
    agent_id: str
    name: str
    role: str  # e.g., "Researcher", "Writer", "Coder"
    goal: str
    backstory: str
    handler: Callable[..., Any]
    tools: List[str] = field(default_factory=list)
    allow_delegation: bool = True
    verbose: bool = False
    max_iter: int = 25
    memory: bool = True
    
    async def execute(self, task: Task, context: Dict[str, Any]) -> Any:
        """Execute task with this agent"""
        context = optimize_context(context, token_threshold=4000)
        if self.verbose:
            print(f"🤖 {self.name} ({self.role}) executing: {task.description[:50]}...")
        
        # Prepare context with agent's backstory
        enriched_context = {
            **context,
            "agent_role": self.role,
            "agent_goal": self.goal,
            "agent_backstory": self.backstory
        }
        
        if asyncio.iscoroutinefunction(self.handler):
            return await self.handler(task, enriched_context)
        else:
            return self.handler(task, enriched_context)


@dataclass
class SwarmState:
    """Enhanced swarm state with checkpoint support"""
    swarm_id: str
    mode: ExecutionMode
    thread_id: str
    status: str = "idle"
    agents: Dict[str, Agent] = field(default_factory=dict)
    tasks: Dict[str, Task] = field(default_factory=dict)
    results: Dict[str, Any] = field(default_factory=dict)
    current_task: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    
    def to_checkpoint(self, checkpoint_id: Optional[str] = None) -> Checkpoint:
        """Convert current state to checkpoint"""
        return Checkpoint(
            checkpoint_id=checkpoint_id or self._generate_checkpoint_id(),
            thread_id=self.thread_id,
            agent_id=self.current_task,
            state={
                "status": self.status,
                "results": self.results,
                "current_task": self.current_task,
                "metadata": self.metadata
            },
            metadata={
                "swarm_id": self.swarm_id,
                "mode": self.mode.name,
                "task_count": len(self.tasks),
                "agent_count": len(self.agents)
            }
        )
    
    def _generate_checkpoint_id(self) -> str:
        data = f"{self.thread_id}{datetime.now().isoformat()}"
        return hashlib.sha256(data.encode()).hexdigest()[:16]
    
    def from_checkpoint(self, checkpoint: Checkpoint):
        """Restore state from checkpoint"""
        self.status = checkpoint.state.get("status", "idle")
        self.results = checkpoint.state.get("results", {})
        self.current_task = checkpoint.state.get("current_task")
        self.metadata = checkpoint.state.get("metadata", {})
        self.updated_at = datetime.now()


class TaskDelegation:
    """
    crewAI-inspired task delegation manager
    Handles agent selection and task assignment
    """
    def __init__(self, agents: Dict[str, Agent]):
        self.agents = agents
        self.task_history: List[Tuple[Task, str, Any]] = []
    
    def select_agent(self, task: Task, context: Dict[str, Any]) -> Optional[Agent]:
        """
        Select best agent for task based on role matching and availability
        """
        if task.assigned_agent and task.assigned_agent in self.agents:
            return self.agents[task.assigned_agent]
        
        # Score each agent based on role match
        best_agent = None
        best_score = -1
        
        for agent_id, agent in self.agents.items():
            score = self._calculate_agent_score(agent, task, context)
            if score > best_score:
                best_score = score
                best_agent = agent
        
        return best_agent
    
    def _calculate_agent_score(self, agent: Agent, task: Task, context: Dict[str, Any]) -> float:
        """Calculate how well an agent matches a task"""
        score = 0.0
        
        # Role matching
        task_desc_lower = task.description.lower()
        role_lower = agent.role.lower()
        
        if role_lower in task_desc_lower:
            score += 2.0
        
        # Tool matching
        for tool in task.tools:
            if tool in agent.tools:
                score += 1.0
        
        # Historical performance (simplified)
        successful_tasks = sum(1 for t, a, r in self.task_history 
                              if a == agent.agent_id and not isinstance(r, Exception))
        score += successful_tasks * 0.1
        
        return score
    
    def can_delegate(self, agent: Agent, task: Task) -> bool:
        """Check if agent can delegate this task"""
        return agent.allow_delegation and task.priority != TaskPriority.CRITICAL
    
    def delegate(self, from_agent: Agent, task: Task, context: Dict[str, Any]) -> Optional[Agent]:
        """Delegate task to another agent"""
        if not self.can_delegate(from_agent, task):
            return None
        
        # Find best agent excluding the current one
        best_agent = None
        best_score = -1
        
        for agent_id, agent in self.agents.items():
            if agent_id == from_agent.agent_id:
                continue
            
            score = self._calculate_agent_score(agent, task, context)
            if score > best_score:
                best_score = score
                best_agent = agent
        
        return best_agent


class SwarmV3:
    """
    Enhanced Swarm Orchestrator with:
    - LangGraph checkpoint patterns
    - crewAI task delegation
    - Quantum optimization
    - Multiple execution modes
    """
    
    def __init__(
        self, 
        swarm_id: str, 
        mode: ExecutionMode = ExecutionMode.HIERARCHICAL,
        checkpoint_manager: Optional[CheckpointManager] = None,
        enable_checkpoints: bool = True
    ):
        self.swarm_id = swarm_id
        self.mode = mode
        self.thread_id = f"{swarm_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.state = SwarmState(
            swarm_id=swarm_id,
            mode=mode,
            thread_id=self.thread_id
        )
        self.checkpoint_manager = checkpoint_manager or CheckpointManager()
        self.enable_checkpoints = enable_checkpoints
        self.delegation = TaskDelegation({})
        self._execution_hooks: List[Callable] = []
    
    def register_agent(self, agent: Agent) -> None:
        """Register an agent with the swarm"""
        self.state.agents[agent.agent_id] = agent
        self.delegation.agents = self.state.agents
    
    def register_hook(self, hook: Callable) -> None:
        """Register execution hook for monitoring/debugging"""
        self._execution_hooks.append(hook)
    
    async def _emit(self, event: Dict[str, Any]):
        """Emit event to all registered hooks"""
        for hook in self._execution_hooks:
            try:
                if asyncio.iscoroutinefunction(hook):
                    await hook(event)
                else:
                    hook(event)
            except Exception as e:
                print(f"Hook error: {e}")
    
    def _save_checkpoint(self, agent_id: Optional[str] = None) -> str:
        """Save current state as checkpoint"""
        if not self.enable_checkpoints:
            return ""
        
        checkpoint = self.state.to_checkpoint()
        checkpoint.agent_id = agent_id
        return self.checkpoint_manager.save(checkpoint)
    
    def load_checkpoint(self, checkpoint_id: Optional[str] = None) -> bool:
        """Load state from checkpoint"""
        checkpoint = self.checkpoint_manager.load(self.thread_id, checkpoint_id)
        if checkpoint:
            self.state.from_checkpoint(checkpoint)
            return True
        return False
    
    async def execute_task(self, task: Task, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Execute a single task with delegation support
        """
        context = context or {}
        self.state.tasks[task.task_id] = task
        self.state.current_task = task.task_id
        
        await self._emit({
            "type": "task_start",
            "task_id": task.task_id,
            "description": task.description
        })
        
        # Select agent
        agent = self.delegation.select_agent(task, context)
        if not agent:
            raise ValueError(f"No suitable agent found for task: {task.description}")
        
        # Save checkpoint before execution
        checkpoint_id = self._save_checkpoint(agent.agent_id)
        
        try:
            # Execute
            result = await agent.execute(task, context)
            self.state.results[task.task_id] = result
            
            # Record in delegation history
            self.delegation.task_history.append((task, agent.agent_id, result))
            
            await self._emit({
                "type": "task_complete",
                "task_id": task.task_id,
                "agent_id": agent.agent_id,
                "result": result
            })
            
            return {
                "task_id": task.task_id,
                "agent_id": agent.agent_id,
                "result": result,
                "checkpoint_id": checkpoint_id
            }
            
        except Exception as e:
            # Try delegation on failure
            if self.delegation.can_delegate(agent, task):
                delegated_agent = self.delegation.delegate(agent, task, context)
                if delegated_agent:
                    await self._emit({
                        "type": "task_delegated",
                        "task_id": task.task_id,
                        "from_agent": agent.agent_id,
                        "to_agent": delegated_agent.agent_id
                    })
                    return await self.execute_task(
                        Task(
                            task_id=f"{task.task_id}_delegated",
                            description=task.description,
                            expected_output=task.expected_output,
                            assigned_agent=delegated_agent.agent_id,
                            priority=task.priority,
                            context=task.context
                        ),
                        context
                    )
            
            raise e
        finally:
            self.state.current_task = None
    
    async def execute(
        self, 
        tasks: Union[Task, List[Task]], 
        context: Optional[Dict[str, Any]] = None,
        resume_from_checkpoint: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Execute tasks based on swarm mode
        """
        if isinstance(tasks, Task):
            tasks = [tasks]
        
        # Resume from checkpoint if specified
        if resume_from_checkpoint:
            if self.load_checkpoint(resume_from_checkpoint):
                print(f"✅ Resumed from checkpoint: {resume_from_checkpoint}")
            else:
                print(f"⚠️ Checkpoint not found: {resume_from_checkpoint}")
        
        context = context or {}
        self.state.status = "running"
        
        await self._emit({
            "type": "swarm_start",
            "swarm_id": self.swarm_id,
            "mode": self.mode.name,
            "task_count": len(tasks)
        })
        
        try:
            if self.mode == ExecutionMode.SEQUENTIAL:
                results = await self._execute_sequential(tasks, context)
            elif self.mode == ExecutionMode.PARALLEL:
                results = await self._execute_parallel(tasks, context)
            elif self.mode == ExecutionMode.HIERARCHICAL:
                results = await self._execute_hierarchical(tasks, context)
            elif self.mode == ExecutionMode.MAP_REDUCE:
                results = await self._execute_map_reduce(tasks, context)
            else:
                results = await self._execute_conditional(tasks, context)
            
            self.state.status = "complete"
            
            await self._emit({
                "type": "swarm_complete",
                "swarm_id": self.swarm_id,
                "results_count": len(results)
            })
            
            return {
                "swarm_id": self.swarm_id,
                "mode": self.mode.name,
                "status": "complete",
                "results": results,
                "thread_id": self.thread_id
            }
            
        except Exception as e:
            self.state.status = "error"
            # Save error checkpoint for recovery
            self._save_checkpoint()
            raise e
    
    async def _execute_sequential(self, tasks: List[Task], context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute tasks in sequence, passing context forward"""
        results = {}
        current_context = context.copy()
        current_context = optimize_context(current_context, token_threshold=4000)
        
        for task in sorted(tasks, key=lambda t: t.priority.value, reverse=True):
            # Check dependencies
            for dep_id in task.dependencies:
                if dep_id not in results:
                    raise ValueError(f"Dependency not met: {dep_id}")
            
            result = await self.execute_task(task, current_context)
            results[task.task_id] = result
            
            # Update context with result for next task
            current_context[f"result_{task.task_id}"] = result["result"]
            current_context = optimize_context(current_context, token_threshold=4000)
        
        return results
    
    async def _execute_parallel(self, tasks: List[Task], context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute tasks in parallel"""
        context = optimize_context(context, token_threshold=4000)
        async def run_task(task: Task) -> Tuple[str, Dict[str, Any]]:
            result = await self.execute_task(task, context)
            return task.task_id, result
        
        # Sort by priority
        sorted_tasks = sorted(tasks, key=lambda t: t.priority.value, reverse=True)
        
        # Execute all in parallel
        pairs = await asyncio.gather(*(run_task(t) for t in sorted_tasks))
        return {task_id: result for task_id, result in pairs}
    
    async def _execute_hierarchical(self, tasks: List[Task], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Hierarchical execution with manager agent
        Manager plans, workers execute
        """
        # Find manager agent (highest priority or explicit manager role)
        manager = None
        for agent in self.state.agents.values():
            if agent.role.lower() in ["manager", "orchestrator", "lead"]:
                manager = agent
                break
        
        if not manager and self.state.agents:
            # Use first agent as manager
            manager = list(self.state.agents.values())[0]
        
        results = {}
        
        # Manager creates execution plan
        plan_task = Task(
            task_id="manager_plan",
            description=f"Create execution plan for {len(tasks)} tasks",
            expected_output="Execution plan with task assignments",
            assigned_agent=manager.agent_id if manager else None
        )
        
        plan_result = await self.execute_task(plan_task, {
            **context,
            "available_agents": [a.agent_id for a in self.state.agents.values()],
            "tasks": [{"id": t.task_id, "desc": t.description} for t in tasks]
        })
        
        results["plan"] = plan_result
        
        # Execute tasks according to plan
        for task in tasks:
            result = await self.execute_task(task, context)
            results[task.task_id] = result
        
        return results
    
    async def _execute_map_reduce(self, tasks: List[Task], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Map-Reduce pattern: split, process in parallel, aggregate
        """
        # Map phase - process in parallel
        map_results = await self._execute_parallel(tasks, context)
        
        # Reduce phase - aggregate results
        reduce_task = Task(
            task_id="reduce_aggregate",
            description="Aggregate results from all tasks",
            expected_output="Combined summary of all results",
            context={"map_results": map_results}
        )
        
        reduce_result = await self.execute_task(reduce_task, context)
        
        return {
            "map_results": map_results,
            "reduce_result": reduce_result
        }
    
    async def _execute_conditional(self, tasks: List[Task], context: Dict[str, Any]) -> Dict[str, Any]:
        """Dynamic execution based on state conditions"""
        results = {}
        remaining_tasks = tasks.copy()
        
        while remaining_tasks:
            # Select next task based on current state
            task = remaining_tasks.pop(0)
            
            result = await self.execute_task(task, context)
            results[task.task_id] = result
            
            # Dynamic task insertion based on result
            if isinstance(result.get("result"), dict) and "next_tasks" in result["result"]:
                for next_task_data in result["result"]["next_tasks"]:
                    new_task = Task(
                        task_id=next_task_data["id"],
                        description=next_task_data["description"],
                        expected_output=next_task_data.get("expected_output", "")
                    )
                    remaining_tasks.append(new_task)
        
        return results
    
    def get_status(self) -> Dict[str, Any]:
        """Get current swarm status"""
        return {
            "swarm_id": self.swarm_id,
            "thread_id": self.thread_id,
            "status": self.state.status,
            "mode": self.mode.name,
            "agents": {
                agent_id: {
                    "name": agent.name,
                    "role": agent.role,
                    "tools": agent.tools
                }
                for agent_id, agent in self.state.agents.items()
            },
            "tasks_total": len(self.state.tasks),
            "tasks_complete": len(self.state.results),
            "checkpoints": len(self.checkpoint_manager.list_checkpoints(self.thread_id))
        }


# Convenience functions for quick swarm creation
def create_sequential_swarm(swarm_id: str) -> SwarmV3:
    """Create a sequential execution swarm"""
    return SwarmV3(swarm_id, ExecutionMode.SEQUENTIAL)


def create_parallel_swarm(swarm_id: str) -> SwarmV3:
    """Create a parallel execution swarm"""
    return SwarmV3(swarm_id, ExecutionMode.PARALLEL)


def create_hierarchical_swarm(swarm_id: str) -> SwarmV3:
    """Create a hierarchical execution swarm with manager"""
    return SwarmV3(swarm_id, ExecutionMode.HIERARCHICAL)


if __name__ == "__main__":
    # Demo
    async def demo():
        # Create swarm
        swarm = SwarmV3("demo-swarm", ExecutionMode.HIERARCHICAL)
        
        # Register agents
        swarm.register_agent(Agent(
            agent_id="researcher",
            name="Research Agent",
            role="Researcher",
            goal="Find relevant information",
            backstory="Expert at finding and summarizing information",
            handler=lambda task, ctx: f"Research result for: {task.description}"
        ))
        
        swarm.register_agent(Agent(
            agent_id="writer",
            name="Writer Agent",
            role="Writer",
            goal="Create compelling content",
            backstory="Expert writer with years of experience",
            handler=lambda task, ctx: f"Written content for: {task.description}"
        ))
        
        # Create tasks
        tasks = [
            Task(
                task_id="research",
                description="Research quantum computing",
                expected_output="Summary of quantum computing basics"
            ),
            Task(
                task_id="write",
                description="Write blog post about quantum computing",
                expected_output="Blog post content",
                dependencies=["research"]
            )
        ]
        
        # Execute
        result = await swarm.execute(tasks)
        print(f"\nResult: {result}")
        print(f"\nStatus: {swarm.get_status()}")
    
    asyncio.run(demo())
