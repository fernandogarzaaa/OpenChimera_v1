"""
CHIMERA API - HuggingFace Spaces Deployment
Uses HF Inference API - no local GPU needed
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import os
import requests

app = FastAPI(title="CHIMERA Quantum API")

# HuggingFace Inference API
HF_API_KEY = os.getenv("HF_API_KEY", "")
API_URL = "https://api-inference.huggingface.co/models/"

# Available models
MODELS = {
    "chimera-local": "Qwen/Qwen2.5-7B-Instruct",
    "qwen-turbo": "Qwen/Qwen2.5-7B-Instruct", 
    "mistral": "mistralai/Mistral-7B-Instruct-v0.2",
    "llama3": "meta-llama/Meta-Llama-3-8B-Instruct",
}

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    model: str = "chimera-local"
    messages: List[ChatMessage]
    temperature: float = 0.7
    max_tokens: int = 512

@app.get("/health")
def health():
    return {"status": "ok", "mode": "huggingface"}

@app.get("/v1/models")
def list_models():
    return {
        "object": "list",
        "data": [
            {"id": k, "object": "model", "owned_by": "huggingface"} 
            for k in MODELS.keys()
        ]
    }

@app.post("/v1/chat/completions")
def chat(req: ChatRequest):
    if not HF_API_KEY:
        raise HTTPException(status_code=500, detail="HF_API_KEY not configured")
    
    # Get model
    model_id = MODELS.get(req.model, MODELS["chimera-local"])
    
    # Convert messages to prompt
    prompt = "\n".join([
        f"{m.role}: {m.content}" 
        for m in req.messages
    ])
    prompt += "\nassistant:"
    
    # Call HF Inference API
    headers = {"Authorization": f"Bearer {HF_API_KEY}"}
    payload = {
        "inputs": prompt,
        "parameters": {
            "max_new_tokens": req.max_tokens,
            "temperature": req.temperature,
            "return_full_text": False,
        }
    }
    
    try:
        response = requests.post(
            API_URL + model_id,
            headers=headers,
            json=payload,
            timeout=60
        )
        response.raise_for_status()
        result = response.json()
        
        # Extract generated text
        if isinstance(result, list) and len(result) > 0:
            generated_text = result[0].get("generated_text", "")
        else:
            generated_text = str(result)
        
        return {
            "id": "chatcmpl-" + os.urandom(8).hex(),
            "object": "chat.completion",
            "created": 1677610602,
            "model": req.model,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": generated_text
                },
                "finish_reason": "stop"
            }],
            "usage": {
                "prompt_tokens": len(prompt) // 4,
                "completion_tokens": len(generated_text) // 4,
                "total_tokens": (len(prompt) + len(generated_text)) // 4
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "7861"))
    uvicorn.run(app, host="0.0.0.0", port=port)
