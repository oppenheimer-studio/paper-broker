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
