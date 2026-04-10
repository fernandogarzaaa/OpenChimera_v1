# CHIMERA_HARNESS: chimera_config
"""
Config discovery utilities for OpenChimera: CHIMERA.md and .chimera.json
"""
from typing import Optional, Dict
import os
import json

def discover_chimera_md(start_path: str) -> Optional[str]:
    path = os.path.abspath(start_path)
    while True:
        candidate = os.path.join(path, "CHIMERA.md")
        if os.path.isfile(candidate):
            with open(candidate, "r", encoding="utf-8") as f:
                return f.read()
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    return None

def load_chimera_json(start_path: str) -> Dict:
    path = os.path.abspath(start_path)
    while True:
        candidate = os.path.join(path, ".chimera.json")
        if os.path.isfile(candidate):
            with open(candidate, "r", encoding="utf-8") as f:
                return json.load(f)
        parent = os.path.dirname(path)
        if parent == path:
            break
        path = parent
    return {}
