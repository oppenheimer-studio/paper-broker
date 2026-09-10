from paper_broker.adapters.rate_limit import HourlyRateLimiter, RateLimitTripped


def test_hourly_limiter_blocks_over_cap():
    now = [0.0]
    slept = []

    def time_fn():
        return now[0]

    def sleep_fn(seconds):
        slept.append(seconds)
        now[0] += seconds

    limiter = HourlyRateLimiter(2, time_fn=time_fn, sleep_fn=sleep_fn)
    assert limiter.acquire() == 0.0
    assert limiter.acquire() == 0.0
    waited = limiter.acquire()
    assert slept
    assert waited >= 3600.0
    assert now[0] >= 3600.0


def test_hourly_limiter_disabled():
    limiter = HourlyRateLimiter(0)
    assert limiter.acquire() == 0.0
    assert limiter.acquire() == 0.0


def test_penalize_blocks_until_cooldown():
    now = [0.0]

    def sleep_fn(seconds):
        now[0] += seconds

    limiter = HourlyRateLimiter(100, time_fn=lambda: now[0], sleep_fn=sleep_fn, cooldown_base_s=30)
    limiter.penalize(40)
    waited = limiter.acquire()
    assert waited >= 40.0
    assert now[0] >= 40.0


def test_trip_after_consecutive_429s():
    limiter = HourlyRateLimiter(100, trip_after=3, cooldown_base_s=1)
    limiter.penalize(0)
    limiter.penalize(0)
    assert not limiter.tripped
    limiter.penalize(0)
    assert limiter.tripped
    try:
        limiter.acquire()
        raise AssertionError("expected RateLimitTripped")
    except RateLimitTripped:
        pass
    limiter.reset_trip()
    assert not limiter.tripped
    limiter.acquire()
