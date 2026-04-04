from __future__ import annotations

import unittest
from unittest.mock import patch

from core.bus import EventBus


class EventBusTests(unittest.TestCase):
    def test_publish_records_history_without_printing(self) -> None:
        bus = EventBus()

        with patch("builtins.print") as print_mock:
            bus.publish("system/demo", {"status": "ok"})

        self.assertEqual(bus.recent_events(), [{"topic": "system/demo", "data": {"status": "ok"}}])
        print_mock.assert_not_called()

    def test_publish_isolates_subscriber_failures(self) -> None:
        bus = EventBus()
        seen: list[dict[str, object]] = []

        def _bad_callback(payload: object) -> None:
            raise RuntimeError("boom")

        def _good_callback(payload: object) -> None:
            seen.append(payload if isinstance(payload, dict) else {})

        bus.subscribe("system/demo", _bad_callback)
        bus.subscribe("system/demo", _good_callback)

        with self.assertLogs("core.bus", level="WARNING") as captured:
            bus.publish("system/demo", {"status": "ok"})

        self.assertEqual(seen, [{"status": "ok"}])
        self.assertTrue(any("subscriber failed" in message.lower() for message in captured.output))


class EventBusBackendTests(unittest.TestCase):
    def test_backend_returns_string(self) -> None:
        from core.bus import backend
        result = backend()
        self.assertIsInstance(result, str)
        self.assertIn(result, {"rust", "python"})

    def test_publish_nowait_does_not_raise(self) -> None:
        """publish_nowait must be safe to call even if the bus has no subscribers."""
        from core._bus_fallback import EventBus as FallbackBus
        bus = FallbackBus()
        # Should not raise despite no subscribers
        bus.publish_nowait("system/test", {"key": "value"})
        events = bus.recent_events()
        self.assertEqual(events[-1]["topic"], "system/test")


if __name__ == "__main__":
    unittest.main()