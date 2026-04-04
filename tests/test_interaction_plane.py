"""Tests for core.interaction_plane — interaction facade over channels/browser/media/query."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from core.interaction_plane import InteractionPlane


def _make_plane(**overrides) -> InteractionPlane:
    defaults = dict(
        channels=MagicMock(),
        browser=MagicMock(),
        multimodal=MagicMock(),
        query_engine=MagicMock(),
        bus=MagicMock(),
        daily_briefing_getter=MagicMock(return_value={"summary": "All good"}),
    )
    defaults.update(overrides)
    return InteractionPlane(**defaults)


class TestInteractionPlane(unittest.TestCase):
    # --- channel methods ---

    def test_channel_status_delegates(self) -> None:
        plane = _make_plane()
        plane.channels.status.return_value = {"ok": True}
        self.assertEqual(plane.channel_status(), {"ok": True})

    def test_channel_delivery_history_delegates(self) -> None:
        plane = _make_plane()
        plane.channels.delivery_history.return_value = []
        result = plane.channel_delivery_history(topic="sys/test", limit=5)
        plane.channels.delivery_history.assert_called_once_with(topic="sys/test", status=None, limit=5)
        self.assertEqual(result, [])

    def test_validate_channel_subscription_publishes(self) -> None:
        plane = _make_plane()
        plane.channels.validate_subscription.return_value = {"valid": True}
        plane.validate_channel_subscription(subscription_id="sub1")
        plane.bus.publish_nowait.assert_called_once()
        topic, payload = plane.bus.publish_nowait.call_args[0]
        self.assertEqual(topic, "system/channels")
        self.assertEqual(payload["action"], "validate")

    def test_upsert_channel_subscription_publishes(self) -> None:
        plane = _make_plane()
        plane.channels.upsert_subscription.return_value = {"id": "sub1"}
        plane.upsert_channel_subscription({"id": "sub1"})
        plane.bus.publish_nowait.assert_called_once()

    def test_delete_channel_subscription_publishes(self) -> None:
        plane = _make_plane()
        plane.channels.delete_subscription.return_value = {"deleted": True}
        plane.delete_channel_subscription("sub1")
        plane.bus.publish_nowait.assert_called_once()

    def test_dispatch_daily_briefing(self) -> None:
        bus = MagicMock()
        channels = MagicMock()
        channels.dispatch.return_value = {"status": "sent"}
        briefing_getter = MagicMock(return_value={"summary": "Morning update"})
        plane = _make_plane(channels=channels, bus=bus, daily_briefing_getter=briefing_getter)
        result = plane.dispatch_daily_briefing()
        self.assertEqual(result["briefing"], {"summary": "Morning update"})
        bus.publish_nowait.assert_called_once()

    def test_dispatch_channel_raises_on_empty_topic(self) -> None:
        plane = _make_plane()
        with self.assertRaises(ValueError):
            plane.dispatch_channel("")

    def test_dispatch_channel_publishes(self) -> None:
        plane = _make_plane()
        plane.channels.dispatch.return_value = {"status": "ok"}
        result = plane.dispatch_channel("sys/health", {"ping": True})
        self.assertEqual(result["topic"], "sys/health")
        plane.bus.publish_nowait.assert_called_once()

    def test_dispatch_channel_non_dict_payload_normalizes(self) -> None:
        plane = _make_plane()
        plane.channels.dispatch.return_value = {}
        result = plane.dispatch_channel("sys/test", None)  # type: ignore[arg-type]
        self.assertEqual(result["payload"], {})

    # --- browser methods ---

    def test_browser_status_delegates(self) -> None:
        plane = _make_plane()
        plane.browser.status.return_value = {"available": False}
        self.assertEqual(plane.browser_status(), {"available": False})

    def test_browser_fetch_publishes(self) -> None:
        plane = _make_plane()
        plane.browser.fetch.return_value = {"content": "page"}
        plane.browser_fetch("https://example.com")
        plane.bus.publish_nowait.assert_called_once()

    def test_browser_submit_form_publishes(self) -> None:
        plane = _make_plane()
        plane.browser.submit_form.return_value = {"status": 200}
        plane.browser_submit_form("https://example.com/form", {"key": "value"})
        plane.bus.publish_nowait.assert_called_once()

    # --- media methods ---

    def test_media_status_delegates(self) -> None:
        plane = _make_plane()
        plane.multimodal.status.return_value = {"available": False}
        self.assertEqual(plane.media_status(), {"available": False})

    def test_media_transcribe_publishes(self) -> None:
        plane = _make_plane()
        plane.multimodal.transcribe.return_value = {"transcript": "hello"}
        plane.media_transcribe(audio_text="hello")
        plane.bus.publish_nowait.assert_called_once()

    def test_media_synthesize_publishes(self) -> None:
        plane = _make_plane()
        plane.multimodal.synthesize.return_value = {"audio": b""}
        plane.media_synthesize("Say something")
        plane.bus.publish_nowait.assert_called_once()

    def test_media_understand_image_publishes(self) -> None:
        plane = _make_plane()
        plane.multimodal.understand_image.return_value = {"description": "A cat"}
        plane.media_understand_image(prompt="What is this?", image_base64="abc")
        plane.bus.publish_nowait.assert_called_once()

    def test_media_generate_image_publishes(self) -> None:
        plane = _make_plane()
        plane.multimodal.generate_image.return_value = {"image_base64": "xyz"}
        plane.media_generate_image("A sunset")
        plane.bus.publish_nowait.assert_called_once()

    # --- query engine methods ---

    def test_query_status_delegates(self) -> None:
        plane = _make_plane()
        plane.query_engine.status.return_value = {"sessions": 0}
        self.assertEqual(plane.query_status(), {"sessions": 0})

    def test_list_query_sessions_delegates(self) -> None:
        plane = _make_plane()
        plane.query_engine.list_sessions.return_value = []
        result = plane.list_query_sessions(limit=5)
        plane.query_engine.list_sessions.assert_called_once_with(limit=5)
        self.assertEqual(result, [])

    def test_get_query_session_delegates(self) -> None:
        plane = _make_plane()
        plane.query_engine.get_session.return_value = {"session_id": "s1"}
        self.assertEqual(plane.get_query_session("s1"), {"session_id": "s1"})

    def test_inspect_memory_delegates(self) -> None:
        plane = _make_plane()
        plane.query_engine.inspect_memory.return_value = {"items": []}
        self.assertEqual(plane.inspect_memory(), {"items": []})

    def test_run_query_publishes(self) -> None:
        plane = _make_plane()
        plane.query_engine.run_query.return_value = {"answer": "42"}
        plane.run_query(query="What is the answer?")
        plane.bus.publish_nowait.assert_called_once()

    def test_run_query_passes_all_params(self) -> None:
        plane = _make_plane()
        plane.query_engine.run_query.return_value = {}
        plane.run_query(
            query="test",
            messages=[{"role": "user", "content": "hi"}],
            session_id="sess1",
            permission_scope="admin",
            max_tokens=256,
            allow_tool_planning=False,
            execute_tools=True,
        )
        call_kw = plane.query_engine.run_query.call_args.kwargs
        self.assertEqual(call_kw["query"], "test")
        self.assertEqual(call_kw["session_id"], "sess1")
        self.assertEqual(call_kw["permission_scope"], "admin")


if __name__ == "__main__":
    unittest.main()
