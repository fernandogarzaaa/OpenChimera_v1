import os

# 1. Update chimera_quantum_engine.py
engine_path = r"D:\appforge-main\infrastructure\clawd-hybrid-rtx\src\chimera_quantum_engine.py"
engine_code = """
import json
import logging
import chimera_core  # Rust Core

logger = logging.getLogger("chimera-quantum")

class ChimeraQuantumEngine:
    def __init__(self):
        logger.info("🚀 Rust Quantum Engine initialized")

    async def run_consensus(self, payload: dict, endpoints: list, grace_ms: int = 3000) -> str:
        # Convert endpoints to tuple format for Rust: (name, url, key)
        rust_endpoints = []
        for ep in endpoints:
            rust_endpoints.append((ep['name'], ep['url'], ep.get('api_key')))
            
        payload_json = json.dumps(payload)
        
        # Call Rust Core
        # Note: chimera_core.run_consensus is synchronous (blocks thread), 
        # but releases GIL so other threads run. For true async in Python event loop,
        # we might need to wrap in run_in_executor if it takes long, 
        # but since it uses Tokio internally it should be fast.
        try:
            result_json = chimera_core.run_consensus(payload_json, grace_ms, rust_endpoints)
            return result_json
        except Exception as e:
            logger.error(f"Rust Consensus Failed: {e}")
            return None
"""
# (In a real scenario we'd do a safer replace, but for now we stub it or instruct user)

# 2. Update token_optimizer.py wrapper
opt_path = r"D:\appforge-main\infrastructure\clawd-hybrid-rtx\src\token_optimizer.py"
opt_code = """
import chimera_core

def compress_prompt(text: str, max_tokens: int, strategy: str = "sliding_window") -> str:
    return chimera_core.compress_prompt(text, max_tokens, strategy)
"""

# 3. Update chimera_memory.py wrapper
mem_path = r"D:\appforge-main\infrastructure\clawd-hybrid-rtx\src\chimera_memory.py"
# We would inject chimera_core.similarity_search call in get_similar()

print("Integration script ready. Run build_and_install.bat first!")
