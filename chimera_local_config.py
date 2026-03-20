"""
CHIMERA Local LLM Integration - Optimized Autonomy Config
Automatically updated by Evolution Engine.
"""

# Dynamic Configuration for RTX 2060 (6GB VRAM)
# Prioritizing speed and local autonomy

LOCAL_MODELS_CONFIG = {
    "qwen2.5-7b": {
        "endpoint": "http://localhost:8080",
        "model_path": "models/qwen2.5-7b-instruct-q4_k_m.gguf",
        "n_gpu_layers": 30,  # RTX 2060 optimized
        "context_length": 8192, # Higher context
        "priority": 1,
        "port": 8080,
    },
    "llama-3.2-3b": {
        "endpoint": "http://localhost:8082",
        "model_path": "models/Llama-3.2-3B-Instruct-Q8_0.gguf",
        "n_gpu_layers": 40, # Fully GPU accelerated
        "context_length": 8192,
        "priority": 2, # Faster, more efficient
        "port": 8082,
    },
    "phi-3.5-mini": {
        "endpoint": "http://localhost:8083",
        "model_path": "models/Phi-3.5-mini-instruct-Q8_0.gguf",
        "n_gpu_layers": 50,
        "context_length": 16384, # Massive context for efficient RAG
        "priority": 3,
        "port": 8083,
    },
    "mistral-forge": {
        "endpoint": "http://localhost:8084",
        "model_path": "models/mistral-forge-q4_k_m.gguf", # Needs download
        "n_gpu_layers": 35,
        "context_length": 8192,
        "priority": 1,
        "port": 8084,
    },
}

# Optimized server command for GPU acceleration
# Added flash-attn and cont-batching
LLAMA_SERVER_CMD = "{llama_server} -m {model_path} -c {context} -ngl {n_gpu_layers} --port {port} --host 0.0.0.0 -t 4 --flash-attn --cont-batching"
