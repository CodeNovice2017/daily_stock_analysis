from __future__ import annotations

import time
import functools
import logging
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RateLimiter:
    """Token-bucket rate limiter."""

    def __init__(self, max_calls: int = 400, period_seconds: int = 60) -> None:
        self._max = max_calls
        self._period = period_seconds
        self._count = 0
        self._window_start = time.monotonic()

    def acquire(self) -> None:
        now = time.monotonic()
        elapsed = now - self._window_start
        if elapsed >= self._period:
            self._window_start = now
            self._count = 0
        if self._count >= self._max:
            sleep_time = self._period - elapsed + 0.1
            logger.debug("Rate limit reached, sleeping %.1fs", sleep_time)
            time.sleep(sleep_time)
            self._window_start = time.monotonic()
            self._count = 0
        self._count += 1


def retry(max_retries: int = 3, base_delay: float = 2.0, backoff: float = 2.0):
    """Decorator with exponential backoff + jitter."""

    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs) -> T:
            last_exc = None
            for attempt in range(max_retries):
                try:
                    return fn(*args, **kwargs)
                except (ConnectionError, TimeoutError, OSError) as e:
                    last_exc = e
                    if attempt < max_retries - 1:
                        delay = base_delay * (backoff ** attempt)
                        logger.warning(
                            "%s attempt %d/%d failed: %s, retrying in %.1fs",
                            fn.__qualname__, attempt + 1, max_retries, e, delay,
                        )
                        time.sleep(delay)
            raise last_exc

        return wrapper

    return decorator
