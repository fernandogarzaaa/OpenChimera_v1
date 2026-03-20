# CHIMERA Controller (chimera-control)

## Description
This skill teaches OpenClaw how to monitor and control the local CHIMERA Ultimate LLM stack running on the NVIDIA RTX 2060 (6GB VRAM). It provides instructions on querying active models, checking system health, and monitoring VRAM usage.

## Endpoints

CHIMERA Ultimate exposes an OpenAI-compatible API and custom health/status endpoints at `http://localhost:7870`.

### 1. Check Active Models
To see which local LLMs are currently loaded into the RTX 2060:
```powershell
Invoke-RestMethod -Uri "http://localhost:7870/v1/models" -Method Get
```
Or using curl:
```bash
curl http://localhost:7870/v1/models
```
**Usage:** Use this when you need to know which model is actively serving requests (e.g., `llama3-8b`, `mistral-7b`) or to verify that a model has successfully loaded into VRAM.

### 2. Check System Health & RTX 2060 Status
To monitor the health of the CHIMERA server and check NVIDIA RTX 2060 VRAM utilization:
```powershell
Invoke-RestMethod -Uri "http://localhost:7870/health" -Method Get
# Alternatively, if a specific status endpoint is used:
Invoke-RestMethod -Uri "http://localhost:7870/api/status" -Method Get
```
Or using curl:
```bash
curl http://localhost:7870/health
```
**Usage:** Use this to ensure the local LLM server is online, responsive, and to check if the 6GB VRAM limit of the RTX 2060 is being saturated. If VRAM usage is at capacity, you may need to offload or swap to a smaller quantized model.

## Operational Guidelines
- **Always Verify First:** Before attempting to route complex local LLM queries, check `v1/models` to ensure the correct model is loaded.
- **VRAM Constraints:** The target hardware is an NVIDIA RTX 2060 with 6GB VRAM. If the user requests a model swap, ensure the target model is adequately quantized (e.g., 4-bit or 5-bit GGUF/AWQ) to fit within this constraint.
- **Failover:** If `http://localhost:7870` is unreachable, alert the user that the CHIMERA Ultimate server is offline and fall back to remote APIs (< 10% API fallback as per core preferences).
