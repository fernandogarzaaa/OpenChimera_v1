# CHIMERA Quantum API - HuggingFace Spaces

## Deploy to HuggingFace Spaces

### Option 1: Manual Deploy

1. Go to https://huggingface.co/spaces
2. Create new Space → **FastAPI**
3. Upload these files:
   - `chimera_hf.py` (the API)
   - `requirements.txt`
   - `README.md`

4. Add secrets:
   - `HF_API_KEY` = your HuggingFace token

### Option 2: CLI Deploy

```bash
# Install huggingface_hub
pip install huggingface_hub

# Login
huggingface-cli login

# Create space
huggingface-cli space create chimera-api

# Push files
git add .
git commit -m "Add CHIMERA API"
git push
```

## Files Needed

### requirements.txt
```
fastapi
uvicorn
pydantic
requests
python-multipart
```

### README.md
```
---
title: CHIMERA Quantum API
emoji: ⚡
colorFrom: purple
colorTo: pink
sdk: streamlit
sdk_version: 0.4.0
app_port: 7861
---

# CHIMERA Quantum LLM API

OpenAI-compatible API powered by HuggingFace Inference.
```

## Usage

Once deployed, use:
```
Base URL: https://your-space.hf.space/v1
API Key: any (not required)
Model: chimera-local, qwen-turbo, mistral, llama3
```
