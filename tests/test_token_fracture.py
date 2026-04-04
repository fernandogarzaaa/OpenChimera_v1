"""Tests for core.token_fracture — compress_context() utility.

All tests are pure-Python with no network or disk I/O.
"""
from __future__ import annotations
import unittest

from core.token_fracture import compress_context, _estimate_tokens


class TestEstimateTokens(unittest.TestCase):
    def test_empty_string(self):
        self.assertEqual(_estimate_tokens(""), 0)

    def test_short_string(self):
        # 4 chars → ceil(4/4) = 1
        self.assertEqual(_estimate_tokens("abcd"), 1)

    def test_longer_string(self):
        text = "a" * 400
        self.assertEqual(_estimate_tokens(text), 100)

    def test_minimum_one(self):
        # Even 1-char strings → 1
        self.assertEqual(_estimate_tokens("x"), 1)


class TestCompressContext(unittest.TestCase):
    def _make_messages(self, n: int, content_len: int = 100) -> list[dict]:
        return [{"role": "user", "content": "a" * content_len}] * n

    # ------------------------------------------------------------------
    # No-op paths
    # ------------------------------------------------------------------

    def test_empty_messages_returns_empty(self):
        msgs, stats = compress_context([], max_tokens=100)
        self.assertEqual(msgs, [])
        self.assertEqual(stats["original_messages"], 0)
        self.assertEqual(stats["original_tokens_estimate"], 0)

    def test_none_messages_returns_empty(self):
        msgs, stats = compress_context(None, max_tokens=100)  # type: ignore[arg-type]
        self.assertEqual(msgs, [])

    def test_zero_max_tokens_returns_original(self):
        """max_tokens <= 0 means no compression."""
        msgs_in = self._make_messages(2, 20)
        msgs_out, stats = compress_context(msgs_in, max_tokens=0)
        self.assertEqual(msgs_out, msgs_in)

    def test_below_limit_returns_uncompressed(self):
        # 2 messages × 4 chars = 8 chars → ~2 tokens; limit is 1000
        msgs_in = self._make_messages(2, 4)
        msgs_out, stats = compress_context(msgs_in, max_tokens=1000)
        self.assertEqual(msgs_out, msgs_in)
        self.assertAlmostEqual(stats["compression_ratio"], 1.0, places=2)

    # ------------------------------------------------------------------
    # Compression paths
    # ------------------------------------------------------------------

    def test_compresses_oversized_content(self):
        # 1 message with 400 chars → ~100 tokens; limit 10 tokens → should compress
        msgs_in = [{"role": "user", "content": "a" * 400}]
        msgs_out, stats = compress_context(msgs_in, max_tokens=10)
        # compressed content should be shorter
        self.assertLess(len(msgs_out[0]["content"]), 400)

    def test_compressed_token_count_below_target(self):
        msgs_in = [{"role": "user", "content": "b" * 800}]
        msgs_out, stats = compress_context(msgs_in, max_tokens=50)
        self.assertLessEqual(stats["compressed_tokens_estimate"], 50)

    def test_roles_preserved_after_compression(self):
        msgs_in = [
            {"role": "system", "content": "s" * 200},
            {"role": "user", "content": "u" * 200},
        ]
        msgs_out, _ = compress_context(msgs_in, max_tokens=20)
        roles_out = [m["role"] for m in msgs_out]
        self.assertEqual(roles_out, ["system", "user"])

    def test_compression_ratio_below_one_when_compressed(self):
        msgs_in = [{"role": "user", "content": "c" * 800}]
        _, stats = compress_context(msgs_in, max_tokens=50)
        self.assertLess(stats["compression_ratio"], 1.0)

    # ------------------------------------------------------------------
    # Stats fields
    # ------------------------------------------------------------------

    def test_stats_contains_expected_keys(self):
        msgs_in = self._make_messages(1, 100)
        _, stats = compress_context(msgs_in, query="hello", max_tokens=500)
        expected_keys = {
            "query", "original_messages", "original_tokens_estimate",
            "compressed_tokens_estimate", "target_max_tokens", "compression_ratio",
        }
        self.assertEqual(set(stats.keys()), expected_keys)

    def test_query_stored_in_stats(self):
        _, stats = compress_context([], query="my query", max_tokens=100)
        self.assertEqual(stats["query"], "my query")


if __name__ == "__main__":
    unittest.main()
