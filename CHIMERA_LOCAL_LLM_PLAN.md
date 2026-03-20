# CHIMERA LOCAL LLM - RTX 2060 Optimization Plan

## Goal
Make CHIMERA QUANTUM LLM truly independent from external APIs by running optimized local models on consumer hardware (RTX 2060 6GB).

---

## Hardware Constraints: RTX 2060

| Spec | Value |
|------|-------|
| VRAM | 6GB GDDR6 |
| CUDA Cores | 1920 |
| Architecture | Turing |
| Max Model Size (4-bit) | ~7-10B parameters |
| Max Model Size (8-bit) | ~3-5B parameters |

---

## Recommended Local Models for RTX 2060

### Primary Models (Fast, Efficient)
1. **Qwen2.5-7B-Instruct-GGUF** (Q4_K_M quantization)
   - VRAM: ~4.5GB
   - Speed: ~25-40 tokens/sec
   - Quality: Excellent for size

2. **Gemma-2-9B-IT-GGUF** (Q4_K_M quantization)
   - VRAM: ~5.5GB
   - Speed: ~20-30 tokens/sec
   - Quality: Strong reasoning

3. **Llama-3.2-3B-Instruct-GGUF** (Q8_0 quantization)
   - VRAM: ~3GB
   - Speed: ~50-80 tokens/sec
   - Quality: Good for fast responses

4. **Phi-3.5-Mini-Instruct-GGUF** (Q8_0 quantization)
   - VRAM: ~2.5GB
   - Speed: ~60-100 tokens/sec
   - Quality: Surprisingly capable

### Fallback Models
- **TinyLlama-1.1B** (Q8_0) - ~1GB VRAM, ultra-fast
- **StableLM-2-1.6B** (Q8_0) - ~1.5GB VRAM

---

## Architecture: Local Inference Stack

```
┌─────────────────────────────────────────────────────────┐
│                 CHIMERA QUANTUM Server                   │
│  (FastAPI - Port 7860)                                  │
└─────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│              Local Model Orchestrator                    │
│  - Model health monitoring                              │
│  - Load balancing across models                         │
│  - Automatic fallback                                   │
└─────────────────────────────────────────────────────────┘
                          │
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
┌─────────────────┐ ┌─────────────┐ ┌─────────────┐
│  llama.cpp      │ │   Ollama    │ │   vLLM      │
│  (GGUF native)  │ │  (optional) │ │  (optional) │
│  Port: 8080     │ │  Port: 11434│ │  Port: 8000 │
└─────────────────┘ └─────────────┘ └─────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────┐
│              NVIDIA RTX 2060 (6GB VRAM)                 │
│  - CUDA 12.x                                            │
│  - cuBLAS acceleration                                  │
│  - GPU offloading (n_gpu_layers)                        │
└─────────────────────────────────────────────────────────┘
```

---

## Implementation Steps

### Phase 1: llama.cpp Server Setup (Core)

1. **Install llama.cpp with CUDA support**
```bash
# Download pre-built binary or build from source
git clone https://github.com/ggerganov/llama.cpp
cd llama.cpp
mkdir build && cd build
cmake .. -DGGML_CUDA=ON -DCMAKE_BUILD_TYPE=Release
cmake --build . --config Release
```

2. **Download quantized models (GGUF format)**
```bash
# Qwen2.5-7B-Instruct (Q4_K_M)
huggingface-cli download Qwen/Qwen2.5-7B-Instruct-GGUF qwen2.5-7b-instruct-q4_k_m.gguf

# Gemma-2-9B-IT (Q4_K_M)
huggingface-cli download google/gemma-2-9b-it-GGUF gemma-2-9b-it-q4_k_m.gguf

# Llama-3.2-3B-Instruct (Q8_0)
huggingface-cli download meta-llama/Llama-3.2-3B-Instruct-GGUF llama-3.2-3b-instruct-q8_0.gguf
```

3. **Start llama.cpp server**
```bash
# Qwen2.5-7B (primary)
.\server.exe -m models\qwen2.5-7b-instruct-q4_k_m.gguf -c 4096 -ngl 35 --port 8080

# Gemma-2-9B (secondary)
.\server.exe -m models\gemma-2-9b-it-q4_k_m.gguf -c 4096 -ngl 35 --port 8081

# Llama-3.2-3B (fast fallback)
.\server.exe -m models\llama-3.2-3b-instruct-q8_0.gguf -c 4096 -ngl 25 --port 8082
```

