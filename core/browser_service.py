from __future__ import annotations

import json
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib import parse, request

from core.config import ROOT
from core.resilience import retry_call
from core.transactions import atomic_write_json


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self.parts.append(text)

    def text(self) -> str:
        return "\n".join(self.parts)


class BrowserService:
    def __init__(self, artifact_root: Path | None = None, history_path: Path | None = None):
        self.artifact_root = artifact_root or (ROOT / "sandbox" / "artifacts" / "browser")
        self.history_path = history_path or (ROOT / "data" / "browser_sessions.json")

    def status(self) -> dict[str, Any]:
        history = self._load_history()
        return {
            "enabled": True,
            "artifact_root": str(self.artifact_root),
            "history_path": str(self.history_path),
            "recent_sessions": history[-10:],
            "supported_actions": ["fetch", "submit_form"],
        }

    def fetch(self, url: str, max_chars: int = 4000) -> dict[str, Any]:
        normalized_url = self._validate_url(url)

        def _fetch() -> tuple[str, str]:
            req = request.Request(normalized_url, headers={"User-Agent": "OpenChimeraBrowser/1.0"}, method="GET")
            with request.urlopen(req, timeout=10) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                html = response.read().decode(charset, errors="ignore")
                return html, response.headers.get_content_type() or "text/html"

        html, content_type = retry_call(_fetch, attempts=2, delay_seconds=0.2, retry_exceptions=(OSError, TimeoutError))
        text = self._extract_text(html)[: max(256, int(max_chars))]
        artifact = self._write_artifact("fetch", normalized_url, {"content_type": content_type, "text": text, "html": html[:10000]})
        record = {
            "action": "fetch",
            "url": normalized_url,
            "content_type": content_type,
            "text_preview": text[:500],
            "artifact": artifact,
            "recorded_at": int(time.time()),
        }
        self._append_history(record)
        return record

    def submit_form(self, url: str, form_data: dict[str, Any], method: str = "POST", max_chars: int = 4000) -> dict[str, Any]:
        normalized_url = self._validate_url(url)
        encoded = parse.urlencode({str(key): str(value) for key, value in form_data.items()}).encode("utf-8")
        upper_method = method.upper()
        if upper_method not in {"GET", "POST"}:
            raise ValueError("Only GET and POST form submissions are supported")

        def _submit() -> tuple[str, str]:
            target_url = normalized_url
            body = None
            if upper_method == "GET":
                separator = "&" if parse.urlparse(target_url).query else "?"
                target_url = target_url + separator + encoded.decode("utf-8")
            else:
                body = encoded
            req = request.Request(
                target_url,
                data=body,
                headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "OpenChimeraBrowser/1.0"},
                method=upper_method,
            )
            with request.urlopen(req, timeout=10) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                html = response.read().decode(charset, errors="ignore")
                return html, response.headers.get_content_type() or "text/html"

        html, content_type = retry_call(_submit, attempts=2, delay_seconds=0.2, retry_exceptions=(OSError, TimeoutError))
        text = self._extract_text(html)[: max(256, int(max_chars))]
        artifact = self._write_artifact(
            "submit_form",
            normalized_url,
            {"method": upper_method, "form_data": form_data, "content_type": content_type, "text": text, "html": html[:10000]},
        )
        record = {
            "action": "submit_form",
            "url": normalized_url,
            "method": upper_method,
            "content_type": content_type,
            "text_preview": text[:500],
            "artifact": artifact,
            "recorded_at": int(time.time()),
        }
        self._append_history(record)
        return record

    def _validate_url(self, url: str) -> str:
        parsed = parse.urlparse(str(url).strip())
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("Only http and https URLs are supported")
        if not parsed.netloc:
            raise ValueError("URL must include a host")
        return parsed.geturl()

    def _extract_text(self, html: str) -> str:
        parser = _TextExtractor()
        parser.feed(html)
        return parser.text()

    def _write_artifact(self, action: str, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        artifact_path = self.artifact_root / f"{action}-{int(time.time() * 1000)}.json"
        atomic_write_json(artifact_path, {"url": url, "action": action, "payload": payload, "created_at": int(time.time())})
        return {"path": str(artifact_path)}

    def _load_history(self) -> list[dict[str, Any]]:
        if not self.history_path.exists():
            return []
        try:
            raw = json.loads(self.history_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        return raw if isinstance(raw, list) else []

    def _append_history(self, record: dict[str, Any]) -> None:
        history = self._load_history()
        history.append(record)
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(self.history_path, history[-50:])