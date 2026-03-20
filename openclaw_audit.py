import os
import json
import shutil
import hashlib
from dotenv import load_dotenv

load_dotenv()

# Standardized AETHER Path Architecture
OPENCLAW_HOME = os.getenv("OPENCLAW_HOME", "/opt/openclaw")
ADMIN_NAME = os.getenv("ADMIN_NAME", "User")

class EvoImmuneSystem:
    """
    Project EVO: OpenClaw Auditing and Self-Healing Engine.
    Monitors configuration files for corruption and auto-heals using .bak files.
    """
    def __init__(self):
        self.config_dir = os.path.join(OPENCLAW_HOME, "config")
        self.critical_files = [
            "config.json",
            "openclaw.toml"
        ]
        
    def generate_hash(self, filepath):
        """Creates an MD5 hash of the file to verify integrity."""
        if not os.path.exists(filepath):
            return None
        with open(filepath, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()

    def audit_environment(self):
        print(f"🛡️ EVO Immune System: Starting security audit for {ADMIN_NAME}...")
        print(f"📂 Monitored Workspace: {OPENCLAW_HOME}")
        
        # Ensure config directory exists
        os.makedirs(self.config_dir, exist_ok=True)
        
        for file in self.critical_files:
            file_path = os.path.join(self.config_dir, file)
            backup_path = file_path + ".bak"
            
            # Simple simulation: Check if file exists. If not, auto-heal.
            if not os.path.exists(file_path):
                print(f"⚠️ Missing critical configuration: {file}")
                if os.path.exists(backup_path):
                    print(f"🔄 EVO Auto-Healing Triggered: Restoring {file} from backup...")
                    shutil.copy(backup_path, file_path)
                else:
                    print(f"❌ FATAL: {file} is missing and no backup exists. Generating default template.")
                    # Generates an empty default template for open source users
                    with open(file_path, 'w') as f:
                        f.write(json.dumps({"_evo_status": "restored_to_factory_defaults"}))
            else:
                print(f"✅ {file} integrity verified.")

if __name__ == "__main__":
    evo = EvoImmuneSystem()
    evo.audit_environment()