### Phase 2: Enhanced Local Model Adapter

Create `local_llm_manager.py` with:
- Multi-model health monitoring
- Automatic model switching on failure
- VRAM usage tracking
- Performance metrics (tokens/sec)

### Phase 3: CHIMERA Integration

Update `chimera_server.py` to:
1. Prioritize local models over API calls
2. Use API models only as fallback
3. Implement local consensus voting (multiple local models)
4. Cache aggressively to reduce compute

### Phase 4: Optimization

- **Context quantization**: KV cache compression
- **Speculative decoding**: Use smaller model to draft, larger to verify
- **Batch processing**: Handle multiple requests efficiently
- **Memory mapping**: Load models on-demand

---

## Configuration: RTX 2060 Optimized

### llama.cpp Server Flags
```bash
# Optimal settings for RTX 2060 6GB
-ngl 35              # Offload 35 layers to GPU (adjust per model)
-c 4096              # Context length
-b 512               # Batch size
-ub 512              # Uber batch size
--n-threads 8        # CPU threads
--memory-f32         # Use FP32 for accuracy
--flash-attn         # Enable flash attention (if supported)
```

### Model-Specific n_gpu_layers
| Model | Quantization | VRAM Usage | n_gpu_layers |
|-------|-------------|------------|--------------|
| Qwen2.5-7B | Q4_K_M | ~4.5GB | 35 |
| Gemma-2-9B | Q4_K_M | ~5.5GB | 35 |
| Llama-3.2-3B | Q8_0 | ~3GB | 25 |
| Phi-3.5-Mini | Q8_0 | ~2.5GB | 25 |

---

## Performance Expectations (RTX 2060)

| Model | Quantization | Tokens/sec | First Token | VRAM |
|-------|-------------|------------|-------------|------|
| Phi-3.5-Mini | Q8_0 | 60-100 | <100ms | 2.5GB |
| Llama-3.2-3B | Q8_0 | 50-80 | <150ms | 3GB |
| Qwen2.5-7B | Q4_K_M | 25-40 | <300ms | 4.5GB |
| Gemma-2-9B | Q4_K_M | 20-30 | <400ms | 5.5GB |

---

## Reverse Engineering Approach

### What We're Learning From Each Model

**Qwen Series:**
- Efficient attention mechanisms
- Strong multilingual support
- Good code generation

**Gemma Series:**
- Clean architecture (from Gemini research)
- Strong reasoning capabilities
- Efficient training techniques

**Llama Series:**
- Industry-standard architecture
- Extensive ecosystem
- Well-documented

**Combination Strategy:**
1. Use Qwen for code & technical tasks
2. Use Gemma for reasoning & analysis
3. Use Llama/Phi for fast responses
4. Consensus voting for critical outputs

---

## File Structure

```
D:\appforge-main\infrastructure\clawd-hybrid-rtx\
├── src\
│   ├── chimera_server.py (updated)
│   ├── local_llm_manager.py (NEW)
│   ├── local_model_adapter.py (enhanced)
│   └── models\
│       ├── qwen2.5-7b-instruct-q4_k_m.gguf
│       ├── gemma-2-9b-it-q4_k_m.gguf
│       ├── llama-3.2-3b-instruct-q8_0.gguf
│       └── phi-3.5-mini-instruct-q8_0.gguf
├── llama.cpp\
│   └── server.exe
└── scripts\
    ├── start_local_llms.bat (NEW)
    └── download_models.py (NEW)
```

---

## Next Actions

1. ✅ Install llama.cpp with CUDA support
2. ✅ Download quantized GGUF models
3. ✅ Create `local_llm_manager.py`
4. ✅ Update `chimera_server.py` to prioritize local
5. ✅ Create startup scripts
6. ✅ Test performance on RTX 2060
7. ✅ Optimize based on benchmarks

---

## Independence Metrics

| Metric | Current | Target |
|--------|---------|--------|
| API Dependency | 100% | <10% |
| Local Model Coverage | 0% | 90%+ |
| Response Time | ~2-5s | <1s (local) |
| Cost | $0 (free tier) | $0 (local) |
| Offline Capability | None | Full |

---

**Status:** Ready to implement
**ETA:** Local models operational within 2-3 setup sessions
