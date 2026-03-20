"""
CHIMERA V2 - Full Integration
Combines: Swarm V2 + Smart Router + Quantum + RAG + AutoGPT-style loops
"""
import asyncio
from typing import Any, Optional
from dataclasses import dataclass, field
from enum import Enum

# Import our modules
from swarm_v2 import SwarmOrchestrator, ProcessMode
from smart_router import router as smart_router
from token_fracture import compress_context

# === CONFIGURATION ===

class TaskType(Enum):
    GENERAL = "general"
    CODING = "coding" 
    REASONING = "reasoning"
    FAST = "fast"
    RESEARCH = "research"


@dataclass
class ChimeraConfig:
    """CHIMERA V2 Configuration"""
    # Model settings
    default_model: str = "ollama_phi3"
    prefer_speed: bool = True
    
    # Swarm settings
    swarm_mode: ProcessMode = ProcessMode.SEQUENTIAL
    enable_autoGPT: bool = True  # Autonomous loop mode
    
    # Context settings
    max_context_tokens: int = 4000
    compression_enabled: bool = True
    
    # Quantum settings
    quantum_enabled: bool = True
    consensus_votes: int = 3
    
    # RAG settings
    rag_enabled: bool = True
    vector_store: str = "memory"  # or "qdrant", "chroma"


@dataclass
class TaskResult:
    """Result from CHIMERA task execution"""
    success: bool
    content: Any
    model_used: str
    tokens_used: int
    method: str  # "direct", "swarm", "rag", "quantum"
    metadata: dict = field(default_factory=dict)


