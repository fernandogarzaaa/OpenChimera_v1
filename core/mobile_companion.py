"""
Phase 6: Mobile & Companion API.

Provides REST API endpoints and data models for:
- iOS/Android mobile nodes (push notifications, sync, offline)
- macOS menu bar companion (status, quick actions)
- Device registration and management
- Cross-device session continuity
"""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Device & Platform Types
# ---------------------------------------------------------------------------

class DevicePlatform(str, Enum):
    IOS = "ios"
    ANDROID = "android"
    MACOS_MENUBAR = "macos_menubar"
    WEB = "web"
    DESKTOP = "desktop"
    OTHER = "other"


class DeviceStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    REVOKED = "revoked"


# ---------------------------------------------------------------------------
# Device Registration
# ---------------------------------------------------------------------------

@dataclass
class DeviceRegistration:
    """Represents a registered mobile/companion device."""
    device_id: str
    user_id: str
    platform: DevicePlatform
    device_name: str = ""
    device_model: str = ""
    os_version: str = ""
    app_version: str = ""
    push_token: str = ""  # FCM or APNs token
    api_token: str = field(default_factory=lambda: secrets.token_hex(32))
    registered_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    status: DeviceStatus = DeviceStatus.ACTIVE
    capabilities: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self, include_token: bool = False) -> dict:
        d = {
            "device_id": self.device_id,
            "user_id": self.user_id,
            "platform": self.platform.value,
            "device_name": self.device_name,
            "device_model": self.device_model,
            "os_version": self.os_version,
            "app_version": self.app_version,
            "registered_at": self.registered_at,
            "last_seen": self.last_seen,
            "status": self.status.value,
            "capabilities": self.capabilities,
            "has_push_token": bool(self.push_token),
        }
        if include_token:
            d["api_token"] = self.api_token
        return d


class DeviceManager:
    """Manages device registrations and authentication."""

    def __init__(self):
        self._devices: Dict[str, DeviceRegistration] = {}  # device_id -> device
        self._token_index: Dict[str, str] = {}  # api_token -> device_id
        self._registration_count = 0

    def register(
        self,
        device_id: str,
        user_id: str,
        platform: DevicePlatform,
        device_name: str = "",
        device_model: str = "",
        os_version: str = "",
        app_version: str = "",
        push_token: str = "",
        capabilities: Optional[List[str]] = None,
    ) -> dict:
        """Register a new device or update existing registration."""
        is_new = device_id not in self._devices
        if not is_new:
            # Update existing device
            device = self._devices[device_id]
            device.last_seen = time.time()
            device.push_token = push_token or device.push_token
            device.app_version = app_version or device.app_version
            device.os_version = os_version or device.os_version
            device.status = DeviceStatus.ACTIVE
        else:
            device = DeviceRegistration(
                device_id=device_id,
                user_id=user_id,
                platform=platform,
                device_name=device_name,
                device_model=device_model,
                os_version=os_version,
                app_version=app_version,
                push_token=push_token,
                capabilities=capabilities or self._default_capabilities(platform),
            )
            self._devices[device_id] = device
            self._token_index[device.api_token] = device_id
            self._registration_count += 1
        reg_status = "registered" if is_new else "updated"
        device_dict = device.to_dict(include_token=is_new)
        return {
            "registration_status": reg_status,
            "status": reg_status,
            "device_id": device_id,
            **{k: v for k, v in device_dict.items() if k not in ("status",)},
            **({"api_token": device.api_token} if is_new else {}),
        }

    def _default_capabilities(self, platform: DevicePlatform) -> List[str]:
        caps = {
            DevicePlatform.IOS: ["push_notifications", "background_fetch", "siri_shortcuts", "widgets"],
            DevicePlatform.ANDROID: ["push_notifications", "background_sync", "widgets", "shortcuts"],
            DevicePlatform.MACOS_MENUBAR: ["menu_bar", "notifications", "quick_actions", "hotkeys"],
            DevicePlatform.WEB: ["notifications", "offline_cache"],
            DevicePlatform.DESKTOP: ["notifications", "system_tray", "hotkeys"],
        }
        return caps.get(platform, ["basic"])

    def authenticate(self, api_token: str) -> Optional[DeviceRegistration]:
        """Authenticate a device by API token."""
        device_id = self._token_index.get(api_token)
        if not device_id:
            return None
        device = self._devices.get(device_id)
        if device and device.status == DeviceStatus.ACTIVE:
            device.last_seen = time.time()
            return device
        return None

    def revoke(self, device_id: str) -> bool:
        """Revoke device access."""
        device = self._devices.get(device_id)
        if not device:
            return False
        device.status = DeviceStatus.REVOKED
        return True

    def get_devices_for_user(self, user_id: str) -> List[dict]:
        return [d.to_dict() for d in self._devices.values() if d.user_id == user_id and d.status == DeviceStatus.ACTIVE]

    def status(self) -> dict:
        active = sum(1 for d in self._devices.values() if d.status == DeviceStatus.ACTIVE)
        by_platform = {}
        for d in self._devices.values():
            by_platform[d.platform.value] = by_platform.get(d.platform.value, 0) + 1
        return {
            "total_registrations": self._registration_count,
            "active_devices": active,
            "by_platform": by_platform,
        }


