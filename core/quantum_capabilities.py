"""Quantum Engine capability registry.

Manages OpenChimera's two-tier capability model:

  ── 50% Tier (local) ──────────────────────────────────────────────────
  Multi-agent consensus using local Ollama/LM Studio models.
  Available out-of-the-box with no credentials.

  ── 100% Tier (cloud) ─────────────────────────────────────────────────
  Full cloud LLM consensus — OpenAI, Anthropic, Gemini, Groq, xAI, etc.
  Requires cloud API keys (collected interactively or via env vars).

  ── Optional Modules ──────────────────────────────────────────────────
  Remote channels for messaging-platform control: Telegram, Discord,
  Slack, and webhook notifications.  Each channel needs its own
  credentials stored via CredentialStore.

Persistence
───────────
Enabled/disabled state is written to
  <ROOT>/config/quantum_capabilities.json
If that file does not exist, default states apply (local 50% on, cloud
100% and all channels off).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from core.config import ROOT

log = logging.getLogger(__name__)

_CAPABILITIES_FILE = ROOT / "config" / "quantum_capabilities.json"

# ── Tier constants ─────────────────────────────────────────────────────

TIER_50 = "50%"
TIER_100 = "100%"
TIER_OPTIONAL = "optional"

CATEGORY_INFERENCE = "inference"
CATEGORY_CHANNEL = "channel"
CATEGORY_AUTONOMY = "autonomy"
CATEGORY_MEMORY = "memory"


# ── Capability descriptor ──────────────────────────────────────────────

@dataclass(frozen=True)
class CapabilitySpec:
    capability_id: str
    name: str
    tier: str
    category: str
    description: str
    enabled_by_default: bool
    requires_auth: bool
    auth_providers: tuple[str, ...] = field(default_factory=tuple)
    # Optional: human-readable setup hint shown in the wizard
    setup_hint: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["auth_providers"] = list(self.auth_providers)
        return d


# ── Built-in capability registry ──────────────────────────────────────

BUILT_IN_CAPABILITIES: dict[str, CapabilitySpec] = {
    # ── inference ──────────────────────────────────────────────────────
    "quantum_engine_50": CapabilitySpec(
        capability_id="quantum_engine_50",
        name="Quantum Engine — Local  (50% capacity)",
        tier=TIER_50,
        category=CATEGORY_INFERENCE,
        description=(
            "Multi-agent consensus using local Ollama / LM Studio models. "
            "No cloud credentials required. Ideal for offline / private use."
        ),
        enabled_by_default=True,
        requires_auth=False,
        setup_hint="Ensure Ollama is running: `ollama serve`",
    ),
    "quantum_engine_100": CapabilitySpec(
        capability_id="quantum_engine_100",
        name="Quantum Engine — Cloud  (100% capacity)",
        tier=TIER_100,
        category=CATEGORY_INFERENCE,
        description=(
            "Full cloud LLM consensus — OpenAI, Anthropic, Gemini, Groq, xAI, "
            "DeepSeek, Together AI, OpenRouter. Combines cloud reasoning with "
            "local models for maximum accuracy."
        ),
        enabled_by_default=False,
        requires_auth=True,
        auth_providers=("openai", "anthropic", "google", "groq", "xai", "deepseek", "together", "openrouter"),
        setup_hint="Enter API keys when prompted, or set OPENAI_API_KEY / ANTHROPIC_API_KEY etc.",
    ),
    # ── channels ───────────────────────────────────────────────────────
    "remote_telegram": CapabilitySpec(
        capability_id="remote_telegram",
        name="Remote Channel — Telegram",
        tier=TIER_OPTIONAL,
        category=CATEGORY_CHANNEL,
        description=(
            "Control OpenChimera from a Telegram bot. "
            "Supports pairing-code DM security (unknown senders must pair first)."
        ),
        enabled_by_default=False,
        requires_auth=True,
        auth_providers=("telegram",),
        setup_hint="Create a bot via @BotFather, paste the token when prompted.",
    ),
    "remote_discord": CapabilitySpec(
        capability_id="remote_discord",
        name="Remote Channel — Discord",
        tier=TIER_OPTIONAL,
        category=CATEGORY_CHANNEL,
        description="Control OpenChimera from a Discord bot via slash commands or DMs.",
        enabled_by_default=False,
        requires_auth=True,
        auth_providers=("discord",),
        setup_hint="Create a bot at discord.com/developers, paste the bot token.",
    ),
    "remote_slack": CapabilitySpec(
        capability_id="remote_slack",
        name="Remote Channel — Slack",
        tier=TIER_OPTIONAL,
        category=CATEGORY_CHANNEL,
        description="Control OpenChimera from a Slack app via slash commands / DMs.",
        enabled_by_default=False,
        requires_auth=True,
        auth_providers=("slack",),
        setup_hint="Create a Slack app, enable Socket Mode, paste bot + app tokens.",
    ),
    "remote_webhook": CapabilitySpec(
        capability_id="remote_webhook",
        name="Remote Channel — Webhook notifications",
        tier=TIER_OPTIONAL,
        category=CATEGORY_CHANNEL,
        description=(
            "POST event notifications to any HTTP(S) endpoint "
            "(extends the existing channels subscription system)."
        ),
        enabled_by_default=False,
        requires_auth=False,
        setup_hint="Provide a URL that accepts POST requests with JSON bodies.",
    ),
    # ── autonomy ───────────────────────────────────────────────────────
    "autonomy_scheduler": CapabilitySpec(
        capability_id="autonomy_scheduler",
        name="Autonomy Scheduler",
        tier=TIER_OPTIONAL,
        category=CATEGORY_AUTONOMY,
        description="Background job scheduler for self-repair, digests, and evolution cycles.",
        enabled_by_default=True,
        requires_auth=False,
    ),
    "evolution_engine": CapabilitySpec(
        capability_id="evolution_engine",
        name="Evolution Engine",
        tier=TIER_OPTIONAL,
        category=CATEGORY_AUTONOMY,
        description="Continuous self-improvement loops that refine model roles and capability rankings.",
        enabled_by_default=True,
        requires_auth=False,
    ),
    # ── memory ─────────────────────────────────────────────────────────
    "rag_memory": CapabilitySpec(
        capability_id="rag_memory",
        name="RAG Memory",
        tier=TIER_OPTIONAL,
        category=CATEGORY_MEMORY,
        description="Retrieval-augmented generation over the local knowledge base.",
        enabled_by_default=True,
        requires_auth=False,
    ),
}


# ── QuantumCapabilityRegistry ──────────────────────────────────────────

class QuantumCapabilityRegistry:
    """Runtime registry for capability flags.

    Uses BUILT_IN_CAPABILITIES as the source of truth for specs and
    persists the enabled/disabled overrides to a JSON file.
    """

    def __init__(self, capabilities_file: Path | None = None) -> None:
        self._file = capabilities_file or _CAPABILITIES_FILE
        self._overrides: dict[str, bool] = {}
        self._load()

    # ── Public API ─────────────────────────────────────────────────────

    def get(self, capability_id: str) -> CapabilitySpec | None:
        return BUILT_IN_CAPABILITIES.get(capability_id)

    def is_enabled(self, capability_id: str) -> bool:
        spec = BUILT_IN_CAPABILITIES.get(capability_id)
        if spec is None:
            return False
        return self._overrides.get(capability_id, spec.enabled_by_default)

    def enable(self, capability_id: str) -> bool:
        """Enable a capability. Returns True on success."""
        if capability_id not in BUILT_IN_CAPABILITIES:
            log.warning("Unknown capability: %s", capability_id)
            return False
        self._overrides[capability_id] = True
        self._save()
        return True

    def disable(self, capability_id: str) -> bool:
        """Disable a capability. Returns True on success."""
        if capability_id not in BUILT_IN_CAPABILITIES:
            log.warning("Unknown capability: %s", capability_id)
            return False
        self._overrides[capability_id] = False
        self._save()
        return True

    def set_enabled(self, capability_id: str, enabled: bool) -> bool:
        return self.enable(capability_id) if enabled else self.disable(capability_id)

    def list_all(self) -> list[dict[str, Any]]:
        """Return all capabilities with their current enabled state."""
        result: list[dict[str, Any]] = []
        for spec in BUILT_IN_CAPABILITIES.values():
            entry = spec.to_dict()
            entry["enabled"] = self.is_enabled(spec.capability_id)
            result.append(entry)
        return result

    def list_by_category(self) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for item in self.list_all():
            grouped.setdefault(item["category"], []).append(item)
        return grouped

    def current_tier(self) -> str:
        """Return the human-readable Quantum Engine capacity string."""
        if self.is_enabled("quantum_engine_100"):
            return "100% — Cloud + Local"
        return "50% — Local Only"

    def enabled_cloud_providers(self) -> list[str]:
        """Return the auth_providers list if cloud is enabled, else empty."""
        if not self.is_enabled("quantum_engine_100"):
            return []
        spec = BUILT_IN_CAPABILITIES["quantum_engine_100"]
        return list(spec.auth_providers)

    def enabled_remote_channels(self) -> list[CapabilitySpec]:
        return [
            spec
            for cid, spec in BUILT_IN_CAPABILITIES.items()
            if spec.category == CATEGORY_CHANNEL and self.is_enabled(cid)
        ]

    def status(self) -> dict[str, Any]:
        return {
            "quantum_tier": self.current_tier(),
            "capabilities": self.list_all(),
        }

    # ── Persistence ────────────────────────────────────────────────────

    def _load(self) -> None:
        if not self._file.exists():
            return
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
            if isinstance(data.get("overrides"), dict):
                self._overrides = {k: bool(v) for k, v in data["overrides"].items()}
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Could not load capabilities file %s: %s", self._file, exc)

    def _save(self) -> None:
        try:
            self._file.parent.mkdir(parents=True, exist_ok=True)
            payload = {"overrides": self._overrides}
            self._file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError as exc:
            log.warning("Could not save capabilities file %s: %s", self._file, exc)


# ── Module-level singleton ─────────────────────────────────────────────

_registry: QuantumCapabilityRegistry | None = None


def get_registry() -> QuantumCapabilityRegistry:
    """Return the module-level registry singleton."""
    global _registry  # noqa: PLW0603
    if _registry is None:
        _registry = QuantumCapabilityRegistry()
    return _registry
