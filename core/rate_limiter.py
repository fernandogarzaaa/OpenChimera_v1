from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Any


EXPENSIVE_ENDPOINTS = {
    "/v1/query/run",
    "/v1/browser/fetch",
}

PUBLIC_ENDPOINTS = {
    "/health",
    "/v1/system/readiness",
}


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int
    scope: str | None = None
    limit: int | None = None


class _TokenBucket:
    def __init__(self, capacity: int, refill_rate_per_second: float):
        self.capacity = float(capacity)
        self.tokens = float(capacity)
        self.refill_rate_per_second = refill_rate_per_second
        self.last_refill = time.monotonic()

    def consume(self, amount: float = 1.0) -> tuple[bool, int]:
        now = time.monotonic()
        elapsed = max(0.0, now - self.last_refill)
        self.tokens = min(self.capacity, self.tokens + (elapsed * self.refill_rate_per_second))
        self.last_refill = now
        if self.tokens >= amount:
            self.tokens -= amount
            return True, 0
        missing = amount - self.tokens
        retry_after = int(max(1.0, missing / self.refill_rate_per_second))
        return False, retry_after


class _InMemoryRateLimiterBackend:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buckets: dict[str, _TokenBucket] = {}

    def check(self, key: str, *, capacity: int, refill_rate_per_second: float) -> tuple[bool, int]:
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _TokenBucket(capacity=capacity, refill_rate_per_second=refill_rate_per_second)
                self._buckets[key] = bucket
            return bucket.consume()


class _RedisSlidingWindowBackend:
    def __init__(self, redis_client: Any) -> None:
        self.redis = redis_client

    def check(self, key: str, *, capacity: int, refill_rate_per_second: float) -> tuple[bool, int]:
        window_seconds = max(1, int(round(capacity / refill_rate_per_second)))
        current_window = int(time.time() // window_seconds)
        namespaced_key = f"openchimera:rate:{key}:{current_window}"
        count = int(self.redis.incr(namespaced_key))
        if count == 1:
            self.redis.expire(namespaced_key, window_seconds)
        if count <= capacity:
            return True, 0
        ttl = int(self.redis.ttl(namespaced_key))
        return False, max(ttl, 1)


class RateLimiter:
    def __init__(
        self,
        *,
        global_rate_per_minute: int = 1000,
        public_ip_rate_per_minute: int = 60,
        expensive_ip_rate_per_minute: int = 10,
        token_rate_per_minute: int | None = None,
        redis_client: Any | None = None,
    ) -> None:
        self.global_rate_per_minute = global_rate_per_minute
        self.public_ip_rate_per_minute = public_ip_rate_per_minute
        self.expensive_ip_rate_per_minute = expensive_ip_rate_per_minute
        self.token_rate_per_minute = token_rate_per_minute or int(os.getenv("OPENCHIMERA_TOKEN_RATE_PER_MINUTE", "300"))

        if redis_client is not None:
            self.backend: Any = _RedisSlidingWindowBackend(redis_client)
        else:
            self.backend = self._build_default_backend()

    def _build_default_backend(self) -> Any:
        redis_url = os.getenv("OPENCHIMERA_REDIS_URL", "").strip()
        if not redis_url:
            return _InMemoryRateLimiterBackend()
        try:
            import redis  # type: ignore
        except Exception:
            return _InMemoryRateLimiterBackend()
        try:
            client = redis.from_url(redis_url)
            client.ping()
        except Exception:
            return _InMemoryRateLimiterBackend()
        return _RedisSlidingWindowBackend(client)

    def _check_bucket(self, key: str, limit_per_minute: int) -> tuple[bool, int]:
        return self.backend.check(
            key,
            capacity=limit_per_minute,
            refill_rate_per_second=(limit_per_minute / 60.0),
        )

    def check(self, *, path: str, client_ip: str, auth_token: str | None = None) -> RateLimitDecision:
        allowed, retry_after = self._check_bucket("global", self.global_rate_per_minute)
        if not allowed:
            return RateLimitDecision(False, retry_after, scope="global", limit=self.global_rate_per_minute)

        if path in EXPENSIVE_ENDPOINTS:
            allowed, retry_after = self._check_bucket(f"expensive:{client_ip}:{path}", self.expensive_ip_rate_per_minute)
            if not allowed:
                return RateLimitDecision(False, retry_after, scope="ip-expensive", limit=self.expensive_ip_rate_per_minute)
        elif path in PUBLIC_ENDPOINTS:
            allowed, retry_after = self._check_bucket(f"public:{client_ip}:{path}", self.public_ip_rate_per_minute)
            if not allowed:
                return RateLimitDecision(False, retry_after, scope="ip-public", limit=self.public_ip_rate_per_minute)

        if auth_token:
            allowed, retry_after = self._check_bucket(f"token:{auth_token}", self.token_rate_per_minute)
            if not allowed:
                return RateLimitDecision(False, retry_after, scope="token", limit=self.token_rate_per_minute)

        return RateLimitDecision(True, 0)