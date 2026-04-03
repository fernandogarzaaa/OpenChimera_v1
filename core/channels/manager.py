from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib import request

from core.config import ROOT
from core.database import DatabaseManager
from core.resilience import retry_call


SUPPORTED_CHANNELS = {"filesystem", "webhook", "slack", "discord", "telegram"}
MAX_DELIVERY_HISTORY = 100


class ChannelManager:
    def __init__(
        self,
        store_path: Path | None = None,
        database: DatabaseManager | None = None,
        database_path: Path | None = None,
    ):
        self.store_path = store_path or (ROOT / "data" / "subscriptions.json")
        self.database = database or DatabaseManager(db_path=database_path or (self.store_path.parent / "openchimera.db"))
        self.database.initialize()

    def status(self) -> dict[str, Any]:
        subscriptions = self.database.list_subscriptions()
        delivery_history = self.database.list_channel_deliveries()
        validation_statuses = [
            str(item.get("last_validation", {}).get("status", "")).strip().lower()
            for item in subscriptions
            if isinstance(item, dict) and isinstance(item.get("last_validation", {}), dict)
        ]
        return {
            "subscriptions": subscriptions,
            "supported_channels": sorted(SUPPORTED_CHANNELS),
            "counts": {
                "total": len(subscriptions),
                "enabled": sum(1 for item in subscriptions if item.get("enabled", True)),
                "validated": len(validation_statuses),
                "healthy": sum(1 for item in validation_statuses if item == "delivered"),
                "errors": sum(1 for item in validation_statuses if item == "error"),
            },
            "last_delivery": delivery_history[-1] if delivery_history else {},
            "delivery_history_count": len(delivery_history),
            "database_path": str(self.database.db_path),
        }

    def list_subscriptions(self) -> list[dict[str, Any]]:
        return list(self.database.list_subscriptions())

    def delivery_history(self, topic: str | None = None, status: str | None = None, limit: int = 20) -> dict[str, Any]:
        entries = [item for item in self.database.list_channel_deliveries() if isinstance(item, dict)]
        normalized_topic = str(topic or "").strip()
        normalized_status = str(status or "").strip().lower()
        if normalized_topic:
            entries = [item for item in entries if str(item.get("topic", "")).strip() == normalized_topic]
        if normalized_status:
            entries = [item for item in entries if any(str(result.get("status", "")).strip().lower() == normalized_status for result in item.get("results", []) if isinstance(result, dict))]
        effective_limit = max(1, int(limit))
        filtered = list(reversed(entries))[:effective_limit]
        return {
            "topic": normalized_topic,
            "status": normalized_status,
            "count": len(filtered),
            "history": filtered,
        }

    def upsert_subscription(self, subscription: dict[str, Any]) -> dict[str, Any]:
        normalized = self._normalize_subscription(subscription)
        self.database.upsert_subscription(normalized)
        return normalized

    def delete_subscription(self, subscription_id: str) -> dict[str, Any]:
        deleted = self.database.delete_subscription(subscription_id)
        return {"deleted": deleted, "subscription_id": subscription_id}

    def dispatch(self, topic: str, payload: dict[str, Any]) -> dict[str, Any]:
        subscriptions = self.database.list_subscriptions()
        results: list[dict[str, Any]] = []
        for subscription in subscriptions:
            if not subscription.get("enabled", True):
                continue
            topics = subscription.get("topics", [])
            if topics and topic not in topics and "*" not in topics:
                continue
            result = self._deliver(subscription, topic, payload)
            results.append(result)
        delivery_record = {
            "topic": topic,
            "dispatched_at": int(time.time()),
            "delivery_count": len(results),
            "delivered_count": sum(1 for item in results if item.get("status") == "delivered"),
            "error_count": sum(1 for item in results if item.get("status") == "error"),
            "skipped_count": sum(1 for item in results if item.get("status") == "skipped"),
            "payload_preview": self._payload_preview(payload),
            "results": results[-10:],
        }
        self.database.record_channel_delivery(delivery_record)
        return {"topic": topic, "delivery_count": len(results), "results": results}

    def validate_subscription(self, subscription_id: str = "", subscription: dict[str, Any] | None = None) -> dict[str, Any]:
        subscriptions = self.database.list_subscriptions()
        target: dict[str, Any] | None = None

        normalized_id = str(subscription_id).strip()
        if normalized_id:
            for current in subscriptions:
                if isinstance(current, dict) and str(current.get("id", "")).strip() == normalized_id:
                    target = dict(current)
                    break
            if target is None:
                raise ValueError(f"Unknown subscription: {normalized_id}")
        elif isinstance(subscription, dict) and subscription:
            target = self._normalize_subscription(subscription)
        else:
            raise ValueError("Channel validation requires a subscription_id or subscription payload")

        probe_payload = {
            "summary": "OpenChimera channel validation ping.",
            "message": "Operator channel validation ping.",
            "severity": "info",
            "subscription_id": target.get("id", ""),
        }
        delivery = self._deliver(target, "system/channels/validate", probe_payload)
        validation = {
            "subscription_id": target.get("id", ""),
            "channel": target.get("channel", ""),
            "validated_at": int(time.time()),
            "topic": "system/channels/validate",
            "endpoint": self._resolve_endpoint(target),
            "status": str(delivery.get("status", "error")),
        }
        if delivery.get("status_code") is not None:
            validation["status_code"] = delivery.get("status_code")
        if delivery.get("error"):
            validation["error"] = str(delivery.get("error"))

        if target is not None and subscription_id:
            updated = dict(target)
            updated["last_validation"] = validation
            self.database.upsert_subscription(updated)
        return validation

    def _deliver(self, subscription: dict[str, Any], topic: str, payload: dict[str, Any]) -> dict[str, Any]:
        channel = str(subscription.get("channel", "webhook"))
        body = {
            "subscription_id": subscription.get("id"),
            "channel": channel,
            "topic": topic,
            "payload": payload,
            "sent_at": int(time.time()),
        }

        if channel == "filesystem":
            file_path = Path(str(subscription.get("file_path", "")).strip())
            if not str(file_path).strip():
                return {"subscription_id": subscription.get("id"), "status": "skipped", "error": "Missing file_path"}
            try:
                file_path.parent.mkdir(parents=True, exist_ok=True)
                with file_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(body) + "\n")
                return {
                    "subscription_id": subscription.get("id"),
                    "status": "delivered",
                    "channel": channel,
                    "file_path": str(file_path),
                }
            except OSError as exc:
                return {
                    "subscription_id": subscription.get("id"),
                    "status": "error",
                    "channel": channel,
                    "file_path": str(file_path),
                    "error": str(exc),
                }

        endpoint = self._resolve_endpoint(subscription)

        if not endpoint:
            return {"subscription_id": subscription.get("id"), "status": "skipped", "error": "Missing endpoint"}

        def _send() -> dict[str, Any]:
            data = json.dumps(body).encode("utf-8")
            headers = {"Content-Type": "application/json"}
            if channel == "telegram":
                data = json.dumps({"chat_id": subscription.get("chat_id"), "text": json.dumps(body)}).encode("utf-8")
            req = request.Request(endpoint, data=data, headers=headers, method="POST")
            with request.urlopen(req, timeout=5) as response:
                return {
                    "subscription_id": subscription.get("id"),
                    "status": "delivered",
                    "status_code": getattr(response, "status", 200),
                    "channel": channel,
                }

        try:
            return retry_call(_send, attempts=2, delay_seconds=0.2, retry_exceptions=(OSError, TimeoutError))
        except Exception as exc:
            return {
                "subscription_id": subscription.get("id"),
                "status": "error",
                "channel": channel,
                "error": str(exc),
            }

    def _resolve_endpoint(self, subscription: dict[str, Any]) -> str:
        channel = str(subscription.get("channel", "webhook"))
        if channel in {"webhook", "slack", "discord"}:
            return str(subscription.get("endpoint", "")).strip()
        if channel == "filesystem":
            return str(subscription.get("file_path", "")).strip()
        if channel == "telegram":
            bot_token = str(subscription.get("bot_token", "")).strip()
            if not bot_token:
                return ""
            return f"https://api.telegram.org/bot{bot_token}/sendMessage"
        return ""

    def _normalize_subscription(self, subscription: dict[str, Any]) -> dict[str, Any]:
        channel = str(subscription.get("channel", "webhook")).strip().lower()
        if channel not in SUPPORTED_CHANNELS:
            raise ValueError(f"Unsupported channel: {channel}")
        subscription_id = str(subscription.get("id") or f"{channel}-{int(time.time() * 1000)}")
        topics = subscription.get("topics", ["system/autonomy/job", "system/autonomy/alert", "system/briefing/daily"])
        if not isinstance(topics, list):
            topics = [str(topics)]
        normalized = {
            "id": subscription_id,
            "channel": channel,
            "enabled": bool(subscription.get("enabled", True)),
            "topics": [str(item) for item in topics],
        }
        if channel == "filesystem":
            file_path = str(subscription.get("file_path", "")).strip()
            if not file_path:
                raise ValueError("Channel 'filesystem' requires a file_path")
            normalized["file_path"] = file_path
        if channel in {"webhook", "slack", "discord"}:
            endpoint = str(subscription.get("endpoint", "")).strip()
            if not endpoint:
                raise ValueError(f"Channel '{channel}' requires a non-empty endpoint")
            normalized["endpoint"] = endpoint
        if channel == "telegram":
            bot_token = str(subscription.get("bot_token", "")).strip()
            chat_id = str(subscription.get("chat_id", "")).strip()
            if not bot_token:
                raise ValueError("Channel 'telegram' requires a bot_token")
            if not chat_id:
                raise ValueError("Channel 'telegram' requires a chat_id")
            normalized["bot_token"] = bot_token
            normalized["chat_id"] = chat_id
        return normalized

    def _payload_preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {}
        preview: dict[str, Any] = {}
        if isinstance(payload.get("briefing"), dict):
            briefing = payload.get("briefing", {})
            preview["summary"] = str(briefing.get("summary", ""))[:200]
        for key in ("summary", "message", "severity", "job", "artifact_name"):
            value = payload.get(key)
            if value not in {None, ""}:
                preview[key] = value
        if not preview:
            preview["keys"] = sorted(str(item) for item in payload.keys())[:8]
        return preview

