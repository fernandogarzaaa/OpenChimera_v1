import os
import subprocess
import time

# Configuration
GATEWAY_PATH = r"D:\openclaw\gateway" # Adjust path as necessary
GATEWAY_CMD = "openclaw gateway restart"

def restart_gateway():
    try:
        print("[System] Initiating controlled Gateway restart...")
        # Graceful shutdown/restart command
        subprocess.run(GATEWAY_CMD, shell=True, check=True)
        print("[System] Gateway restart command issued.")
        
        # Verify persistence (Optional: ping service if available)
        print("[System] Sessions should remain intact in the local database/gateway cache.")
    except subprocess.CalledProcessError as e:
        print(f"[System] Failed to restart Gateway: {e}")

if __name__ == "__main__":
    restart_gateway()
