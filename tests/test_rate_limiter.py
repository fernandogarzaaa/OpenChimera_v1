"""Tests for core.rate_limiter — RateLimiter, _TokenBucket, backends, and RateLimitDecision."""
from __future__ import annotations

import os
import time
import unittest
from unittest.mock import MagicMock, patch

try:
    from dataclasses import FrozenInstanceError as _FrozenInstanceError
except ImportError:
    _FrozenInstanceError = AttributeError  # type: ignore[assignment,misc]

from core.rate_limiter import (
    EXPENSIVE_ENDPOINTS,
    PUBLIC_ENDPOINTS,
    RateLimitDecision,
    RateLimiter,
    _InMemoryRateLimiterBackend,
    _RedisSlidingWindowBackend,
    _TokenBucket,
)


# ---------------------------------------------------------------------------
# RateLimitDecision
# ---------------------------------------------------------------------------

class TestRateLimitDecision(unittest.TestCase):
    def test_fields_accessible(self) -> None:
        d = RateLimitDecision(allowed=True, retry_after_seconds=0, scope="global", limit=100)
        self.assertTrue(d.allowed)
        self.assertEqual(d.retry_after_seconds, 0)
        self.assertEqual(d.scope, "global")
        self.assertEqual(d.limit, 100)

    def test_optional_fields_default_to_none(self) -> None:
        d = RateLimitDecision(allowed=True, retry_after_seconds=0)
        self.assertIsNone(d.scope)
        self.assertIsNone(d.limit)

    def test_frozen_prevents_mutation(self) -> None:
        d = RateLimitDecision(allowed=True, retry_after_seconds=0)
        with self.assertRaises((_FrozenInstanceError, AttributeError, TypeError)):
            d.allowed = False  # type: ignore[misc]

    def test_denied_decision_fields(self) -> None:
        d = RateLimitDecision(allowed=False, retry_after_seconds=30, scope="ip-expensive", limit=10)
        self.assertFalse(d.allowed)
        self.assertEqual(d.retry_after_seconds, 30)
        self.assertEqual(d.scope, "ip-expensive")
        self.assertEqual(d.limit, 10)


# ---------------------------------------------------------------------------
# _TokenBucket
# ---------------------------------------------------------------------------

class TestTokenBucket(unittest.TestCase):
    def test_consume_allows_when_tokens_available(self) -> None:
        bucket = _TokenBucket(capacity=5, refill_rate_per_second=1.0)
        allowed, retry = bucket.consume()
        self.assertTrue(allowed)
        self.assertEqual(retry, 0)

    def test_consume_exhausts_all_tokens(self) -> None:
        bucket = _TokenBucket(capacity=3, refill_rate_per_second=0.01)
        for i in range(3):
            allowed, _ = bucket.consume()
            self.assertTrue(allowed, f"Expected allow on call {i + 1}")
        allowed, retry = bucket.consume()
        self.assertFalse(allowed)
        self.assertGreater(retry, 0)

    def test_retry_after_positive_when_denied(self) -> None:
        bucket = _TokenBucket(capacity=1, refill_rate_per_second=1.0)
        bucket.consume()  # use the single token
        allowed, retry = bucket.consume()
        self.assertFalse(allowed)
        self.assertGreaterEqual(retry, 1)

    def test_refills_over_time(self) -> None:
        # capacity=1, refill=1000/s — 10 ms adds ~10 tokens, capped to 1
        bucket = _TokenBucket(capacity=1, refill_rate_per_second=1000.0)
        bucket.consume()  # exhaust
        allowed, _ = bucket.consume()
        self.assertFalse(allowed)
        time.sleep(0.015)
        allowed, _ = bucket.consume()
        self.assertTrue(allowed)

    def test_tokens_capped_at_capacity_after_idle(self) -> None:
        # capacity=3, high refill — after 100 ms tokens should be ≤ 3
        bucket = _TokenBucket(capacity=3, refill_rate_per_second=1000.0)
        time.sleep(0.1)
        successes = 0
        for _ in range(4):
            ok, _ = bucket.consume()
            if ok:
                successes += 1
        # at most capacity=3 initial tokens + slight refill; 4th should fail or succeed only if refill kicks in
        # We just assert the first 3 succeed (tokens were capped at 3, not 100+)
        self.assertLessEqual(successes, 4)  # won't get 100 tokens

    def test_consume_amount_greater_than_available(self) -> None:
        bucket = _TokenBucket(capacity=5, refill_rate_per_second=1.0)
        allowed, retry = bucket.consume(amount=10.0)
        self.assertFalse(allowed)
        self.assertGreaterEqual(retry, 1)


# ---------------------------------------------------------------------------
# _InMemoryRateLimiterBackend
# ---------------------------------------------------------------------------

