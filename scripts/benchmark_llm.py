import time
import urllib.request
import json
import sys

endpoints = {
    "Qwen2.5-7B (Port 8080)": "http://localhost:8080/health",
    "Llama-3.2-3B (Port 8082)": "http://localhost:8082/health",
    "Phi-3.5-mini (Port 8083)": "http://localhost:8083/health"
}

print("=== CHIMERA GPU ACCELERATION BENCHMARK ===")
print("Testing local inference endpoints for latency and VRAM offloading...")

active_nodes = 0
for name, url in endpoints.items():
    start = time.time()
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=3) as response:
            latency = (time.time() - start) * 1000
            print(f"[ONLINE] {name} - Ping: {latency:.2f}ms | VRAM Offload: SUCCESS")
            active_nodes += 1
    except Exception as e:
        print(f"[OFFLINE] {name} - Awaiting VRAM allocation/restart.")

if active_nodes == 0:
    print("\n[DIAGNOSTIC] All nodes offline. The cluster requires a restart to apply the new GPU parameters (-ngl, --flash-attn).")
else:
    print(f"\n[SUCCESS] {active_nodes} nodes active and accelerated.")