# ---------------------------------------------------------------------------
# Push Notification Manager
# ---------------------------------------------------------------------------

@dataclass
class PushNotification:
    """A push notification to be sent to a device."""
    device_id: str
    title: str
    body: str
    data: Dict[str, Any] = field(default_factory=dict)
    badge: Optional[int] = None
    sound: str = "default"
    category: str = ""
    thread_id: str = ""
    notification_id: str = field(default_factory=lambda: secrets.token_hex(8))
    created_at: float = field(default_factory=time.time)
    delivered: bool = False
    delivery_error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "notification_id": self.notification_id,
            "device_id": self.device_id,
            "title": self.title,
            "body": self.body,
            "data": self.data,
            "badge": self.badge,
            "sound": self.sound,
            "category": self.category,
            "created_at": self.created_at,
            "delivered": self.delivered,
        }


class PushNotificationManager:
    """Manages push notification dispatch to mobile devices."""

    def __init__(self, device_manager: Optional[DeviceManager] = None):
        self._device_manager = device_manager or DeviceManager()
        self._notification_queue: List[PushNotification] = []
        self._delivery_history: List[PushNotification] = []
        self._sent_count = 0

    def send(
        self,
        device_id: str,
        title: str,
        body: str,
        data: Optional[dict] = None,
        badge: Optional[int] = None,
    ) -> dict:
        """Queue a push notification for delivery."""
        device = self._device_manager._devices.get(device_id)
        if not device:
            return {"status": "error", "reason": "device_not_found", "device_id": device_id}
        if device.status != DeviceStatus.ACTIVE:
            return {"status": "error", "reason": "device_inactive", "device_id": device_id}
        notification = PushNotification(
            device_id=device_id,
            title=title,
            body=body,
            data=data or {},
            badge=badge,
        )
        self._notification_queue.append(notification)
        # Attempt delivery (mock — real implementation would use APNs/FCM)
        return self._attempt_delivery(notification)

    def broadcast(
        self,
        user_id: str,
        title: str,
        body: str,
        data: Optional[dict] = None,
        platforms: Optional[List[DevicePlatform]] = None,
    ) -> dict:
        """Broadcast a notification to all devices for a user."""
        devices = self._device_manager.get_devices_for_user(user_id)
        if platforms:
            platform_values = {p.value for p in platforms}
            devices = [d for d in devices if d["platform"] in platform_values]
        results = []
        for device in devices:
            result = self.send(device["device_id"], title, body, data)
            results.append(result)
        return {
            "status": "broadcast",
            "target_devices": len(devices),
            "delivered": sum(1 for r in results if r.get("status") == "delivered"),
            "results": results,
        }

    def _attempt_delivery(self, notification: PushNotification) -> dict:
        """Attempt to deliver a notification (mock implementation)."""
        device = self._device_manager._devices.get(notification.device_id)
        if device and device.push_token:
            # In production: call APNs (iOS) or FCM (Android)
            notification.delivered = True
            self._sent_count += 1
            self._delivery_history.append(notification)
            return {"status": "delivered", "notification_id": notification.notification_id}
        else:
            notification.delivery_error = "no_push_token"
            return {"status": "queued", "notification_id": notification.notification_id, "reason": "no_push_token"}

    def get_history(self, device_id: Optional[str] = None, limit: int = 20) -> List[dict]:
        history = self._delivery_history
        if device_id:
            history = [n for n in history if n.device_id == device_id]
        return [n.to_dict() for n in reversed(history)][:limit]

    def status(self) -> dict:
        return {
            "sent_count": self._sent_count,
            "queued_count": len(self._notification_queue),
            "history_count": len(self._delivery_history),
        }


