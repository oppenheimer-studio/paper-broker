from __future__ import annotations

import time
from collections import deque
from threading import Lock


class RateLimitTripped(Exception):
    """Yahoo (or another feed) hit too many 429s; stop issuing HTTP until reset."""


class HourlyRateLimiter:
    """Sliding window: at most `max_per_hour` acquires in any 3600s span.

    429s call `penalize`: every worker waits out a shared cooldown, and after
    `trip_after` consecutive penalties the limiter refuses new acquires so an
    ingest cannot livelock overnight.
    """

    def __init__(
        self,
        max_per_hour: int,
        *,
        time_fn=time.monotonic,
        sleep_fn=time.sleep,
        cooldown_base_s: float = 45.0,
        trip_after: int = 12,
    ) -> None:
        self.max_per_hour = max(0, int(max_per_hour))
        self._time = time_fn
        self._sleep = sleep_fn
        self._lock = Lock()
        self._hits: deque[float] = deque()
        self._cooldown_until = 0.0
        self._consecutive_429 = 0
        self._tripped = False
        self.cooldown_base_s = max(0.0, float(cooldown_base_s))
        self.trip_after = max(1, int(trip_after))

    @property
    def tripped(self) -> bool:
        return self._tripped

    @property
    def consecutive_429(self) -> int:
        return self._consecutive_429

    def reset_trip(self) -> None:
        with self._lock:
            self._tripped = False
            self._consecutive_429 = 0
            self._cooldown_until = 0.0

    def note_success(self) -> None:
        with self._lock:
            self._consecutive_429 = 0

    def penalize(self, seconds: float | None = None) -> float:
        """Record a 429. Returns the cooldown seconds applied."""
        with self._lock:
            self._consecutive_429 += 1
            if seconds is None:
                exp = min(self._consecutive_429 - 1, 3)
                seconds = min(300.0, self.cooldown_base_s * (2**exp))
            wait = max(0.0, float(seconds))
            now = float(self._time())
            self._cooldown_until = max(self._cooldown_until, now + wait)
            if self._consecutive_429 >= self.trip_after:
                self._tripped = True
            return wait

    def acquire(self) -> float:
        """Block until a slot is free. Returns seconds waited."""
        if self.max_per_hour <= 0:
            return 0.0
        waited = 0.0
        while True:
            delay = 0.0
            with self._lock:
                now = float(self._time())
                if self._tripped:
                    raise RateLimitTripped("yahoo 429 circuit open")
                if now < self._cooldown_until:
                    delay = max(self._cooldown_until - now, 0.01)
                else:
                    cutoff = now - 3600.0
                    while self._hits and self._hits[0] <= cutoff:
                        self._hits.popleft()
                    if len(self._hits) < self.max_per_hour:
                        self._hits.append(now)
                        return waited
                    delay = max(self._hits[0] + 3600.0 - now, 0.01)
            self._sleep(delay)
            waited += delay
