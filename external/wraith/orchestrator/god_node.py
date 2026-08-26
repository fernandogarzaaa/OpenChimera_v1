import logging
import os
import time
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Securely fetch configuration without hardcoding personal data
OPENCLAW_HOME = os.getenv("OPENCLAW_HOME", "/opt/openclaw")
APPFORGE_HOME = os.getenv("APPFORGE_HOME", "/opt/appforge")
ADMIN_PHONE = os.getenv("ADMIN_PHONE_NUMBER", "+10000000000")
GPU_LAYERS = int(os.getenv("LLAMA_CPP_GPU_LAYERS", "0"))


class WraithOrchestrator:
    """
    Project WRAITH: Master Orchestrator (god_node)
    Manages scrapers with exponential backoff and graceful degradation.
    Refactored for Open Source (AETHER Standard).
    """

    def __init__(self):
        self.workspace = OPENCLAW_HOME
        self.max_retries = 5
        self.base_backoff = 2  # seconds

    def log_alert(self, message):
        masked_phone = f"{ADMIN_PHONE[:4]}****{ADMIN_PHONE[-2:]}" if len(ADMIN_PHONE) > 6 else "****"
        print(f"[ALERT -> {masked_phone}]: {message}")

    def run_scraper_task(self, task_id):
        print(f"🚀 WRAITH initializing task {task_id}...")
        print(f"⚙️ Utilizing hardware profile: {GPU_LAYERS} GPU Layers")

        retries = 0
        while retries < self.max_retries:
            try:
                print(f"Attempting extraction... (Attempt {retries + 1}/{self.max_retries})")
                if retries < 2:
                    raise ConnectionError("Target host rejected connection (Simulated instability).")
                print("✅ Extraction successful.")
                return True
            except Exception as e:
                wait_time = self.base_backoff ** retries
                print(f"⚠️ Error: {str(e)}. Exponential backoff: waiting {wait_time}s...")
                time.sleep(wait_time)
                retries += 1

        self.log_alert(f"CRITICAL: Task {task_id} failed after {self.max_retries} retries.")
        return False

    def run(self):
        """
        OpenChimera service entry point.
        Runs the WRAITH orchestrator's default task loop.
        Called by WraithService in a background thread.

        The bundled scraper task is a simulation (it deliberately raises and
        retries with backoff). It is opt-in so a normal boot stays quiet and
        fast — set WRAITH_RUN_DEMO=1 to run the sample task loop.
        """
        log = logging.getLogger("openchimera.wraith")
        default_task = os.getenv("WRAITH_DEFAULT_TASK", "CHIMERA_INGEST_01")
        if os.getenv("WRAITH_RUN_DEMO", "").strip().lower() in ("1", "true", "yes", "on"):
            log.info("WRAITH run() invoked — starting sample task loop (task=%s)", default_task)
            self.run_scraper_task(default_task)
        else:
            log.info("WRAITH orchestrator ready (idle; set WRAITH_RUN_DEMO=1 to run the sample task loop).")


if __name__ == "__main__":
    node = WraithOrchestrator()
    node.run_scraper_task("DATA_INGEST_01")
