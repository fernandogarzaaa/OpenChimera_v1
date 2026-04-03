from __future__ import annotations

import json
import logging
import tempfile
import unittest
from pathlib import Path

from core.logging_utils import JsonLogFormatter, RequestContextFilter, clear_request_context, configure_runtime_logging, set_request_context


class LoggingUtilsTests(unittest.TestCase):
    def setUp(self) -> None:
        root_logger = logging.getLogger()
        self._root_level = root_logger.level
        self._root_handlers = list(root_logger.handlers)

    def tearDown(self) -> None:
        root_logger = logging.getLogger()
        for handler in list(root_logger.handlers):
            root_logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass
        root_logger.setLevel(self._root_level)
        for handler in self._root_handlers:
            root_logger.addHandler(handler)

    def test_json_formatter_includes_request_context(self) -> None:
        logger = logging.getLogger("openchimera.test.logging.json")
        logger.handlers = []
        logger.propagate = False
        logger.setLevel(logging.INFO)

        records: list[str] = []

        class _ListHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(self.format(record))

        handler = _ListHandler()
        handler.addFilter(RequestContextFilter())
        handler.setFormatter(JsonLogFormatter())
        logger.addHandler(handler)

        token = set_request_context("req-123")
        try:
            logger.info("structured message", extra={"event": "unit_test", "component": "logging"})
        finally:
            clear_request_context(token)
            logger.removeHandler(handler)

        payload = json.loads(records[0])
        self.assertEqual(payload["message"], "structured message")
        self.assertEqual(payload["request_id"], "req-123")
        self.assertEqual(payload["event"], "unit_test")
        self.assertEqual(payload["component"], "logging")

    def test_configure_runtime_logging_writes_structured_log_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "openchimera-runtime.jsonl"
            configure_runtime_logging(level="INFO", structured_log_path=log_path, enable_console=False)

            logger = logging.getLogger("openchimera.test.logging.file")
            token = set_request_context("req-file")
            try:
                logger.info("file output", extra={"event": "file_test"})
            finally:
                clear_request_context(token)

            root_logger = logging.getLogger()
            for handler in list(root_logger.handlers):
                handler.flush()

            lines = log_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 1)
            payload = json.loads(lines[0])
            self.assertEqual(payload["message"], "file output")
            self.assertEqual(payload["request_id"], "req-file")
            self.assertEqual(payload["event"], "file_test")

            for handler in list(root_logger.handlers):
                root_logger.removeHandler(handler)
                handler.close()