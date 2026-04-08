"""Remote control channels for OpenChimera.

Transports that allow operators to send commands and receive events
from OpenChimera through external messaging platforms or webhooks.

Each channel runs as an async listener that bridges incoming messages
to the OpenChimera bus and sends responses/events back out.

Supported channels:
  - Telegram (bot DMs with pairing-code security)
  - Discord  (slash commands or DMs)
  - Slack    (Socket Mode slash commands / DMs)
  - Webhook  (outbound HTTP POST event notifications)
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import secrets
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from core.config import ROOT
from core.credential_store import CredentialStore
from core.quantum_capabilities import get_registry

log = logging.getLogger(__name__)


# ── Channel status ──────────────────────────────────────────────────────

class ChannelStatus(str, Enum):
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"


# ── Base channel ────────────────────────────────────────────────────────

@dataclass
class ChannelInfo:
    channel_id: str
    display_name: str
    status: ChannelStatus = ChannelStatus.STOPPED
    error: str = ""
    connected_at: float = 0.0
    messages_received: int = 0
    messages_sent: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel_id": self.channel_id,
            "display_name": self.display_name,
            "status": self.status.value,
            "error": self.error,
            "connected_at": self.connected_at,
            "messages_received": self.messages_received,
            "messages_sent": self.messages_sent,
        }


class RemoteChannel:
    """Base class for all remote control channels."""

    channel_id: str = ""
    display_name: str = ""

    def __init__(self, credential_store: CredentialStore | None = None) -> None:
        self._creds = credential_store or CredentialStore()
        self._info = ChannelInfo(
            channel_id=self.channel_id,
            display_name=self.display_name,
        )
        self._command_handler: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    @property
    def info(self) -> ChannelInfo:
        return self._info

    @property
    def is_running(self) -> bool:
        return self._info.status == ChannelStatus.RUNNING

    def set_command_handler(
        self, handler: Callable[[str, dict[str, Any]], dict[str, Any]]
    ) -> None:
        """Set callback: handler(command_text, metadata) → response dict."""
        self._command_handler = handler

    def start(self) -> None:
        """Start the channel listener in a background thread."""
        if self._info.status == ChannelStatus.RUNNING:
            return
        self._stop_event.clear()
        self._info.status = ChannelStatus.STARTING
        self._thread = threading.Thread(
            target=self._run_loop, name=f"channel-{self.channel_id}", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal the channel to stop."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        self._info.status = ChannelStatus.STOPPED

    def _run_loop(self) -> None:
        """Override in subclasses to implement the listener loop."""
        raise NotImplementedError

    def _dispatch_command(self, text: str, meta: dict[str, Any] | None = None) -> dict[str, Any]:
        """Route an incoming command to the registered handler."""
        self._info.messages_received += 1
        if self._command_handler is None:
            return {"ok": False, "error": "No command handler registered"}
        try:
            result = self._command_handler(text, meta or {})
            self._info.messages_sent += 1
            return result
        except Exception as exc:
            log.exception("Command handler error on %s", self.channel_id)
            return {"ok": False, "error": str(exc)}


# ── Telegram channel ───────────────────────────────────────────────────

class TelegramChannel(RemoteChannel):
    """Telegram bot channel with pairing-code DM security.

    Requires ``python-telegram-bot`` at runtime.  If the package is
    missing the channel logs a warning and stays stopped.
    """

    channel_id = "remote_telegram"
    display_name = "Telegram"

    def __init__(self, credential_store: CredentialStore | None = None) -> None:
        super().__init__(credential_store)
        self._pairing_code: str = ""
        self._paired_users: set[str] = set()
        creds = self._creds.get_provider_credentials("telegram")
        self._bot_token = creds.get("bot_token", "")
        allowed = creds.get("allowed_user", "")
        if allowed:
            self._paired_users.add(allowed.lower())

    def _run_loop(self) -> None:
        if not self._bot_token:
            self._info.status = ChannelStatus.ERROR
            self._info.error = "No Telegram bot token configured"
            log.warning("Telegram channel: no bot token")
            return

        try:
            from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
        except ImportError:
            self._info.status = ChannelStatus.ERROR
            self._info.error = "python-telegram-bot not installed"
            log.warning("Telegram channel requires `pip install python-telegram-bot`")
            return

        self._pairing_code = secrets.token_hex(4)
        log.info("Telegram pairing code: %s", self._pairing_code)

        async def _start_cmd(update: Any, context: Any) -> None:
            username = (update.effective_user.username or "").lower()
            if username in self._paired_users:
                await update.message.reply_text("Already paired. Send any command.")
                return
            await update.message.reply_text(
                f"Send the pairing code to authenticate.\n"
                f"Hint: check your OpenChimera console log."
            )

        async def _handle_message(update: Any, context: Any) -> None:
            text = (update.message.text or "").strip()
            username = (update.effective_user.username or "").lower()

            # Pairing flow
            if username not in self._paired_users:
                if text == self._pairing_code:
                    self._paired_users.add(username)
                    self._creds.set_provider_credential(
                        "telegram", "allowed_user", username
                    )
                    await update.message.reply_text("Paired successfully!")
                    return
                await update.message.reply_text("Send the pairing code first.")
                return

            result = self._dispatch_command(text, {"platform": "telegram", "user": username})
            reply = result.get("response", json.dumps(result, indent=2))
            # Telegram message limit is 4096 chars
            for i in range(0, len(reply), 4096):
                await update.message.reply_text(reply[i : i + 4096])

        app = ApplicationBuilder().token(self._bot_token).build()
        app.add_handler(CommandHandler("start", _start_cmd))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _handle_message))

        self._info.status = ChannelStatus.RUNNING
        self._info.connected_at = time.time()

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(app.run_polling(stop_signals=None))
        except Exception as exc:
            if not self._stop_event.is_set():
                self._info.status = ChannelStatus.ERROR
                self._info.error = str(exc)
                log.exception("Telegram channel error")
        finally:
            loop.close()


# ── Discord channel ────────────────────────────────────────────────────

class DiscordChannel(RemoteChannel):
    """Discord bot channel with slash commands and DM support.

    Requires ``discord.py`` (``pip install discord.py``) at runtime.
    """

    channel_id = "remote_discord"
    display_name = "Discord"

    def __init__(self, credential_store: CredentialStore | None = None) -> None:
        super().__init__(credential_store)
        creds = self._creds.get_provider_credentials("discord")
        self._bot_token = creds.get("bot_token", "")
        self._guild_id = creds.get("guild_id", "")

    def _run_loop(self) -> None:
        if not self._bot_token:
            self._info.status = ChannelStatus.ERROR
            self._info.error = "No Discord bot token configured"
            log.warning("Discord channel: no bot token")
            return

        try:
            import discord
            from discord import app_commands
        except ImportError:
            self._info.status = ChannelStatus.ERROR
            self._info.error = "discord.py not installed"
            log.warning("Discord channel requires `pip install discord.py`")
            return

        intents = discord.Intents.default()
        intents.message_content = True
        client = discord.Client(intents=intents)
        tree = app_commands.CommandTree(client)
        channel_self = self

        @tree.command(name="chimera", description="Send a command to OpenChimera")
        async def chimera_cmd(interaction: discord.Interaction, query: str) -> None:
            result = channel_self._dispatch_command(
                query, {"platform": "discord", "user": str(interaction.user)}
            )
            reply = result.get("response", json.dumps(result, indent=2))
            # Discord response limit is 2000 chars
            if len(reply) > 2000:
                reply = reply[:1997] + "..."
            await interaction.response.send_message(reply)

        @client.event
        async def on_ready() -> None:
            guild_obj = None
            if channel_self._guild_id:
                guild_obj = discord.Object(id=int(channel_self._guild_id))
            if guild_obj:
                tree.copy_global_to(guild=guild_obj)
                await tree.sync(guild=guild_obj)
            else:
                await tree.sync()
            channel_self._info.status = ChannelStatus.RUNNING
            channel_self._info.connected_at = time.time()
            log.info("Discord channel connected as %s", client.user)

        @client.event
        async def on_message(message: discord.Message) -> None:
            if message.author == client.user:
                return
            # DM handling
            if isinstance(message.channel, discord.DMChannel):
                result = channel_self._dispatch_command(
                    message.content,
                    {"platform": "discord", "user": str(message.author)},
                )
                reply = result.get("response", json.dumps(result, indent=2))
                if len(reply) > 2000:
                    reply = reply[:1997] + "..."
                await message.channel.send(reply)

        try:
            client.run(self._bot_token, log_handler=None)
        except Exception as exc:
            if not self._stop_event.is_set():
                self._info.status = ChannelStatus.ERROR
                self._info.error = str(exc)
                log.exception("Discord channel error")


# ── Slack channel ──────────────────────────────────────────────────────

class SlackChannel(RemoteChannel):
    """Slack channel using Socket Mode for real-time commands.

    Requires ``slack-bolt`` (``pip install slack-bolt``) at runtime.
    """

    channel_id = "remote_slack"
    display_name = "Slack"

    def __init__(self, credential_store: CredentialStore | None = None) -> None:
        super().__init__(credential_store)
        creds = self._creds.get_provider_credentials("slack")
        self._bot_token = creds.get("bot_token", "")
        self._app_token = creds.get("app_token", "")

    def _run_loop(self) -> None:
        if not self._bot_token or not self._app_token:
            self._info.status = ChannelStatus.ERROR
            self._info.error = "Slack bot_token and app_token required"
            log.warning("Slack channel: missing tokens")
            return

        try:
            from slack_bolt import App
            from slack_bolt.adapter.socket_mode import SocketModeHandler
        except ImportError:
            self._info.status = ChannelStatus.ERROR
            self._info.error = "slack-bolt not installed"
            log.warning("Slack channel requires `pip install slack-bolt`")
            return

        app = App(token=self._bot_token)
        channel_self = self

        @app.command("/chimera")  # type: ignore[misc]
        def handle_chimera(ack: Any, body: Any, respond: Any) -> None:
            ack()
            text = body.get("text", "")
            user = body.get("user_name", "unknown")
            result = channel_self._dispatch_command(
                text, {"platform": "slack", "user": user}
            )
            reply = result.get("response", json.dumps(result, indent=2))
            respond(reply)

        @app.event("message")  # type: ignore[misc]
        def handle_dm(event: dict[str, Any], say: Any) -> None:
            if event.get("channel_type") != "im":
                return
            text = event.get("text", "")
            user = event.get("user", "unknown")
            result = channel_self._dispatch_command(
                text, {"platform": "slack", "user": user}
            )
            reply = result.get("response", json.dumps(result, indent=2))
            say(reply)

        self._info.status = ChannelStatus.RUNNING
        self._info.connected_at = time.time()

        try:
            handler = SocketModeHandler(app, self._app_token)
            handler.start()  # blocks until stopped
        except Exception as exc:
            if not self._stop_event.is_set():
                self._info.status = ChannelStatus.ERROR
                self._info.error = str(exc)
                log.exception("Slack channel error")


# ── Webhook channel ────────────────────────────────────────────────────

class WebhookChannel(RemoteChannel):
    """Outbound webhook — POSTs event payloads to a configured endpoint.

    Unlike the other channels this is push-only (no listener loop).
    It starts immediately and posts events via ``send_event()``.
    """

    channel_id = "remote_webhook"
    display_name = "Webhook"

    def __init__(self, credential_store: CredentialStore | None = None) -> None:
        super().__init__(credential_store)
        creds = self._creds.get_provider_credentials("webhook")
        self._endpoint = creds.get("endpoint_url", "")
        self._signing_secret = creds.get("signing_secret", "")

    def _run_loop(self) -> None:
        if not self._endpoint:
            self._info.status = ChannelStatus.ERROR
            self._info.error = "No webhook endpoint URL configured"
            log.warning("Webhook channel: no endpoint URL")
            return
        self._info.status = ChannelStatus.RUNNING
        self._info.connected_at = time.time()
        log.info("Webhook channel ready → %s", self._endpoint)
        # Webhook is push-only; wait for stop signal
        self._stop_event.wait()

    def send_event(self, topic: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST an event to the configured endpoint.

        Returns ``{"ok": True}`` on 2xx, error dict otherwise.
        """
        if self._info.status != ChannelStatus.RUNNING:
            return {"ok": False, "error": "Webhook channel not running"}

        import urllib.request
        import urllib.error

        body = json.dumps({"topic": topic, "payload": payload, "ts": time.time()}).encode()
        headers: dict[str, str] = {"Content-Type": "application/json"}

        if self._signing_secret:
            sig = hmac.new(
                self._signing_secret.encode(), body, hashlib.sha256
            ).hexdigest()
            headers["X-OpenChimera-Signature"] = f"sha256={sig}"

        req = urllib.request.Request(self._endpoint, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                self._info.messages_sent += 1
                return {"ok": True, "status": resp.status}
        except urllib.error.HTTPError as exc:
            log.warning("Webhook POST failed: %s %s", exc.code, exc.reason)
            return {"ok": False, "error": f"HTTP {exc.code}: {exc.reason}"}
        except Exception as exc:
            log.warning("Webhook POST error: %s", exc)
            return {"ok": False, "error": str(exc)}


# ── Channel registry / manager ─────────────────────────────────────────

# Mapping from capability_id → channel class
CHANNEL_CLASSES: dict[str, type[RemoteChannel]] = {
    "remote_telegram": TelegramChannel,
    "remote_discord": DiscordChannel,
    "remote_slack": SlackChannel,
    "remote_webhook": WebhookChannel,
}


class RemoteChannelManager:
    """Lifecycle manager for all remote channels.

    Reads the QuantumCapabilityRegistry to decide which channels to boot.
    """

    def __init__(self, credential_store: CredentialStore | None = None) -> None:
        self._creds = credential_store or CredentialStore()
        self._channels: dict[str, RemoteChannel] = {}
        self._command_handler: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None

    def set_command_handler(
        self, handler: Callable[[str, dict[str, Any]], dict[str, Any]]
    ) -> None:
        self._command_handler = handler
        for ch in self._channels.values():
            ch.set_command_handler(handler)

    def boot_enabled_channels(self) -> list[str]:
        """Start all channels that are enabled in the capability registry."""
        registry = get_registry()
        booted: list[str] = []

        for cap_id, cls in CHANNEL_CLASSES.items():
            if not registry.is_enabled(cap_id):
                continue
            if cap_id in self._channels and self._channels[cap_id].is_running:
                continue
            ch = cls(self._creds)
            if self._command_handler:
                ch.set_command_handler(self._command_handler)
            ch.start()
            self._channels[cap_id] = ch
            booted.append(cap_id)
            log.info("Booted remote channel: %s", cap_id)

        return booted

    def stop_all(self) -> None:
        for ch in self._channels.values():
            ch.stop()
        self._channels.clear()

    def stop_channel(self, cap_id: str) -> bool:
        ch = self._channels.pop(cap_id, None)
        if ch:
            ch.stop()
            return True
        return False

    def get_channel(self, cap_id: str) -> RemoteChannel | None:
        return self._channels.get(cap_id)

    def status(self) -> dict[str, Any]:
        return {
            "channels": {
                cid: ch.info.to_dict() for cid, ch in self._channels.items()
            },
            "active_count": sum(1 for ch in self._channels.values() if ch.is_running),
        }

    def send_webhook_event(self, topic: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Convenience: dispatch a webhook event if the webhook channel is active."""
        wh = self._channels.get("remote_webhook")
        if isinstance(wh, WebhookChannel) and wh.is_running:
            return wh.send_event(topic, payload)
        return {"ok": False, "error": "Webhook channel not active"}
