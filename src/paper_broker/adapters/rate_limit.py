from __future__ import annotations

import time
from collections import deque
from threading import Lock


class HourlyRateLimiter:
    """Sliding window: at most `max_per_hour` acquires in any 3600s span."""

    def __init__(
        self,
        max_per_hour: int,
        *,
        time_fn=time.monotonic,
        sleep_fn=time.sleep,
    ) -> None:
        self.max_per_hour = max(0, int(max_per_hour))
        self._time = time_fn
        self._sleep = sleep_fn
        self._lock = Lock()
        self._hits: deque[float] = deque()

    def acquire(self) -> float:
        """Block until a slot is free. Returns seconds waited."""
        if self.max_per_hour <= 0:
            return 0.0
        waited = 0.0
        while True:
            delay = 0.0
            with self._lock:
                now = float(self._time())
                cutoff = now - 3600.0
                while self._hits and self._hits[0] <= cutoff:
                    self._hits.popleft()
                if len(self._hits) < self.max_per_hour:
                    self._hits.append(now)
                    return waited
                delay = max(self._hits[0] + 3600.0 - now, 0.01)
            self._sleep(delay)
            waited += delay
