"""Tests for Phase 5 — ActiveInquiry bus event emission."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from core.active_inquiry import ActiveInquiry


def _make_semantic(triples=None):
    sem = MagicMock()
    sem.get_triples = MagicMock(return_value=triples or [])
    return sem


class TestActiveInquiryBusEmission(unittest.TestCase):
    """Verify post_question emits bus events when bus is provided."""

    def test_post_question_emits_event_with_bus(self):
        bus = MagicMock()
        bus.publish_nowait = MagicMock()
        ai = ActiveInquiry(semantic=_make_semantic(), episodic=None, bus=bus)
        entry = ai.post_question("Why is the sky blue?")
        bus.publish_nowait.assert_called_once()
        topic, payload = bus.publish_nowait.call_args[0]
        self.assertEqual(topic, "inquiry/question_posted")
        self.assertEqual(payload["question_id"], entry["question_id"])
        self.assertIn("Why is the sky blue?", payload["question"])

    def test_post_question_no_bus_does_not_raise(self):
        ai = ActiveInquiry(semantic=_make_semantic(), episodic=None, bus=None)
        entry = ai.post_question("Test question")
        self.assertIn("question_id", entry)

    def test_post_question_truncates_long_question_in_event(self):
        bus = MagicMock()
        bus.publish_nowait = MagicMock()
        ai = ActiveInquiry(semantic=_make_semantic(), episodic=None, bus=bus)
        long_q = "Q" * 500
        ai.post_question(long_q)
        _, payload = bus.publish_nowait.call_args[0]
        self.assertLessEqual(len(payload["question"]), 200)

    def test_bus_exception_is_swallowed(self):
        bus = MagicMock()
        bus.publish_nowait = MagicMock(side_effect=RuntimeError("bus down"))
        ai = ActiveInquiry(semantic=_make_semantic(), episodic=None, bus=bus)
        entry = ai.post_question("Should not fail")
        self.assertIn("question_id", entry)


if __name__ == "__main__":
    unittest.main()