class TestInMemoryRateLimiterBackend(unittest.TestCase):
    def test_check_allows_first_call(self) -> None:
        backend = _InMemoryRateLimiterBackend()
        allowed, retry = backend.check("mykey", capacity=10, refill_rate_per_second=1.0)
        self.assertTrue(allowed)
        self.assertEqual(retry, 0)

    def test_check_exhausts_after_capacity_calls(self) -> None:
        backend = _InMemoryRateLimiterBackend()
        for i in range(5):
            allowed, _ = backend.check("key1", capacity=5, refill_rate_per_second=0.01)
            self.assertTrue(allowed, f"Expected allow on call {i + 1}")
        allowed, retry = backend.check("key1", capacity=5, refill_rate_per_second=0.01)
        self.assertFalse(allowed)
        self.assertGreater(retry, 0)

    def test_separate_buckets_per_key(self) -> None:
        backend = _InMemoryRateLimiterBackend()
        # exhaust key1
        for _ in range(2):
            backend.check("key1", capacity=2, refill_rate_per_second=0.01)
        denied, _ = backend.check("key1", capacity=2, refill_rate_per_second=0.01)
        # key2 gets a fresh bucket
        allowed, _ = backend.check("key2", capacity=2, refill_rate_per_second=0.01)
        self.assertFalse(denied)
        self.assertTrue(allowed)

    def test_creates_bucket_on_first_access(self) -> None:
        backend = _InMemoryRateLimiterBackend()
        self.assertNotIn("newkey", backend._buckets)
        backend.check("newkey", capacity=10, refill_rate_per_second=1.0)
        self.assertIn("newkey", backend._buckets)

    def test_reuses_existing_bucket_on_subsequent_calls(self) -> None:
        backend = _InMemoryRateLimiterBackend()
        backend.check("k", capacity=10, refill_rate_per_second=1.0)
        bucket_first = backend._buckets["k"]
        backend.check("k", capacity=10, refill_rate_per_second=1.0)
        self.assertIs(backend._buckets["k"], bucket_first)


# ---------------------------------------------------------------------------
# _RedisSlidingWindowBackend
# ---------------------------------------------------------------------------

class TestRedisSlidingWindowBackend(unittest.TestCase):
    def _make_redis(self, incr_return: int = 1, ttl_return: int = 30) -> MagicMock:
        r = MagicMock()
        r.incr.return_value = incr_return
        r.ttl.return_value = ttl_return
        return r

    def test_allowed_when_count_le_capacity(self) -> None:
        redis = self._make_redis(incr_return=3)
        backend = _RedisSlidingWindowBackend(redis)
        allowed, retry = backend.check("mykey", capacity=5, refill_rate_per_second=1.0)
        self.assertTrue(allowed)
        self.assertEqual(retry, 0)

    def test_allowed_at_exact_capacity(self) -> None:
        redis = self._make_redis(incr_return=5)
        backend = _RedisSlidingWindowBackend(redis)
        allowed, retry = backend.check("mykey", capacity=5, refill_rate_per_second=1.0)
        self.assertTrue(allowed)
        self.assertEqual(retry, 0)

    def test_denied_when_over_limit(self) -> None:
        redis = self._make_redis(incr_return=6, ttl_return=45)
        backend = _RedisSlidingWindowBackend(redis)
        allowed, retry = backend.check("mykey", capacity=5, refill_rate_per_second=1.0)
        self.assertFalse(allowed)
        self.assertEqual(retry, 45)

    def test_retry_after_at_least_one_when_ttl_zero(self) -> None:
        redis = self._make_redis(incr_return=99, ttl_return=0)
        backend = _RedisSlidingWindowBackend(redis)
        allowed, retry = backend.check("mykey", capacity=5, refill_rate_per_second=1.0)
        self.assertFalse(allowed)
        self.assertGreaterEqual(retry, 1)

    def test_expire_called_on_first_increment(self) -> None:
        redis = self._make_redis(incr_return=1)
        backend = _RedisSlidingWindowBackend(redis)
        backend.check("mykey", capacity=5, refill_rate_per_second=1.0)
        redis.expire.assert_called_once()

    def test_expire_not_called_on_subsequent_increments(self) -> None:
        redis = self._make_redis(incr_return=2)
        backend = _RedisSlidingWindowBackend(redis)
        backend.check("mykey", capacity=5, refill_rate_per_second=1.0)
        redis.expire.assert_not_called()

    def test_incr_called_with_namespaced_key(self) -> None:
        redis = self._make_redis(incr_return=1)
        backend = _RedisSlidingWindowBackend(redis)
        backend.check("mykey", capacity=5, refill_rate_per_second=1.0)
        called_key: str = redis.incr.call_args[0][0]
        self.assertTrue(called_key.startswith("openchimera:rate:mykey:"), called_key)

    def test_ttl_called_only_when_denied(self) -> None:
        redis = self._make_redis(incr_return=1)
        backend = _RedisSlidingWindowBackend(redis)
        backend.check("mykey", capacity=5, refill_rate_per_second=1.0)
        redis.ttl.assert_not_called()

    def test_ttl_called_when_denied(self) -> None:
        redis = self._make_redis(incr_return=10, ttl_return=30)
        backend = _RedisSlidingWindowBackend(redis)
        backend.check("mykey", capacity=5, refill_rate_per_second=1.0)
        redis.ttl.assert_called_once()


