"""
Hugging Face Inference API Client for CHIMERA
Provides fallback inference using HF's free tier
"""
import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
import httpx

from .config import HF_API_KEY, HF_MODELS

logger = logging.getLogger(__name__)

HF_BASE_URL = "https://api-inference.huggingface.co/models"

@dataclass
class HFResponse:
    model: str
    content: str
    error: str | None = None
    request_id: str | None = None


async def query_hf_model(
    model: str,
    messages: list[dict],
    temperature: float = 0.7,
    max_tokens: int = 256,
) -> HFResponse:
    """Query a single Hugging Face model."""
    request_id = str(uuid.uuid4())
    
    # Convert messages to prompt
    prompt = ""
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role == "user":
            prompt += f"User: {content}\n"
        elif role == "assistant":
            prompt += f"Assistant: {content}\n"
    prompt += "Assistant: "
    
    headers = {
        "Authorization": f"Bearer {HF_API_KEY}",
        "Content-Type": "application/json",
    }
    
    payload = {
        "inputs": prompt,
        "parameters": {
            "max_new_tokens": max_tokens,
            "temperature": temperature,
            "return_full_text": False,
        },
    }
    
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{HF_BASE_URL}/{model}",
                json=payload,
                headers=headers,
                timeout=60.0,
            )
            
            if resp.status_code == 401:
                error_msg = "HF API key invalid or missing"
                logger.error(f"[req:{request_id}] Auth error: {error_msg}")
                return HFResponse(model=model, content="", error=error_msg, request_id=request_id)
            
            if resp.status_code != 200:
                error_msg = f"HTTP {resp.status_code}: {resp.text[:200]}"
                logger.error(f"[req:{request_id}] Error: {error_msg}")
                return HFResponse(model=model, content="", error=error_msg, request_id=request_id)
            
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                content = data[0].get("generated_text", "")
            elif isinstance(data, dict):
                content = data.get("generated_text", "")
            else:
                content = str(data)
            
            logger.info(f"[req:{request_id}] HF success: {model}")
            return HFResponse(model=model, content=content.strip(), request_id=request_id)
            
    except Exception as e:
        error_msg = str(e)
        logger.error(f"[req:{request_id}] Exception: {error_msg}")
        return HFResponse(model=model, content="", error=error_msg, request_id=request_id)


async def query_hf_fallback(
    messages: list[dict],
    temperature: float = 0.7,
    max_tokens: int = 256,
) -> HFResponse:
    """Query HF models as fallback when OpenRouter fails."""
    for model in HF_MODELS:
        logger.info(f"Trying HF model: {model}")
        resp = await query_hf_model(model, messages, temperature, max_tokens)
        if resp.content and not resp.error:
            return resp
    return HFResponse(model="hf-fallback", content="", error="All HF models failed")
