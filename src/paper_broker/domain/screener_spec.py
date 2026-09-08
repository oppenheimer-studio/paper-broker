from __future__ import annotations

from paper_broker.domain.models import FilterOp, ScreenerFilter, ScreenerRequest

PRESET_OPEN_RELVOL = "open_relvol"

PRESETS: dict[str, list[ScreenerFilter]] = {
    PRESET_OPEN_RELVOL: [
        ScreenerFilter(field="rel_vol_at", op=FilterOp.GT, value=1.0, lookback=14, window_minutes=5),
        ScreenerFilter(field="price", op=FilterOp.GT, value=5),
        ScreenerFilter(field="avg_volume", op=FilterOp.GT, value=1_000_000, lookback=14),
        ScreenerFilter(field="atr", op=FilterOp.GT, value=0.5, lookback=14),
        ScreenerFilter(field="market", op=FilterOp.EQ, value="US"),
    ]
}

SNAPSHOT_FIELDS = {"price", "avg_volume", "atr", "rel_vol_at", "market", "dollar_volume", "market_cap"}

OPS_SQL = {
    FilterOp.GT: ">",
    FilterOp.GTE: ">=",
    FilterOp.LT: "<",
    FilterOp.LTE: "<=",
    FilterOp.EQ: "=",
}


def resolve_filters(req: ScreenerRequest) -> list[ScreenerFilter]:
    if req.preset:
        if req.preset not in PRESETS:
            raise ValueError(f"unknown preset {req.preset}")
        if req.filters:
            return req.filters
        return list(PRESETS[req.preset])
    if not req.filters:
        raise ValueError("filters or preset required")
    for f in req.filters:
        if f.field not in SNAPSHOT_FIELDS:
            raise ValueError(f"unknown field {f.field}")
    return req.filters
