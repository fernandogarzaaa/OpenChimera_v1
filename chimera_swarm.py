"""
CHIMERA Swarm API - LLM-Powered Agents
Each agent uses the local LLM for its specialized task
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Any, Optional
import requests
import os
import uuid
import asyncio

from token_fracture import compress_context
from swarm_v2 import SwarmOrchestrator, ProcessMode

app = FastAPI(title="CHIMERA Swarm API")

# Config - Use Ollama for GPU acceleration
LOCAL_URL = "http://localhost:11434"  # Ollama with CUDA
HF_API_KEY = os.getenv("HF_API_KEY", "REDACTED_BY_AETHER_SECURITY")
MAX_CONTEXT_TOKENS = 4000
USE_OLLAMA = True

# Initialize swarm orchestrator
swarm = SwarmOrchestrator("chimera-swarm", ProcessMode.SEQUENTIAL)

# LLM Client - Uses Ollama with CUDA
def call_llm(prompt: str, system: str = None, max_tokens: int = 200) -> str:
    """Call Ollama LLM (GPU-accelerated)"""
    full_prompt = prompt
    if system:
        full_prompt = f"{system}\n\n{prompt}"
    
    try:
        resp = requests.post(
            f"{LOCAL_URL}/api/generate",
            json={
                "model": "phi3:mini",  # Fast model for agents
                "prompt": full_prompt,
                "stream": False,
                "options": {"num_predict": max_tokens}
            },
            timeout=120
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get("response", "").strip()
    except Exception as e:
        print(f"Ollama error: {e}")
    
    # Fallback to llama-server
    try:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        
        resp = requests.post(
            "http://localhost:8080/v1/chat/completions",
            json={"messages": messages, "max_tokens": max_tokens, "temperature": 0.7},
            timeout=60
        )
        if resp.status_code == 200:
            data = resp.json()
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"Fallback error: {e}")
    
    return "Error calling LLM"

# === LLM-POWERED AGENTS ===

def spec_agent(task: str, context: dict, prev: dict) -> str:
    """Spec Agent - analyze requirements"""
    prompt = f"""Analyze this task and create a detailed specification:
    
Task: {task}

Previous work: {prev}

Provide:
1. Requirements summary
2. Key components needed
3. Acceptance criteria (3-5 bullet points)"""
    
    return call_llm(prompt, system="You are a senior requirements analyst. Create clear, actionable specs.")

def architect_agent(task: str, context: dict, prev: dict) -> str:
    """Architect Agent - design solution"""
    prompt = f"""Design a technical architecture for this task:

Task: {task}
Requirements: {prev.get('spec', 'N/A')}

Provide:
1. Data models (if needed)
2. API endpoints
3. Key modules/functions
4. Technology stack"""
    
    return call_llm(prompt, system="You are a system architect. Design scalable, clean architectures.")

def implement_agent(task: str, context: dict, prev: dict) -> str:
    """Implement Agent - write code"""
    prompt = f"""Write production-ready code for this task:

Task: {task}
Architecture: {prev.get('architect', 'N/A')}

Provide complete, working code with:
1. Main implementation
2. Necessary imports
3. Error handling
4. Brief comments"""
    
    return call_llm(prompt, system="You are a senior developer. Write clean, tested code.")

def test_agent(task: str, context: dict, prev: str) -> str:
    """Test Agent - write tests"""
    implementation = prev if isinstance(prev, str) else str(prev.get('implement', ''))
    
    prompt = f"""Write unit tests for this implementation:

Task: {task}
Code: {implementation[:1000]}

Provide:
1. Test class/functions
2. At least 3 test cases
3. Assertions for expected behavior"""
    
    return call_llm(prompt, system="You are a QA engineer. Write comprehensive unit tests.")

def review_agent(task: str, context: dict, prev: dict) -> str:
    """Review Agent - code review"""
    prompt = f"""Review this implementation:

Task: {task}
Implementation: {prev.get('implement', 'N/A')[:1500]}
Tests: {prev.get('test', 'N/A')[:500]}

Provide:
1. Code quality score (1-10)
2. Issues found (if any)
3. Recommendations"""
    
    return call_llm(prompt, system="You are a code reviewer. Be thorough but constructive.")

def doc_agent(task: str, context: dict, prev: dict) -> str:
    """Doc Agent - write documentation"""
    prompt = f"""Write documentation for this feature:

Task: {task}
Implementation: {prev.get('implement', 'N/A')[:1000]}

