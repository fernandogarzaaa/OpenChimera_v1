import os
import time
import json
import logging
import requests
import subprocess
from typing import Optional, Dict, Any

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger("VRAM_Balancer")

# Configuration
LLAMA_CPP_HOST = os.getenv("LLAMA_CPP_HOST", "http://localhost:8080")
# RTX 2060 has 6GB of VRAM (approx 6144 MB)
MAX_VRAM_MB = 6144
# Safety margin to avoid OOM crashes
VRAM_SAFETY_MARGIN_MB = 500

class VRAMBalancer:
    """
    Hardware-aware VRAM monitor and model lifecycle manager for RTX 2060 (6GB).
    Interfaces with a local llama.cpp server to dynamically load/unload models.
    """
    def __init__(self, host: str = LLAMA_CPP_HOST):
        self.host = host.rstrip('/')
        
    def get_current_vram_usage(self) -> int:
        """
        Queries nvidia-smi for the current VRAM usage in MB.
        Returns 0 if nvidia-smi fails (fallback/mock mode).
        """
        try:
            result = subprocess.check_output(
                ['nvidia-smi', '--query-gpu=memory.used', '--format=csv,nounits,noheader'],
                encoding='utf-8'
            )
            return int(result.strip().split('\n')[0])
        except Exception as e:
            logger.warning(f"Could not read from nvidia-smi: {e}. Assuming 0 MB usage.")
            return 0

    def get_available_vram(self) -> int:
        """Calculates available VRAM on the RTX 2060 considering the safety margin."""
        used = self.get_current_vram_usage()
        available = MAX_VRAM_MB - used - VRAM_SAFETY_MARGIN_MB
        return max(0, available)

    def unload_current_model(self) -> bool:
        """
        Attempts to unload the current model from the llama.cpp server to free up VRAM.
        Note: Exact endpoint depends on the llama.cpp server version.
        This uses standard OpenAI-compatible or typical llama.cpp management endpoints.
        """
        logger.info("Attempting to unload current model from llama.cpp server...")
        
        # Some llama.cpp configurations support unloading via a specific endpoint or by loading an empty model.
        # We will attempt a common pattern:
        try:
            # 1. Try checking which models are loaded
            models_resp = requests.get(f"{self.host}/v1/models", timeout=5)
            if models_resp.status_code == 200:
                models = models_resp.json().get("data", [])
                for model in models:
                    model_id = model.get("id")
                    if model_id:
                        # Attempt to DELETE the model if the server supports OpenAI-like unloads
                        requests.delete(f"{self.host}/v1/models/{model_id}", timeout=5)
                        logger.info(f"Sent unload request for model: {model_id}")
            
            # 2. Alternatively, try a hypothetical llama.cpp specific unload endpoint
            # requests.post(f"{self.host}/unload", timeout=5)
            
            logger.info("Unload sequence complete. Verifying VRAM recovery...")
            time.sleep(2) # Give it a moment to free memory
            logger.info(f"Current VRAM usage: {self.get_current_vram_usage()} MB")
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to connect to llama.cpp server at {self.host}: {e}")
            return False

    def load_model(self, model_path: str, required_vram_mb: int, context_size: int = 4096) -> bool:
        """
        Loads a new model into the llama.cpp server, but first checks if the 
        RTX 2060 has enough VRAM. If not, unloads the existing model.
        """
        logger.info(f"Task requires loading '{model_path}' (Est. VRAM: {required_vram_mb} MB)")
        
        # Check against absolute hardware limits
        if required_vram_mb > (MAX_VRAM_MB - VRAM_SAFETY_MARGIN_MB):
            logger.error(f"Cannot load model! {required_vram_mb} MB exceeds the safe capacity of the RTX 2060 (6GB).")
            return False

        available_vram = self.get_available_vram()
        logger.info(f"Available VRAM: {available_vram} MB")
        
        if available_vram < required_vram_mb:
            logger.warning(f"Insufficient VRAM ({available_vram} MB < {required_vram_mb} MB). Unloading current models...")
            self.unload_current_model()
            
            # Re-check available VRAM after unload
            available_vram = self.get_available_vram()
            if available_vram < required_vram_mb:
                logger.error(f"Still not enough VRAM after unloading! Available: {available_vram} MB")
                return False
                
        logger.info(f"VRAM sufficient. Proceeding to load model: {model_path}...")
        
        try:
            # Send load request to llama.cpp (endpoint depends on the server fork/features)
            # Some servers use POST /v1/models with the path/configuration
            payload = {
                "model": model_path,
                "n_ctx": context_size,
                "n_gpu_layers": 35 # Assume mostly offloaded for 6GB depending on model size
            }
            # Note: The exact endpoint and payload schema varies by llama.cpp version/wrapper
            # We use a hypothetical standard /load endpoint or /v1/models
            response = requests.post(f"{self.host}/v1/models", json=payload, timeout=30)
            
            if response.status_code in [200, 201]:
                logger.info(f"Successfully loaded model: {model_path}")
                return True
            else:
                logger.error(f"Failed to load model. Server responded: {response.status_code} - {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            logger.error(f"Error communicating with llama.cpp server: {e}")
            return False

if __name__ == "__main__":
    # Example usage / test run
    balancer = VRAMBalancer()
    logger.info("--- RTX 2060 VRAM Balancer Started ---")
    logger.info(f"Initial VRAM Usage: {balancer.get_current_vram_usage()} MB")
    
    # Test a hypothetical model load request
    # E.g. A 7B Q4_K_M model requires roughly 4.5 GB of VRAM
    test_model = "models/llama-3-8b-instruct.Q4_K_M.gguf"
    test_vram_requirement = 4500 # MB
    
    balancer.load_model(test_model, test_vram_requirement)
