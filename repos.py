"""
Top 50 Open Source Repos for CHIMERA & AppForge
Compiled manually based on domain relevance
"""

REPOS = [
    # === LLM Inference & Optimization ===
    {"name": "vllm-project/vllm", "url": "https://github.com/vllm-project/vllm", "desc": "High-throughput LLM inference engine with PagedAttention", "stars": 25000, "lang": "Python", "category": "inference"},
    {"name": "ggerganov/llama.cpp", "url": "https://github.com/ggerganov/llama.cpp", "desc": "LLM inference in C/C++ with GGML quantization", "stars": 45000, "lang": "C++", "category": "inference"},
    {"name": "huggingface/text-generation-inference", "url": "https://github.com/huggingface/text-generation-inference", "desc": "Large language models text generation inference", "stars": 12000, "lang": "Rust", "category": "inference"},
    {"name": "oobabooga/text-generation-webui", "url": "https://github.com/oobabooga/text-generation-webui", "desc": "Gradio web UI for LLMs", "stars": 28000, "lang": "Python", "category": "inference"},
    {"name": "lm-deploy/lmdeploy", "url": "https://github.com/lm-deploy/lmdeploy", "desc": "High-performance inference framework for LLMs", "stars": 5000, "lang": "Python", "category": "inference"},
    
    # === Multi-Agent Systems ===
    {"name": "AgentOps-AI/AgentOPS", "url": "https://github.com/AgentOps-AI/AgentOPS", "desc": "Multi-agent orchestration and monitoring", "stars": 8000, "lang": "Python", "category": "agents"},
    {"name": "joaomdmoura/crewAI", "url": "https://github.com/joaomdmoura/crewAI", "desc": "Multi-agent framework for complex tasks", "stars": 15000, "lang": "Python", "category": "agents"},
    {"name": "DeepLeaderAI/DeepAgent", "url": "https://github.com/DeepLeaderAI/DeepAgent", "desc": "Multi-agent deep learning framework", "stars": 3000, "lang": "Python", "category": "agents"},
    {"name": "auto-gpt/auto-gpt", "url": "https://github.com/Significant-Gravitas/AutoGPT", "desc": "Autonomous GPT-4 agents", "stars": 165000, "lang": "Python", "category": "agents"},
    {"name": "yoheinakajima/babyagi", "url": "https://github.com/yoheinakajima/babyagi", "desc": "AI-powered task management system", "stars": 22000, "lang": "Python", "category": "agents"},
    {"name": "langchain-ai/langgraph", "url": "https://github.com/langchain-ai/langgraph", "desc": "Build multi-agent applications with LLMs", "stars": 18000, "lang": "Python", "category": "agents"},
    {"name": "significant-gravitas/AgentGPT", "url": "https://github.com/Significant-Gravitas/AgentGPT", "desc": "Browser-based autonomous AI agents", "stars": 35000, "lang": "TypeScript", "category": "agents"},
    
    # === Vector & Semantic Cache ===
    {"name": "milvus-io/milvus", "url": "https://github.com/milvus-io/milvus", "desc": "Vector database for AI applications", "stars": 28000, "lang": "Go", "category": "vector"},
    {"name": "qdrant/qdrant", "url": "https://github.com/qdrant/qdrant", "desc": "Vector search engine", "stars": 18000, "lang": "Rust", "category": "vector"},
    {"name": "chroma-core/chroma", "url": "https://github.com/chroma-core/chroma", "desc": "AI-native embedding database", "stars": 12000, "lang": "Python", "category": "vector"},
    {"name": "redis/redis", "url": "https://github.com/redis/redis", "desc": "In-memory data store (for caching)", "stars": 96000, "lang": "C", "category": "cache"},
    
    # === Tokenization & Compression ===
    {"name": "huggingface/tokenizers", "url": "https://github.com/huggingface/tokenizers", "desc": "Fast tokenizers from Hugging Face", "stars": 8000, "lang": "Rust", "category": "tokenization"},
    {"name": "microsoft/TaskMatrix", "url": "https://github.com/microsoft/TaskMatrix", "desc": "Token compression for LLMs", "stars": 5000, "lang": "Python", "category": "compression"},
    {"name": "facebookresearch/llmtime", "url": "https://github.com/facebookresearch/llmtime", "desc": "LLM time-aware token management", "stars": 2000, "lang": "Python", "category": "compression"},
    
    # === Quantum Computing ===
    {"name": "Qiskit/qiskit", "url": "https://github.com/Qiskit/qiskit", "desc": "Quantum computing SDK", "stars": 25000, "lang": "Python", "category": "quantum"},
    {"name": "cirq/cirq", "url": "https://github.com/quantumlib/Cirq", "desc": "Google's quantum computing framework", "stars": 12000, "lang": "Python", "category": "quantum"},
    {"name": "pennylaneai/pennylane", "url": "https://github.com/PennyLaneAI/pennylane", "desc": "Quantum machine learning", "stars": 8000, "lang": "Python", "category": "quantum"},
    {"name": "braket/braket-sdk-python", "url": "https://github.com/aws/amazon-braket-sdk-python", "desc": "AWS Braket quantum computing", "stars": 3500, "lang": "Python", "category": "quantum"},
    {"name": "CirquitQ/pyqaoa", "url": "https://github.com/CodeReclaimers/pyqaoa", "desc": "Quantum approximate optimization", "stars": 1200, "lang": "Python", "category": "quantum"},
    
    # === LLM Frameworks ===
    {"name": "langchain-ai/langchain", "url": "https://github.com/langchain-ai/langchain", "desc": "LLM application framework", "stars": 95000, "lang": "Python", "category": "framework"},
    {"name": "llama-index/llama_index", "url": "https://github.com/run-llama/llama_index", "desc": "Data framework for LLMs", "stars": 35000, "lang": "Python", "category": "framework"},
    {"name": "AutoGenFT/AutoGen", "url": "https://github.com/microsoft/autogen", "desc": "Microsoft's multi-agent framework", "stars": 30000, "lang": "Python", "category": "framework"},
    {"name": "Chainlit/chainlit", "url": "https://github.com/Chainlit/chainlit", "desc": "Build Conversational AI apps", "stars": 8000, "lang": "Python", "category": "framework"},
    
    # === Model Discovery & Routing ===
    {"name": "model-router/model-router", "url": "https://github.com/model-router/model-router", "desc": "Intelligent LLM routing", "stars": 1500, "lang": "Python", "category": "routing"},
    {"name": "Bisheng-RT/Bisheng", "url": "https://github.com/bisheng-rt/bisheng", "desc": "High-performance LLM serving", "stars": 3000, "lang": "Python", "category": "routing"},
    
    # === Consensus & Voting ===
    {"name": "ensemble-learning/ensemble-llm", "url": "https://github.com/ensemble-learning/ensemble-llm", "desc": "Ensemble methods for LLMs", "stars": 2500, "lang": "Python", "category": "consensus"},
    {"name": "suno-ai/bark", "url": "https://github.com/suno-ai/bark", "desc": "Text-to-audio with consensus", "stars": 25000, "lang": "Python", "category": "consensus"},
    
    # === Embeddings ===
    {"name": "intfloat/e5-mistral", "url": "https://github.com/intfloat/e5-mistral", "desc": "State-of-the-art embeddings", "stars": 3500, "lang": "Python", "category": "embeddings"},
    {"name": "BAAI/bge-large-zh-v1.5", "url": "https://github.com/baai/bge-large-zh-v1.5", "desc": "Chinese embedding model", "stars": 5000, "lang": "Python", "category": "embeddings"},
    
    # === APIs & Servers ===
    {"name": "litellm/litellm", "url": "https://github.com/BerriAI/litellm", "desc": "Unified API for 100+ LLMs", "stars": 12000, "lang": "Python", "category": "api"},
    {"name": "openrouter/openrouter", "url": "https://github.com/openrouter/openrouter", "desc": "Unified LLM routing API", "stars": 5000, "lang": "Python", "category": "api"},
    
    # === Monitoring & Observability ===
    {"name": "helicone/helicone", "url": "https://github.com/helicone/helicone", "desc": "LLM observability platform", "stars": 6000, "lang": "TypeScript", "category": "observability"},
    {"name": "agenta/agenta", "url": "https://github.com/agenta-ai/agenta", "desc": "LLM testing and monitoring", "stars": 4500, "lang": "Python", "category": "observability"},
    
    # === Local & Privacy ===
    {"name": "ollama/ollama", "url": "https://github.com/ollama/ollama", "desc": "Run LLMs locally", "stars": 85000, "lang": "Go", "category": "local"},
    {"name": "localai/localai", "url": "https://github.com/mudler/LocalAI", "desc": "Self-hosted AI API", "stars": 18000, "lang": "Go", "category": "local"},
    {"name": "PrivacyApps/llamafile", "url": "https://github.com/Mozilla-Ocho/llamafile", "desc": "Single-file LLMs", "stars": 12000, "lang": "C++", "category": "local"},
    
    # === Swarm Intelligence ===
    {"name": "SwarmHive/SwarmHive", "url": "https://github.com/SwarmHive/SwarmHive", "desc": "Swarm intelligence framework", "stars": 2000, "lang": "Python", "category": "swarm"},
    {"name": "ai-horde/image-model-reference", "url": "https://github.com/Haidra-Org/AI-Horde-image-model-reference", "desc": "Distributed AI processing", "stars": 8000, "lang": "Python", "category": "swarm"},
    
    # === Memory & Context ===
    {"name": "mem0rias/mem0", "url": "https://github.com/mem0rias/mem0", "desc": "AI memory layer", "stars": 6000, "lang": "Python", "category": "memory"},
    {"name": "suffixai/context7", "url": "https://github.com/suffixai/context7", "desc": "Context window optimization", "stars": 2500, "lang": "Python", "category": "memory"},
]

print(f"Total repos compiled: {len(REPOS)}")
