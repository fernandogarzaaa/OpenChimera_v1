"""
CHIMERA Smart Router - LiteLLM-style unified API
Routes requests to best available model (local, Ollama, HF, OpenRouter)
"""
import os
import random
from typing import Any, Optional
import requests

# Model configurations
MODELS = {
    "gemini_openrouter": {
        "provider": "openrouter",
        "model": "google/gemini-3-pro-preview",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "api_key": "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",
        "max_tokens": 8192,
        "latency": "fast",
        "cost": 0.5,
        "strengths": ["general", "reasoning", "coding"]
    },

    # Local (fastest, free)
    "ollama_phi3": {
        "provider": "ollama",
        "model": "phi3:mini",
        "url": "http://127.0.0.1:11434/api/generate",
        "max_tokens": 512,
        "latency": "fast",
        "cost": 0,
        "strengths": ["general", "fast"]
    },
    "ollama_mistral": {
        "provider": "ollama",
        "model": "mistral",
        "url": "http://127.0.0.1:11434/api/generate",
        "max_tokens": 512,
        "latency": "medium",
        "cost": 0,
        "strengths": ["reasoning", "coding"]
    },
    "ollama_llama3": {
        "provider": "ollama",
        "model": "llama3:instruct",
        "url": "http://127.0.0.1:11434/api/generate",
        "max_tokens": 512,
        "latency": "slow",
        "cost": 0,
        "strengths": ["general", "reasoning"]
    },
    
    # llama.cpp server (CPU)
    "llama_cpp": {
        "provider": "llama_cpp",
        "model": "qwen2.5-7b",
        "url": "http://127.0.0.1:8080/v1/chat/completions",
        "max_tokens": 512,
        "latency": "slow",
        "cost": 0,
        "strengths": ["local", "offline"]
    }
}


class SmartRouter:
    """
    LiteLLM-style router that intelligently selects the best model
    based on task type, latency requirements, and availability
    """
    
import json
import os

