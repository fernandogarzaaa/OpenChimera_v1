"""Tests for core.fim_daemon — FIMDaemon file integrity monitoring.

Uses temporary files to avoid real filesystem side effects.
"""
from __future__ import annotations
import os
import tempfile
import unittest
from unittest.mock import MagicMock, call, patch

from core.fim_daemon import FIMDaemon


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bus():
    bus = MagicMock()
    bus.publish = MagicMock()
    return bus


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFIMDaemonInit(unittest.TestCase):
    def test_init_with_empty_file_list(self):
        bus = _make_bus()
        daemon = FIMDaemon(bus=bus, files_to_watch=[])
        self.assertEqual(daemon.files_to_watch, [])
        self.assertEqual(daemon.hashes, {})

    def test_init_hashes_existing_files(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
            f.write(b"initial content")
            path = f.name
        try:
            bus = _make_bus()
            daemon = FIMDaemon(bus=bus, files_to_watch=[path])
            self.assertIn(path, daemon.hashes)
            self.assertIsNotNone(daemon.hashes[path])
        finally:
            os.unlink(path)

    def test_init_nonexistent_file_not_in_hashes(self):
        bus = _make_bus()
        daemon = FIMDaemon(bus=bus, files_to_watch=["/nonexistent/path.txt"])
        # Nonexistent files produce None hash and are not added
        self.assertNotIn("/nonexistent/path.txt", daemon.hashes)

    def test_hash_file_returns_none_for_missing(self):
        bus = _make_bus()
        daemon = FIMDaemon(bus=bus, files_to_watch=[])
        result = daemon._hash_file("/does/not/exist")
        self.assertIsNone(result)

    def test_hash_file_is_hex_string(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt") as f:
            f.write(b"hello")
            path = f.name
        try:
            bus = _make_bus()
            daemon = FIMDaemon(bus=bus, files_to_watch=[])
            h = daemon._hash_file(path)
            self.assertIsInstance(h, str)
            self.assertEqual(len(h), 64)  # SHA-256 hex
        finally:
            os.unlink(path)

    def test_hash_changes_after_file_modification(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="wb") as f:
            f.write(b"version1")
            path = f.name
        try:
            bus = _make_bus()
            daemon = FIMDaemon(bus=bus, files_to_watch=[])
            hash1 = daemon._hash_file(path)
            with open(path, "wb") as f2:
                f2.write(b"version2_different")
            hash2 = daemon._hash_file(path)
            self.assertNotEqual(hash1, hash2)
        finally:
            os.unlink(path)


class TestFIMDaemonRunDetection(unittest.TestCase):
    def test_run_detects_file_modification(self):
        """Patch time.sleep so run() ticks once then we break."""
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="wb") as f:
            f.write(b"original")
            path = f.name
        try:
            bus = _make_bus()
            daemon = FIMDaemon(bus=bus, files_to_watch=[path])

            # Modify the file content after init
            with open(path, "wb") as fmod:
                fmod.write(b"tampered content!")

            call_count = {"n": 0}

            def fake_sleep(_sec):
                call_count["n"] += 1
                if call_count["n"] >= 1:
                    raise StopIteration("done")

            with patch("time.sleep", side_effect=fake_sleep):
                try:
                    daemon.run()
                except StopIteration:
                    pass

            bus.publish.assert_called_once()
            event = bus.publish.call_args[0]
            self.assertEqual(event[0], "security_alert")
            self.assertEqual(event[1]["file"], path)
            self.assertEqual(event[1]["status"], "unauthorized_change")
        finally:
            os.unlink(path)

    def test_run_does_not_alert_on_unchanged_file(self):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="wb") as f:
            f.write(b"stable content")
            path = f.name
        try:
            bus = _make_bus()
            daemon = FIMDaemon(bus=bus, files_to_watch=[path])

            call_count = {"n": 0}

            def fake_sleep(_sec):
                call_count["n"] += 1
                raise StopIteration("done")

            with patch("time.sleep", side_effect=fake_sleep):
                try:
                    daemon.run()
                except StopIteration:
                    pass

            bus.publish.assert_not_called()
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
