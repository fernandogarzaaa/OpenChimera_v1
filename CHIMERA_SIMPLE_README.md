# CHIMERA Simple (Local+HF)

This is a lightweight API server optimized for speed and reliability, bypassing the complex CHIMERA stack's delays.

## Status
- **Port:** 7861
- **Primary:** Local LLM (llama.cpp on port 8080)
- **Fallback:** Hugging Face Inference API (using your token)

## Usage
To use this as your main LLM in OpenClaw or any OpenAI-compatible client:

- **Base URL:** `http://localhost:7861/v1`
- **API Key:** `chimera-local` (or any string)
- **Model:** `chimera-local` (or `qwen2.5-7b`)

## Startup
Run `D:\openclaw\start_chimera_simple.bat` to start the server.

## Note
This server automatically handles failover. If your local model is down or slow, it switches to Hugging Face.
