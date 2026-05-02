"""
Tests for Phase 6: Mobile & Companion API.
"""
from __future__ import annotations

import time
import unittest

from core.mobile_companion import (
    DevicePlatform,
    DeviceStatus,
    DeviceRegistration,
    DeviceManager,
    PushNotification,
    PushNotificationManager,
    MenuBarAction,
    MenuBarCompanion,
    DeviceSession,
    SessionContinuityManager,
    MobileCompanionAPI,
)


# ---------------------------------------------------------------------------
# Device Manager Tests
# ---------------------------------------------------------------------------

class TestDeviceManager(unittest.TestCase):
    def setUp(self):
        self.manager = DeviceManager()

    def test_register_new_device(self):
        result = self.manager.register(
            device_id="device-1",
            user_id="user-1",
            platform=DevicePlatform.IOS,
            device_name="iPhone 15",
            push_token="fcm-token-123",
        )
        self.assertEqual(result["status"], "registered")
        self.assertEqual(result["device_id"], "device-1")
        self.assertIn("api_token", result)

    def test_register_existing_device_updates(self):
        self.manager.register("device-2", "user-2", DevicePlatform.ANDROID)
        result = self.manager.register("device-2", "user-2", DevicePlatform.ANDROID, app_version="2.0")
        self.assertEqual(result["status"], "updated")
        self.assertNotIn("api_token", result)  # Token not returned on update

    def test_authenticate_valid_token(self):
        result = self.manager.register("device-3", "user-3", DevicePlatform.IOS)
        token = result["api_token"]
        device = self.manager.authenticate(token)
        self.assertIsNotNone(device)
        self.assertEqual(device.device_id, "device-3")

    def test_authenticate_invalid_token(self):
        device = self.manager.authenticate("invalid-token-xyz")
        self.assertIsNone(device)

    def test_revoke_device(self):
        result = self.manager.register("device-4", "user-4", DevicePlatform.IOS)
        token = result["api_token"]
        self.manager.revoke("device-4")
        # Token should now fail
        device = self.manager.authenticate(token)
        self.assertIsNone(device)

    def test_get_devices_for_user(self):
        self.manager.register("d1", "user-x", DevicePlatform.IOS)
        self.manager.register("d2", "user-x", DevicePlatform.ANDROID)
        self.manager.register("d3", "user-y", DevicePlatform.IOS)
        devices = self.manager.get_devices_for_user("user-x")
        self.assertEqual(len(devices), 2)

    def test_ios_default_capabilities(self):
        result = self.manager.register("ios-dev", "user", DevicePlatform.IOS)
        # Get device capabilities from registered device
        device = self.manager._devices["ios-dev"]
        self.assertIn("push_notifications", device.capabilities)
        self.assertIn("siri_shortcuts", device.capabilities)

    def test_android_default_capabilities(self):
        self.manager.register("android-dev", "user", DevicePlatform.ANDROID)
        device = self.manager._devices["android-dev"]
        self.assertIn("push_notifications", device.capabilities)
        self.assertIn("widgets", device.capabilities)

    def test_macos_menubar_capabilities(self):
        self.manager.register("mac-dev", "user", DevicePlatform.MACOS_MENUBAR)
        device = self.manager._devices["mac-dev"]
        self.assertIn("menu_bar", device.capabilities)
        self.assertIn("quick_actions", device.capabilities)

    def test_status_structure(self):
        status = self.manager.status()
        self.assertIn("total_registrations", status)
        self.assertIn("active_devices", status)
        self.assertIn("by_platform", status)

    def test_device_to_dict_excludes_token(self):
        result = self.manager.register("d-dict", "user", DevicePlatform.IOS)
        device = self.manager._devices["d-dict"]
        d = device.to_dict()
        self.assertNotIn("api_token", d)
        self.assertIn("has_push_token", d)


# ---------------------------------------------------------------------------
# Push Notification Tests
# ---------------------------------------------------------------------------