# ---------------------------------------------------------------------------
# macOS Menu Bar Companion
# ---------------------------------------------------------------------------

@dataclass
class MenuBarAction:
    """A quick action available in the macOS menu bar."""
    id: str
    label: str
    shortcut: str = ""
    icon: str = ""
    handler_id: str = ""
    enabled: bool = True
    separator_after: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "shortcut": self.shortcut,
            "icon": self.icon,
            "handler_id": self.handler_id,
            "enabled": self.enabled,
            "separator_after": self.separator_after,
        }


class MenuBarCompanion:
    """
    macOS menu bar companion state and quick actions.
    """

    DEFAULT_ACTIONS = [
        MenuBarAction("new-chat", "New Chat", "⌘N", "chat", "new_chat"),
        MenuBarAction("quick-ask", "Quick Ask...", "⌘K", "search", "quick_ask"),
        MenuBarAction("sep1", "-", separator_after=True),
        MenuBarAction("toggle-voice", "Toggle Voice", "⌘M", "mic", "toggle_voice"),
        MenuBarAction("capture-screen", "Capture Screen", "⌘⇧S", "screenshot", "capture_screen"),
        MenuBarAction("sep2", "-", separator_after=True),
        MenuBarAction("open-dashboard", "Open Dashboard", "⌘D", "dashboard", "open_dashboard"),
        MenuBarAction("preferences", "Preferences...", "⌘,", "gear", "open_prefs"),
        MenuBarAction("sep3", "-", separator_after=True),
        MenuBarAction("quit", "Quit OpenChimera", "⌘Q", "quit", "quit"),
    ]

    def __init__(self):
        self._actions: Dict[str, MenuBarAction] = {a.id: a for a in self.DEFAULT_ACTIONS}
        self._status_text = "OpenChimera"
        self._status_icon = "chimera"
        self._active = False
        self._notifications_enabled = True
        self._last_heartbeat = time.time()
        self._action_history: List[dict] = []

    def update_status(self, text: str, icon: str = "") -> None:
        self._status_text = text
        if icon:
            self._status_icon = icon
        self._last_heartbeat = time.time()

    def add_action(self, action: MenuBarAction) -> None:
        self._actions[action.id] = action

    def remove_action(self, action_id: str) -> bool:
        if action_id in self._actions:
            del self._actions[action_id]
            return True
        return False

    def trigger_action(self, action_id: str, context: Optional[dict] = None) -> dict:
        """Trigger a menu bar action."""
        action = self._actions.get(action_id)
        if not action:
            return {"status": "error", "reason": "action_not_found", "action_id": action_id}
        if not action.enabled:
            return {"status": "error", "reason": "action_disabled", "action_id": action_id}
        entry = {
            "action_id": action_id,
            "label": action.label,
            "handler_id": action.handler_id,
            "context": context or {},
            "timestamp": time.time(),
        }
        self._action_history.append(entry)
        return {"status": "triggered", "action_id": action_id, "handler_id": action.handler_id}

    def heartbeat(self) -> dict:
        """Report companion health status."""
        self._last_heartbeat = time.time()
        return {
            "status": "alive",
            "status_text": self._status_text,
            "status_icon": self._status_icon,
            "active": self._active,
            "notifications_enabled": self._notifications_enabled,
            "last_heartbeat": self._last_heartbeat,
        }

    def get_menu_items(self) -> List[dict]:
        return [a.to_dict() for a in self._actions.values()]

    def status(self) -> dict:
        return {
            "active": self._active,
            "status_text": self._status_text,
            "action_count": len(self._actions),
            "notifications_enabled": self._notifications_enabled,
            "last_heartbeat": self._last_heartbeat,
            "action_history_count": len(self._action_history),
        }


