from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.browser_service import BrowserService


class _FakeHeaders:
    def get_content_charset(self) -> str:
        return "utf-8"

    def get_content_type(self) -> str:
        return "text/html"


class _FakeResponse:
    def __init__(self, html: str):
        self._html = html.encode("utf-8")
        self.headers = _FakeHeaders()

    def read(self) -> bytes:
        return self._html

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


class BrowserServiceTests(unittest.TestCase):
    def test_fetch_extracts_text_and_writes_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = BrowserService(
                artifact_root=Path(temp_dir) / "artifacts",
                history_path=Path(temp_dir) / "browser_sessions.json",
            )
            with patch("core.browser_service.request.urlopen", return_value=_FakeResponse("<html><body><h1>Hello</h1><p>World</p></body></html>")):
                result = service.fetch("https://example.invalid")
            self.assertIn("Hello", result["text_preview"])
            artifact = Path(result["artifact"]["path"])
            self.assertTrue(artifact.exists())
            history = json.loads((Path(temp_dir) / "browser_sessions.json").read_text(encoding="utf-8"))
            self.assertEqual(history[-1]["action"], "fetch")

    def test_submit_form_supports_post_and_records_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = BrowserService(
                artifact_root=Path(temp_dir) / "artifacts",
                history_path=Path(temp_dir) / "browser_sessions.json",
            )
            with patch("core.browser_service.request.urlopen", return_value=_FakeResponse("<html><body>Submitted</body></html>")):
                result = service.submit_form("https://example.invalid/form", {"q": "openchimera"}, method="POST")
            self.assertEqual(result["method"], "POST")
            self.assertIn("Submitted", result["text_preview"])


if __name__ == "__main__":
    unittest.main()