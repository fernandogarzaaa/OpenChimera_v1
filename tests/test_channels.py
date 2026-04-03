from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.channels import ChannelManager


class _FakeResponse:
    def __init__(self, status: int = 200, body: str = "{}"):
        self.status = status
        self._body = body.encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class ChannelManagerTests(unittest.TestCase):
    def test_upsert_and_delete_subscription(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = ChannelManager(store_path=Path(temp_dir) / "subscriptions.json")
            stored = manager.upsert_subscription({"id": "ops", "channel": "webhook", "endpoint": "http://example.invalid", "topics": ["*"]})
            self.assertEqual(stored["id"], "ops")
            self.assertEqual(manager.status()["counts"]["total"], 1)
            deleted = manager.delete_subscription("ops")
            self.assertTrue(deleted["deleted"])

    def test_dispatch_uses_matching_subscriptions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = ChannelManager(store_path=Path(temp_dir) / "subscriptions.json")
            manager.upsert_subscription({"id": "ops", "channel": "webhook", "endpoint": "http://example.invalid", "topics": ["system/briefing/daily"]})
            with patch("core.channels.manager.request.urlopen", return_value=_FakeResponse()):
                result = manager.dispatch("system/briefing/daily", {"summary": "ok"})
            self.assertEqual(result["delivery_count"], 1)
            self.assertEqual(result["results"][0]["status"], "delivered")

    def test_default_subscription_topics_include_autonomy_alerts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = ChannelManager(store_path=Path(temp_dir) / "subscriptions.json")

            stored = manager.upsert_subscription({"id": "ops", "channel": "webhook", "endpoint": "http://example.invalid"})

            self.assertIn("system/autonomy/alert", stored["topics"])

    def test_webhook_subscription_requires_endpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = ChannelManager(store_path=Path(temp_dir) / "subscriptions.json")

            with self.assertRaisesRegex(ValueError, "requires a non-empty endpoint"):
                manager.upsert_subscription({"id": "ops", "channel": "webhook"})

    def test_telegram_subscription_requires_bot_token_and_chat_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = ChannelManager(store_path=Path(temp_dir) / "subscriptions.json")

            with self.assertRaisesRegex(ValueError, "requires a bot_token"):
                manager.upsert_subscription({"id": "ops", "channel": "telegram", "chat_id": "123"})

            with self.assertRaisesRegex(ValueError, "requires a chat_id"):
                manager.upsert_subscription({"id": "ops", "channel": "telegram", "bot_token": "abc"})

    def test_delivery_history_records_and_filters_dispatches(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = ChannelManager(store_path=Path(temp_dir) / "subscriptions.json")
            manager.upsert_subscription({"id": "ops", "channel": "webhook", "endpoint": "http://example.invalid", "topics": ["system/autonomy/alert"]})
            with patch("core.channels.manager.request.urlopen", return_value=_FakeResponse()):
                manager.dispatch("system/autonomy/alert", {"message": "ok", "severity": "high"})

            history = manager.delivery_history(topic="system/autonomy/alert", status="delivered", limit=5)

            self.assertEqual(history["count"], 1)
            self.assertEqual(history["history"][0]["delivered_count"], 1)
            self.assertEqual(history["history"][0]["payload_preview"]["message"], "ok")
            self.assertTrue((Path(temp_dir) / "openchimera.db").exists())

    def test_validate_subscription_persists_last_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = ChannelManager(store_path=Path(temp_dir) / "subscriptions.json")
            manager.upsert_subscription({"id": "ops", "channel": "webhook", "endpoint": "http://example.invalid", "topics": ["*"]})

            with patch("core.channels.manager.request.urlopen", return_value=_FakeResponse(status=202)):
                result = manager.validate_subscription(subscription_id="ops")

            self.assertEqual(result["status"], "delivered")
            self.assertEqual(result["status_code"], 202)
            status = manager.status()
            self.assertEqual(status["counts"]["validated"], 1)
            self.assertEqual(status["counts"]["healthy"], 1)
            self.assertEqual(status["subscriptions"][0]["last_validation"]["status"], "delivered")

    def test_filesystem_subscription_writes_local_operator_feed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            feed_path = temp_root / "operator-feed.jsonl"
            manager = ChannelManager(store_path=temp_root / "subscriptions.json")
            manager.upsert_subscription({"id": "ops-local", "channel": "filesystem", "file_path": str(feed_path), "topics": ["system/autonomy/alert"]})

            result = manager.dispatch("system/autonomy/alert", {"message": "attention", "severity": "high"})

            self.assertEqual(result["results"][0]["status"], "delivered")
            lines = feed_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 1)
            payload = json.loads(lines[0])
            self.assertEqual(payload["topic"], "system/autonomy/alert")
            self.assertEqual(payload["payload"]["message"], "attention")

    def test_channel_manager_migrates_legacy_subscription_store(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            legacy_path = Path(temp_dir) / "subscriptions.json"
            legacy_path.write_text(
                '{"subscriptions":[{"id":"ops","channel":"webhook","enabled":true,"topics":["*"],"endpoint":"http://example.invalid"}],"last_delivery":{},"delivery_history":[]}',
                encoding="utf-8",
            )
            manager = ChannelManager(store_path=legacy_path)

            status = manager.status()

            self.assertEqual(status["counts"]["total"], 1)
            self.assertFalse(legacy_path.exists())


if __name__ == "__main__":
    unittest.main()