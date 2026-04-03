from __future__ import annotations

import time
from typing import Any, Callable, TypeVar


T = TypeVar("T")


def retry_call(
    func: Callable[[], T],
    *,
    attempts: int = 3,
    delay_seconds: float = 0.2,
    retry_exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> T:
    last_error: BaseException | None = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            return func()
        except retry_exceptions as exc:
            last_error = exc
            if attempt >= attempts:
                raise
            time.sleep(delay_seconds * attempt)
    assert last_error is not None
    raise last_error