class TestPushNotificationManager(unittest.TestCase):
    def setUp(self):
        self.device_mgr = DeviceManager()
        self.push_mgr = PushNotificationManager(self.device_mgr)

    def _register_device_with_token(self, device_id, user_id, platform=DevicePlatform.IOS):
        return self.device_mgr.register(
            device_id, user_id, platform, push_token=f"token-{device_id}"
        )

    def test_send_notification_with_token(self):
        self._register_device_with_token("push-dev-1", "user-push")
        result = self.push_mgr.send("push-dev-1", "Test Title", "Test Body")
        self.assertEqual(result["status"], "delivered")

    def test_send_to_unknown_device(self):
        result = self.push_mgr.send("nonexistent", "Title", "Body")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["reason"], "device_not_found")

    def test_send_without_push_token(self):
        self.device_mgr.register("no-token-dev", "user", DevicePlatform.IOS, push_token="")
        result = self.push_mgr.send("no-token-dev", "Title", "Body")
        self.assertEqual(result["status"], "queued")

    def test_broadcast_to_user_devices(self):
        self._register_device_with_token("broadcast-1", "user-bc")
        self._register_device_with_token("broadcast-2", "user-bc")
        result = self.push_mgr.broadcast("user-bc", "Broadcast", "Hello all devices")
        self.assertEqual(result["status"], "broadcast")
        self.assertEqual(result["target_devices"], 2)
        self.assertEqual(result["delivered"], 2)

    def test_broadcast_platform_filter(self):
        self._register_device_with_token("ios-bc", "user-filter", DevicePlatform.IOS)
        self._register_device_with_token("android-bc", "user-filter", DevicePlatform.ANDROID)
        result = self.push_mgr.broadcast("user-filter", "iOS Only", "For iOS", platforms=[DevicePlatform.IOS])
        self.assertEqual(result["target_devices"], 1)

    def test_delivery_history(self):
        self._register_device_with_token("hist-dev", "user-hist")
        self.push_mgr.send("hist-dev", "Test", "Body")
        history = self.push_mgr.get_history()
        self.assertGreater(len(history), 0)

    def test_status_structure(self):
        status = self.push_mgr.status()
        self.assertIn("sent_count", status)
        self.assertIn("queued_count", status)


# ---------------------------------------------------------------------------
# Menu Bar Tests
# ---------------------------------------------------------------------------

class TestMenuBarCompanion(unittest.TestCase):
    def setUp(self):
        self.menubar = MenuBarCompanion()

    def test_default_actions_present(self):
        items = self.menubar.get_menu_items()
        self.assertGreater(len(items), 0)
        action_ids = [item["id"] for item in items]
        self.assertIn("new-chat", action_ids)
        self.assertIn("quit", action_ids)

    def test_trigger_valid_action(self):
        result = self.menubar.trigger_action("new-chat")
        self.assertEqual(result["status"], "triggered")
        self.assertEqual(result["action_id"], "new-chat")

    def test_trigger_unknown_action(self):
        result = self.menubar.trigger_action("nonexistent")
        self.assertEqual(result["status"], "error")

    def test_trigger_disabled_action(self):
        action = MenuBarAction(id="disabled-action", label="Disabled", enabled=False)
        self.menubar.add_action(action)
        result = self.menubar.trigger_action("disabled-action")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["reason"], "action_disabled")

    def test_add_custom_action(self):
        action = MenuBarAction(id="custom", label="Custom Action", shortcut="⌘X", handler_id="custom_handler")
        self.menubar.add_action(action)
        items = self.menubar.get_menu_items()
        ids = [i["id"] for i in items]
        self.assertIn("custom", ids)

    def test_remove_action(self):
        result = self.menubar.remove_action("quit")
        self.assertTrue(result)
        result = self.menubar.remove_action("quit")  # Already removed
        self.assertFalse(result)

    def test_update_status(self):
        self.menubar.update_status("Thinking...", "spinner")
        status = self.menubar.status()
        self.assertEqual(status["status_text"], "Thinking...")

    def test_heartbeat(self):
        result = self.menubar.heartbeat()
        self.assertEqual(result["status"], "alive")
        self.assertIn("status_text", result)
        self.assertIn("last_heartbeat", result)

    def test_status_structure(self):
        status = self.menubar.status()
        self.assertIn("active", status)
        self.assertIn("action_count", status)
        self.assertIn("last_heartbeat", status)