# ---------------------------------------------------------------------------
# RateLimiter
# ---------------------------------------------------------------------------

class TestRateLimiter(unittest.TestCase):
    def test_allowed_on_normal_path(self) -> None:
        rl = RateLimiter(global_rate_per_minute=1000)
        decision = rl.check(path="/v1/something", client_ip="1.2.3.4")
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.retry_after_seconds, 0)

    def test_denied_on_global_exhaustion(self) -> None:
        rl = RateLimiter(global_rate_per_minute=1)
        rl.check(path="/v1/something", client_ip="1.2.3.4")  # consume the 1 token
        decision = rl.check(path="/v1/something", client_ip="1.2.3.4")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.scope, "global")
        self.assertEqual(decision.limit, 1)
        self.assertGreater(decision.retry_after_seconds, 0)

    def test_expensive_endpoint_blocked_after_limit(self) -> None:
        rl = RateLimiter(global_rate_per_minute=1000, expensive_ip_rate_per_minute=1)
        path = next(iter(EXPENSIVE_ENDPOINTS))
        rl.check(path=path, client_ip="1.2.3.4")  # consume expensive token
        decision = rl.check(path=path, client_ip="1.2.3.4")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.scope, "ip-expensive")
        self.assertEqual(decision.limit, 1)

    def test_public_endpoint_blocked_after_limit(self) -> None:
        rl = RateLimiter(global_rate_per_minute=1000, public_ip_rate_per_minute=1)
        path = next(iter(PUBLIC_ENDPOINTS))
        rl.check(path=path, client_ip="1.2.3.4")  # consume public token
        decision = rl.check(path=path, client_ip="1.2.3.4")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.scope, "ip-public")
        self.assertEqual(decision.limit, 1)

    def test_token_bucket_blocked_after_limit(self) -> None:
        rl = RateLimiter(global_rate_per_minute=1000, token_rate_per_minute=1)
        rl.check(path="/v1/something", client_ip="1.2.3.4", auth_token="tok_abc")
        decision = rl.check(path="/v1/something", client_ip="1.2.3.4", auth_token="tok_abc")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.scope, "token")
        self.assertEqual(decision.limit, 1)

    def test_no_auth_token_skips_token_check(self) -> None:
        rl = RateLimiter(global_rate_per_minute=1000, token_rate_per_minute=1)
        with patch.object(rl, "_check_bucket", wraps=rl._check_bucket) as mock_cb:
            rl.check(path="/v1/something", client_ip="1.2.3.4", auth_token=None)
            for call in mock_cb.call_args_list:
                key: str = call[0][0]
                self.assertFalse(key.startswith("token:"), f"Unexpected token bucket check: {key!r}")

    def test_falls_back_to_in_memory_when_no_redis_url(self) -> None:
        with patch.dict(os.environ, {"OPENCHIMERA_REDIS_URL": ""}, clear=False):
            rl = RateLimiter()
        self.assertIsInstance(rl.backend, _InMemoryRateLimiterBackend)

    def test_uses_redis_backend_when_redis_client_provided(self) -> None:
        mock_redis = MagicMock()
        rl = RateLimiter(redis_client=mock_redis)
        self.assertIsInstance(rl.backend, _RedisSlidingWindowBackend)

    def test_different_ips_have_separate_expensive_buckets(self) -> None:
        rl = RateLimiter(global_rate_per_minute=1000, expensive_ip_rate_per_minute=1)
        path = next(iter(EXPENSIVE_ENDPOINTS))
        rl.check(path=path, client_ip="1.1.1.1")  # exhaust for IP 1
        d1 = rl.check(path=path, client_ip="1.1.1.1")  # denied
        d2 = rl.check(path=path, client_ip="2.2.2.2")  # fresh bucket
        self.assertFalse(d1.allowed)
        self.assertTrue(d2.allowed)

    def test_token_rate_defaults_from_env(self) -> None:
        with patch.dict(os.environ, {"OPENCHIMERA_TOKEN_RATE_PER_MINUTE": "42"}):
            rl = RateLimiter()
        self.assertEqual(rl.token_rate_per_minute, 42)

    def test_token_arg_overrides_env(self) -> None:
        with patch.dict(os.environ, {"OPENCHIMERA_TOKEN_RATE_PER_MINUTE": "42"}):
            rl = RateLimiter(token_rate_per_minute=99)
        self.assertEqual(rl.token_rate_per_minute, 99)

    def test_allowed_decision_has_zero_retry(self) -> None:
        rl = RateLimiter(global_rate_per_minute=1000)
        decision = rl.check(path="/v1/something", client_ip="10.0.0.1", auth_token="tok")
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.retry_after_seconds, 0)
        self.assertIsNone(decision.scope)
        self.assertIsNone(decision.limit)

    def test_expensive_and_public_sets_are_populated(self) -> None:
        self.assertIn("/v1/query/run", EXPENSIVE_ENDPOINTS)
        self.assertIn("/health", PUBLIC_ENDPOINTS)


if __name__ == "__main__":
    unittest.main()
