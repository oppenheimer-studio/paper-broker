from datetime import date

from paper_broker.adapters.duckdb_warehouse import DuckDbWarehouse
from paper_broker.application.screener import ScreenerService
from paper_broker.domain.models import DailyBar, MinuteOpenBar, QueryRequest, QueryWhere, ScreenerRequest, SecurityDraft


def test_eod_upsert_does_not_duplicate(tmp_path):
    wh = DuckDbWarehouse(tmp_path)
    drafts = [SecurityDraft(ticker="AAA", name="Aaa", exchange="NYSE")]
    secs = wh.upsert_securities(drafts)
    sid = secs[0].security_id
    bar = DailyBar(
        security_id=sid,
        date=date(2026, 9, 8),
        open=1,
        high=2,
        low=1,
        close=1.5,
        adj_close=1.5,
        volume=100,
    )
    assert wh.write_daily_bars([bar]) == 1
    assert wh.write_daily_bars([bar]) == 1
    have = wh.dates_with_eod(sid, date(2026, 9, 1), date(2026, 9, 10))
    assert have == {date(2026, 9, 8)}
    rows = wh.bars("AAA", None, None, 10)
    assert len(rows) == 1


def test_screener_open_relvol_preset(tmp_path):
    wh = DuckDbWarehouse(tmp_path)
    drafts = [
        SecurityDraft(ticker="HOT", name="Hot", exchange="NYSE"),
        SecurityDraft(ticker="COLD", name="Cold", exchange="NYSE"),
    ]
    secs = {s.ticker: s for s in wh.upsert_securities(drafts)}
    as_of = date(2026, 9, 20)
    bars = []
    for i, d in enumerate(range(1, 21)):
        day = date(2026, 9, d)
        for ticker, close, vol in [("HOT", 10 + i, 2_000_000), ("COLD", 3, 1000)]:
            sid = secs[ticker].security_id
            bars.append(
                DailyBar(
                    security_id=sid,
                    date=day,
                    open=close,
                    high=close + 1,
                    low=close - 0.4,
                    close=close,
                    adj_close=close,
                    volume=vol,
                )
            )
    wh.write_daily_bars(bars)
    opens = []
    for d in range(1, 21):
        day = date(2026, 9, d)
        opens.append(
            MinuteOpenBar(
                security_id=secs["HOT"].security_id,
                date=day,
                window_minutes=5,
                open=10,
                high=11,
                low=9,
                close=10,
                volume=50_000 if d < 20 else 200_000,
            )
        )
        opens.append(
            MinuteOpenBar(
                security_id=secs["COLD"].security_id,
                date=day,
                window_minutes=5,
                open=3,
                high=3,
                low=3,
                close=3,
                volume=10,
            )
        )
    wh.write_minute_open(opens)
    wh.rewrite_derived(as_of, 14, 14, 14, 5)
    rows = ScreenerService(wh).run(ScreenerRequest(preset="open_relvol"), as_of)
    tickers = {r.ticker for r in rows}
    assert "HOT" in tickers
    assert "COLD" not in tickers  # price 3 < 5 and tiny volume


def test_screener_empty_after_first_filter(tmp_path):
    """Live Coolify crash: lookback iloc[0] on an empty frame after rel_vol_at filters everyone out."""
    wh = DuckDbWarehouse(tmp_path)
    secs = {s.ticker: s for s in wh.upsert_securities([SecurityDraft(ticker="SLOW", name="Slow", exchange="NYSE")])}
    as_of = date(2026, 9, 20)
    bars = []
    opens = []
    for d in range(1, 21):
        day = date(2026, 9, d)
        bars.append(
            DailyBar(
                security_id=secs["SLOW"].security_id,
                date=day,
                open=10,
                high=11,
                low=9,
                close=10,
                adj_close=10,
                volume=2_000_000,
            )
        )
        opens.append(
            MinuteOpenBar(
                security_id=secs["SLOW"].security_id,
                date=day,
                window_minutes=5,
                open=10,
                high=10,
                low=10,
                close=10,
                volume=1,
            )
        )
    wh.write_daily_bars(bars)
    wh.write_minute_open(opens)
    wh.rewrite_derived(as_of, 14, 14, 14, 5)
    rows = ScreenerService(wh).run(ScreenerRequest(preset="open_relvol"), as_of)
    assert rows == []


def test_screener_default_is_latest_us_by_market_cap(tmp_path):
    wh = DuckDbWarehouse(tmp_path)
    drafts = [
        SecurityDraft(ticker="OLD", name="Old", exchange="NYSE"),
        SecurityDraft(ticker="NEW", name="New", exchange="NYSE"),
    ]
    secs = {s.ticker: s for s in wh.upsert_securities(drafts)}
    old_day = date(2026, 9, 8)
    new_day = date(2026, 9, 9)
    wh.write_daily_bars(
        [
            DailyBar(
                security_id=secs["OLD"].security_id,
                date=old_day,
                open=10,
                high=11,
                low=9,
                close=10,
                adj_close=10,
                volume=1_000_000,
            ),
            DailyBar(
                security_id=secs["NEW"].security_id,
                date=new_day,
                open=20,
                high=21,
                low=19,
                close=20,
                adj_close=20,
                volume=2_000_000,
            ),
        ]
    )
    wh.rewrite_derived(old_day, 14, 14, 14, 5)
    wh.rewrite_derived(new_day, 14, 14, 14, 5)
    rows = ScreenerService(wh).run(ScreenerRequest())
    by_ticker = {r.ticker: r for r in rows}
    assert set(by_ticker) == {"OLD", "NEW"}
    assert by_ticker["OLD"].as_of == old_day
    assert by_ticker["NEW"].as_of == new_day
    # No shares outstanding yet: default market-cap sort uses dollar volume.
    assert [r.ticker for r in rows] == ["NEW", "OLD"]
    pinned = ScreenerService(wh).run(ScreenerRequest(as_of=new_day))
    assert {r.ticker for r in pinned} == {"NEW"}


def test_query_avg_volume(tmp_path):
    wh = DuckDbWarehouse(tmp_path)
    secs = wh.upsert_securities([SecurityDraft(ticker="AAA", name="Aaa", exchange="NYSE")])
    sid = secs[0].security_id
    wh.write_daily_bars(
        [
            DailyBar(
                security_id=sid,
                date=date(2026, 9, 8),
                open=1,
                high=1,
                low=1,
                close=1,
                adj_close=1,
                volume=10,
            ),
            DailyBar(
                security_id=sid,
                date=date(2026, 9, 9),
                open=1,
                high=1,
                low=1,
                close=1,
                adj_close=1,
                volume=30,
            ),
        ]
    )
    rows = wh.query(
        QueryRequest(
            table="daily_data",
            select=["security_id", {"agg": "avg", "field": "volume", "as": "avg_vol"}],
            where=[QueryWhere(field="security_id", op="eq", value=sid)],
            group_by=["security_id"],
            limit=10,
        )
    )
    assert rows
    assert abs(float(rows[0]["avg_vol"]) - 20) < 1e-6
