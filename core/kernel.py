import threading
import time
from senses.predictive_engine import PredictiveEngine
from core.fim_daemon import FIMDaemon
from core.personality import Personality
from core.bus import EventBus

class Kernel:
    def __init__(self):
        self.bus = EventBus()
        self.personality = Personality()
        self.predictive_engine = PredictiveEngine(self.bus)
        self.fim_daemon = FIMDaemon(self.bus, ["D:/openclaw/AGENTS.md", "D:/openclaw/TOOLS.md"]) 

    def boot(self):
        print("AETHER Booting...")
        # Start threads
        threading.Thread(target=self.predictive_engine.run, daemon=True).start()
        threading.Thread(target=self.fim_daemon.run, daemon=True).start()
        print(f"AETHER Personality Loaded: {self.personality.system_prompt[:50]}...")
        print("AETHER Components Online.")

if __name__ == "__main__":
    k = Kernel()
    k.boot()
    # Keep main alive
    while True: time.sleep(1)
