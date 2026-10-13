from __future__ import annotations

import unittest
from http import HTTPStatus

from core.api_server import (
    MAX_DISCARD_BODY_BYTES,
    MAX_JSON_BODY_BYTES,
    RequestValidationFailure,
    _ProviderRequestHandler,
)


class _EndlessReader:
    """Fake rfile that always has more data and records each read size."""

    def __init__(self) -> None:
        self.reads: list[int] = []

    def read(self, n: int = -1) -> bytes:
        assert n is not None and n >= 0, "unbounded read on request body"
        self.reads.append(n)
        return b"x" * n


class OversizedBodyTests(unittest.TestCase):
    def _handler(self, content_length: str) -> tuple[_ProviderRequestHandler, _EndlessReader]:
        handler = _ProviderRequestHandler.__new__(_ProviderRequestHandler)
        handler.headers = {"Content-Length": content_length}
        reader = _EndlessReader()
        handler.rfile = reader
        handler.close_connection = False
        return handler, reader

    def test_huge_content_length_is_not_buffered(self) -> None:
        handler, reader = self._handler(str(50 * 1024 * 1024 * 1024))  # 50 GB claimed

        with self.assertRaises(RequestValidationFailure) as ctx:
            handler._read_json_body()

        self.assertEqual(ctx.exception.status, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        self.assertLessEqual(max(reader.reads), 64 * 1024)
        self.assertLessEqual(sum(reader.reads), MAX_DISCARD_BODY_BYTES)
        self.assertTrue(handler.close_connection)

    def test_slightly_oversized_body_is_fully_drained(self) -> None:
        size = MAX_JSON_BODY_BYTES + 10
        handler, reader = self._handler(str(size))

        with self.assertRaises(RequestValidationFailure):
            handler._read_json_body()

        self.assertEqual(sum(reader.reads), size)


if __name__ == "__main__":
    unittest.main()
