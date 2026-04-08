"""Interactive CLI setup wizard for OpenChimera.

Runs after ``bootstrap_workspace()`` finishes and walks the user through:

  ── Core Setup (always shown) ──────────────────────────────────────────
  Step 1  — Hardware Detection      (auto, no input required)
  Step 2  — Model Discovery         (Ollama + HuggingFace scan)
  Step 3  — Local Model Optimization(pick model + tune runtime params)
  Step 4  — Cloud API Keys          (enter keys for model consensus)
  Step 5  — Feature Selection       (enable/disable subsystems)
  Step 6  — Summary + Next Steps

  ── Advanced Setup (opt-in menu) ───────────────────────────────────────
  Step 7  — Channel Integrations    (Discord / Slack / Telegram / Webhook)
  Step 8  — Cloud Failover Chain    (provider priority ordering)
  Step 9  — External Roots          (validate subsystem paths)
  Step 10 — Database Verification   (run migrations, confirm DB)
  Step 11 — API Security            (auth token + TLS)
  Step 12 — Plugin Discovery        (enable/disable available plugins)
  Step 13 — MCP Server Registry     (register external tool servers)
  Step 14 — Autonomy Job Tuning     (job intervals and toggles)
  Step 15 — Model Roles Assignment  (per-task model routing)
  Step 16 — External Tool Check     (ffmpeg, chromium, llama-server)
  Step 17 — Logging & Observability (log level, retention, metrics)
  Step 18 — MiniMind Configuration  (reasoning engine device & params)
  Step 19 — Sandbox Retention       (artifact limits and age)
  Step 20 — System Personality      (identity / persona norms)
  Step 21 — RAG / Knowledge Base    (initialize retrieval storage)
  Step 22 — Full Summary

Every step is skippable.  Running ``openchimera setup --skip-wizard``
will bypass the wizard entirely and just run bootstrap + doctor.
"""

from __future__ import annotations

import getpass
import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from core.config import ROOT, load_runtime_profile, save_runtime_profile

LOGGER = logging.getLogger(__name__)

# ── ANSI helpers ─────────────────────────────────────────────────────────

_FORCE_NO_COLOR = os.environ.get("NO_COLOR") is not None

def _supports_color() -> bool:
    if _FORCE_NO_COLOR:
        return False
    if sys.platform == "win32":
        return os.environ.get("TERM") == "xterm" or os.environ.get("WT_SESSION") is not None
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

_COLOR = _supports_color()

def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text

def _bold(t: str) -> str:   return _c("1", t)
def _cyan(t: str) -> str:   return _c("36", t)
def _green(t: str) -> str:  return _c("32", t)
def _yellow(t: str) -> str: return _c("33", t)
def _red(t: str) -> str:    return _c("31", t)
def _dim(t: str) -> str:    return _c("2", t)


def _banner(step: int, total: int, title: str) -> None:
    print()
    print(_bold(f"{'═' * 60}"))
    print(_bold(f"  [{step}/{total}]  {title}"))
    print(_bold(f"{'═' * 60}"))
    print()


def _ask(prompt: str, default: str = "") -> str:
    """Prompt user for input.  Empty input returns *default*."""
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"  {prompt}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return default
    return answer or default


