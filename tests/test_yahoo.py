from paper_broker.adapters.rate_limit import HourlyRateLimiter
from paper_broker.adapters.yahoo import YahooError, YahooFeed


def test_parse_dividends_and_splits():
    payload = {
        "chart": {
            "result": [
                {
                    "timestamp": [],
                    "indicators": {"quote": [{}], "adjclose": [{}]},
                    "events": {
                        "dividends": {
                            "1756944000": {"amount": 0.25, "date": 1756944000},
                        },
                        "splits": {
                            "1756944000": {
                                "date": 1756944000,
                                "numerator": 4,
                                "denominator": 1,
                                "splitRatio": "4:1",
                            }
                        },
                    },
                }
            ]
        }
    }
    feed = YahooFeed("test-agent", 5)
    actions = feed._parse_actions("AAPL", payload)
    kinds = {a.action: a for a in actions}
    assert "dividend" in kinds
    assert kinds["dividend"].value == 0.25
    assert "split" in kinds
    assert kinds["split"].numerator == 4
    assert kinds["split"].denominator == 1
    assert kinds["split"].value == 4.0


class _Resp:
    def __init__(self, status, payload=None, text=""):
        self.status_code = status
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class _Client429:
    def __init__(self):
        self.calls = 0

    def get(self, url):
        self.calls += 1
        return _Resp(429, text="Too Many Requests")


def test_yahoo_429_does_not_hammer_hosts_or_retries():
    limiter = HourlyRateLimiter(10_000, cooldown_base_s=0, trip_after=50)
    feed = YahooFeed("test-agent", 5, limiter=limiter)
    client = _Client429()
    feed._client = client
    try:
        feed.fetch_eod("AAPL", __import__("datetime").date(2026, 9, 8), __import__("datetime").date(2026, 9, 8))
        raise AssertionError("expected YahooError")
    except YahooError as exc:
        assert exc.status == 429
    # one host, two attempts — not query1+query2 × 4
    assert client.calls == 2
    assert limiter.consecutive_429 == 2