class SmartRouter:
    """
    LiteLLM-style router that intelligently selects the best model
    based on task type, latency requirements, and availability
    """
    
    def __init__(self):
        self.models = dict(MODELS)
        self.health_cache = {}
        self._load_free_fallbacks()
        self._load_scouted_registry()
        
    def _load_free_fallbacks(self):
        fallback_file = r"D:\openclaw\chimera_free_fallbacks.json"
        if os.path.exists(fallback_file):
            try:
                with open(fallback_file, "r", encoding="utf-8") as f:
                    fallbacks = json.load(f)
                
                or_key = self.models.get("gemini_openrouter", {}).get("api_key", "")
                
                for idx, model_data in enumerate(fallbacks):
                    model_id = model_data.get("model_id")
                    if not model_id: continue
                    
                    self.models[f"openrouter_free_{idx}"] = {
                        "provider": "openrouter",
                        "model": model_id,
                        "url": "https://openrouter.ai/api/v1/chat/completions",
                        "api_key": or_key,
                        "max_tokens": min(8192, model_data.get("context_length", 8192) // 4),
                        "latency": "medium",
                        "cost": 0,
                        "strengths": model_data.get("strengths", ["general", "fallback"])
                    }
            except Exception as e:
                print(f"Error loading free fallbacks: {e}")

    def _load_scouted_registry(self):
        REGISTRY_FILE = r"D:\openclaw\scouted_models_registry.json"
        if os.path.exists(REGISTRY_FILE):
            try:
                with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
                    models = json.load(f)
                for m in models:
                    self.models[m['model_id']] = {
                        "provider": "openrouter",
                        "model": m['model_id'],
                        "url": "https://openrouter.ai/api/v1/chat/completions",
                        "api_key": self.models.get("gemini_openrouter", {}).get("api_key", ""),
                        "max_tokens": 8192,
                        "latency": "medium",
                        "cost": 0,
                        "strengths": m.get("strengths", ["general", "fallback"])
                    }
                print(f"[SmartRouter] Autonomously loaded {len(models)} scouted models.")
            except:
                pass

        """Find all healthy models"""
        healthy = []
        for name, config in self.models.items():
            if self._check_health(config):
                healthy.append(name)
        return healthy
    
    def _check_health(self, config: dict) -> bool:
        """Check if a model is healthy"""
        try:
            if config["provider"] == "ollama":
                tags_resp = requests.get("http://127.0.0.1:11434/api/tags", timeout=6)
                if tags_resp.status_code != 200:
                    return False
                models = tags_resp.json().get("models", [])
                installed = {m.get("name", "").split(":")[0] for m in models}
                wanted = config["model"].split(":")[0]
                if wanted not in installed:
                    return False

                resp = requests.post(
                    "http://127.0.0.1:11434/api/generate",
                    json={"model": config["model"], "prompt": "ping", "stream": False, "options": {"num_predict": 1}},
                    timeout=20
                )
                return resp.status_code == 200
            elif config["provider"] == "llama_cpp":
                health_url = config["url"].replace("/v1/chat/completions", "/health").replace("localhost", "127.0.0.1")
                resp = requests.get(health_url, timeout=10)
                return resp.status_code == 200
            elif config["provider"] == "openrouter":
                headers = {"Authorization": f"Bearer {config.get('api_key', '')}"}
                resp = requests.get("https://openrouter.ai/api/v1/auth/key", headers=headers, timeout=5)
                return resp.status_code == 200
            elif config["provider"] == "hf":
                return True  # HF has consistent uptime
        except Exception as e:
            self.health_cache[config.get("model", "unknown")] = str(e)
            return False
        return False
    
    def select_model(
        self, 
        task_type: str = "general",
        prefer_speed: bool = True,
        exclude: list = None
    ) -> Optional[str]:
        """
        Select best model for task
        
        Args:
            task_type: "general", "coding", "reasoning", "fast"
            prefer_speed: True for fast responses, False for quality
            exclude: Models to exclude
        """
        exclude = exclude or []
        healthy = self.get_healthy_models()
        
        # Filter excluded
        candidates = [m for m in healthy if m not in exclude]
        
        if not candidates:
            return None
        
        # Score each model
        scored = []
        for name in candidates:
            config = self.models[name]
            score = 0
            
            # Speed preference
            if prefer_speed:
                if config.get("latency") == "fast":
                    score += 3
                elif config.get("latency") == "medium":
                    score += 1
            else:
                if config.get("latency") == "slow":
                    score += 2
            
            # Task match
            strengths = config.get("strengths", [])
            if task_type in strengths:
                score += 4
            
            # Always prefer free models
            if config.get("cost") == 0:
                score += 2
            
            scored.append((name, score))
        
        # Sort by score
        scored.sort(key=lambda x: x[1], reverse=True)
        
        return scored[0][0] if scored else None
    
    async def route(
        self,
        prompt: str,
        task_type: str = "general",
        max_tokens: int = 256,
        temperature: float = 0.7
    ) -> dict:
        """Route request to best model and return response"""
        
        model_name = self.select_model(task_type=task_type)
        
        if not model_name:
            return {"error": "No healthy models available"}
        
        config = self.models[model_name]
        
        try:
            if config["provider"] == "ollama":
                resp = requests.post(
                    config["url"],
                    json={
                        "model": config["model"],
                        "prompt": prompt,
                        "stream": False,
                        "options": {
                            "num_predict": max_tokens,
                            "temperature": temperature
                        }
                    },
                    timeout=120
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return {
                        "content": data.get("response", "").strip(),
                        "model": model_name,
                        "provider": "ollama",
                        "tokens": data.get("eval_count", 0)
                    }
                    
            elif config["provider"] == "openrouter":
                headers = {
                    "Authorization": f"Bearer {config['api_key']}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "http://localhost",
                    "X-Title": "CHIMERA Ultimate"
                }
                resp = requests.post(
                    config["url"],
                    headers=headers,
                    json={
                        "model": config["model"],
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": max_tokens,
                        "temperature": temperature
                    },
                    timeout=120
                )
                if resp.status_code == 200:
                    data = resp.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                    return {
                        "content": content,
                        "model": model_name,
                        "provider": "openrouter",
                        "tokens": data.get("usage", {}).get("completion_tokens", 0)
                    }
            elif config["provider"] == "hf":
                resp = requests.post(
                    config["url"],
                    headers={"Authorization": f"Bearer {config['api_key']}"},
                    json={
                        "inputs": prompt,
                        "parameters": {
                            "max_new_tokens": max_tokens,
                            "temperature": temperature,
                            "return_full_text": False
                        }
                    },
                    timeout=120
                )
                if resp.status_code == 200:
                    data = resp.json()
                    content = data[0].get("generated_text", "").strip()
                    return {
                        "content": content,
                        "model": model_name,
                        "provider": "hf",
                        "tokens": len(content.split())
                    }
                    
            elif config["provider"] == "llama_cpp":
                resp = requests.post(
                    config["url"],
                    json={
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": max_tokens,
                        "temperature": temperature
                    },
                    timeout=120
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return {
                        "content": data["choices"][0]["message"]["content"],
                        "model": model_name,
                        "provider": "llama_cpp",
                        "tokens": data.get("usage", {}).get("completion_tokens", 0)
                    }
                    
        except Exception as e:
            return {"error": str(e), "model": model_name}
        
        return {"error": f"Failed with status {resp.status_code}"}
    
    def get_status(self) -> dict:
        """Get router status"""
        healthy = self.get_healthy_models()
        return {
            "total_models": len(self.models),
            "healthy_models": len(healthy),
            "available": healthy,
            "models": {
                name: {
                    "provider": cfg["provider"],
                    "latency": cfg.get("latency", "unknown"),
                    "cost": cfg.get("cost", "unknown"),
                    "healthy": name in healthy
                }
                for name, cfg in self.models.items()
            }
        }


# Singleton
router = SmartRouter()


# Demo
if __name__ == "__main__":
    import asyncio
    
    async def test():
        status = router.get_status()
        print("Router Status:")
        print(f"  Healthy: {status['healthy_models']}/{status['total_models']}")
        print(f"  Available: {status['available']}")
        
        # Test routing
        print("\nTest: Fast general query")
        result = await router.route("What is 2+2?", task_type="fast")
        print(f"  Model: {result.get('model')}")
        print(f"  Response: {result.get('content', result.get('error'))[:100]}")
        
        print("\nTest: Coding query")
        result = await router.route("Write a hello world in Python", task_type="coding")
        print(f"  Model: {result.get('model')}")
        print(f"  Response: {result.get('content', result.get('error'))[:100]}")
    
    asyncio.run(test())
