"""
CHIMERA Local LLM Integration Module
Integrates local llama.cpp servers with CHIMERA QUANTUM

Provides:
- Local model priority routing
- Automatic fallback to API
- Health monitoring
- Multi-model consensus

Usage:
    from chimera_local_integration import LocalLLMClient, should_use_local
    
    if should_use_local():
        client = LocalLLMClient()
        response = await client.chat_completion(messages)
    else:
        # Fall back to API
        pass
"""

import asyncio
import aiohttp
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger("chimera-local")


@dataclass
class LocalModelEndpoint:
    """Configuration for a local model endpoint."""
    name: str
    url: str
    priority: int
    max_tokens: int = 4096
    healthy: bool = True


# RTX 2060 Optimized Model Endpoints
LOCAL_MODELS = [
    LocalModelEndpoint(
        name="qwen2.5-7b",
        url="http://localhost:8080",
        priority=1,
        max_tokens=4096,
    ),
    LocalModelEndpoint(
        name="gemma-2-9b",
        url="http://localhost:8081",
        priority=2,
        max_tokens=4096,
    ),
    LocalModelEndpoint(
        name="llama-3.2-3b",
        url="http://localhost:8082",
        priority=3,
        max_tokens=4096,
    ),
    LocalModelEndpoint(
        name="phi-3.5-mini",
        url="http://localhost:8083",
        priority=4,
        max_tokens=4096,
    ),
]


class LocalLLMClient:
    """Client for local LLM servers with failover support."""
    
    def __init__(self, models: Optional[List[LocalModelEndpoint]] = None):
        self.models = models or LOCAL_MODELS
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=60),
            headers={"Content-Type": "application/json"},
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def check_health(self, model: LocalModelEndpoint) -> bool:
        """Check if a local model endpoint is healthy."""
        try:
            async with self.session.get(f"{model.url}/health") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("status") == "ok"
                # 503 means still loading, not unhealthy
                return resp.status == 503
        except Exception as e:
            logger.debug(f"Health check failed for {model.name}: {e}")
            return False
    
    async def get_healthy_models(self) -> List[LocalModelEndpoint]:
        """Get list of healthy models sorted by priority."""
        healthy = []
        for model in self.models:
            if await self.check_health(model):
                healthy.append(model)
        return sorted(healthy, key=lambda m: m.priority)
    
    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 256,
        temperature: float = 0.7,
        model: Optional[str] = None,
        fallback_to_api: bool = True,
    ) -> Dict[str, Any]:
        """
        Send chat completion request to local models with failover.
        
        Args:
            messages: List of chat messages
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            model: Specific model name (auto-select if None)
            fallback_to_api: Whether to fall back to API if all local fail
            
        Returns:
            Response dict with content, model, usage, etc.
        """
        payload = {
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        
        # If specific model requested, try it first
        if model:
            target = next((m for m in self.models if m.name == model), None)
            if target:
                result = await self._try_model(target, payload)
                if result:
                    return result
        
        # Otherwise, try all healthy models in priority order
        healthy_models = await self.get_healthy_models()
        
        for target in healthy_models:
            result = await self._try_model(target, payload)
            if result:
                return result
            logger.warning(f"Model {target.name} failed, trying next...")
        
        # All local models failed
        if fallback_to_api:
            logger.error("All local models failed, API fallback required")
            return {
                "error": "All local models failed",
                "fallback_required": True,
                "content": None,
            }
        else:
            raise RuntimeError("All local models failed and fallback disabled")
    
    async def _try_model(
        self,
        model: LocalModelEndpoint,
        payload: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Try a single model endpoint."""
        try:
            async with self.session.post(
                f"{model.url}/v1/chat/completions",
                json=payload,
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return {
                        "content": data["choices"][0]["message"]["content"],
                        "model": model.name,
                        "usage": data.get("usage", {}),
                        "local": True,
                        "error": None,
                    }
                else:
                    logger.warning(f"Model {model.name} returned {resp.status}")
                    return None
        except Exception as e:
            logger.warning(f"Model {model.name} error: {e}")
            return None
    
    async def chat_completion_with_consensus(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 256,
        temperature: float = 0.7,
        min_agreement: int = 2,
    ) -> Dict[str, Any]:
        """
        Query multiple local models and return consensus response.
        
        Args:
            messages: Chat messages
            max_tokens: Max tokens
            temperature: Temperature
            min_agreement: Minimum number of models that must agree
            
        Returns:
            Best response with metadata about consensus
        """
        healthy = await self.get_healthy_models()
        if len(healthy) < min_agreement:
            logger.warning(f"Not enough healthy models for consensus ({len(healthy)} < {min_agreement})")
            # Fall back to single model
            return await self.chat_completion(messages, max_tokens, temperature)
        
        # Query all healthy models in parallel
        payload = {
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        
        tasks = [self._try_model(model, payload) for model in healthy]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Collect successful responses
        responses = []
        for i, result in enumerate(results):
            if isinstance(result, dict) and result.get("content"):
                responses.append({
                    "model": healthy[i].name,
                    "content": result["content"],
                })
        
        if not responses:
            return {"error": "All models failed", "content": None}
        
        # Simple consensus: return first response (can be enhanced)
        # TODO: Implement actual consensus voting based on content similarity
        return {
            "content": responses[0]["content"],
            "model": responses[0]["model"],
            "consensus_models": [r["model"] for r in responses],
            "consensus_count": len(responses),
            "local": True,
            "error": None,
        }


def should_use_local(
    query_type: str = "general",
    force_local: bool = False,
) -> bool:
    """
    Determine if local models should be used for this query.
    
    Args:
        query_type: Type of query (fast, code, reasoning, general)
        force_local: Always use local if True
        
    Returns:
        True if local models should be used
    """
    if force_local:
        return True
    
    # Always use local for these types
    local_preferred = ["fast", "simple", "short"]
    if query_type in local_preferred:
        return True
    
    # Use local for code and reasoning too (our models are good at this)
    return True  # Default to local for everything now


async def test_local_servers():
    """Test all local servers and print status."""
    print("🧪 Testing CHIMERA Local LLM Servers")
    print("=" * 50)
    
    async with LocalLLMClient() as client:
        for model in LOCAL_MODELS:
            healthy = await client.check_health(model)
            status = "✅ Healthy" if healthy else "❌ Unavailable"
            print(f"{model.name:20} ({model.url}) - {status}")
    
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(test_local_servers())
