"""Interactive TUI configuration wizard for OpenChimera.

Invoked by:
  openchimera configure            # full interactive wizard
  openchimera configure --list     # print capability table
  openchimera configure --enable quantum_engine_100
  openchimera configure --disable remote_telegram
  openchimera configure --json     # machine-readable status

Wizard rendering uses plain terminal escape codes — no curses required.
The only external dependency is the readline module (stdlib on POSIX;
pyreadline3 for Windows, gracefully degraded if absent).
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

from core.quantum_capabilities import (
    BUILT_IN_CAPABILITIES,
    CATEGORY_CHANNEL,
    CATEGORY_INFERENCE,
    CapabilitySpec,
    QuantumCapabilityRegistry,
    get_registry,
)

# ── ANSI helpers ──────────────────────────────────────────────────────

_NO_COLOR = not sys.stdout.isatty() or os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb"


def _c(code: str, text: str) -> str:          # pylint: disable=invalid-name
    if _NO_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


def bold(text: str) -> str:
    return _c("1", text)


def dim(text: str) -> str:
    return _c("2", text)


def cyan(text: str) -> str:
    return _c("96", text)


def green(text: str) -> str:
    return _c("92", text)


def yellow(text: str) -> str:
    return _c("93", text)


def red(text: str) -> str:
    return _c("91", text)


def magenta(text: str) -> str:
    return _c("95", text)


def blue(text: str) -> str:
    return _c("94", text)


# ── Banner ─────────────────────────────────────────────────────────────

_BANNER = """\
╔══════════════════════════════════════════════════════════════╗
║  ⚛   OpenChimera  — Quantum Engine Configuration           ║
╚══════════════════════════════════════════════════════════════╝"""


def _print_banner(registry: QuantumCapabilityRegistry) -> None:
    print(cyan(bold(_BANNER)))
    tier = registry.current_tier()
    tier_str = (
        green(bold("100 %  —  Cloud + Local")) if "100" in tier
        else yellow(bold(" 50 %  —  Local Only"))
    )
    print(f"  Current capacity: {tier_str}\n")


# ── Capability table (--list) ──────────────────────────────────────────

_CATEGORY_LABELS: dict[str, str] = {
    "inference": "INFERENCE ENGINE",
    "channel":   "REMOTE CHANNELS",
    "autonomy":  "AUTONOMY",
    "memory":    "MEMORY / RAG",
}


def print_capability_table(registry: QuantumCapabilityRegistry | None = None) -> None:
    """Pretty-print capability table to stdout."""
    if registry is None:
        registry = get_registry()

    _print_banner(registry)
    grouped = registry.list_by_category()

    for cat in ("inference", "channel", "autonomy", "memory"):
        items = grouped.get(cat, [])
        if not items:
            continue
        print(bold(cyan(f"  {_CATEGORY_LABELS.get(cat, cat.upper())}")))
        for item in items:
            tick = green("[✓]") if item["enabled"] else dim("[ ]")
            tier_badge = (
                magenta("[100%]") if item["tier"] == "100%"
                else yellow("[50%]") if item["tier"] == "50%"
                else dim("[opt]")
            )
            name = item["name"]
            cid  = dim(f'  ({item["capability_id"]})')
            print(f"    {tick} {tier_badge} {name}{cid}")
        print()


# ── Readline setup ─────────────────────────────────────────────────────

def _setup_readline() -> None:
    try:
        import readline  # noqa: F401
    except ImportError:
        pass  # Windows without pyreadline3 — still works, just no history


# ── Interactive prompts ────────────────────────────────────────────────

def _prompt(question: str, default: str = "") -> str:
    """Ask the user a question and return their answer (stripped)."""
    _setup_readline()
    hint = f" [{default}]" if default else ""
    try:
        answer = input(f"  {question}{hint}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return default
    return answer or default


def _confirm(question: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    raw = _prompt(f"{question} ({hint})", "y" if default else "n").lower()
    return raw in {"y", "yes"}


def _choose_from_list(
    title: str,
    options: list[tuple[str, str]],   # (key, label)
    initial_selected: set[str],
) -> set[str]:
    """Simple interactive checkbox selection.

    Displays a numbered list; user enters comma-separated numbers to
    toggle, presses ENTER with nothing to confirm.

    Returns the final set of selected keys.
    """
    selected = set(initial_selected)
    while True:
        print(f"\n  {bold(title)}")
        for i, (key, label) in enumerate(options, 1):
            mark = green("[✓]") if key in selected else dim("[ ]")
            print(f"    {i}. {mark} {label}")
        print(dim("\n  Enter number(s) to toggle (e.g. 1,3) or press ENTER to confirm: "), end="")
        raw = _prompt("").strip()
        if not raw:
            break
        for token in raw.replace(" ", "").split(","):
            try:
                idx = int(token) - 1
                if 0 <= idx < len(options):
                    key = options[idx][0]
                    if key in selected:
                        selected.discard(key)
                    else:
                        selected.add(key)
            except ValueError:
                pass  # ignore garbage input
    return selected


# ── Cloud API-key collection ───────────────────────────────────────────

def _collect_cloud_api_keys(providers_to_configure: list[str]) -> None:
    """Walk through a list of cloud provider IDs and call CloudAuthManager."""
    try:
        from core.cloud_auth import CloudAuthManager
        auth_manager = CloudAuthManager()
    except ImportError:
        print(red("  [!] core.cloud_auth unavailable — skipping API key collection."))
        return

    already_configured = set(auth_manager.configured_providers())
    print()
    print(bold("  Cloud LLM API Keys"))
    print(dim("  Press ENTER to skip any provider.\n"))

    for pid in providers_to_configure:
        # retrieve display name from CloudAuthManager's known providers
        from core.cloud_auth import CLOUD_PROVIDERS
        pname = CLOUD_PROVIDERS.get(pid, type("_Fake", (), {"display_name": pid})).display_name  # type: ignore[arg-type]
        star = green(" ✓ already configured") if pid in already_configured else ""
        api_key = _prompt(f"{pname} API key{star}").strip()
        if api_key:
            try:
                auth_manager.add_api_key(pid, api_key)
                print(green(f"    ✓ {pname} key saved."))
            except Exception as exc:  # noqa: BLE001
                print(red(f"    ✗ Could not save {pname} key: {exc}"))
        elif pid in already_configured:
            print(dim(f"    Keeping existing {pname} key."))
        else:
            print(dim(f"    Skipped {pname}."))


# ── Messaging channel credential collection ───────────────────────────

def _collect_channel_credentials(capability_id: str) -> None:
    """Interactively collect and store credentials for a messaging channel."""
    try:
        from core.credential_store import CredentialStore
        store = CredentialStore()
    except ImportError:
        print(red("  [!] CredentialStore unavailable."))
        return

    spec = BUILT_IN_CAPABILITIES.get(capability_id)
    if spec is None:
        return

    print(f"\n  {bold(spec.name)} Setup")
    if spec.setup_hint:
        print(dim(f"  Hint: {spec.setup_hint}"))
    print()

    if capability_id == "remote_telegram":
        token = _prompt("Telegram bot token").strip()
        if token:
            store.set_provider_credential("telegram", "bot_token", token)
            allowed = _prompt("Allowed Telegram username (leave blank for pairing mode)").strip()
            if allowed:
                store.set_provider_credential("telegram", "allowed_user", allowed)
            print(green("    ✓ Telegram credentials saved."))

    elif capability_id == "remote_discord":
        token = _prompt("Discord bot token").strip()
        if token:
            store.set_provider_credential("discord", "bot_token", token)
            guild = _prompt("Discord guild (server) ID (optional)").strip()
            if guild:
                store.set_provider_credential("discord", "guild_id", guild)
            print(green("    ✓ Discord credentials saved."))

    elif capability_id == "remote_slack":
        bot_token = _prompt("Slack bot token (xoxb-…)").strip()
        app_token = _prompt("Slack app token for Socket Mode (xapp-…)").strip()
        if bot_token:
            store.set_provider_credential("slack", "bot_token", bot_token)
        if app_token:
            store.set_provider_credential("slack", "app_token", app_token)
        if bot_token or app_token:
            print(green("    ✓ Slack credentials saved."))

    elif capability_id == "remote_webhook":
        endpoint = _prompt("Webhook endpoint URL").strip()
        if endpoint:
            store.set_provider_credential("webhook", "endpoint_url", endpoint)
            secret = _prompt("Optional HMAC-SHA256 signing secret").strip()
            if secret:
                store.set_provider_credential("webhook", "signing_secret", secret)
            print(green("    ✓ Webhook credentials saved."))


# ── Full interactive wizard ────────────────────────────────────────────

def run_interactive_wizard(registry: QuantumCapabilityRegistry | None = None) -> int:
    """Run the full TUI configure session. Returns an exit code."""
    if registry is None:
        registry = get_registry()

    _print_banner(registry)

    # ── STEP 1: Inference tier ───────────────────────────────────────
    print(bold(cyan("  STEP 1 — Inference Engine Tier\n")))

    inference_options: list[tuple[str, str]] = [
        ("quantum_engine_50",  "Quantum Engine 50%  — Local Ollama / LM Studio"),
        ("quantum_engine_100", "Quantum Engine 100% — Cloud LLMs  (API keys required)"),
    ]
    initial_inference = {
        cid for cid in (o[0] for o in inference_options) if registry.is_enabled(cid)
    }
    chosen_inference = _choose_from_list(
        "Select inference tiers (toggle with numbers, ENTER to confirm):",
        inference_options,
        initial_inference,
    )

    for cid, _ in inference_options:
        registry.set_enabled(cid, cid in chosen_inference)

    # If cloud selected, collect API keys
    if "quantum_engine_100" in chosen_inference:
        print(f"\n  {yellow('Quantum Engine 100% enabled!')}")
        spec = BUILT_IN_CAPABILITIES["quantum_engine_100"]
        providers = list(spec.auth_providers)
        # Let user pick which providers to configure
        provider_options: list[tuple[str, str]] = []
        try:
            from core.cloud_auth import CLOUD_PROVIDERS
            for pid in providers:
                pobj = CLOUD_PROVIDERS.get(pid)
                label = pobj.display_name if pobj else pid  # type: ignore[union-attr]
                provider_options.append((pid, label))
        except ImportError:
            provider_options = [(p, p) for p in providers]

        try:
            from core.cloud_auth import CloudAuthManager
            already = set(CloudAuthManager().configured_providers())
        except ImportError:
            already = set()

        chosen_providers = _choose_from_list(
            "Which cloud providers to configure?",
            provider_options,
            already,
        )
        if chosen_providers:
            _collect_cloud_api_keys(list(chosen_providers))

    # ── STEP 2: Remote channels ──────────────────────────────────────
    _step2_header = "  STEP 2 \u2014 Remote Control Channels\n"
    print("\n" + bold(cyan(_step2_header)))

    channel_options: list[tuple[str, str]] = [
        ("remote_telegram", "Telegram — control via bot DMs"),
        ("remote_discord",  "Discord  — control via bot DMs / slash commands"),
        ("remote_slack",    "Slack    — control via slash commands / DMs"),
        ("remote_webhook",  "Webhook  — HTTP POST event notifications"),
    ]
    initial_channels = {
        cid for cid, _ in channel_options if registry.is_enabled(cid)
    }
    chosen_channels = _choose_from_list(
        "Select remote channels to enable:",
        channel_options,
        initial_channels,
    )

    newly_enabled_channels = chosen_channels - initial_channels
    for cid, _ in channel_options:
        registry.set_enabled(cid, cid in chosen_channels)

    # Collect credentials for newly enabled channels
    for cid in (c for c, _ in channel_options if c in newly_enabled_channels):
        _collect_channel_credentials(cid)

    # ── STEP 3: Optional modules ─────────────────────────────────────
    _step3_header = "  STEP 3 \u2014 Optional Modules\n"
    print("\n" + bold(cyan(_step3_header)))

    optional_options: list[tuple[str, str]] = [
        ("autonomy_scheduler", "Autonomy Scheduler  — background self-repair and digest jobs"),
        ("evolution_engine",   "Evolution Engine    — continuous self-improvement loops"),
        ("rag_memory",         "RAG Memory          — retrieval-augmented local knowledge base"),
    ]
    initial_optional = {
        cid for cid, _ in optional_options if registry.is_enabled(cid)
    }
    chosen_optional = _choose_from_list(
        "Toggle optional modules:",
        optional_options,
        initial_optional,
    )
    for cid, _ in optional_options:
        registry.set_enabled(cid, cid in chosen_optional)

    # ── Summary ──────────────────────────────────────────────────────
    _summary_header = "  \u2713  Configuration saved.  Current status:\n"
    print("\n" + bold(cyan(_summary_header)))
    print_capability_table(registry)

    return 0


# ── Non-interactive helpers ────────────────────────────────────────────

def cmd_list_capabilities(as_json: bool = False) -> int:
    registry = get_registry()
    if as_json:
        print(json.dumps(registry.status(), indent=2))
        return 0
    print_capability_table(registry)
    return 0


def cmd_enable_capability(capability_id: str, as_json: bool = False) -> int:
    registry = get_registry()
    ok = registry.enable(capability_id)
    if as_json:
        print(json.dumps({"ok": ok, "capability_id": capability_id, "action": "enable"}))
    elif ok:
        print(green(f"  ✓ Enabled: {capability_id}"))
    else:
        print(red(f"  ✗ Unknown capability: {capability_id}"))
    return 0 if ok else 1


def cmd_disable_capability(capability_id: str, as_json: bool = False) -> int:
    registry = get_registry()
    ok = registry.disable(capability_id)
    if as_json:
        print(json.dumps({"ok": ok, "capability_id": capability_id, "action": "disable"}))
    elif ok:
        print(green(f"  ✓ Disabled: {capability_id}"))
    else:
        print(red(f"  ✗ Unknown capability: {capability_id}"))
    return 0 if ok else 1


# ── Entry point used by run.py ─────────────────────────────────────────

def configure_command(
    *,
    list_caps: bool = False,
    enable_id: str = "",
    disable_id: str = "",
    as_json: bool = False,
) -> int:
    """Dispatch configure sub-command; returns process exit code."""
    if enable_id:
        return cmd_enable_capability(enable_id, as_json=as_json)
    if disable_id:
        return cmd_disable_capability(disable_id, as_json=as_json)
    if list_caps:
        return cmd_list_capabilities(as_json=as_json)
    # Default: full interactive wizard
    return run_interactive_wizard()
