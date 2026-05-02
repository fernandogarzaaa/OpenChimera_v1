"""
Phase 1: Channel Adapters — WhatsApp, WebChat, DM Security Model.

Extends the core ChannelManager with additional channel types:
- WhatsApp (Meta Cloud API webhook)
- WebChat (WebSocket/SSE real-time channel)
- DM security model with per-user routing, rate-limiting, and audit logging
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DM Security Model
# ---------------------------------------------------------------------------

@dataclass
class DMSecurityPolicy:
    """Per-channel DM security policy."""
    max_messages_per_minute: int = 30
    allow_anonymous: bool = False
    require_verified_sender: bool = True
    blocked_patterns: List[str] = field(default_factory=list)
    allowed_user_ids: Optional[List[str]] = None  # None = allow all
    audit_enabled: bool = True

    def is_rate_limited(self, user_id: str, history: dict) -> bool:
        now = time.time()
        window_key = f"{user_id}:window_start"
        count_key = f"{user_id}:count"
        window_start = history.get(window_key, now)
        count = history.get(count_key, 0)
        if now - window_start > 60:
            history[window_key] = now
            history[count_key] = 1
            return False
        if count >= self.max_messages_per_minute:
            return True
        history[count_key] = count + 1
        return False

    def is_user_allowed(self, user_id: str) -> bool:
        if self.allowed_user_ids is None:
            return True
        return user_id in self.allowed_user_ids

    def contains_blocked_pattern(self, text: str) -> bool:
        for pattern in self.blocked_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        return False


class DMSecurityManager:
    """Manages DM security across channels."""

    def __init__(self, policy: Optional[DMSecurityPolicy] = None):
        self.policy = policy or DMSecurityPolicy()
        self._rate_history: Dict[str, Any] = {}
        self._audit_log: List[dict] = []

    def validate_message(self, user_id: str, text: str, channel: str) -> dict:
        result = {
            "allowed": True,
            "reason": None,
            "user_id": user_id,
            "channel": channel,
            "timestamp": time.time(),
        }
        if not self.policy.is_user_allowed(user_id):
            result["allowed"] = False
            result["reason"] = "user_not_allowed"
        elif self.policy.is_rate_limited(user_id, self._rate_history):
            result["allowed"] = False
            result["reason"] = "rate_limited"
        elif self.policy.contains_blocked_pattern(text):
            result["allowed"] = False
            result["reason"] = "blocked_pattern"
        if self.policy.audit_enabled:
            self._audit_log.append({**result, "text_hash": hashlib.sha256(text.encode()).hexdigest()[:16]})
        return result

    def get_audit_log(self, limit: int = 50) -> List[dict]:
        return list(reversed(self._audit_log))[:limit]

    def status(self) -> dict:
        return {
            "policy": {
                "max_messages_per_minute": self.policy.max_messages_per_minute,
                "allow_anonymous": self.policy.allow_anonymous,
                "require_verified_sender": self.policy.require_verified_sender,
                "audit_enabled": self.policy.audit_enabled,
            },
            "audit_log_count": len(self._audit_log),
            "tracked_users": len(set(k.split(":")[0] for k in self._rate_history.keys())),
        }


# ---------------------------------------------------------------------------
# WhatsApp Channel Adapter (Meta Cloud API)
# ---------------------------------------------------------------------------

class WhatsAppAdapter:
    """
    WhatsApp Business Cloud API adapter.
    Handles webhook verification and outbound message dispatch.
    """

    API_VERSION = "v18.0"
    BASE_URL = "https://graph.facebook.com"

    def __init__(
        self,
        phone_number_id: str = "",
        access_token: str = "",
        verify_token: str = "",
        webhook_secret: str = "",
    ):
        self.phone_number_id = phone_number_id
        self.access_token = access_token
        self.verify_token = verify_token
        self.webhook_secret = webhook_secret
        self._message_handlers: List[Callable] = []

    @property
    def send_url(self) -> str:
        return f"{self.BASE_URL}/{self.API_VERSION}/{self.phone_number_id}/messages"

    def verify_webhook(self, mode: str, token: str, challenge: str) -> Optional[str]:
        """Verify WhatsApp webhook challenge."""
        if mode == "subscribe" and token == self.verify_token:
            return challenge
        return None

    def validate_signature(self, body: bytes, signature: str) -> bool:
        """Validate X-Hub-Signature-256 header."""
        if not self.webhook_secret:
            return True  # skip validation if no secret configured
        expected = hmac.new(
            self.webhook_secret.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(f"sha256={expected}", signature)

    def parse_inbound(self, payload: dict) -> List[dict]:
        """Parse inbound webhook payload into normalized messages."""
        messages = []
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for msg in value.get("messages", []):
                    messages.append({
                        "id": msg.get("id"),
                        "from": msg.get("from"),
                        "type": msg.get("type", "text"),
                        "text": msg.get("text", {}).get("body", ""),
                        "timestamp": msg.get("timestamp"),
                        "channel": "whatsapp",
                    })
        return messages

    def build_text_message(self, to: str, text: str) -> dict:
        """Build outbound text message payload."""
        return {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"preview_url": False, "body": text},
        }

    def build_template_message(self, to: str, template_name: str, language_code: str = "en_US", components: Optional[List] = None) -> dict:
        """Build template message payload."""
        return {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language_code},
                "components": components or [],
            },
        }

    def dispatch(self, to: str, text: str, http_post: Optional[Callable] = None) -> dict:
        """Send message via WhatsApp API (uses http_post callable for testability)."""
        payload = self.build_text_message(to, text)
        if http_post:
            try:
                response = http_post(
                    self.send_url,
                    payload,
                    headers={"Authorization": f"Bearer {self.access_token}"},
                )
                return {"status": "delivered", "response": response, "to": to}
            except Exception as exc:
                return {"status": "error", "error": str(exc), "to": to}
        # Dry-run mode (no http_post provided)
        return {"status": "dry_run", "payload": payload, "to": to}


# ---------------------------------------------------------------------------
# WebChat Channel Adapter (SSE / WebSocket)
# ---------------------------------------------------------------------------

@dataclass
class WebChatSession:
    """Represents a connected WebChat client session."""
    session_id: str
    user_id: str
    connected_at: float = field(default_factory=time.time)
    last_ping: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_stale(self, timeout_seconds: float = 300.0) -> bool:
        return (time.time() - self.last_ping) > timeout_seconds


class WebChatAdapter:
    """
    WebChat channel adapter for real-time browser chat via SSE/WebSocket.
    Manages sessions, message queue, and broadcast.
    """

    def __init__(self, session_timeout: float = 300.0):
        self.session_timeout = session_timeout
        self._sessions: Dict[str, WebChatSession] = {}
        self._message_queue: List[dict] = []
        self._security = DMSecurityManager()

    def connect(self, session_id: str, user_id: str, metadata: Optional[dict] = None) -> WebChatSession:
        """Register a new WebChat session."""
        session = WebChatSession(
            session_id=session_id,
            user_id=user_id,
            metadata=metadata or {},
        )
        self._sessions[session_id] = session
        logger.info("WebChat session connected: %s (user=%s)", session_id, user_id)
        return session

    def disconnect(self, session_id: str) -> bool:
        """Remove a WebChat session."""
        if session_id in self._sessions:
            del self._sessions[session_id]
            return True
        return False

    def ping(self, session_id: str) -> bool:
        """Update last ping for a session."""
        if session_id in self._sessions:
            self._sessions[session_id].last_ping = time.time()
            return True
        return False

    def receive(self, session_id: str, text: str) -> dict:
        """Process inbound message from a WebChat client."""
        session = self._sessions.get(session_id)
        if not session:
            return {"status": "error", "reason": "session_not_found"}
        validation = self._security.validate_message(session.user_id, text, "webchat")
        if not validation["allowed"]:
            return {"status": "rejected", "reason": validation["reason"]}
        msg = {
            "id": f"wc-{int(time.time() * 1000)}",
            "session_id": session_id,
            "user_id": session.user_id,
            "text": text,
            "channel": "webchat",
            "timestamp": time.time(),
        }
        self._message_queue.append(msg)
        return {"status": "received", "message_id": msg["id"]}

    def broadcast(self, text: str, session_ids: Optional[List[str]] = None) -> dict:
        """Broadcast a message to all (or selected) connected sessions."""
        targets = session_ids or list(self._sessions.keys())
        delivered = 0
        for sid in targets:
            if sid in self._sessions:
                self._message_queue.append({
                    "id": f"bc-{int(time.time() * 1000)}-{sid}",
                    "session_id": sid,
                    "direction": "outbound",
                    "text": text,
                    "channel": "webchat",
                    "timestamp": time.time(),
                })
                delivered += 1
        return {"status": "broadcast", "delivered_count": delivered, "total_sessions": len(self._sessions)}

    def flush_messages(self, session_id: Optional[str] = None) -> List[dict]:
        """Retrieve and clear queued messages for a session (or all)."""
        if session_id:
            msgs = [m for m in self._message_queue if m.get("session_id") == session_id]
            self._message_queue = [m for m in self._message_queue if m.get("session_id") != session_id]
        else:
            msgs = list(self._message_queue)
            self._message_queue.clear()
        return msgs

    def evict_stale_sessions(self) -> int:
        """Remove sessions that have exceeded the timeout."""
        stale = [sid for sid, sess in self._sessions.items() if sess.is_stale(self.session_timeout)]
        for sid in stale:
            del self._sessions[sid]
        return len(stale)

    def status(self) -> dict:
        self.evict_stale_sessions()
        return {
            "active_sessions": len(self._sessions),
            "queued_messages": len(self._message_queue),
            "security": self._security.status(),
        }


# ---------------------------------------------------------------------------
# Unified Channel Router
# ---------------------------------------------------------------------------

CHANNEL_TYPE_MAP = {
    "webhook": "webhook",
    "slack": "slack",
    "discord": "discord",
    "telegram": "telegram",
    "filesystem": "filesystem",
    "whatsapp": "whatsapp",
    "webchat": "webchat",
}


class ChannelRouter:
    """
    Routes messages to the appropriate channel adapter.
    Acts as a facade over all channel implementations.
    """

    def __init__(self, security_policy: Optional[DMSecurityPolicy] = None):
        self._whatsapp: Optional[WhatsAppAdapter] = None
        self._webchat = WebChatAdapter()
        self._dm_security = DMSecurityManager(policy=security_policy)
        self._routing_table: Dict[str, Any] = {}

    def register_whatsapp(self, phone_number_id: str, access_token: str, verify_token: str = "", webhook_secret: str = "") -> WhatsAppAdapter:
        self._whatsapp = WhatsAppAdapter(
            phone_number_id=phone_number_id,
            access_token=access_token,
            verify_token=verify_token,
            webhook_secret=webhook_secret,
        )
        return self._whatsapp

    @property
    def webchat(self) -> WebChatAdapter:
        return self._webchat

    @property
    def whatsapp(self) -> Optional[WhatsAppAdapter]:
        return self._whatsapp

    def route_inbound(self, channel: str, payload: dict) -> List[dict]:
        """Route inbound payload to appropriate adapter and return normalized messages."""
        if channel == "whatsapp" and self._whatsapp:
            return self._whatsapp.parse_inbound(payload)
        if channel == "webchat":
            session_id = payload.get("session_id", "")
            text = payload.get("text", "")
            result = self._webchat.receive(session_id, text)
            return [result]
        return []

    def status(self) -> dict:
        return {
            "whatsapp_configured": self._whatsapp is not None,
            "webchat": self._webchat.status(),
            "dm_security": self._dm_security.status(),
            "supported_channels": sorted(CHANNEL_TYPE_MAP.keys()),
        }