Provide:
1. Overview
2. Usage examples
3. API reference (if applicable)"""
    
    return call_llm(prompt, system="You are a technical writer. Write clear docs.")

# Register agents
swarm.register_agent("spec", "Spec Agent", spec_agent)
swarm.register_agent("architect", "Architect Agent", architect_agent)
swarm.register_agent("implement", "Implement Agent", implement_agent)
swarm.register_agent("test", "Test Agent", test_agent)
swarm.register_agent("review", "Review Agent", review_agent)
swarm.register_agent("doc", "Doc Agent", doc_agent)

# Set up pipeline
swarm.set_handoff("spec", "architect")
swarm.set_handoff("architect", "implement")
swarm.set_handoff("implement", "test")
swarm.set_handoff("test", "review")
swarm.set_handoff("review", "doc")

# === API MODELS ===

class ChatRequest(BaseModel):
    messages: list
    temperature: float = 0.7
    max_tokens: int = 256

class SwarmRequest(BaseModel):
    task: str
    mode: str = "sequential"
    context: dict = {}
    max_tokens: int = 300

# === ENDPOINTS ===

@app.get("/health")
def health():
    return {
        "status": "ok", 
        "mode": "llm-swarm",
        "agents": list(swarm.agents.keys()),
        "llm": "Qwen2.5-7B"
    }

@app.get("/v1/models")
def list_models():
    return {
        "object": "list",
        "data": [
            {"id": "chimera-local", "object": "model", "created": 1677610602, "owned_by": "local"},
            {"id": "chimera-swarm", "object": "model", "created": 1677610603, "owned_by": "swarm-llm"}
        ]
    }

@app.post("/v1/chat/completions")
def chat(req: ChatRequest):
    """Standard chat with Token Fracture"""
    query = ""
    for msg in reversed(req.messages):
        if msg.get("role") == "user":
            query = msg.get("content", "")[:200]
            break
    
    compressed_messages, stats = compress_context(
        req.messages, query=query, max_tokens=MAX_CONTEXT_TOKENS
    )
    
    if stats["savings_ratio"] > 0:
        print(f"[TOKEN] {stats['savings_ratio']*100:.1f}% saved")
    
    # Build prompt
    prompt = ""
    for msg in compressed_messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "user":
            prompt += f"User: {content}\n"
        elif role == "assistant":
            prompt += f"Assistant: {content}\n"
    prompt += "Assistant: "
    
    # Try Ollama (GPU-accelerated)
    try:
        # Build prompt from messages
        prompt = ""
        for msg in compressed_messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "user":
                prompt += f"User: {content}\n"
            elif role == "assistant":
                prompt += f"Assistant: {content}\n"
        prompt += "Assistant: "
        
        resp = requests.post(
            f"{LOCAL_URL}/api/generate",
            json={
                "model": "phi3:mini",
                "prompt": prompt,
                "stream": False,
                "options": {"num_predict": req.max_tokens, "temperature": req.temperature}
            },
            timeout=120
        )
        if resp.status_code == 200:
            data = resp.json()
            return {
                "id": f"chimera-{uuid.uuid4().hex[:8]}",
                "object": "chat.completion",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": data.get("response", "")}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": stats["compressed_tokens"], "completion_tokens": data.get("eval_count", 0)},
                "compression": stats,
                "model": "phi3:mini"
            }
    except Exception as e:
        print(f"Ollama failed: {e}")
    
    # Fallback to llama-server
    try:
        resp = requests.post(
            "http://localhost:8080/v1/chat/completions",
            json={"messages": compressed_messages, "max_tokens": req.max_tokens, "temperature": req.temperature},
            timeout=60
        )
        if resp.status_code == 200:
            data = resp.json()
            return {
                "id": f"chimera-{uuid.uuid4().hex[:8]}",
                "object": "chat.completion",
                "choices": [{"index": 0, "message": data.get("choices", [{}])[0].get("message", {}), "finish_reason": "stop"}],
                "usage": {"prompt_tokens": stats["compressed_tokens"], "completion_tokens": data.get("usage", {}).get("completion_tokens", 0)},
                "compression": stats
            }
    except Exception as e:
        print(f"Fallback failed: {e}")
    
    raise HTTPException(status_code=502, error="All providers failed")

@app.post("/swarm/execute")
async def swarm_execute(req: SwarmRequest):
    """Execute task through LLM-powered swarm"""
    
    # Update mode
    if req.mode == "parallel":
        swarm.process_mode = ProcessMode.PARALLEL
    elif req.mode == "hierarchical":
        swarm.process_mode = ProcessMode.HIERARCHICAL
    else:
        swarm.process_mode = ProcessMode.SEQUENTIAL
    
    # Save checkpoint
    swarm.checkpoint(f"before_{req.task[:15]}")
    
    print(f"[SWARM] Executing: {req.task}")
    
    # Execute through pipeline
    result = await swarm.execute_task(req.task, req.context)
    
    return {
        "task": req.task,
        "mode": req.mode,
        "pipeline": list(swarm.agents.keys()),
        "result": result,
        "status": swarm.get_status()
    }

@app.get("/swarm/status")
def swarm_status():
    return swarm.get_status()

@app.get("/swarm/agents")
def list_agents():
    return {
        "agents": [
            {"id": k, "role": v["role"]} 
            for k, v in swarm.agents.items()
        ]
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7862)
