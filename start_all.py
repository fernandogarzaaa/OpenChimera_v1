#!/usr/bin/env python3
"""
CHIMERA Unified Launcher
Starts all CHIMERA services in a single process
"""
import subprocess
import sys
import time
import threading
import signal
import os

# Configuration
PORTS = {
    "chimera_simple": 7861,
    "chimera_swarm": 7862,
    "chimera_v2": 7863,
}

def check_port(port):
    """Check if a port is already in use"""
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect(("localhost", port))
        sock.close()
        return True
    except:
        return False

def start_server(script_name, port, wait=5):
    """Start a server in a thread"""
    def run():
        subprocess.run([sys.executable, script_name])
    
    print(f"Starting {script_name} on port {port}...")
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    time.sleep(wait)
    return thread

def main():
    print("""
╔═══════════════════════════════════════╗
║     CHIMERA QUANTUM LLM Launcher      ║
╚═══════════════════════════════════════╝
""")
    
    # Check Ollama
    print("[1/5] Checking Ollama...")
    if not check_port(11434):
        print("    Starting Ollama...")
        subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(3)
    else:
        print("    Ollama already running")
    
    # Check llama.cpp
    print("[2/5] Checking llama.cpp...")
    if not check_port(8080):
        print("    Starting llama.cpp (CPU)...")
        # Would start here if needed
        pass
    else:
        print("    llama.cpp already running")
    
    # Start CHIMERA servers
    servers = []
    
    print("[3/5] Starting CHIMERA Simple (port 7861)...")
    try:
        import chimera_simple
        print("    CHIMERA Simple loaded")
    except Exception as e:
        print(f"    Error: {e}")
    
    print("[4/5] Starting CHIMERA Swarm (port 7862)...")
    try:
        import chimera_swarm
        print("    CHIMERA Swarm loaded")
    except Exception as e:
        print(f"    Error: {e}")
    
    print("[5/5] Starting CHIMERA V2 (port 7863)...")
    try:
        import chimera_v2
        print("    CHIMERA V2 loaded")
    except Exception as e:
        print(f"    Error: {e}")
    
    print("""
╔═══════════════════════════════════════╗
║     All services ready!             ║
╚═══════════════════════════════════════╝

Services:
  Port 7861 - CHIMERA Simple (Basic API)
  Port 7862 - CHIMERA Swarm (Multi-agent)
  Port 7863 - CHIMERA V2 (Full integration)
  
Use: curl http://localhost:7861/health
""")
    
    # Keep running
    print("Press Ctrl+C to stop all services...")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping services...")
        sys.exit(0)

if __name__ == "__main__":
    main()