# ---------------------------------------------------------------------------
# Session Continuity Tests
# ---------------------------------------------------------------------------

class TestSessionContinuityManager(unittest.TestCase):
    def setUp(self):
        self.manager = SessionContinuityManager()

    def test_create_session(self):
        session = self.manager.create_session("user-1", "device-1", {"mode": "voice"})
        self.assertIsNotNone(session.session_id)
        self.assertEqual(session.user_id, "user-1")
        self.assertEqual(session.origin_device, "device-1")

    def test_resume_session(self):
        session = self.manager.create_session("user-2", "device-2")
        result = self.manager.resume_session(session.session_id, "device-3")
        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "resumed")
        self.assertEqual(result["session"]["active_device"], "device-3")

    def test_resume_unknown_session(self):
        result = self.manager.resume_session("nonexistent-session", "device-x")
        self.assertIsNone(result)

    def test_save_and_restore_checkpoint(self):
        session = self.manager.create_session("user-3", "device-3")
        checkpoint = {"conversation": [{"role": "user", "text": "Hello"}], "goal": "answer_question"}
        self.manager.save_checkpoint(session.session_id, checkpoint)
        result = self.manager.resume_session(session.session_id, "device-4")
        self.assertIsNotNone(result["checkpoint"])
        self.assertIn("conversation", result["checkpoint"])

    def test_update_context(self):
        session = self.manager.create_session("user-4", "device-4")
        self.manager.update_context(session.session_id, {"active_tool": "web-search"})
        self.assertEqual(session.context.get("active_tool"), "web-search")

    def test_list_sessions_for_user(self):
        self.manager.create_session("user-5", "device-5a")
        self.manager.create_session("user-5", "device-5b")
        self.manager.create_session("user-6", "device-6")
        sessions = self.manager.list_sessions("user-5")
        self.assertEqual(len(sessions), 2)

    def test_status_structure(self):
        status = self.manager.status()
        self.assertIn("total_sessions", status)
        self.assertIn("active_users", status)


# ---------------------------------------------------------------------------
# MobileCompanionAPI Facade Tests
# ---------------------------------------------------------------------------

class TestMobileCompanionAPI(unittest.TestCase):
    def setUp(self):
        self.api = MobileCompanionAPI()

    def test_register_device_payload(self):
        result = self.api.register_device({
            "device_id": "api-dev-1",
            "user_id": "api-user-1",
            "platform": "ios",
            "device_name": "Test iPhone",
            "push_token": "apns-token",
        })
        self.assertEqual(result["status"], "registered")

    def test_register_unknown_platform(self):
        result = self.api.register_device({
            "device_id": "api-dev-2",
            "user_id": "api-user-2",
            "platform": "unknown-platform-xyz",
        })
        # Should default to "other"
        self.assertIn("status", result)

    def test_send_push_via_api(self):
        self.api.register_device({
            "device_id": "push-api-dev",
            "user_id": "push-user",
            "platform": "android",
            "push_token": "fcm-token",
        })
        result = self.api.send_push("push-api-dev", "Hello", "World")
        self.assertEqual(result["status"], "delivered")

    def test_status_structure(self):
        status = self.api.status()
        self.assertIn("devices", status)
        self.assertIn("push", status)
        self.assertIn("menu_bar", status)
        self.assertIn("session_continuity", status)


if __name__ == "__main__":
    unittest.main()
