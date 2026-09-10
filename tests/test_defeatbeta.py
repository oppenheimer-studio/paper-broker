from datetime import date

import pandas as pd

from paper_broker.adapters.defeatbeta import DefeatbetaFeed, _parse_split_factor


def _write_prices(path, rows):
    pd.DataFrame(rows).to_parquet(path / "stock_prices.parquet", index=False)


def test_parse_split_factor():
    assert _parse_split_factor("4:1") == (4.0, 1.0, 4.0)
    assert _parse_split_factor("1/2") == (1.0, 2.0, 0.5)
    assert _parse_split_factor("3.0") == (3.0, 1.0, 3.0)


def test_sessions_ready_and_fetch_range(tmp_path, monkeypatch):
    _write_prices(
        tmp_path,
        [
            {
                "symbol": "QQQ",
                "report_date": "2026-09-08",
                "open": 1,
                "high": 2,
                "low": 0.5,
                "close": 1.5,
                "volume": 100,
            },
            {
                "symbol": "AAPL",
                "report_date": "2026-09-08",
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10.5,
                "volume": 200,
            },
        ],
    )
    pd.DataFrame(
        [{"symbol": "AAPL", "report_date": "2026-09-08", "amount": 0.25}]
    ).to_parquet(tmp_path / "stock_dividend_events.parquet", index=False)
    pd.DataFrame(
        [{"symbol": "QQQ", "report_date": "2026-09-08", "split_factor": "4:1"}]
    ).to_parquet(tmp_path / "stock_split_events.parquet", index=False)

    feed = DefeatbetaFeed(tmp_path, timeout=5)
    monkeypatch.setattr(feed, "_fetch_spec", lambda: {"update_time": "x", "files": {}})
    monkeypatch.setattr(feed, "_refresh_files", lambda spec: True)

    assert feed.sessions_ready([date(2026, 9, 8)]) is True
    assert feed.sessions_ready([date(2026, 9, 8), date(2026, 9, 9)]) is False

    bars, actions = feed.fetch_range(date(2026, 9, 8), date(2026, 9, 8))
    tickers = {b.ticker for b in bars}
    assert tickers == {"QQQ", "AAPL"}
    assert all(b.source == "defeatbeta" for b in bars)
    kinds = {(a.ticker, a.action) for a in actions}
    assert ("AAPL", "dividend") in kinds
    assert ("QQQ", "split") in kinds
    split = next(a for a in actions if a.action == "split")
    assert split.numerator == 4
    assert split.denominator == 1
    feed.close()


def test_local_session_dates_reads_cached_parquet_only(tmp_path):
    _write_prices(
        tmp_path,
        [
            {
                "symbol": "QQQ",
                "report_date": "2026-09-08",
                "open": 1,
                "high": 2,
                "low": 0.5,
                "close": 1.5,
                "volume": 100,
            },
            {
                "symbol": "QQQ",
                "report_date": "2026-09-09",
                "open": 1,
                "high": 2,
                "low": 0.5,
                "close": 1.6,
                "volume": 110,
            },
        ],
    )
    feed = DefeatbetaFeed(tmp_path, timeout=5)
    days = feed.local_session_dates("QQQ")
    assert days == [date(2026, 9, 8), date(2026, 9, 9)]
    feed.close()