# ---------------------------------------------------------------------------
# Cross-device Session Continuity
# ---------------------------------------------------------------------------

@dataclass
class DeviceSession:
    """A session that can be resumed across devices."""
    session_id: str
    user_id: str
    context: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    origin_device: str = ""
    active_device: str = ""
    checkpoint_data: Optional[str] = None  # JSON-serialized checkpoint

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "origin_device": self.origin_device,
            "active_device": self.active_device,
            "has_checkpoint": self.checkpoint_data is not None,
            "context_keys": list(self.context.keys()),
        }


class SessionContinuityManager:
    """Manages cross-device session continuity."""

    def __init__(self):
        self._sessions: Dict[str, DeviceSession] = {}

    def create_session(self, user_id: str, device_id: str, context: Optional[dict] = None) -> DeviceSession:
        session_id = f"sess-{hashlib.sha256(f'{user_id}:{device_id}:{time.time()}'.encode()).hexdigest()[:16]}"
        session = DeviceSession(
            session_id=session_id,
            user_id=user_id,
            origin_device=device_id,
            active_device=device_id,
            context=context or {},
        )
        self._sessions[session_id] = session
        return session

    def resume_session(self, session_id: str, device_id: str) -> Optional[dict]:
        """Resume a session on a new device."""
        session = self._sessions.get(session_id)
        if not session:
            return None
        session.active_device = device_id
        session.updated_at = time.time()
        return {
            "status": "resumed",
            "session": session.to_dict(),
            "context": session.context,
            "checkpoint": json.loads(session.checkpoint_data) if session.checkpoint_data else None,
        }

    def save_checkpoint(self, session_id: str, checkpoint: dict) -> bool:
        session = self._sessions.get(session_id)
        if not session:
            return False
        session.checkpoint_data = json.dumps(checkpoint)
        session.updated_at = time.time()
        return True

    def update_context(self, session_id: str, context_update: dict) -> bool:
        session = self._sessions.get(session_id)
        if not session:
            return False
        session.context.update(context_update)
        session.updated_at = time.time()
        return True

    def list_sessions(self, user_id: str) -> List[dict]:
        return [s.to_dict() for s in self._sessions.values() if s.user_id == user_id]

    def status(self) -> dict:
        return {
            "total_sessions": len(self._sessions),
            "active_users": len(set(s.user_id for s in self._sessions.values())),
        }


# ---------------------------------------------------------------------------
# Mobile API Facade
# ---------------------------------------------------------------------------

class MobileCompanionAPI:
    """
    Unified facade for all mobile and companion functionality.
    """

    def __init__(self):
        self.device_manager = DeviceManager()
        self.push_manager = PushNotificationManager(self.device_manager)
        self.menu_bar = MenuBarCompanion()
        self.session_continuity = SessionContinuityManager()

    def register_device(self, payload: dict) -> dict:
        """Register a device from mobile API payload."""
        platform_str = payload.get("platform", "other")
        try:
            platform = DevicePlatform(platform_str)
        except ValueError:
            platform = DevicePlatform.OTHER
        return self.device_manager.register(
            device_id=payload.get("device_id", secrets.token_hex(16)),
            user_id=payload.get("user_id", "anonymous"),
            platform=platform,
            device_name=payload.get("device_name", ""),
            device_model=payload.get("device_model", ""),
            os_version=payload.get("os_version", ""),
            app_version=payload.get("app_version", ""),
            push_token=payload.get("push_token", ""),
        )

    def send_push(self, device_id: str, title: str, body: str, data: Optional[dict] = None) -> dict:
        return self.push_manager.send(device_id, title, body, data)

    def status(self) -> dict:
        return {
            "devices": self.device_manager.status(),
            "push": self.push_manager.status(),
            "menu_bar": self.menu_bar.status(),
            "session_continuity": self.session_continuity.status(),
        }
