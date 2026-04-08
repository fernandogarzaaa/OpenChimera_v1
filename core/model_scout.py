"""Scout compatible LLM models from Ollama and HuggingFace based on hardware.

Given a hardware profile (from ``hardware_detector``), this module:
  1. Queries the local Ollama instance for already-installed models
  2. Fetches the Ollama library page to find pullable models that fit
  3. Queries HuggingFace GGUF models that match the user's VRAM/RAM
  4. Returns a ranked list of recommendations
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib import error, request

from core.hardware_detector import hardware_tier

LOGGER = logging.getLogger(__name__)

# ── Size tiers for Ollama models ─────────────────────────────────────────
# Maps parameter-count suffixes to approximate VRAM requirements in GB.
_PARAM_VRAM_MAP: list[tuple[str, float, float]] = [
    # (suffix_pattern, min_vram_gb, min_ram_gb)
    ("1b", 1.5, 4),
    ("1.5b", 2, 4),
    ("2b", 2, 6),
    ("3b", 3, 8),
    ("4b", 3.5, 8),
    ("7b", 5, 16),
    ("8b", 6, 16),
    ("9b", 7, 18),
    ("12b", 8, 24),
    ("13b", 10, 24),
    ("14b", 10, 28),
    ("27b", 18, 48),
    ("32b", 22, 48),
    ("70b", 40, 80),
]

# Models we specifically recommend per tier from Ollama
OLLAMA_RECOMMENDATIONS: dict[str, list[dict[str, Any]]] = {
    "minimal": [
        {"name": "tinyllama:1.1b", "params": "1.1B", "vram_gb": 1.5, "desc": "Tiny but functional — fits anywhere"},
        {"name": "qwen3:1.7b", "params": "1.7B", "vram_gb": 2, "desc": "Strong reasoning for its size"},
        {"name": "phi4-mini:3.8b", "params": "3.8B", "vram_gb": 3, "desc": "Microsoft's efficient small model"},
    ],
    "low": [
        {"name": "gemma3:4b", "params": "4B", "vram_gb": 3.5, "desc": "Google's latest small model — great quality"},
        {"name": "llama3.2:3b", "params": "3B", "vram_gb": 3, "desc": "Meta's compact model — solid all-rounder"},
        {"name": "phi4-mini:3.8b", "params": "3.8B", "vram_gb": 3, "desc": "Microsoft's efficient reasoning model"},
        {"name": "qwen3:4b", "params": "4B", "vram_gb": 3.5, "desc": "Alibaba's strong multilingual model"},
    ],
    "mid": [
        {"name": "gemma3:12b", "params": "12B", "vram_gb": 8, "desc": "Best quality at this tier"},
        {"name": "llama3.1:8b", "params": "8B", "vram_gb": 6, "desc": "Meta's workhorse — great at code + reasoning"},
        {"name": "qwen3:8b", "params": "8B", "vram_gb": 6, "desc": "Strong multilingual + reasoning"},
        {"name": "mistral:7b", "params": "7B", "vram_gb": 5, "desc": "Fast, reliable general model"},
        {"name": "deepseek-r1:8b", "params": "8B", "vram_gb": 6, "desc": "Chain-of-thought reasoning specialist"},
    ],
    "high": [
        {"name": "gemma3:27b", "params": "27B", "vram_gb": 18, "desc": "Near-cloud quality running locally"},
        {"name": "qwen3:14b", "params": "14B", "vram_gb": 10, "desc": "Excellent code + reasoning"},
        {"name": "llama3.1:8b", "params": "8B", "vram_gb": 6, "desc": "Fast general-purpose model"},
        {"name": "deepseek-r1:14b", "params": "14B", "vram_gb": 10, "desc": "Strong reasoning chains"},
        {"name": "codellama:13b", "params": "13B", "vram_gb": 10, "desc": "Specialized code generation"},
    ],
}


def scout_models(hw: dict[str, Any]) -> dict[str, Any]:
    """Run the full model scout pipeline and return results."""
    tier = hardware_tier(hw)
    ollama_installed = _probe_ollama_installed()
    ollama_running = _probe_ollama_running()

    result: dict[str, Any] = {
        "hardware_tier": tier,
        "ollama": {
            "installed": ollama_installed,
            "running": ollama_running,
            "local_models": [],
            "recommended": [],
        },
        "huggingface": {
            "recommended": [],
        },
    }

    # Installed Ollama models
    if ollama_running:
        result["ollama"]["local_models"] = _get_ollama_local_models()

    # Curated recommendations based on tier
    result["ollama"]["recommended"] = _get_ollama_recommendations(tier, hw)

    # HuggingFace GGUF recommendations
    result["huggingface"]["recommended"] = _get_hf_recommendations(tier, hw)

    return result


# ── Ollama probes ────────────────────────────────────────────────────────

def _probe_ollama_installed() -> bool:
    """Check if the ``ollama`` CLI is on PATH."""
    import shutil
    return shutil.which("ollama") is not None


def _probe_ollama_running() -> bool:
    """Check if Ollama API is responding."""
    try:
        req = request.Request("http://127.0.0.1:11434/api/tags", headers={"Accept": "application/json"})
        with request.urlopen(req, timeout=3):
            return True
    except Exception:
        return False


def _get_ollama_local_models() -> list[dict[str, Any]]:
    """List models already pulled in Ollama."""
    try:
        req = request.Request("http://127.0.0.1:11434/api/tags", headers={"Accept": "application/json"})
        with request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        models = data.get("models", [])
        results = []
        for m in models:
            if not isinstance(m, dict):
                continue
            name = str(m.get("name", ""))
            size_bytes = m.get("size", 0)
            size_gb = round(size_bytes / (1024 ** 3), 1) if size_bytes else 0
            results.append({
                "name": name,
                "size_gb": size_gb,
                "modified": m.get("modified_at", ""),
            })
        return results
    except Exception:
        return []


def _get_ollama_recommendations(tier: str, hw: dict[str, Any]) -> list[dict[str, Any]]:
    """Return curated Ollama model recommendations for the hardware tier."""
    recs = OLLAMA_RECOMMENDATIONS.get(tier, OLLAMA_RECOMMENDATIONS["low"])
    vram = float(hw.get("gpu", {}).get("vram_gb", 0))
    ram = float(hw.get("ram_gb", 0))
    backend = hw.get("gpu", {}).get("backend", "none")

    filtered = []
    for r in recs:
        required_vram = r["vram_gb"]
        # For MPS / CPU-only, check against RAM instead
        if backend in ("mps", "none"):
            if ram >= required_vram * 2:  # need ~2x model size in RAM for CPU inference
                filtered.append(r)
        elif vram >= required_vram:
            filtered.append(r)
        elif ram >= required_vram * 2.5:
            # Can still run on CPU with enough RAM (slower)
            cpu_rec = dict(r)
            cpu_rec["note"] = "Will run on CPU (slower but functional)"
            filtered.append(cpu_rec)

    return filtered


# ── HuggingFace discovery ────────────────────────────────────────────────

def _get_hf_recommendations(tier: str, hw: dict[str, Any]) -> list[dict[str, Any]]:
    """Query HuggingFace API for top GGUF models compatible with hardware."""
    vram = float(hw.get("gpu", {}).get("vram_gb", 0))
    ram = float(hw.get("ram_gb", 0))

    # Determine max model size we can handle
    if vram > 0:
        max_size_gb = vram * 0.9  # leave 10% headroom
    else:
        max_size_gb = ram * 0.4  # CPU-only: use ~40% of RAM

    results: list[dict[str, Any]] = []
    try:
        # Search for popular GGUF models sorted by downloads
        url = "https://huggingface.co/api/models?search=gguf&sort=downloads&direction=-1&limit=20"
        req = request.Request(url, headers={
            "Accept": "application/json",
            "User-Agent": "OpenChimera/1.0",
        })
        with request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        if not isinstance(data, list):
            return results

        for model in data:
            if not isinstance(model, dict):
                continue
            model_id = model.get("modelId", "") or model.get("id", "")
            if not model_id:
                continue

            # Estimate size from model name hints
            estimated_gb = _estimate_model_size(model_id)
            if estimated_gb is not None and estimated_gb <= max_size_gb:
                downloads = model.get("downloads", 0)
                likes = model.get("likes", 0)
                results.append({
                    "model_id": model_id,
                    "estimated_gb": estimated_gb,
                    "downloads": downloads,
                    "likes": likes,
                    "source": "huggingface",
                })

        # Sort by downloads, take top 5
        results.sort(key=lambda x: x.get("downloads", 0), reverse=True)
        return results[:5]

    except Exception as exc:
        LOGGER.debug("HuggingFace API query failed: %s", exc)
        return results


def _estimate_model_size(name: str) -> float | None:
    """Estimate GGUF model size in GB from name patterns like '7B', 'Q4_K_M'."""
    name_lower = name.lower()

    # Extract parameter count
    param_match = re.search(r"(\d+\.?\d*)\s*b(?:illion)?", name_lower)
    if not param_match:
        return None

    params_b = float(param_match.group(1))

    # Estimate based on quantization
    if "q2" in name_lower:
        bytes_per_param = 0.3
    elif "q3" in name_lower:
        bytes_per_param = 0.45
    elif "q4" in name_lower or "iq4" in name_lower:
        bytes_per_param = 0.55
    elif "q5" in name_lower:
        bytes_per_param = 0.65
    elif "q6" in name_lower:
        bytes_per_param = 0.75
    elif "q8" in name_lower:
        bytes_per_param = 1.0
    elif "f16" in name_lower or "fp16" in name_lower:
        bytes_per_param = 2.0
    else:
        # Default to Q4 estimate (most common GGUF quant)
        bytes_per_param = 0.55

    return round(params_b * bytes_per_param, 1)


def format_model_table(scout_result: dict[str, Any]) -> list[str]:
    """Return human-readable lines describing scouted models."""
    lines: list[str] = []
    tier = scout_result.get("hardware_tier", "unknown")
    lines.append(f"Hardware tier: {tier.upper()}")
    lines.append("")

    # Ollama local models
    ollama = scout_result.get("ollama", {})
    local = ollama.get("local_models", [])
    if local:
        lines.append(f"Ollama models already installed ({len(local)}):")
        for m in local:
            lines.append(f"  * {m['name']}  ({m.get('size_gb', '?')} GB)")
        lines.append("")

    # Ollama recommendations
    recs = ollama.get("recommended", [])
    if recs:
        lines.append("Recommended Ollama models for your hardware:")
        for i, r in enumerate(recs, 1):
            note = f" [{r['note']}]" if r.get("note") else ""
            lines.append(f"  {i}. {r['name']}  ({r['params']}) — {r['desc']}{note}")
        lines.append("")
        lines.append("Pull one with:  ollama pull <model-name>")
        lines.append("")

    # HuggingFace
    hf = scout_result.get("huggingface", {})
    hf_recs = hf.get("recommended", [])
    if hf_recs:
        lines.append("HuggingFace GGUF models compatible with your hardware:")
        for i, r in enumerate(hf_recs, 1):
            lines.append(f"  {i}. {r['model_id']}  (~{r['estimated_gb']} GB)")
        lines.append("")

    if not recs and not hf_recs:
        lines.append("No compatible models found for your hardware configuration.")
        lines.append("Consider using cloud providers instead (OpenAI, Anthropic, etc.)")
        lines.append("")

    return lines
