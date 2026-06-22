"""Token-bucket rate limiter для Bitrix24 (по умолчанию ~2 rps)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable


class TokenBucket:
    """Классический token bucket.

    capacity — максимум токенов (всплеск); refill_rate — токенов/сек. Токены
    пополняются непрерывно по времени. acquire ждёт асинхронно, без busy-wait.
    """

    def __init__(
        self,
        rps: float,
        time_func: Callable[[], float] = time.monotonic,
    ) -> None:
        self.refill_rate = rps
        self.capacity = max(1.0, rps)
        self._time = time_func
        self.tokens = self.capacity
        self.last_refill_at = time_func()

    def _refill(self) -> None:
        now = self._time()
        elapsed = now - self.last_refill_at
        if elapsed > 0:
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
            self.last_refill_at = now

    def try_acquire(self, count: float = 1.0) -> bool:
        self._refill()
        if self.tokens >= count:
            self.tokens -= count
            return True
        return False

    def time_until_available(self, count: float = 1.0) -> float:
        self._refill()
        if self.tokens >= count:
            return 0.0
        return (count - self.tokens) / self.refill_rate

    async def acquire(self) -> None:
        """Дождаться одного токена (асинхронно)."""
        while not self.try_acquire():
            wait = self.time_until_available()
            if wait <= 0:
                continue
            await asyncio.sleep(wait)
