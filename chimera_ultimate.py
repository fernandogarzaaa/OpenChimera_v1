import os
import sys
import uvicorn
from fastapi import FastAPI
from dotenv import load_dotenv

load_dotenv()

# Secure Environment Configuration (AETHER Standard)
OPENCLAW_HOME = os.getenv("OPENCLAW_HOME", "/opt/openclaw")
CHIMERA_PORT = int(os.getenv("CHIMERA_PORT", "7870"))
GPU_LAYERS = int(os.getenv("LLAMA_CPP_GPU_LAYERS", "0"))

app = FastAPI(title="CHIMERA ULTIMATE SERVER", version="1.0.0")

@app.get("/health")
def health_check():
    return {
        "status": "online",
        "gpu_layers_active": GPU_LAYERS,
        "mode": "hybrid-consensus",
        "privacy": "AETHER-Secured"
    }

if __name__ == "__main__":
    print(f"⚡ CHIMERA ULTIMATE INITIALIZING ⚡")
    print(f"⚙️ Hardware Profile: RTX Optimized (GPU Layers: {GPU_LAYERS})")
    print(f"🔌 Binding to port {CHIMERA_PORT}...")
    
    # Run the server dynamically instead of hardcoding port 7870
    uvicorn.run(app, host="0.0.0.0", port=CHIMERA_PORT, log_level="info")