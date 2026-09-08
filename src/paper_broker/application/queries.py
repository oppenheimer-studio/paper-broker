from __future__ import annotations

from datetime import date
from typing import Any

from paper_broker.domain.models import QueryRequest
from paper_broker.domain.ports import Warehouse
from paper_broker.logging import get_logger

log = get_logger("query")


class QueryService:
    def __init__(self, warehouse: Warehouse) -> None:
        self._wh = warehouse

    def query(self, req: QueryRequest) -> list[dict[str, Any]]:
        rows = self._wh.query(req)
        log.info("query_ok", table=req.table, n=len(rows))
        return rows

    def bars(self, ticker: str, start: date | None, end: date | None, limit: int) -> list[dict[str, Any]]:
        return self._wh.bars(ticker, start, end, limit)

    def search(self, q: str, limit: int = 20) -> list[dict[str, Any]]:
        q = q.upper().strip()
        hits = []
        for s in self._wh.list_securities(market=None):
            if q in s.ticker or q in s.name.upper():
                hits.append(s.model_dump())
            if len(hits) >= limit:
                break
        return hits
