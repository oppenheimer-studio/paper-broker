from __future__ import annotations

from paper_broker.domain.models import ScreenerRequest, ScreenerRow
from paper_broker.domain.ports import Warehouse
from paper_broker.domain.screener_spec import resolve_filters
from paper_broker.logging import get_logger

log = get_logger("screener")


class ScreenerService:
    def __init__(self, warehouse: Warehouse) -> None:
        self._wh = warehouse

    def run(self, req: ScreenerRequest, default_as_of) -> list[ScreenerRow]:
        as_of = req.as_of or default_as_of
        if as_of is None:
            raise ValueError("no as_of: run daily update first")
        filters = resolve_filters(req)
        avg_n = _lookback(filters, "avg_volume", 14)
        atr_n = _lookback(filters, "atr", 14)
        rel_n = _lookback(filters, "rel_vol_at", 14)
        window = next((f.window_minutes for f in filters if f.window_minutes), 5)
        if avg_n != 14 or atr_n != 14 or rel_n != 14 or window != 5:
            log.info("screener_recompute_derived", avg_n=avg_n, atr_n=atr_n, rel_n=rel_n, window=window)
            self._wh.rewrite_derived(as_of, avg_n, atr_n, rel_n, window)
        rows = self._wh.run_screener(req, as_of)
        log.info("screener_done", as_of=str(as_of), n=len(rows), preset=req.preset)
        return rows


def _lookback(filters, field: str, default: int) -> int:
    for f in filters:
        if f.field == field and f.lookback:
            return int(f.lookback)
    return default
