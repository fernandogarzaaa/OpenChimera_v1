"""Auto-detect host hardware: CPU, RAM, GPU/VRAM.

Writes detected values into runtime_profile.json so subsequent systems
(model registry, optimizer, onboarding) can make informed decisions
without the user filling in specs manually.
"""

from __future__ import annotations

import logging
import os
import platform
import subprocess
from typing import Any

LOGGER = logging.getLogger(__name__)


def detect_hardware() -> dict[str, Any]:
    """Return a hardware snapshot dict matching the runtime_profile ``hardware`` schema."""
    cpu = _detect_cpu()
    ram = _detect_ram()
    gpu = _detect_gpu()
    return {
        "cpu_count": cpu["count"],
        "cpu_name": cpu["name"],
        "ram_gb": ram["total_gb"],
        "ram_available_gb": ram["available_gb"],
        "gpu": gpu,
        "os": platform.system(),
        "arch": platform.machine(),
    }


# ── CPU ──────────────────────────────────────────────────────────────────

def _detect_cpu() -> dict[str, Any]:
    count = os.cpu_count() or 1
    name = platform.processor() or "unknown"
    # Attempt a friendlier name on Windows
    if platform.system() == "Windows" and (name == "unknown" or not name.strip()):
        try:
            raw = subprocess.check_output(
                ["wmic", "cpu", "get", "Name"],
                text=True,
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            lines = [line.strip() for line in raw.splitlines() if line.strip() and line.strip().lower() != "name"]
            if lines:
                name = lines[0]
        except Exception:
            pass
    return {"count": count, "name": name}


# ── RAM ──────────────────────────────────────────────────────────────────

def _detect_ram() -> dict[str, Any]:
    try:
        import psutil
        mem = psutil.virtual_memory()
        return {
            "total_gb": round(mem.total / (1024 ** 3), 1),
            "available_gb": round(mem.available / (1024 ** 3), 1),
        }
    except ImportError:
        LOGGER.debug("psutil not available — RAM detection skipped")
        return {"total_gb": 0.0, "available_gb": 0.0}


# ── GPU ──────────────────────────────────────────────────────────────────

def _detect_gpu() -> dict[str, Any]:
    """Try CUDA (via torch), then nvidia-smi, then report cpu-only."""
    result = _try_torch_cuda()
    if result:
        return result

    result = _try_nvidia_smi()
    if result:
        return result

    return {
        "available": False,
        "name": "cpu-only",
        "vram_gb": 0.0,
        "device_count": 0,
        "backend": "none",
    }


def _try_torch_cuda() -> dict[str, Any] | None:
    try:
        import torch
        if torch.cuda.is_available():
            device_count = torch.cuda.device_count()
            name = torch.cuda.get_device_name(0) if device_count > 0 else "unknown"
            total_vram = 0.0
            for i in range(device_count):
                props = torch.cuda.get_device_properties(i)
                total_vram += props.total_mem / (1024 ** 3)
            return {
                "available": True,
                "name": name,
                "vram_gb": round(total_vram, 1),
                "device_count": device_count,
                "backend": "cuda",
            }
        # Check for MPS (Apple Silicon)
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return {
                "available": True,
                "name": "Apple Silicon (MPS)",
                "vram_gb": 0.0,  # shared memory, reported via RAM
                "device_count": 1,
                "backend": "mps",
            }
    except ImportError:
        pass
    except Exception as exc:
        LOGGER.debug("torch GPU detection failed: %s", exc)
    return None


def _try_nvidia_smi() -> dict[str, Any] | None:
    """Fallback: call nvidia-smi directly."""
    try:
        raw = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            text=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        lines = [line.strip() for line in raw.strip().splitlines() if line.strip()]
        if not lines:
            return None
        total_vram_mb = 0.0
        first_name = ""
        for line in lines:
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 2:
                if not first_name:
                    first_name = parts[0]
                try:
                    total_vram_mb += float(parts[1])
                except ValueError:
                    pass
        if total_vram_mb > 0:
            return {
                "available": True,
                "name": first_name or "NVIDIA GPU",
                "vram_gb": round(total_vram_mb / 1024, 1),
                "device_count": len(lines),
                "backend": "cuda",
            }
    except FileNotFoundError:
        pass
    except Exception as exc:
        LOGGER.debug("nvidia-smi fallback failed: %s", exc)
    return None


def format_hardware_summary(hw: dict[str, Any]) -> list[str]:
    """Return human-readable lines describing the detected hardware."""
    lines = []
    lines.append(f"CPU:  {hw.get('cpu_name', 'unknown')} ({hw.get('cpu_count', '?')} cores)")
    lines.append(f"RAM:  {hw.get('ram_gb', 0):.1f} GB total, {hw.get('ram_available_gb', 0):.1f} GB available")
    gpu = hw.get("gpu", {})
    if gpu.get("available"):
        lines.append(f"GPU:  {gpu.get('name', 'unknown')} — {gpu.get('vram_gb', 0):.1f} GB VRAM ({gpu.get('backend', '')})")
    else:
        lines.append("GPU:  None detected (CPU-only mode)")
    return lines


def hardware_tier(hw: dict[str, Any]) -> str:
    """Classify hardware into a tier for model recommendations.

    Tiers:
      - ``high``   — ≥12 GB VRAM (or MPS + ≥32 GB RAM)
      - ``mid``    — ≥6 GB VRAM (or MPS + ≥16 GB RAM)
      - ``low``    — ≥4 GB VRAM (or ≥16 GB RAM, CPU-only)
      - ``minimal``— everything else
    """
    gpu = hw.get("gpu", {})
    vram = float(gpu.get("vram_gb", 0))
    ram = float(hw.get("ram_gb", 0))
    backend = gpu.get("backend", "")

    # Apple Silicon uses shared memory
    if backend == "mps":
        if ram >= 32:
            return "high"
        if ram >= 16:
            return "mid"
        return "low"

    if vram >= 12:
        return "high"
    if vram >= 6:
        return "mid"
    if vram >= 4 or ram >= 16:
        return "low"
    return "minimal"
