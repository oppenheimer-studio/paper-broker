from paper_broker.adapters.rate_limit import HourlyRateLimiter


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