class ChimeraV2:
    """
    CHIMERA V2 - Full AI System
    
    Features:
    - Smart model routing (LiteLLM-style)
    - Multi-agent Swarm orchestration  
    - Quantum-inspired consensus
    - RAG knowledge retrieval
    - AutoGPT-style autonomous loops
    - Token compression
    """
    
    def __init__(self, config: ChimeraConfig = None):
        self.config = config or ChimeraConfig()
        
        # Initialize components
        self.swarm = SwarmOrchestrator("chimera-main", self.config.swarm_mode)
        self.router = smart_router
        self.task_history = []
        
        # Register default swarm agents
        self._setup_swarm_agents()
        
    def _setup_swarm_agents(self):
        """Set up default swarm agents with LLM handlers"""
        
        async def spec_agent(task, ctx, prev):
            result = await self._call_llm(
                f"Analyze this task and create requirements:\n{task}",
                task_type=TaskType.GENERAL
            )
            return result
            
        async def architect_agent(task, ctx, prev):
            result = await self._call_llm(
                f"Design a solution for:\n{task}\n\nRequirements: {prev}",
                task_type=TaskType.REASONING
            )
            return result
            
        async def implement_agent(task, ctx, prev):
            result = await self._call_llm(
                f"Implement:\n{task}\n\nDesign: {prev}",
                task_type=TaskType.CODING
            )
            return result
            
        # Register agents
        self.swarm.register_agent("spec", "Spec Agent", spec_agent)
        self.swarm.register_agent("architect", "Architect Agent", architect_agent) 
        self.swarm.register_agent("implement", "Implement Agent", implement_agent)
        
        # Set up handoffs
        self.swarm.set_handoff("spec", "architect")
        self.swarm.set_handoff("architect", "implement")
        
    async def _call_llm(
        self, 
        prompt: str, 
        task_type: TaskType = TaskType.GENERAL,
        max_tokens: int = 256
    ) -> str:
        """Call LLM through smart router"""
        result = await self.router.route(
            prompt=prompt,
            task_type=task_type.value,
            max_tokens=max_tokens
        )
        
        if "content" in result:
            return result["content"]
        return f"Error: {result.get('error', 'Unknown')}"
        
    async def _rag_retrieve(self, query: str, top_k: int = 3) -> list[str]:
        """RAG-style retrieval from task history"""
        # Simple memory-based RAG
        results = []
        for item in self.task_history[-10:]:
            if query.lower() in str(item.get("task", "")).lower():
                results.append(f"Previous: {item.get('task')} -> {item.get('result', '')[:100]}")
        return results[:top_k]
        
    async def _quantum_consensus(
        self, 
        prompt: str, 
        votes: int = 3
    ) -> str:
        """Quantum-inspired consensus - multiple models vote"""
        responses = []
        
        # Get multiple opinions
        for _ in range(votes):
            result = await self._call_llm(prompt, max_tokens=150)
            responses.append(result)
            
        # Simple consensus - return first response (could implement voting)
        return responses[0] if responses else "No response"
        
    async def _autonomous_loop(
        self, 
        goal: str, 
        max_iterations: int = 5
    ) -> dict:
        """
        AutoGPT-style autonomous loop
        - Takes a goal
        - Plans steps
        - Executes them
        - Evaluates results
        """
        iterations = []
        
        for i in range(max_iterations):
            # Think - plan next step
            thinking = await self._call_llm(
                f"Goal: {goal}\n"
                f"Previous steps: {iterations}\n"
                f"What is the next step to achieve this goal? Respond with just ONE specific action.",
                task_type=TaskType.REASONING
            )
            
            # Execute
            result = await self._call_llm(
                f"Execute this step: {thinking}\nGoal: {goal}",
                task_type=TaskType.CODING
            )
            
            iterations.append({
                "iteration": i + 1,
                "thought": thinking,
                "action": result
            })
            
            # Check if goal achieved (simple check)
            if "complete" in result.lower() or "done" in result.lower():
                break
                
        return {
            "goal": goal,
            "iterations": iterations,
            "final_result": iterations[-1]["action"] if iterations else "No result"
        }
        
    async def execute(
        self,
        task: str,
        method: str = "auto",  # "direct", "swarm", "rag", "quantum", "autonomous", "auto"
        task_type: TaskType = TaskType.GENERAL
    ) -> TaskResult:
        """
        Execute task using best method
        
        Methods:
        - direct: Single LLM call
        - swarm: Multi-agent pipeline  
        - rag: Retrieval-augmented
        - quantum: Consensus voting
        - autonomous: AutoGPT loop
        - auto: CHIMERA decides
        """
        
        # Compress context if enabled
        context = ""
        if self.config.compression_enabled:
            # Get recent history for context
            recent_tasks = [t["task"] for t in self.task_history[-5:]]
            if recent_tasks:
                context = f"\n\nContext from recent tasks: {recent_tasks}"
        
        full_task = task + context
        
        # Auto-select method
        if method == "auto":
            if len(task) > 500:
                method = "swarm"
            elif "search" in task.lower() or "find" in task.lower():
                method = "rag"
            elif self.config.quantum_enabled and self.config.consensus_votes > 1:
                method = "quantum"
            elif self.config.enable_autoGPT and ("build" in task.lower() or "create" in task.lower()):
                method = "autonomous"
            else:
                method = "direct"
                
        # Execute
        if method == "direct":
            content = await self._call_llm(full_task, task_type)
            result = TaskResult(
                success=True,
                content=content,
                model_used="smart_router",
                tokens_used=len(content.split()),
                method="direct"
            )
            
        elif method == "swarm":
            self.swarm.checkpoint(f"before_{task[:10]}")
            swarm_result = await self.swarm.execute_task(full_task, {})
            result = TaskResult(
                success=True,
                content=str(swarm_result),
                model_used="swarm",
                tokens_used=sum(len(str(v).split()) for v in swarm_result.values()),
                method="swarm"
            )
            
        elif method == "rag":
            context_results = await self._rag_retrieve(task)
            rag_context = "\n".join(context_results)
            prompt = f"Based on this context:\n{rag_context}\n\nAnswer: {task}"
            content = await self._call_llm(prompt, task_type)
            result = TaskResult(
                success=True,
                content=content,
                model_used="rag",
                tokens_used=len(content.split()),
                method="rag",
                metadata={"context_used": len(context_results)}
            )
            
        elif method == "quantum":
            content = await self._quantum_consensus(full_task, self.config.consensus_votes)
            result = TaskResult(
                success=True,
                content=content,
                model_used="quantum_consensus",
                tokens_used=len(content.split()),
                method="quantum"
            )
            
        elif method == "autonomous":
            loop_result = await self._autonomous_loop(task)
            result = TaskResult(
                success=True,
                content=loop_result["final_result"],
                model_used="autonomous",
                tokens_used=sum(len(i["action"].split()) for i in loop_result["iterations"]),
                method="autonomous",
                metadata={"iterations": len(loop_result["iterations"])}
            )
            
        else:
            result = TaskResult(
                success=False,
                content=f"Unknown method: {method}",
                model_used="none",
                tokens_used=0,
                method=method
            )
            
        # Save to history
        self.task_history.append({
            "task": task,
            "method": method,
            "result": result.content,
            "success": result.success
        })
        
        return result
        
    def get_status(self) -> dict:
        """Get CHIMERA V2 status"""
        return {
            "config": {
                "default_model": self.config.default_model,
                "swarm_mode": self.config.swarm_mode.value,
                "compression": self.config.compression_enabled,
                "quantum": self.config.quantum_enabled,
                "autonomous": self.config.enable_autoGPT,
                "rag": self.config.rag_enabled
            },
            "router": self.router.get_status(),
            "swarm": self.swarm.get_status(),
            "history_count": len(self.task_history)
        }


# === API SERVER ===

def create_app():
    """Create FastAPI app"""
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel
    import uuid
    
    app = FastAPI(title="CHIMERA V2")
    chimera = ChimeraV2()
    
    class ExecuteRequest(BaseModel):
        task: str
        method: str = "auto"
        task_type: str = "general"
        
    @app.get("/health")
    def health():
        return {"status": "ok", "version": "2.0", "components": ["swarm", "router", "quantum", "rag", "autonomous"]}
        
    @app.get("/status")
    def status():
        return chimera.get_status()
        
    @app.post("/execute")
    async def execute(req: ExecuteRequest):
        task_type = TaskType(req.task_type) if req.task_type in [t.value for t in TaskType] else TaskType.GENERAL
        result = await chimera.execute(req.task, req.method, task_type)
        
        return {
            "success": result.success,
            "content": result.content,
            "model": result.model_used,
            "method": result.method,
            "tokens": result.tokens_used,
            "metadata": result.metadata
        }
        
    @app.get("/history")
    def history():
        return {"tasks": chimera.task_history}
        
    return app


if __name__ == "__main__":
    import uvicorn
    app = create_app()
    uvicorn.run(app, host="0.0.0.0", port=7863)
