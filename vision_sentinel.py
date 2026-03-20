import time
import os
import subprocess

# This script is a wrapper for the OpenClaw vision sentinel
# It monitors D:\openclaw\temp\cctv_latest.jpg and detects hand raises
# by calling the 'image' tool via the OpenClaw CLI if available or
# by simply looping and notifying the agent.

def run_sentinel():
    filepath = r"D:\openclaw\temp\cctv_latest.jpg"
    last_mtime = 0
    print("Sentinel started.")
    while True:
        try:
            if os.path.exists(filepath):
                mtime = os.path.getmtime(filepath)
                if mtime > last_mtime:
                    last_mtime = mtime
                    # Trigger analysis - since we can't directly call the tool here,
                    # we print a specific marker to be picked up by the logger
                    print(f"TRIGGER_ANALYSIS:{filepath}")
            time.sleep(10)
        except Exception as e:
            time.sleep(10)

if __name__ == "__main__":
    run_sentinel()
