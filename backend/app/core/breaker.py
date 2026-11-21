"""Per-provider circuit breaker: 3 failures open the breaker for 60 seconds.

One bad provider must not slow every question down. While a provider is open,
the chain skips it without a network call; after the cool-down it is tried once
more. State is in memory: correct for the single backend replica this app runs.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable

log = logging.getLogger("kaarigar.core.breaker")


class CircuitBreaker:
    def __init__(self, failures: int = 3, cooldown_sec: float = 60.0,
                 clock: Callable[[], float] = time.monotonic):
        self.failures = max(1, int(failures))
        self.cooldown = max(0.0, float(cooldown_sec))
        self._clock = clock
        self._lock = threading.Lock()
        self._state: dict[str, tuple[int, float | None]] = {}   # key -> (count, opened_at)

    def allow(self, key: str) -> bool:
        now = self._clock()
        with self._lock:
            count, opened = self._state.get(key, (0, None))
            if opened is None:
                return True
            if now - opened < self.cooldown:
                return False
            self._state[key] = (0, None)
            return True

    def failure(self, key: str) -> None:
        now = self._clock()
        with self._lock:
            count, opened = self._state.get(key, (0, None))
            if opened is not None:
                return
            count += 1
            if count >= self.failures:
                self._state[key] = (count, now)
                log.info("provider=%s breaker open for %ss after %d failures",
                         key, int(self.cooldown), count)
            else:
                self._state[key] = (count, None)

    def success(self, key: str) -> None:
        with self._lock:
            self._state.pop(key, None)

    def is_open(self, key: str) -> bool:
        return not self.allow(key)
