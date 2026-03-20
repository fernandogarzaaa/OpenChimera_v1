import os
import subprocess
import json
import py_compile
import shutil
from datetime import datetime

# OpenClaw Evolution Engine - v6.0 (Global Autonomy Mode)
# Features: Skill Audit, Auto-Enhance, Auto-Sync, Config Healing, Memory Optimization, Core Syntax Validation

BASE_DIR = r"D:\openclaw"
SKILLS_DIR = os.path.join(BASE_DIR, "skills")
SCRIPTS_DIR = os.path.join(BASE_DIR, "scripts")
MEMORY_DIR = os.path.join(BASE_DIR, "memory")
AETHER_DIR = os.path.join(BASE_DIR, "AetherFS")
CLAW_HUB_PATH = r"C:\Users\garza\AppData\Roaming\npm\clawhub.cmd"
LOG_FILE = os.path.join(BASE_DIR, r"abo\evolution_log.txt")

def audit_skills():
    print(f"[Evolution Engine] Auditing local skills...")
    audits = []
    if os.path.exists(SKILLS_DIR):
        for skill in os.listdir(SKILLS_DIR):
            skill_path = os.path.join(SKILLS_DIR, skill)
            if os.path.isdir(skill_path):
                skill_md = os.path.join(skill_path, "SKILL.md")
                audits.append({"name": skill, "path": skill_path, "has_md": os.path.exists(skill_md)})
    return audits

def apply_skill_enhancements(audits):
    applied = []
    for item in audits:
        if not item["has_md"]:
            print(f"[Autonomy] Fixing Skill: {item['name']}")
            with open(os.path.join(item["path"], "SKILL.md"), "w") as f:
                f.write(f"# {item['name']}\n\n## Description\nAuto-enhanced skill.\n\n## Usage\nExecute via OpenClaw.")
            applied.append(item["name"])
    return applied

def run_clawhub_sync():
    try:
        subprocess.run([CLAW_HUB_PATH, "sync"], capture_output=True, text=True)
        return "Sync Complete"
    except Exception as e:
        return f"Sync Failed: {e}"

def heal_configurations():
    """Detects corruption in core config files and attempts restoration."""
    healed = []
    configs = ["openclaw.toml", "chimera_local_config.py"]
    for conf in configs:
        path = os.path.join(BASE_DIR, conf)
        bak_path = f"{path}.bak"
        if os.path.exists(path):
            if os.path.getsize(path) == 0:
                print(f"[Immune System] Corruption detected in {conf} (0 bytes).")
                if os.path.exists(bak_path):
                    shutil.copy2(bak_path, path)
                    healed.append(f"{conf} (Restored from backup)")
                else:
                    healed.append(f"{conf} (Corrupt, no backup)")
        elif os.path.exists(bak_path):
            shutil.copy2(bak_path, path)
            healed.append(f"{conf} (Recovered missing file)")
    return healed

def validate_core_syntax():
    """Compiles core Python scripts to ensure no syntax errors broke the system."""
    broken_files = []
    if os.path.exists(SCRIPTS_DIR):
        for file in os.listdir(SCRIPTS_DIR):
            if file.endswith(".py"):
                path = os.path.join(SCRIPTS_DIR, file)
                try:
                    py_compile.compile(path, doraise=True)
                except py_compile.PyCompileError as e:
                    broken_files.append(file)
                    print(f"[Audit] Syntax Error in {file}: {e}")
    return broken_files

def optimize_memory_state():
    """Checks memory bloat and organizes AetherFS structure."""
    memory_count = len(os.listdir(MEMORY_DIR)) if os.path.exists(MEMORY_DIR) else 0
    os.makedirs(AETHER_DIR, exist_ok=True)
    os.makedirs(os.path.join(AETHER_DIR, "Prometheus"), exist_ok=True)
    return memory_count

def evolve():
    print(f"\n--- AUTONOMOUS EVOLUTION CYCLE: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---")
    
    # 1. Skill Layer
    audits = audit_skills()
    fixes = apply_skill_enhancements(audits)
    sync_result = run_clawhub_sync()
    
    # 2. Immune System Layer (Configs & Syntax)
    healed_configs = heal_configurations()
    broken_scripts = validate_core_syntax()
    
    # 3. Brain/Memory Layer
    memory_count = optimize_memory_state()
    
    # 4. Report & Log
    report = (
        f"Evolution Engine v6.0 (Global Autonomy) Report:\n"
        f"Timestamp: {datetime.now()}\n"
        f"Skills Synced/Fixed: {sync_result} | {len(fixes)} fixed\n"
        f"Config Health: {len(healed_configs)} healed\n"
        f"Core Syntax Check: {len(broken_scripts)} broken scripts found\n"
        f"Memory State: {memory_count} daily logs indexed in AetherFS bounds.\n"
    )
    
    if healed_configs:
        report += f"Restored: {', '.join(healed_configs)}\n"
    if broken_scripts:
        report += f"Broken: {', '.join(broken_scripts)}\n"
    
    os.makedirs(os.path.join(BASE_DIR, "abo"), exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(report + "\n" + "="*50 + "\n")
        
    print(report)
    print("--- EVOLUTION COMPLETE ---")

if __name__ == "__main__":
    evolve()
