import httpx

from paper_broker.adapters.duckdb_warehouse import DuckDbWarehouse
from paper_broker.adapters.nasdaq import NasdaqUniverse
from paper_broker.domain.models import SecurityDraft

NASDAQ_TXT = """Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
AAPL|Apple Inc.|Q|N|N|100|N|N
"""

OTHER_TXT = """ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
IBM|International Business Machines Corporation|N|IBM|N|100|N|IBM
"""


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_otherlisted_survives_nasdaq_406():
    def handler(request: httpx.Request) -> httpx.Response:
        if "nasdaqlisted" in str(request.url):
            return httpx.Response(406, text="Not Acceptable")
        if "otherlisted" in str(request.url):
            return httpx.Response(200, text=OTHER_TXT)
        return httpx.Response(404)

    uni = NasdaqUniverse(client=_client(handler), retries=1)
    snap = uni.fetch_universe()
    assert snap.source == "partial"
    tickers = {d.ticker for d in snap.drafts}
    assert "IBM" in tickers
    assert "QQQ" in tickers
    assert any("nasdaqlisted" in w for w in snap.warnings)


def test_seed_when_both_files_fail(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(406, text="nope")

    uni = NasdaqUniverse(client=_client(handler), retries=1, warehouse=DuckDbWarehouse(tmp_path))
    snap = uni.fetch_universe()
    assert snap.source == "seed"
    tickers = {d.ticker for d in snap.drafts}
    assert "AAPL" in tickers
    assert "QQQ" in tickers


def test_cache_when_nasdaq_down(tmp_path):
    wh = DuckDbWarehouse(tmp_path)
    wh.upsert_securities([SecurityDraft(ticker="ZZZ", name="Zed", exchange="NYSE")])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="down")

    uni = NasdaqUniverse(client=_client(handler), retries=1, warehouse=wh)
    snap = uni.fetch_universe()
    assert snap.source == "cache"
    assert any(d.ticker == "ZZZ" for d in snap.drafts)


def test_full_nasdaq_and_other():
    def handler(request: httpx.Request) -> httpx.Response:
        if "nasdaqlisted" in str(request.url):
            return httpx.Response(200, text=NASDAQ_TXT)
        if "otherlisted" in str(request.url):
            return httpx.Response(200, text=OTHER_TXT)
        return httpx.Response(404)

    uni = NasdaqUniverse(client=_client(handler), retries=1)
    snap = uni.fetch_universe()
    assert snap.source == "nasdaq"
    tickers = {d.ticker for d in snap.drafts}
    assert {"AAPL", "IBM", "QQQ"} <= tickers
