"""
CHIMERA Local LLM Manager
Manages multiple local LLM endpoints (llama.cpp, Ollama, vLLM)
with health monitoring, load balancing, and automatic fallback.

Optimized for NVIDIA RTX 2060 (6GB VRAM)
"""

import logging
import time
import threading
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
import requests

logger = logging.getLogger("chimera-local")


@dataclass
class ModelStats:
    """Performance statistics for a local model."""
    model_name: str
    endpoint: str
    status: str = "unknown"  # healthy, degraded, offline
    last_check: float = 0.0
    avg_latency_ms: float = 0.0
    tokens_per_sec: float = 0.0
    total_requests: int = 0
    failed_requests: int = 0
    vram_usage_gb: float = 0.0
    context_length: int = 4096
    quantization: str = "unknown"


@dataclass
class ModelConfig:
    """Configuration for a local model."""
    name: str
    endpoint: str
    model_path: str
    quantization: str
    n_gpu_layers: int
    context_length: int = 4096
    priority: int = 1  # Lower = higher priority
    max_batch_size: int = 512


class LocalLLMManager:
    """
    Manages multiple local LLM endpoints with:
    - Health monitoring
    - Automatic failover
    - Load balancing
    - Performance tracking
    """
    
    def __init__(self, config_path: Optional[str] = None):
        self.models: Dict[str, ModelStats] = {}
        self.configs: Dict[str, ModelConfig] = {}
        self._lock = threading.Lock()
        self._health_check_interval = 30  # seconds
        self._health_thread: Optional[threading.Thread] = None
        self._running = False
        
        # Default RTX 2060 optimized configs
        self._default_configs = [
            ModelConfig(
                name="qwen2.5-7b",
                endpoint="http://localhost:8080",
                model_path="models/qwen2.5-7b-instruct-q4_k_m.gguf",
                quantization="Q4_K_M",
                n_gpu_layers=35,
                context_length=4096,
                priority=1,
            ),
            ModelConfig(
                name="gemma-2-9b",
                endpoint="http://localhost:8081",
                model_path="models/gemma-2-9b-it-q4_k_m.gguf",
                quantization="Q4_K_M",
                n_gpu_layers=35,
                context_length=4096,
                priority=2,
            ),
            ModelConfig(
                name="llama-3.2-3b",
                endpoint="http://localhost:8082",
                model_path="models/llama-3.2-3b-instruct-q8_0.gguf",
                quantization="Q8_0",
                n_gpu_layers=25,
                context_length=4096,
                priority=3,
            ),
            ModelConfig(
                name="phi-3.5-mini",
                endpoint="http://localhost:8083",
                model_path="models/phi-3.5-mini-instruct-q8_0.gguf",
                quantization="Q8_0",
                n_gpu_layers=25,
                context_length=4096,
                priority=4,
            ),
        ]
        
        self._initialize_defaults()
    
    def _initialize_defaults(self):
        """Initialize with default RTX 2060 optimized models."""
        for config in self._default_configs:
            self.configs[config.name] = config
            self.models[config.name] = ModelStats(
                model_name=config.name,
                endpoint=config.endpoint,
                quantization=config.quantization,
                context_length=config.context_length,
            )
    
    def start_health_monitoring(self):
        """Start background health monitoring thread."""
        if self._running:
            return
        
        self._running = True
        self._health_thread = threading.Thread(
            target=self._health_monitor_loop,
            daemon=True,
            name="LocalLLM-HealthMonitor"
        )
        self._health_thread.start()
        logger.info("🏥 Local LLM health monitoring started")
    
    def stop_health_monitoring(self):
        """Stop background health monitoring."""
        self._running = False
        if self._health_thread:
            self._health_thread.join(timeout=5)
            logger.info("🏥 Local LLM health monitoring stopped")
    
    def _health_monitor_loop(self):
        """Background loop to check model health."""
        while self._running:
            for name, stats in self.models.items():
                self._check_model_health(name, stats)
            time.sleep(self._health_check_interval)
    
    def _check_model_health(self, name: str, stats: ModelStats):
        """Check health of a single model endpoint."""
        try:
            start = time.time()
            resp = requests.get(f"{stats.endpoint}/health", timeout=5)
            latency = (time.time() - start) * 1000
            
            with self._lock:
                if resp.status_code == 200:
                    stats.status = "healthy"
                    stats.last_check = time.time()
                    # Update running average latency
                    n = stats.total_requests or 1
                    stats.avg_latency_ms = (stats.avg_latency_ms * n + latency) / (n + 1)
                else:
                    stats.status = "degraded"
                    stats.last_check = time.time()
        except Exception as e:
            with self._lock:
                stats.status = "offline"
                stats.last_check = time.time()
                logger.debug(f"Model {name} health check failed: {e}")
    
    def get_healthy_models(self, min_priority: int = 1, max_priority: int = 10) -> List[str]:
        """Get list of healthy model names, sorted by priority."""
        healthy = []
        with self._lock:
            for name, stats in self.models.items():
                config = self.configs.get(name)
                if (stats.status == "healthy" and 
                    config and 
                    min_priority <= config.priority <= max_priority):
                    healthy.append((config.priority, name))
        
        healthy.sort(key=lambda x: x[0])
        return [name for _, name in healthy]
    
    def get_best_model(self, query_type: str = "general") -> Optional[str]:
        """
        Get the best available model for a query type.
        
        Args:
            query_type: Type of query (general, code, reasoning, fast)
        
        Returns:
            Model name or None if no models available
        """
        healthy = self.get_healthy_models()
        if not healthy:
            return None
        
        # Simple routing logic - can be enhanced with ML
        if query_type == "fast":
            # Prefer smaller, faster models
            for name in healthy:
                if "3b" in name.lower() or "mini" in name.lower() or "1b" in name.lower():
                    return name
            return healthy[0]
        elif query_type == "code":
            # Prefer Qwen for code
            for name in healthy:
                if "qwen" in name.lower():
                    return name
            return healthy[0]
        elif query_type == "reasoning":
            # Prefer Gemma or larger models
            for name in healthy:
                if "gemma" in name.lower():
                    return name
            return healthy[0]
        else:
            # General: use highest priority
            return healthy[0]
    
    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        max_tokens: int = 256,
        temperature: float = 0.7,
        timeout: float = 30.0,
    ) -> Dict[str, Any]:
        """
        Send chat completion request to a local model.
        
        Args:
            messages: Chat messages in OpenAI format
            model: Model name (auto-select if None)
            max_tokens: Max tokens to generate
            temperature: Sampling temperature
            timeout: Request timeout in seconds
        
        Returns:
            Response dict with content, model, usage, etc.
        """
        if model is None:
            model = self.get_best_model()
        
        if model is None:
            return {
                "error": "No healthy local models available",
                "content": "",
                "model": None,
            }
        
        stats = self.models.get(model)
        if not stats:
            return {
                "error": f"Model {model} not configured",
                "content": "",
                "model": model,
            }
        
        endpoint = stats.endpoint
        payload = {
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        
        try:
            start = time.time()
            resp = requests.post(
                f"{endpoint}/v1/chat/completions",
                json=payload,
                timeout=timeout,
            )
            latency = (time.time() - start) * 1000
            
            resp.raise_for_status()
            data = resp.json()
            
            # Update stats
            with self._lock:
                stats.total_requests += 1
                n = stats.total_requests
                stats.avg_latency_ms = (stats.avg_latency_ms * (n - 1) + latency) / n
            
            # Extract response
            choices = data.get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content", "")
                usage = data.get("usage", {})
                return {
                    "content": content,
                    "model": model,
                    "usage": usage,
                    "latency_ms": latency,
                    "error": None,
                }
            else:
                return {
                    "content": "",
                    "model": model,
                    "error": "No choices in response",
                }
                
        except requests.Timeout:
            with self._lock:
                stats.total_requests += 1
                stats.failed_requests += 1
            logger.warning(f"Model {model} request timed out")
            return {
                "content": "",
                "model": model,
                "error": "Request timeout",
            }
        except Exception as e:
            with self._lock:
                stats.total_requests += 1
                stats.failed_requests += 1
            logger.error(f"Model {model} request failed: {e}")
            return {
                "content": "",
                "model": model,
                "error": str(e),
            }
    
    def chat_completion_with_fallback(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 256,
        temperature: float = 0.7,
        timeout: float = 30.0,
        max_retries: int = 2,
    ) -> Dict[str, Any]:
        """
        Send chat completion with automatic fallback to other models.
        
        Args:
            messages: Chat messages
            max_tokens: Max tokens
            temperature: Temperature
            timeout: Request timeout
            max_retries: Number of fallback attempts
        
        Returns:
            Response dict
        """
        attempted = []
        
        for attempt in range(max_retries + 1):
            # Get best available model not yet attempted
            healthy = self.get_healthy_models()
            available = [m for m in healthy if m not in attempted]
            
            if not available:
                break
            
            # Select model based on attempt number
            if attempt == 0:
                model = self.get_best_model()
            else:
                model = available[0] if available else None
            
            if model is None:
                break
            
            attempted.append(model)
            logger.info(f"Trying local model: {model} (attempt {attempt + 1})")
            
            result = self.chat_completion(
                messages=messages,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                timeout=timeout,
            )
            
            if result.get("content") and not result.get("error"):
                return result
            
            logger.warning(f"Model {model} failed, trying next...")
        
        # All attempts failed
        return {
            "content": "",
            "model": attempted[-1] if attempted else None,
            "error": f"All local models failed (tried: {', '.join(attempted)})",
        }
    
    def get_status(self) -> Dict[str, Any]:
        """Get status of all local models."""
        with self._lock:
            return {
                "models": {
                    name: {
                        "status": stats.status,
                        "endpoint": stats.endpoint,
                        "avg_latency_ms": round(stats.avg_latency_ms, 2),
                        "total_requests": stats.total_requests,
                        "failed_requests": stats.failed_requests,
                        "quantization": stats.quantization,
                        "context_length": stats.context_length,
                        "config": {
                            "priority": self.configs[name].priority if name in self.configs else None,
                            "n_gpu_layers": self.configs[name].n_gpu_layers if name in self.configs else None,
                        }
                    }
                    for name, stats in self.models.items()
                },
                "healthy_count": sum(1 for s in self.models.values() if s.status == "healthy"),
                "total_count": len(self.models),
            }
    
    def add_model(self, config: ModelConfig):
        """Add a new model configuration."""
        with self._lock:
            self.configs[config.name] = config
            self.models[config.name] = ModelStats(
                model_name=config.name,
                endpoint=config.endpoint,
                quantization=config.quantization,
                context_length=config.context_length,
            )
        logger.info(f"Added local model: {config.name}")
    
    def remove_model(self, name: str):
        """Remove a model configuration."""
        with self._lock:
            if name in self.models:
                del self.models[name]
            if name in self.configs:
                del self.configs[name]
        logger.info(f"Removed local model: {name}")


# Singleton instance
_local_llm_manager: Optional[LocalLLMManager] = None


def get_local_llm_manager() -> LocalLLMManager:
    """Get or create the singleton LocalLLMManager instance."""
    global _local_llm_manager
    if _local_llm_manager is None:
        _local_llm_manager = LocalLLMManager()
    return _local_llm_manager
