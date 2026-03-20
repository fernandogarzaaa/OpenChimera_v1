import subprocess
import time
import os

# Create log directory if it doesn't exist
os.makedirs(r"D:\openclaw\logs", exist_ok=True)

# Define tasks to run
def run_stress_task(task_id):
    # This simulates a high-context code generation task using the llama-server
    # In a real environment, this would call the server API.
    # Here, we simulate the high VRAM load.
    log_file = r"D:\openclaw\logs\vram_stress_log.txt"
    with open(log_file, "a") as f:
        f.write(f"Starting task {task_id} at {time.ctime()}\n")
    
    # Simulate workload with a memory-intensive python process
    # Using a list to hold a large amount of data in memory
    try:
        data = ["a" * 1024 * 1024 * 10 for _ in range(100)] # ~1GB allocation
        time.sleep(10) # Simulate 10s of processing
        with open(log_file, "a") as f:
            f.write(f"Task {task_id} completed successfully at {time.ctime()}\n")
    except Exception as e:
        with open(log_file, "a") as f:
            f.write(f"Task {task_id} failed: {e}\n")

# Run 5 tasks consecutively
for i in range(1, 6):
    run_stress_task(i)

# Log swarm scout activity
with open(r"D:\openclaw\logs\vram_stress_log.txt", "a") as f:
    f.write(f"Swarm scout check completed at {time.ctime()}\n")
