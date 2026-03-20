"""
CHIMERA Qwen-Agent API Server
FastAPI server for enhanced Qwen-Agent integration
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Any
import uvicorn
import os
import sys

# Add paths
QWEN_PATH = os.path.join(os.path.dirname(__file__), '..', 'appforge-main', 'Qwen-Agent')
if os.path.exists(QWEN_PATH):
    sys.path.insert(0, QWEN_PATH)

app = FastAPI(title="CHIMERA Qwen-Agent API")

# Try to import Qwen-Agent
try:
    from chimera_qwen_enhanced import ChimeraQwenEnhanced, ChimeraAgentFactory
    AGENT = ChimeraQwenEnhanced()
    QWEN_AVAILABLE = True
except Exception as e:
    AGENT = None
    QWEN_AVAILABLE = False
    print(f"Qwen-Agent not available: {e}")

# ========== REQUEST MODELS ==========

class ChatRequest(BaseModel):
    query: str
    system: Optional[str] = None

class ReactRequest(BaseModel):
    query: str
    tools: Optional[List[str]] = None
    allow_code: bool = True

class FunctionCallRequest(BaseModel):
    query: str
    functions: List[dict]

class GroupChatRequest(BaseModel):
    query: str
    agents: Optional[List[dict]] = None

class CodeRequest(BaseModel):
    code: Optional[str] = None
    query: Optional[str] = None

class RAGRequest(BaseModel):
    query: str
    documents: Optional[List[str]] = None
    file_paths: Optional[List[str]] = None

class WebSearchRequest(BaseModel):
    query: str
    num_results: int = 5

class BrowserRequest(BaseModel):
    task: str

class MultimodalRequest(BaseModel):
    query: str
    images: Optional[List[str]] = None
    video: Optional[str] = None
    audio: Optional[str] = None

# ========== ENDPOINTS ==========

@app.get("/")
def root():
    return {
        "name": "CHIMERA Qwen-Agent API",
        "version": "1.0.0",
        "qwen_available": QWEN_AVAILABLE
    }

@app.get("/health")
def health():
    return {
        "status": "ok",
        "qwen_available": QWEN_AVAILABLE
    }

@app.post("/chat")
def chat(req: ChatRequest):
    """Simple chat"""
    if not QWEN_AVAILABLE:
        raise HTTPException(503, "Qwen-Agent not installed")
    
    return {"response": AGENT.chat(req.query, req.system)}

@app.post("/react")
def react(req: ReactRequest):
    """ReAct agent - reasoning + acting"""
    if not QWEN_AVAILABLE:
        raise HTTPException(503, "Qwen-Agent not installed")
    
    result = AGENT.react(req.query, req.tools, req.allow_code)
    return {"response": result}

@app.post("/function_call")
def function_call(req: FunctionCallRequest):
    """Function calling"""
    if not QWEN_AVAILABLE:
        raise HTTPException(503, "Qwen-Agent not installed")
    
    result = AGENT.function_call(req.query, req.functions)
    return {"response": result}

@app.post("/group_chat")
def group_chat(req: GroupChatRequest):
    """Multi-agent group chat"""
    if not QWEN_AVAILABLE:
        raise HTTPException(503, "Qwen-Agent not installed")
    
    result = AGENT.group_chat(req.query, req.agents)
    return {"response": result}

@app.post("/code")
def code(req: CodeRequest):
    """Code interpreter"""
    if not QWEN_AVAILABLE:
        raise HTTPException(503, "Qwen-Agent not installed")
    
    result = AGENT.code_interpreter(req.code, req.query)
    return {"response": result}

@app.post("/rag")
def rag(req: RAGRequest):
    """Retrieval Augmented Generation"""
    if not QWEN_AVAILABLE:
        raise HTTPException(503, "Qwen-Agent not installed")
    
    result = AGENT.rag(req.query, req.documents, req.file_paths)
    return {"response": result}

@app.post("/web_search")
def web_search(req: WebSearchRequest):
    """Web search"""
    if not QWEN_AVAILABLE:
        raise HTTPException(503, "Qwen-Agent not installed")
    
    result = AGENT.web_search(req.query, req.num_results)
    return {"results": result}

@app.post("/browser")
def browser(req: BrowserRequest):
    """Browser automation"""
    if not QWEN_AVAILABLE:
        raise HTTPException(503, "Qwen-Agent not installed")
    
    result = AGENT.browser(req.task)
    return {"response": result}

@app.post("/multimodal")
def multimodal(req: MultimodalRequest):
    """Multimodal (images, video, audio)"""
    if not QWEN_AVAILABLE:
        raise HTTPException(503, "Qwen-Agent not installed")
    
    result = AGENT.multimodal(req.query, req.images, req.video, req.audio)
    return {"response": result}

@app.get("/factory/agents")
def list_factory_agents():
    """List predefined agent factories"""
    return {
        "agents": [
            ChimeraAgentFactory.researcher(),
            ChimeraAgentFactory.coder(),
            ChimeraAgentFactory.analyst(),
            ChimeraAgentFactory.writer(),
            ChimeraAgentFactory.reviewer()
        ]
    }


if __name__ == "__main__":
    print("Starting CHIMERA Qwen-Agent API on port 7864...")
    uvicorn.run(app, host="0.0.0.0", port=7864)
