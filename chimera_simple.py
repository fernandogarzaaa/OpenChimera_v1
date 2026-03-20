"""
Simple CHIMERA API - Local + HF only
Bypasses complex CHIMERA stack for faster responses
With Token Fracture compression for efficiency
"""
from fastapi import FastAPI
from pydantic import BaseModel
import requests
import os

from token_fracture import compress_context

app = FastAPI(title="CHIMERA Local API")

# Config
LOCAL_URL = "http://localhost:8080"
HF_API_KEY = os.getenv("HF_API_KEY", "REDACTED_BY_AETHER_SECURITY")

# Token budget - adjust based on model context window
MAX_CONTEXT_TOKENS = 6000  # Leave room for output

class ChatRequest(BaseModel):
    messages: list
    temperature: float = 0.7
    max_tokens: int = 256

@app.get("/health")
def health():
    return {"status": "ok", "mode": "local+hf"}

@app.get("/v1/models")
def list_models():
    return {
        "object": "list",
        "data": [
            {
                "id": "chimera-local",
                "object": "model",
                "created": 1677610602,
                "owned_by": "local"
            }
        ]
    }

@app.post("/v1/chat/completions")
def chat(req: ChatRequest):
    # Extract query from last user message for relevance scoring
    query = ""
    for msg in reversed(req.messages):
        if msg.get("role") == "user":
            query = msg.get("content", "")[:200]  # Limit query length
            break
    
    # Apply token fracture compression
    compressed_messages, stats = compress_context(
        req.messages,
        query=query,
        max_tokens=MAX_CONTEXT_TOKENS,
        keep_recent=3  # Keep last 3 messages intact
    )
    
    if stats["savings_ratio"] > 0:
        print(f"📉 Token Fracture: {stats['savings_ratio']*100:.1f}% savings ({stats['original_tokens']} → {stats['compressed_tokens']} tokens)")
    
    # Build prompt from compressed messages
    prompt = ""
    for msg in compressed_messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "user":
            prompt += f"User: {content}\n"
        elif role == "assistant":
            prompt += f"Assistant: {content}\n"
    prompt += "Assistant: "
    
    # Try local first
    try:
        resp = requests.post(
            f"{LOCAL_URL}/v1/chat/completions",
            json={
                "messages": compressed_messages,
                "max_tokens": req.max_tokens,
                "temperature": req.temperature
            },
            timeout=60
        )
        if resp.status_code == 200:
            data = resp.json()
            return {
                "id": "chimera-local",
                "object": "chat.completion",
                "choices": [{
                    "index": 0,
                    "message": data.get("choices", [{}])[0].get("message", {}),
                    "finish_reason": "stop"
                }],
                "usage": {
                    "prompt_tokens": stats["compressed_tokens"],
                    "completion_tokens": data.get("usage", {}).get("completion_tokens", 0),
                    "total_tokens": stats["compressed_tokens"] + data.get("usage", {}).get("completion_tokens", 0)
                },
                "compression": {
                    "original_tokens": stats["original_tokens"],
                    "compressed_tokens": stats["compressed_tokens"],
                    "savings_ratio": stats["savings_ratio"],
                    "method": stats["method"]
                }
            }
    except Exception as e:
        print(f"Local failed: {e}")
    
    # Fallback to HF
    try:
        hf_resp = requests.post(
            "https://api-inference.huggingface.co/models/Qwen/Qwen2.5-7B-Instruct",
            headers={"Authorization": f"Bearer {HF_API_KEY}"},
            json={
                "inputs": prompt,
                "parameters": {
                    "max_new_tokens": req.max_tokens,
                    "temperature": req.temperature,
                    "return_full_text": False
                }
            },
            timeout=60
        )
        if hf_resp.status_code == 200:
            content = hf_resp.json()[0]["generated_text"]
            return {
                "id": "chimera-hf",
                "object": "chat.completion", 
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": content.strip()},
                    "finish_reason": "stop"
                }]
            }
    except Exception as e:
        print(f"HF failed: {e}")
    
    return {"error": "All providers failed"}, 502

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7861)
