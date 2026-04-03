from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_REQUEST_ID: ContextVar[str | None] = ContextVar("openchimera_request_id", default=None)

_STANDARD_RECORD_FIELDS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
}


def set_request_context(request_id: str | None) -> object:
    return _REQUEST_ID.set(request_id or None)


def clear_request_context(token: object | None = None) -> None:
    if token is None:
        _REQUEST_ID.set(None)
        return
    _REQUEST_ID.reset(token)


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "request_id", None):
            record.request_id = _REQUEST_ID.get()
        return True


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = getattr(record, "request_id", None)
        if request_id:
            payload["request_id"] = request_id

        for key, value in record.__dict__.items():
            if key in _STANDARD_RECORD_FIELDS or key.startswith("_"):
                continue
            if key == "request_id" and not value:
                continue
            payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)
        return json.dumps(payload, default=str)


def configure_runtime_logging(*, level: str, structured_log_path: str | Path | None, verbose: bool = False, enable_console: bool = True) -> None:
    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass

    resolved_level_name = "DEBUG" if verbose else str(level or "INFO").upper()
    resolved_level = getattr(logging, resolved_level_name, logging.INFO)
    root_logger.setLevel(resolved_level)

    context_filter = RequestContextFilter()

    if enable_console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(resolved_level)
        console_handler.addFilter(context_filter)
        console_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        root_logger.addHandler(console_handler)

    if structured_log_path:
        target_path = Path(structured_log_path).expanduser()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(target_path, encoding="utf-8")
        file_handler.setLevel(resolved_level)
        file_handler.addFilter(context_filter)
        file_handler.setFormatter(JsonLogFormatter())
        root_logger.addHandler(file_handler)