def _ask_yes_no(prompt: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    answer = _ask(f"{prompt} ({hint})", "y" if default else "n")
    return answer.lower() in ("y", "yes", "1", "true")


def _ask_choice(prompt: str, choices: list[str], default: int = 1) -> int:
    """Display numbered choices and return 1-based index."""
    for i, c in enumerate(choices, 1):
        marker = _cyan("→") if i == default else " "
        print(f"  {marker} {i}. {c}")
    print()
    raw = _ask(prompt, str(default))
    try:
        idx = int(raw)
        if 1 <= idx <= len(choices):
            return idx
    except ValueError:
        pass
    return default


def _ask_password(prompt: str) -> str:
    """Prompt for a secret (masked input)."""
    try:
        return getpass.getpass(f"  {prompt}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return ""


# ── The Wizard ───────────────────────────────────────────────────────────

CORE_STEPS = 6
ADVANCED_STEPS = 16
TOTAL_STEPS = CORE_STEPS + ADVANCED_STEPS  # 22

# Cloud providers users are most likely to set up
CLOUD_PROVIDERS = [
    {"id": "openai",     "name": "OpenAI",         "key_name": "OPENAI_API_KEY",      "url": "https://platform.openai.com/api-keys"},
    {"id": "anthropic",  "name": "Anthropic",       "key_name": "ANTHROPIC_API_KEY",   "url": "https://console.anthropic.com/settings/keys"},
    {"id": "google",     "name": "Google / Gemini",  "key_name": "GOOGLE_API_KEY",     "url": "https://aistudio.google.com/apikey"},
    {"id": "groq",       "name": "Groq",            "key_name": "GROQ_API_KEY",        "url": "https://console.groq.com/keys"},
    {"id": "openrouter", "name": "OpenRouter",      "key_name": "OPENROUTER_API_KEY",  "url": "https://openrouter.ai/keys"},
    {"id": "xai",        "name": "xAI (Grok)",      "key_name": "XAI_API_KEY",         "url": "https://console.x.ai/"},
]

# Modular features the user can toggle
OPTIONAL_FEATURES = [
    {
        "id": "autonomy",
        "name": "Autonomous Background Jobs",
        "desc": "Periodic model scouting, health monitoring, evolution cycles",
        "default": True,
    },
    {
        "id": "channels",
        "name": "Notification Channels",
        "desc": "Push notifications to filesystem, webhook, or operator feeds",
        "default": True,
    },
    {
        "id": "ethical_reasoning",
        "name": "Ethical Reasoning Engine",
        "desc": "Built-in ethical deliberation before high-impact actions",
        "default": True,
    },
    {
        "id": "causal_reasoning",
        "name": "Causal Reasoning",
        "desc": "Causal inference and counterfactual analysis subsystem",
        "default": False,
    },
    {
        "id": "evolution",
        "name": "Evolutionary Self-Improvement",
        "desc": "Autonomous evolution cycles with checkpoint management",
        "default": False,
    },
    {
        "id": "browser_service",
        "name": "Browser Interaction",
        "desc": "Headless browser for web research and interaction",
        "default": False,
    },
    {
        "id": "embodied_interaction",
        "name": "Embodied Interaction",
        "desc": "Spatial awareness and physical-world reasoning",
        "default": False,
    },
]

# Channel/notification integrations
CHANNEL_PROVIDERS = [
    {"id": "discord",  "name": "Discord",        "token_env": "DISCORD_BOT_TOKEN",  "url": "https://discord.com/developers/applications"},
    {"id": "slack",    "name": "Slack",           "token_env": "SLACK_BOT_TOKEN",    "url": "https://api.slack.com/apps"},
    {"id": "telegram", "name": "Telegram",        "token_env": "TELEGRAM_BOT_TOKEN", "url": "https://t.me/BotFather"},
    {"id": "webhook",  "name": "Custom Webhook",  "token_env": "WEBHOOK_URL",        "url": ""},
]

# External tools that subsystems may need
EXTERNAL_TOOLS = [
    {"bin": "ffmpeg",          "desc": "Media transcoding (audio/video processing)",          "required_by": "media pipelines"},
    {"bin": "chromium",        "desc": "Headless browser (web research & interaction)",        "required_by": "browser_service", "alt": ["google-chrome", "chrome", "msedge"]},
    {"bin": "playwright",      "desc": "Browser automation framework",                        "required_by": "browser_service"},
    {"bin": "llama-server",    "desc": "llama.cpp inference server",                          "required_by": "local LLM launcher", "alt": ["llama-cli", "llamacpp-server"]},
    {"bin": "ollama",          "desc": "Ollama model runner",                                 "required_by": "model_registry"},
]

# Model role definitions
MODEL_ROLES = [
    {"id": "fast",      "desc": "Quick responses, simple tasks (small model)"},
    {"id": "reasoning", "desc": "Complex analysis, logic, math (strong model)"},
    {"id": "coding",    "desc": "Code generation and debugging"},
    {"id": "creative",  "desc": "Writing, brainstorming, open-ended tasks"},
    {"id": "vision",    "desc": "Image understanding and description"},
]


def run_wizard() -> dict[str, Any]:
    """Run the full interactive setup wizard. Returns a summary dict."""
    print()
    print(_bold(_cyan("  ╔══════════════════════════════════════════════════════╗")))
    print(_bold(_cyan("  ║       OpenChimera  —  Intelligent Setup Wizard      ║")))
    print(_bold(_cyan("  ╚══════════════════════════════════════════════════════╝")))
    print()
    print(_dim("  Each step is optional. Press Enter to use defaults, or type 'skip' to skip."))
    print()

    profile = load_runtime_profile()
    results: dict[str, Any] = {
        "hardware": {},
        "models_scouted": {},
        "optimization": {},
        "cloud_keys_configured": [],
        "features_enabled": [],
        "features_disabled": [],
    }

    # ── Step 1: Hardware Detection ───────────────────────────────────────
    hw = _step_hardware_detection(profile, results)

    # ── Step 2: Model Discovery ──────────────────────────────────────────
    scout = _step_model_discovery(hw, results)

    # ── Step 3: Optimization ─────────────────────────────────────────────
    _step_optimization(hw, scout, profile, results)

    # ── Step 4: Cloud API Keys ───────────────────────────────────────────
    _step_cloud_api_keys(profile, results)

    # ── Step 5: Feature Selection ────────────────────────────────────────
    _step_feature_selection(profile, results)

    # ── Step 6: Core Summary ─────────────────────────────────────────────
    _step_core_summary(results)

    # ── Advanced Setup Gate ──────────────────────────────────────────────
    print()
    print(_bold("  ── Advanced Setup ──────────────────────────────────────"))
    print()
    print("  The core setup is complete. Advanced setup lets you configure:")
    print(f"    • Channel integrations (Discord, Slack, Telegram)")
    print(f"    • Cloud failover chain & model roles")
    print(f"    • API security, database, plugins, MCP servers")
    print(f"    • Autonomy job tuning, logging, sandbox retention")
    print(f"    • External tools, MiniMind, RAG, system personality")
    print()

    if _ask_yes_no("Continue to advanced setup?", default=False):
        _run_advanced_setup(profile, results)
    else:
        print(f"  {_dim('You can run advanced setup later with: openchimera setup')}")

    # ── Final Summary ────────────────────────────────────────────────────
    _step_summary(results)

    return results


def _run_advanced_setup(profile: dict[str, Any], results: dict[str, Any]) -> None:
    """Run all advanced setup steps."""
    hw = results.get("hardware", {})

    _step_channel_integrations(profile, results)
    _step_failover_chain(profile, results)
    _step_external_roots(profile, results)
    _step_database_verification(results)
    _step_api_security(profile, results)
    _step_plugin_discovery(profile, results)
    _step_mcp_registry(results)
    _step_autonomy_tuning(profile, results)
    _step_model_roles(profile, results)
    _step_external_tools(results)
    _step_logging_observability(profile, results)
    _step_minimind_config(hw, profile, results)
    _step_sandbox_retention(profile, results)
    _step_system_personality(results)
    _step_rag_knowledge_base(results)


# ── Step Implementations ─────────────────────────────────────────────────

def _step_hardware_detection(profile: dict[str, Any], results: dict[str, Any]) -> dict[str, Any]:
    _banner(1, TOTAL_STEPS, "Hardware Detection")
    print("  Scanning your system...")
    print()

    from core.hardware_detector import detect_hardware, format_hardware_summary, hardware_tier

    hw = detect_hardware()
    results["hardware"] = hw

    for line in format_hardware_summary(hw):
        print(f"  {_green('✓')} {line}")

    tier = hardware_tier(hw)
    tier_labels = {
        "high": "High-end — can run large models (13B+) with full quality",
        "mid": "Mid-range — ideal for 7-8B models",
        "low": "Entry — suited for 3-4B compact models",
        "minimal": "Minimal — tiny models only, cloud providers recommended",
    }
    print()
    print(f"  Hardware Tier: {_bold(_cyan(tier.upper()))} — {tier_labels.get(tier, '')}")

    # Persist to profile
    profile.setdefault("hardware", {})
    profile["hardware"]["cpu_count"] = hw["cpu_count"]
    profile["hardware"]["ram_gb"] = hw["ram_gb"]
    gpu_data = hw.get("gpu", {})
    profile["hardware"]["gpu"] = {
        "available": gpu_data.get("available", False),
        "name": gpu_data.get("name", ""),
        "vram_gb": gpu_data.get("vram_gb", 0.0),
        "device_count": gpu_data.get("device_count", 0),
    }
    save_runtime_profile(profile)
    print()
    print(f"  {_dim('Hardware profile saved to runtime_profile.json')}")

    return hw


def _step_model_discovery(hw: dict[str, Any], results: dict[str, Any]) -> dict[str, Any]:
    _banner(2, TOTAL_STEPS, "Model Discovery  (Ollama + HuggingFace)")

    skip = _ask("Press Enter to scan for compatible models, or type 'skip'")
    if skip.lower() == "skip":
        print(f"  {_dim('Skipped model discovery.')}")
        return {}

    print()
    print("  Scanning Ollama and HuggingFace for compatible models...")
    print()

    from core.model_scout import scout_models, format_model_table

    scout = scout_models(hw)
    results["models_scouted"] = scout

    for line in format_model_table(scout):
        print(f"  {line}")

    ollama = scout.get("ollama", {})
    if not ollama.get("installed"):
        print(f"  {_yellow('!')} Ollama is not installed.")
        print(f"    Install it from: {_cyan('https://ollama.com/download')}")
        print(f"    Then pull a model: {_dim('ollama pull llama3.2:3b')}")
        print()
    elif not ollama.get("running"):
        print(f"  {_yellow('!')} Ollama is installed but not running.")
        print(f"    Start it with: {_dim('ollama serve')}")
        print()

    return scout


def _step_optimization(
    hw: dict[str, Any],
    scout: dict[str, Any],
    profile: dict[str, Any],
    results: dict[str, Any],
) -> None:
    _banner(3, TOTAL_STEPS, "Local Runtime Optimization")

    if not hw:
        print(f"  {_dim('Hardware detection was skipped — cannot optimize. Skipping.')}")
        return

    from core.hardware_detector import hardware_tier
    tier = hardware_tier(hw)

    choices = [
        "Optimize for my hardware (recommended)",
        "Skip optimization — keep current settings",
    ]
    choice = _ask_choice("What would you like to do?", choices, default=1)

    if choice == 2:
        print(f"  {_dim('Optimization skipped.')}")
        return

    # ── Calculate optimal settings ───────────────────────────────────────
    cpu_count = int(hw.get("cpu_count", 4))
    ram_gb = float(hw.get("ram_gb", 8))
    gpu = hw.get("gpu", {})
    vram_gb = float(gpu.get("vram_gb", 0))
    has_gpu = gpu.get("available", False)

    # CPU threads: use 75% of cores, minimum 2, max 32
    optimal_threads = max(2, min(32, int(cpu_count * 0.75)))

    # Context length based on RAM
    if ram_gb >= 32 and (vram_gb >= 8 or not has_gpu):
        optimal_context = 8192
    elif ram_gb >= 16:
        optimal_context = 4096
    elif ram_gb >= 8:
        optimal_context = 2048
    else:
        optimal_context = 1024

    # Max tokens
    if tier == "high":
        optimal_max_tokens = 512
    elif tier == "mid":
        optimal_max_tokens = 256
    elif tier == "low":
        optimal_max_tokens = 128
    else:
        optimal_max_tokens = 64

    # Select best model for hardware
    recommended_models: list[str] = []
    ollama_recs = scout.get("ollama", {}).get("recommended", []) if scout else []
    if ollama_recs:
        recommended_models = [r["name"].split(":")[0] for r in ollama_recs[:2]]

    if not recommended_models:
        # Fall back to LOCAL_MODEL_SEEDS
        from core.model_registry import LOCAL_MODEL_SEEDS
        for model_id, seed in LOCAL_MODEL_SEEDS.items():
            min_vram = float(seed.get("min_vram_gb", 999))
            min_ram = float(seed.get("min_ram_gb", 999))
            if (has_gpu and vram_gb >= min_vram) or ram_gb >= min_ram:
                recommended_models.append(model_id)

    # Runtime mode
    if tier in ("high", "mid") and has_gpu:
        mode = "performance"
    elif has_gpu:
        mode = "balanced"
    else:
        mode = "bootstrap-safe"

    print()
    print(f"  {_green('✓')} Optimized settings for your hardware:")
    print()
    print(f"    CPU threads:          {_cyan(str(optimal_threads))} (of {cpu_count} cores)")
    print(f"    Context length:       {_cyan(str(optimal_context))} tokens")
    print(f"    Max output tokens:    {_cyan(str(optimal_max_tokens))}")
    print(f"    Runtime mode:         {_cyan(mode)}")
    if recommended_models:
        print(f"    Recommended models:   {_cyan(', '.join(recommended_models[:3]))}")
    print()

    if _ask_yes_no("Apply these settings?"):
        lr = profile.setdefault("local_runtime", {})
        lr["cpu_threads"] = optimal_threads
        lr["context_length"] = optimal_context
        lr["local_max_tokens"] = optimal_max_tokens
        lr["mode"] = mode
        if recommended_models:
            lr["preferred_local_models"] = recommended_models[:3]

        save_runtime_profile(profile)
        results["optimization"] = {
            "applied": True,
            "cpu_threads": optimal_threads,
            "context_length": optimal_context,
            "max_tokens": optimal_max_tokens,
            "mode": mode,
            "recommended_models": recommended_models[:3],
        }
        print(f"  {_green('✓')} Settings applied and saved.")
    else:
        results["optimization"] = {"applied": False}
        print(f"  {_dim('Settings not applied.')}")


def _step_cloud_api_keys(profile: dict[str, Any], results: dict[str, Any]) -> None:
    _banner(4, TOTAL_STEPS, "Cloud Provider API Keys")

    print("  Cloud providers enable model consensus — OpenChimera queries")
    print("  multiple LLMs and synthesizes the best answer.")
    print()
    print("  Configure at least 1-2 providers for the best experience.")
    print("  You can always add more later with: " + _dim("openchimera onboard"))
    print()

    skip = _ask("Press Enter to configure API keys, or type 'skip'")
    if skip.lower() == "skip":
        print(f"  {_dim('Skipped API key configuration.')}")
        return

    configured: list[str] = []

    # Try to import credential store for persistence
    try:
        from core.credential_store import CredentialStore
        from core.database import DatabaseManager
        db = DatabaseManager()
        cred_store = CredentialStore(db)
        cred_store.load()
    except Exception:
        cred_store = None

    for provider in CLOUD_PROVIDERS:
        print()
        print(f"  {_bold(provider['name'])}")
        print(f"    Get your key: {_cyan(provider['url'])}")

        # Check if env var already set
        env_val = os.environ.get(provider["key_name"], "")
        if env_val:
            print(f"    {_green('✓')} Already set via environment variable {provider['key_name']}")
            configured.append(provider["id"])
            continue

        # Check if already stored
        if cred_store:
            existing = cred_store.get_provider_credentials(provider["id"])
            if existing and existing.get(provider["key_name"]):
                print(f"    {_green('✓')} Already configured in credential store")
                configured.append(provider["id"])
                continue

        key = _ask_password(f"Paste {provider['key_name']} (or press Enter to skip)")
        if not key:
            print(f"    {_dim('Skipped')}")
            continue

        # Validate the key
        valid = _validate_api_key(provider, key)
        if valid:
            print(f"    {_green('✓')} Key validated successfully!")
            # Store it
            if cred_store:
                cred_store.set_provider_credential(provider["id"], provider["key_name"], key)

            # Enable the provider
            providers = profile.setdefault("providers", {})
            enabled = providers.setdefault("enabled", [])
            if provider["id"] not in enabled:
                enabled.append(provider["id"])

            configured.append(provider["id"])
        else:
            print(f"    {_yellow('!')} Could not validate key — stored anyway (may work with different endpoints)")
            if cred_store:
                cred_store.set_provider_credential(provider["id"], provider["key_name"], key)
            configured.append(provider["id"])

        # Ask if they want to continue adding more
        if not _ask_yes_no("Add another provider?", default=True):
            break

    results["cloud_keys_configured"] = configured
    if configured:
        save_runtime_profile(profile)
        print()
        print(f"  {_green('✓')} Configured {len(configured)} cloud provider(s): {', '.join(configured)}")
    else:
        print()
        print(f"  {_dim('No cloud providers configured. You can add them later.')}")


def _validate_api_key(provider: dict[str, str], key: str) -> bool:
    """Quick validation of an API key by hitting the provider's endpoint."""
    from urllib import error as url_error, request as url_request

    probe_urls = {
        "openai": "https://api.openai.com/v1/models",
        "anthropic": "https://api.anthropic.com/v1/messages",
        "google": "https://generativelanguage.googleapis.com/v1beta/models",
        "groq": "https://api.groq.com/openai/v1/models",
        "openrouter": "https://openrouter.ai/api/v1/models",
        "xai": "https://api.x.ai/v1/models",
    }

    url = probe_urls.get(provider["id"])
    if not url:
        return True  # Can't validate, assume good

    # Google uses query param instead of header
    if provider["id"] == "google":
        url = f"{url}?key={key}"
        headers = {"Accept": "application/json"}
    elif provider["id"] == "anthropic":
        headers = {
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
    else:
        headers = {
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
        }

    try:
        req = url_request.Request(url, headers=headers)
        with url_request.urlopen(req, timeout=10) as resp:
            return resp.status < 400
    except url_error.HTTPError as exc:
        # 401/403 = invalid key, anything else might be fine
        return exc.code not in (401, 403)
    except Exception:
        return False


def _step_feature_selection(profile: dict[str, Any], results: dict[str, Any]) -> None:
    _banner(5, TOTAL_STEPS, "Feature Selection")

    print("  OpenChimera has modular capabilities. Enable only what you need.")
    print("  You can change these later in config/runtime_profile.json")
    print()

    skip = _ask("Press Enter to customize features, or type 'skip' for defaults")
    if skip.lower() == "skip":
        enabled = [f["id"] for f in OPTIONAL_FEATURES if f["default"]]
        disabled = [f["id"] for f in OPTIONAL_FEATURES if not f["default"]]
        results["features_enabled"] = enabled
        results["features_disabled"] = disabled
        print(f"  {_dim('Using defaults: ' + ', '.join(enabled) + ' enabled')}")
        return

    enabled = []
    disabled = []

    for feature in OPTIONAL_FEATURES:
        default_str = _green("ON") if feature["default"] else _dim("OFF")
        print(f"  {_bold(feature['name'])} {_dim('(default: ')}{default_str}{_dim(')')}")
        print(f"    {feature['desc']}")
        on = _ask_yes_no("Enable?", default=feature["default"])
        if on:
            enabled.append(feature["id"])
        else:
            disabled.append(feature["id"])
        print()

    results["features_enabled"] = enabled
    results["features_disabled"] = disabled

    # Persist feature flags
    features = profile.setdefault("features", {})
    for fid in enabled:
        features[fid] = True
    for fid in disabled:
        features[fid] = False
    save_runtime_profile(profile)

    print(f"  {_green('✓')} Features saved: {len(enabled)} enabled, {len(disabled)} disabled")


def _step_core_summary(results: dict[str, Any]) -> None:
    _banner(6, TOTAL_STEPS, "Core Setup Complete")

    hw = results.get("hardware", {})
    if hw:
        gpu = hw.get("gpu", {})
        gpu_str = f"{gpu.get('name', 'none')} ({gpu.get('vram_gb', 0):.0f} GB)" if gpu.get("available") else "CPU-only"
        print(f"  Hardware:    {hw.get('cpu_count', '?')} cores, {hw.get('ram_gb', 0):.0f} GB RAM, {gpu_str}")

    opt = results.get("optimization", {})
    if opt.get("applied"):
        print(f"  Runtime:     {opt.get('mode', '')} mode, {opt.get('cpu_threads', '?')} threads")
    else:
        print(f"  Runtime:     {_dim('Using defaults')}")

    keys = results.get("cloud_keys_configured", [])
    if keys:
        print(f"  Cloud:       {', '.join(keys)}")

    features_on = results.get("features_enabled", [])
    if features_on:
        print(f"  Features:    {', '.join(features_on)}")
    print()


# ── Advanced Step Implementations ────────────────────────────────────────

def _step_channel_integrations(profile: dict[str, Any], results: dict[str, Any]) -> None:
    _banner(7, TOTAL_STEPS, "Channel Integrations")

    print("  Connect notification channels so OpenChimera can alert you")
    print("  via Discord, Slack, Telegram, or custom webhooks.")
    print()

    skip = _ask("Press Enter to configure channels, or type 'skip'")
    if skip.lower() == "skip":
        print(f"  {_dim('Skipped channel setup.')}")
        return

    try:
        from core.credential_store import CredentialStore
        from core.database import DatabaseManager
        db = DatabaseManager()
        cred_store = CredentialStore(db)
        cred_store.load()
    except Exception:
        cred_store = None

    configured_channels: list[str] = []

    for ch in CHANNEL_PROVIDERS:
        print()
        print(f"  {_bold(ch['name'])}")
        if ch["url"]:
            print(f"    Setup guide: {_cyan(ch['url'])}")

        existing = os.environ.get(ch["token_env"], "")
        if existing:
            print(f"    {_green('✓')} Already set via {ch['token_env']}")
            configured_channels.append(ch["id"])
            continue

        if cred_store:
            stored = cred_store.get_provider_credentials(ch["id"])
            if stored and stored.get(ch["token_env"]):
                print(f"    {_green('✓')} Already in credential store")
                configured_channels.append(ch["id"])
                continue

        if ch["id"] == "webhook":
            val = _ask("Paste webhook URL (or Enter to skip)")
        else:
            val = _ask_password(f"Paste {ch['token_env']} (or Enter to skip)")

        if not val:
            print(f"    {_dim('Skipped')}")
            continue

        if cred_store:
            cred_store.set_provider_credential(ch["id"], ch["token_env"], val)

        configured_channels.append(ch["id"])
        print(f"    {_green('✓')} Saved")

        if ch["id"] == "webhook":
            # Ask for channel ID assignment
            channel_id = _ask("Channel/room ID for webhook delivery (optional)")
            if channel_id:
                subs = profile.setdefault("channels", {})
                subs[ch["id"]] = {"url": val, "channel_id": channel_id}

    results["channels_configured"] = configured_channels
    if configured_channels:
        save_runtime_profile(profile)
        print()
        print(f"  {_green('✓')} Configured {len(configured_channels)} channel(s): {', '.join(configured_channels)}")


def _step_failover_chain(profile: dict[str, Any], results: dict[str, Any]) -> None:
    _banner(8, TOTAL_STEPS, "Cloud Failover Chain")

    keys = results.get("cloud_keys_configured", [])
    if not keys:
        print(f"  {_dim('No cloud providers configured — skipping failover chain.')}")
        return

    print("  When a provider fails, OpenChimera tries the next one in the chain.")
    print(f"  Configured providers: {_cyan(', '.join(keys))}")
    print()

    skip = _ask("Press Enter to set priority order, or type 'skip'")
    if skip.lower() == "skip":
        # Auto-build from configured order
        providers = profile.setdefault("providers", {})
        providers["failover_chain"] = keys
        if keys:
            providers["preferred_cloud_provider"] = keys[0]
        save_runtime_profile(profile)
        print(f"  {_dim('Using default order: ' + ' → '.join(keys))}")
        results["failover_chain"] = keys
        return

    print()
    print("  Drag providers into priority order (highest priority first):")
    print()

    chain: list[str] = []
    remaining = list(keys)

    for pos in range(1, len(remaining) + 1):
        for i, p in enumerate(remaining, 1):
            print(f"    {i}. {p}")
        choice_raw = _ask(f"  Priority #{pos}", "1")
        try:
            idx = int(choice_raw) - 1
            if 0 <= idx < len(remaining):
                chain.append(remaining.pop(idx))
            else:
                chain.append(remaining.pop(0))
        except ValueError:
            chain.append(remaining.pop(0))
        print()

    providers = profile.setdefault("providers", {})
    providers["failover_chain"] = chain
    providers["preferred_cloud_provider"] = chain[0] if chain else ""
    save_runtime_profile(profile)

    results["failover_chain"] = chain
    print(f"  {_green('✓')} Failover chain: {' → '.join(chain)}")


def _step_external_roots(profile: dict[str, Any], results: dict[str, Any]) -> None:
    _banner(9, TOTAL_STEPS, "External Roots Validation")

    print("  OpenChimera integrates with external subsystem directories.")
    print("  Validating configured paths...")
    print()

    ext_roots = profile.get("external_roots", {})
    int_roots = profile.get("integration_roots", {})
    all_roots = {**ext_roots, **int_roots}

    found = 0
    missing = 0
    fixed: list[str] = []

    for name, rel_path in all_roots.items():
        full = ROOT / rel_path
        if full.exists():
            print(f"  {_green('✓')} {name}: {_dim(rel_path)}")
            found += 1
        else:
            print(f"  {_yellow('!')} {name}: {_dim(rel_path)} — {_yellow('not found')}")
            missing += 1

            new_path = _ask(f"    New path for {name} (or Enter to skip)")
            if new_path:
                check = ROOT / new_path if not Path(new_path).is_absolute() else Path(new_path)
                if check.exists():
                    if name in ext_roots:
                        profile["external_roots"][name] = new_path
                    else:
                        profile["integration_roots"][name] = new_path
                    fixed.append(name)
                    print(f"    {_green('✓')} Updated to: {new_path}")
                else:
                    print(f"    {_yellow('!')} Path doesn't exist — keeping original")

    if fixed:
        save_runtime_profile(profile)

    print()
    print(f"  {_green('✓')} Found: {found}  {_yellow('Missing:')} {missing}  Fixed: {len(fixed)}")
    results["external_roots"] = {"found": found, "missing": missing, "fixed": len(fixed)}


def _step_database_verification(results: dict[str, Any]) -> None:
    _banner(10, TOTAL_STEPS, "Database Verification")

    db_path = ROOT / "data" / "openchimera.db"
    migrations_dir = ROOT / "data" / "migrations"

    if db_path.exists():
        size_mb = db_path.stat().st_size / (1024 * 1024)
        print(f"  {_green('✓')} Database found: {_dim(str(db_path))} ({size_mb:.1f} MB)")
    else:
        print(f"  {_yellow('!')} Database not found — will be auto-created on first run")

    # Check migrations
    if migrations_dir.exists():
        sql_files = sorted(migrations_dir.glob("*.sql"))
        print(f"  {_green('✓')} {len(sql_files)} migration(s) available")
        for f in sql_files:
            print(f"    • {_dim(f.name)}")
    else:
        print(f"  {_yellow('!')} No migrations directory found")

    # Run migrations if DB exists
    if db_path.exists() and migrations_dir.exists():
        print()
        if _ask_yes_no("Run pending migrations?", default=True):
            try:
                import sqlite3
                conn = sqlite3.connect(str(db_path))
                for sql_file in sorted(migrations_dir.glob("*.sql")):
                    sql = sql_file.read_text(encoding="utf-8")
                    try:
                        conn.executescript(sql)
                        print(f"    {_green('✓')} Applied: {sql_file.name}")
                    except sqlite3.OperationalError:
                        print(f"    {_dim('Already applied: ' + sql_file.name)}")
                conn.close()
                results["database"] = {"migrated": True}
            except Exception as exc:
                print(f"    {_red('✗')} Migration error: {exc}")
                results["database"] = {"migrated": False, "error": str(exc)}
        else:
            results["database"] = {"migrated": False}
    else:
        results["database"] = {"exists": db_path.exists()}

    print()


def _step_api_security(profile: dict[str, Any], results: dict[str, Any]) -> None:
    _banner(11, TOTAL_STEPS, "API Security")

    print("  The OpenChimera API runs on port 7870. Without auth,")
    print("  anyone on the network can access it.")
    print()

    auth_cfg = profile.get("api", {}).get("auth", {})
    tls_cfg = profile.get("api", {}).get("tls", {})

    # ── Auth token ───────────────────────────────────────────────────────
    if auth_cfg.get("token"):
        print(f"  {_green('✓')} Auth token already configured")
    else:
        print(f"  {_yellow('!')} No auth token set — API is open")
        if _ask_yes_no("Generate a random API auth token?", default=True):
            import secrets
            token = secrets.token_urlsafe(32)
            api = profile.setdefault("api", {})
            auth = api.setdefault("auth", {})
            auth["enabled"] = True
            auth["token"] = token
            save_runtime_profile(profile)
            print(f"  {_green('✓')} Auth token generated: {_cyan(token[:12])}...")
            print(f"    Use header: {_dim('Authorization: Bearer <token>')}")
            results["api_auth"] = True
        else:
            custom = _ask_password("Enter custom auth token (or Enter to skip)")
            if custom:
                api = profile.setdefault("api", {})
                auth = api.setdefault("auth", {})
                auth["enabled"] = True
                auth["token"] = custom
                save_runtime_profile(profile)
                print(f"  {_green('✓')} Custom token saved")
                results["api_auth"] = True
            else:
                print(f"  {_dim('API will remain open. Set a token in runtime_profile.json later.')}")

    # ── Admin token ──────────────────────────────────────────────────────
    print()
    if not auth_cfg.get("admin_token"):
        if _ask_yes_no("Generate a separate admin token for destructive operations?", default=False):
            import secrets
            admin_token = secrets.token_urlsafe(32)
            api = profile.setdefault("api", {})
            auth = api.setdefault("auth", {})
            auth["admin_token"] = admin_token
            save_runtime_profile(profile)
            print(f"  {_green('✓')} Admin token: {_cyan(admin_token[:12])}...")

    # ── TLS ──────────────────────────────────────────────────────────────
    print()
    if tls_cfg.get("certfile"):
        print(f"  {_green('✓')} TLS configured: {_dim(tls_cfg['certfile'])}")
    else:
        print(f"  {_dim('TLS not configured (HTTP only). For HTTPS:')}")
        print(f"    Set api.tls.certfile and api.tls.keyfile in runtime_profile.json")

    print()


def _step_plugin_discovery(profile: dict[str, Any], results: dict[str, Any]) -> None:
    _banner(12, TOTAL_STEPS, "Plugin Discovery")

    plugins_dir = ROOT / "plugins"
    if not plugins_dir.exists():
        print(f"  {_dim('No plugins directory found.')}")
        return

    available: list[dict[str, Any]] = []
    for pf in sorted(plugins_dir.glob("*.json")):
        try:
            data = json.loads(pf.read_text(encoding="utf-8"))
            if data.get("id"):
                available.append(data)
        except Exception:
            continue

    if not available:
        print(f"  {_dim('No plugins found.')}")
        return

    print(f"  Found {len(available)} plugin(s):")
    print()

    skip = _ask("Press Enter to configure plugins, or type 'skip'")
    if skip.lower() == "skip":
        print(f"  {_dim('Skipped plugin setup.')}")
        return

    enabled_plugins: list[str] = []
    plugins_state_path = ROOT / "data" / "plugins_state.json"

    for plugin in available:
        pid = plugin["id"]
        pname = plugin.get("name", pid)
        pdesc = plugin.get("description", "")
        print()
        print(f"  {_bold(pname)} ({pid})")
        if pdesc:
            print(f"    {_dim(pdesc)}")
        cmds = plugin.get("commands", [])
        if cmds:
            print(f"    Commands: {_cyan(', '.join(cmds))}")

        is_core = pid == "openchimera-core"
        if is_core:
            print(f"    {_green('✓')} Core plugin — always enabled")
            enabled_plugins.append(pid)
            continue

        if _ask_yes_no(f"Enable {pname}?", default=True):
            enabled_plugins.append(pid)
        else:
            print(f"    {_dim('Disabled')}")

    # Persist
    try:
        state = {"installed": enabled_plugins}
        plugins_state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        print()
        print(f"  {_green('✓')} {len(enabled_plugins)} plugin(s) enabled")
        results["plugins_enabled"] = enabled_plugins
    except Exception as exc:
        print(f"  {_red('✗')} Could not save plugin state: {exc}")


def _step_mcp_registry(results: dict[str, Any]) -> None:
    _banner(13, TOTAL_STEPS, "MCP Server Registry")

    print("  MCP (Model Context Protocol) servers provide external tools")
    print("  and resources that OpenChimera can invoke.")
    print()

    registry_path = ROOT / "data" / "mcp_registry.json"
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except Exception:
        registry = {"servers": {}}

    existing = list(registry.get("servers", {}).keys())
    if existing:
        print(f"  Registered servers: {_cyan(', '.join(existing))}")
        print()

    skip = _ask("Press Enter to add MCP servers, or type 'skip'")
    if skip.lower() == "skip":
        print(f"  {_dim('Skipped MCP setup.')}")
        return

    added: list[str] = []
    while True:
        print()
        name = _ask("Server name (e.g. 'filesystem', 'github') or Enter to finish")
        if not name:
            break

        command = _ask("Command to launch (e.g. 'npx @modelcontextprotocol/server-filesystem')")
        if not command:
            continue

        transport = _ask("Transport", "stdio")
        args_raw = _ask("Additional args (space-separated, or Enter for none)")
        args = args_raw.split() if args_raw else []

        servers = registry.setdefault("servers", {})
        servers[name] = {
            "name": name,
            "command": command,
            "args": args,
            "transport": transport,
            "enabled": True,
        }
        added.append(name)
        print(f"  {_green('✓')} Registered: {name}")

    if added:
        try:
            registry_path.write_text(json.dumps(registry, indent=2), encoding="utf-8")
            print()
            print(f"  {_green('✓')} Added {len(added)} server(s): {', '.join(added)}")
        except Exception as exc:
            print(f"  {_red('✗')} Could not save registry: {exc}")

    results["mcp_servers_added"] = added


def _step_autonomy_tuning(profile: dict[str, Any], results: dict[str, Any]) -> None:
    _banner(14, TOTAL_STEPS, "Autonomy Job Tuning")

    autonomy = profile.get("autonomy", {})
    jobs = autonomy.get("jobs", {})

    if not jobs:
        print(f"  {_dim('No autonomy jobs found in profile.')}")
        return

    print("  OpenChimera runs background jobs at configurable intervals.")
    print(f"  {len(jobs)} jobs found:")
    print()

    skip = _ask("Press Enter to tune job intervals, or type 'skip'")
    if skip.lower() == "skip":
        print(f"  {_dim('Keeping default intervals.')}")
        return

    changed = 0
    for job_id, job_cfg in jobs.items():
        enabled = job_cfg.get("enabled", True)
        interval = job_cfg.get("interval_seconds", 0)

        status = _green("ON") if enabled else _red("OFF")
        friendly_name = job_id.replace("_", " ").title()

        print(f"  {_bold(friendly_name)} [{status}] — every {_cyan(_format_interval(interval))}")

        choices = ["Keep current settings", "Change interval", "Toggle on/off"]
        choice = _ask_choice("", choices, default=1)

        if choice == 2:
            new_raw = _ask(f"New interval in seconds (current: {interval})", str(interval))
            try:
                new_interval = max(60, int(new_raw))  # minimum 60s
                job_cfg["interval_seconds"] = new_interval
                changed += 1
                print(f"    {_green('✓')} Set to {_format_interval(new_interval)}")
            except ValueError:
                print(f"    {_dim('Invalid — keeping current')}")
        elif choice == 3:
            job_cfg["enabled"] = not enabled
            changed += 1
            new_status = _green("ON") if job_cfg["enabled"] else _red("OFF")
            print(f"    {_green('✓')} Toggled to {new_status}")

        print()

    if changed:
        save_runtime_profile(profile)
        print(f"  {_green('✓')} Updated {changed} job(s)")

    results["autonomy_tuned"] = changed


def _format_interval(seconds: int) -> str:
    if seconds >= 3600:
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m"
    if seconds >= 60:
        return f"{seconds // 60}m"
    return f"{seconds}s"


def _step_model_roles(profile: dict[str, Any], results: dict[str, Any]) -> None:
    _banner(15, TOTAL_STEPS, "Model Roles Assignment")

    print("  Assign specific models to task roles for optimized routing.")
    print("  Leave blank to use the default model for all roles.")
    print()

    skip = _ask("Press Enter to assign model roles, or type 'skip'")
    if skip.lower() == "skip":
        print(f"  {_dim('Using default model for all roles.')}")
        return

    # Gather available model names
    available_models: list[str] = []
    lr = profile.get("local_runtime", {})
    preferred = lr.get("preferred_local_models", [])
    available_models.extend(preferred)

    # Also check configured cloud providers
    keys = results.get("cloud_keys_configured", [])
    for k in keys:
        available_models.append(f"{k} (cloud)")

    if available_models:
        print(f"  Available: {_cyan(', '.join(available_models))}")
        print()

    roles_path = ROOT / "config" / "model_role_assignments.json"
    try:
        roles_data = json.loads(roles_path.read_text(encoding="utf-8"))
    except Exception:
        roles_data = {}

    assigned = 0
    for role in MODEL_ROLES:
        current = roles_data.get(role["id"], {}).get("model", "")
        current_str = f" (current: {_cyan(current)})" if current else ""
        print(f"  {_bold(role['id'].upper())} — {role['desc']}{current_str}")
        model = _ask(f"    Model name (or Enter to skip)")
        if model:
            roles_data[role["id"]] = {
                "role": role["id"],
                "model": model,
                "reason": "wizard",
                "assigned_at": __import__("time").time(),
            }
            assigned += 1
            print(f"    {_green('✓')} {role['id']} → {model}")
        print()

    if assigned:
        try:
            roles_path.write_text(json.dumps(roles_data, indent=2), encoding="utf-8")
            print(f"  {_green('✓')} {assigned} role(s) assigned")
        except Exception as exc:
            print(f"  {_red('✗')} Could not save: {exc}")

    results["model_roles_assigned"] = assigned


def _step_external_tools(results: dict[str, Any]) -> None:
    _banner(16, TOTAL_STEPS, "External Tool Check")

    print("  Checking for external tools that subsystems depend on...")
    print()

    found_tools: list[str] = []
    missing_tools: list[str] = []

    for tool in EXTERNAL_TOOLS:
        bins_to_check = [tool["bin"]] + tool.get("alt", [])
        located = False
        for b in bins_to_check:
            if shutil.which(b):
                print(f"  {_green('✓')} {tool['bin']}: {_dim(tool['desc'])}")
                found_tools.append(tool["bin"])
                located = True
                break

        if not located:
            print(f"  {_yellow('!')} {tool['bin']}: {_yellow('not found')} — needed by {tool['required_by']}")
            missing_tools.append(tool["bin"])

    print()
    print(f"  Found: {len(found_tools)}/{len(EXTERNAL_TOOLS)}")
    if missing_tools:
        print(f"  {_dim('Missing tools are optional but some features may not work.')}")

    results["external_tools"] = {"found": found_tools, "missing": missing_tools}


def _step_logging_observability(profile: dict[str, Any], results: dict[str, Any]) -> None:
    _banner(17, TOTAL_STEPS, "Logging & Observability")

    log_cfg = profile.get("logging", {})
    obs_cfg = profile.get("observability", {})

    current_level = log_cfg.get("level", "INFO")
    print(f"  Current log level: {_cyan(current_level)}")
    print()

    skip = _ask("Press Enter to configure, or type 'skip'")
    if skip.lower() == "skip":
        return

    # Log level
    levels = ["DEBUG", "INFO", "WARNING", "ERROR"]
    current_idx = levels.index(current_level) + 1 if current_level in levels else 2
    print()
    choice = _ask_choice("Log level:", levels, default=current_idx)
    new_level = levels[choice - 1]

    logging_section = profile.setdefault("logging", {})
    logging_section["level"] = new_level

    # Structured logging
    structured = log_cfg.get("structured", {})
    if _ask_yes_no("Enable structured JSON logging?", default=structured.get("enabled", True)):
        logging_section.setdefault("structured", {})["enabled"] = True
    else:
        logging_section.setdefault("structured", {})["enabled"] = False

    # Observability persistence
    print()
    obs_section = profile.setdefault("observability", {})
    recent_limit = obs_cfg.get("recent_limit", 64)
    new_limit = _ask(f"Max recent events to keep in memory", str(recent_limit))
    try:
        obs_section["recent_limit"] = max(10, int(new_limit))
    except ValueError:
        pass

    save_runtime_profile(profile)
    print()
    print(f"  {_green('✓')} Log level: {new_level}, structured: {logging_section.get('structured', {}).get('enabled', False)}")

    results["logging_configured"] = True


def _step_minimind_config(
    hw: dict[str, Any],
    profile: dict[str, Any],
    results: dict[str, Any],
) -> None:
    _banner(18, TOTAL_STEPS, "MiniMind Reasoning Engine")

    re_cfg = profile.get("local_runtime", {}).get("reasoning_engine_config", {})

    print("  MiniMind is OpenChimera's built-in lightweight reasoning engine.")
    print(f"  Current device: {_cyan(re_cfg.get('device', 'cpu'))}")
    print()

    skip = _ask("Press Enter to configure MiniMind, or type 'skip'")
    if skip.lower() == "skip":
        return

    lr = profile.setdefault("local_runtime", {})
    config = lr.setdefault("reasoning_engine_config", {})

    # Device selection
    gpu = hw.get("gpu", {})
    device_options = ["cpu"]
    if gpu.get("available"):
        backend = gpu.get("backend", "cuda")
        device_options.insert(0, backend)
    if sys.platform == "darwin":
        device_options.insert(0, "mps")

    if len(device_options) > 1:
        choice = _ask_choice("Device for MiniMind inference:", device_options, default=1)
        config["device"] = device_options[choice - 1]
    else:
        config["device"] = "cpu"

    print()

    # Auto-start
    config["auto_start_server"] = _ask_yes_no("Auto-start MiniMind server with OpenChimera?", default=False)

    # Sequence length
    seq_len = _ask(f"Max sequence length", str(config.get("serve_max_seq_len", 8192)))
    try:
        config["serve_max_seq_len"] = max(512, int(seq_len))
    except ValueError:
        pass

    # Training config
    print()
    if _ask_yes_no("Configure training parameters?", default=False):
        epochs = _ask("Training epochs", str(config.get("training_epochs", 1)))
        try:
            config["training_epochs"] = max(1, int(epochs))
        except ValueError:
            pass

        batch = _ask("Training batch size", str(config.get("training_batch_size", 4)))
        try:
            config["training_batch_size"] = max(1, int(batch))
        except ValueError:
            pass

    save_runtime_profile(profile)
    print()
    print(f"  {_green('✓')} MiniMind: device={config['device']}, auto_start={config.get('auto_start_server', False)}")

    results["minimind_configured"] = True


def _step_sandbox_retention(profile: dict[str, Any], results: dict[str, Any]) -> None:
    _banner(19, TOTAL_STEPS, "Sandbox & Artifact Retention")

    retention = profile.get("autonomy", {}).get("artifacts", {}).get("retention", {})
    max_entries = retention.get("max_history_entries", 100)
    max_age = retention.get("max_age_days", 30)

    print(f"  Current limits: {_cyan(str(max_entries))} entries, {_cyan(str(max_age))} days max age")
    print()

    skip = _ask("Press Enter to adjust, or type 'skip'")
    if skip.lower() == "skip":
        return

    new_entries = _ask("Max history entries", str(max_entries))
    new_age = _ask("Max age in days", str(max_age))

    auto = profile.setdefault("autonomy", {})
    arts = auto.setdefault("artifacts", {})
    ret = arts.setdefault("retention", {})

    try:
        ret["max_history_entries"] = max(10, int(new_entries))
    except ValueError:
        pass

    try:
        ret["max_age_days"] = max(1, int(new_age))
    except ValueError:
        pass

    save_runtime_profile(profile)
    print(f"  {_green('✓')} Retention: {ret.get('max_history_entries', max_entries)} entries, {ret.get('max_age_days', max_age)} days")

    results["sandbox_retention_configured"] = True


def _step_system_personality(results: dict[str, Any]) -> None:
    _banner(20, TOTAL_STEPS, "System Personality")

    norms_path = ROOT / "config" / "social_norms.json"

    print("  OpenChimera's personality is defined by social norms that")
    print("  guide its behaviour — honesty, helpfulness, privacy, etc.")
    print()

    if not norms_path.exists():
        print(f"  {_dim('social_norms.json not found — using built-in defaults.')}")
        return

    try:
        norms_data = json.loads(norms_path.read_text(encoding="utf-8"))
        norms = norms_data.get("norms", [])
    except Exception:
        print(f"  {_dim('Could not read social_norms.json')}")
        return

    print(f"  {len(norms)} norms loaded:")
    for n in norms:
        weight_bar = "█" * int(float(n.get("weight", 0.5)) * 10)
        print(f"    {n.get('name', '?'):20s} {_cyan(weight_bar)} {n.get('weight', '?')}")

    print()
    skip = _ask("Press Enter to adjust norm weights, or type 'skip'")
    if skip.lower() == "skip":
        print(f"  {_dim('Keeping default personality.')}")
        return

    changed = 0
    for n in norms:
        name = n.get("name", "")
        current = n.get("weight", 0.5)
        new_raw = _ask(f"  {name} weight (0.0-1.0)", f"{current}")
        try:
            new_w = max(0.0, min(1.0, float(new_raw)))
            if new_w != current:
                n["weight"] = round(new_w, 2)
                changed += 1
        except ValueError:
            pass

    if changed:
        try:
            norms_path.write_text(json.dumps(norms_data, indent=2), encoding="utf-8")
            print(f"  {_green('✓')} Updated {changed} norm weight(s)")
        except Exception as exc:
            print(f"  {_red('✗')} Could not save: {exc}")

    results["personality_tuned"] = changed


def _step_rag_knowledge_base(results: dict[str, Any]) -> None:
    _banner(21, TOTAL_STEPS, "RAG / Knowledge Base")

    rag_path = ROOT / "rag_storage.json"
    kb_path = ROOT / "chimera_kb.json"

    print("  OpenChimera can use a local knowledge base for retrieval-")
    print("  augmented generation (RAG) to answer domain-specific questions.")
    print()

    if rag_path.exists():
        try:
            rag_data = json.loads(rag_path.read_text(encoding="utf-8"))
            entries = len(rag_data) if isinstance(rag_data, list) else len(rag_data.get("entries", rag_data.get("documents", [])))
            print(f"  {_green('✓')} RAG storage: {entries} entries")
        except Exception:
            print(f"  {_green('✓')} RAG storage exists: {_dim(str(rag_path))}")
    else:
        print(f"  {_yellow('!')} RAG storage not initialized")
        if _ask_yes_no("Create empty RAG storage?", default=True):
            try:
                rag_path.write_text(json.dumps({"entries": [], "created_by": "setup-wizard"}, indent=2), encoding="utf-8")
                print(f"  {_green('✓')} Created: {_dim(str(rag_path))}")
            except Exception as exc:
                print(f"  {_red('✗')} Error: {exc}")

    if kb_path.exists():
        try:
            kb_data = json.loads(kb_path.read_text(encoding="utf-8"))
            kb_len = len(kb_data) if isinstance(kb_data, list) else len(kb_data.get("nodes", kb_data.get("entries", [])))
            print(f"  {_green('✓')} Knowledge base: {kb_len} entries")
        except Exception:
            print(f"  {_green('✓')} Knowledge base exists: {_dim(str(kb_path))}")
    else:
        print(f"  {_yellow('!')} Knowledge base not found")

    print()
    print(f"  {_dim('Add documents to rag_storage.json to enhance retrieval.')}")
    print(f"  {_dim('Use: openchimera serve → POST /api/rag/ingest')}")

    results["rag_initialized"] = rag_path.exists()


# ── Final Summary ────────────────────────────────────────────────────────

def _step_summary(results: dict[str, Any]) -> None:
    _banner(TOTAL_STEPS, TOTAL_STEPS, "Setup Complete!")

    print(f"  {_green('✓')} Your OpenChimera installation is fully configured.")
    print()

    # ── Core Setup ───────────────────────────────────────────────────────
    print(_bold("  Core Setup"))

    hw = results.get("hardware", {})
    if hw:
        gpu = hw.get("gpu", {})
        gpu_str = (
            f"{gpu.get('name', 'none')} ({gpu.get('vram_gb', 0):.0f} GB)"
            if gpu.get("available")
            else "CPU-only"
        )
        print(f"    Hardware:      {hw.get('cpu_count', '?')} cores, {hw.get('ram_gb', 0):.0f} GB RAM, {gpu_str}")

    opt = results.get("optimization", {})
    if opt.get("applied"):
        print(f"    Runtime:       {opt.get('mode', '')} mode, {opt.get('cpu_threads', '?')} threads")
    else:
        print(f"    Runtime:       {_dim('Using defaults')}")

    keys = results.get("cloud_keys_configured", [])
    print(f"    Cloud:         {', '.join(keys) if keys else _dim('None')}")

    features_on = results.get("features_enabled", [])
    if features_on:
        print(f"    Features:      {', '.join(features_on)}")

    # ── Advanced Setup ───────────────────────────────────────────────────
    has_advanced = any(
        k in results
        for k in (
            "channels_configured",
            "failover_chain",
            "external_roots",
            "database",
            "api_auth",
            "plugins_enabled",
            "mcp_servers_added",
            "autonomy_tuned",
            "model_roles_assigned",
            "external_tools",
            "logging_configured",
            "minimind_configured",
            "sandbox_retention_configured",
            "personality_tuned",
            "rag_initialized",
        )
    )

    if has_advanced:
        print()
        print(_bold("  Advanced Setup"))

        channels = results.get("channels_configured", [])
        if channels:
            print(f"    Channels:      {', '.join(channels)}")

        fc = results.get("failover_chain", [])
        if fc:
            print(f"    Failover:      {' → '.join(fc)}")

        roots = results.get("external_roots", {})
        if roots:
            print(f"    Ext roots:     {roots.get('found', 0)} found, {roots.get('missing', 0)} missing")

        db = results.get("database", {})
        if db:
            migrated = db.get("migrated", False)
            print(f"    Database:      {'migrated' if migrated else _dim('pending')}")

        if results.get("api_auth"):
            print(f"    API security:  {_green('auth enabled')}")

        plugins = results.get("plugins_enabled", [])
        if plugins:
            print(f"    Plugins:       {len(plugins)} enabled")

        mcp_added = results.get("mcp_servers_added", [])
        if mcp_added:
            print(f"    MCP servers:   {', '.join(mcp_added)}")

        tuned = results.get("autonomy_tuned", 0)
        if tuned:
            print(f"    Autonomy:      {tuned} job(s) tuned")

        roles = results.get("model_roles_assigned", 0)
        if roles:
            print(f"    Model roles:   {roles} assigned")

        ext_tools = results.get("external_tools", {})
        if ext_tools:
            print(f"    Ext tools:     {len(ext_tools.get('found', []))}/{len(ext_tools.get('found', [])) + len(ext_tools.get('missing', []))} found")

        if results.get("logging_configured"):
            print(f"    Logging:       {_green('configured')}")

        if results.get("minimind_configured"):
            print(f"    MiniMind:      {_green('configured')}")

        if results.get("sandbox_retention_configured"):
            print(f"    Retention:     {_green('configured')}")

        personality = results.get("personality_tuned", 0)
        if personality:
            print(f"    Personality:   {personality} norm(s) tuned")

        if results.get("rag_initialized"):
            print(f"    RAG / KB:      {_green('initialized')}")

    # ── Next Steps ───────────────────────────────────────────────────────
    print()
    print(_bold("  Next Steps:"))
    print()
    print(f"  1. Start OpenChimera:     {_cyan('openchimera serve')}")
    print(f"  2. Open the dashboard:    {_cyan('http://localhost:7870')}")
    print(f"  3. Check system health:   {_cyan('openchimera doctor')}")
    print(f"  4. View full status:      {_cyan('openchimera status')}")

    if not keys:
        print()
        print(f"  {_yellow('Tip:')} Add cloud API keys later with: {_cyan('openchimera onboard')}")

    ollama = results.get("models_scouted", {}).get("ollama", {})
    if ollama and not ollama.get("installed"):
        print()
        print(f"  {_yellow('Tip:')} Install Ollama for local models: {_cyan('https://ollama.com/download')}")

    print()
    print(_dim("  Run 'openchimera setup' again at any time to reconfigure."))
    print()
