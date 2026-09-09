from __future__ import annotations

import json
from datetime import date

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from paper_broker.composition import Container
from paper_broker.domain.models import QueryRequest, ScreenerRequest
from paper_broker.logging import get_logger

log = get_logger("mcp")


def _csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def build_mcp(container: Container) -> FastMCP:
    settings = container.settings
    mcp = FastMCP(
        "paper-broker",
        json_response=True,
        host=settings.host,
        port=settings.mcp_port,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=_csv(settings.mcp_allowed_hosts),
            allowed_origins=_csv(settings.mcp_allowed_origins),
        ),
    )

    @mcp.tool()
    def get_clock() -> str:
        """Market clock: last successful ingest, expected session, pending catch-up."""
        return container.daily.clock().model_dump_json()

    @mcp.tool()
    def run_screener(
        preset: str = "open_relvol",
        filters_json: str = "",
        limit: int = 100,
        as_of: str = "",
    ) -> str:
        """Screen US stocks. Default preset is open_relvol (relvol 5m, price, avg vol, ATR)."""
        req = ScreenerRequest(preset=preset or None, limit=limit)
        if filters_json:
            req = ScreenerRequest.model_validate(json.loads(filters_json))
            req.limit = limit
        if as_of:
            req.as_of = date.fromisoformat(as_of)
        rows = container.screener.run(req, container.daily.clock().as_of)
        return json.dumps({"n": len(rows), "rows": [r.model_dump(mode="json") for r in rows]})

    @mcp.tool()
    def get_bars(ticker: str, days: int = 60) -> str:
        """EOD OHLCV for a ticker."""
        bars = container.queries.bars(ticker, None, None, days)
        return json.dumps({"ticker": ticker.upper(), "bars": bars}, default=str)

    @mcp.tool()
    def search_securities(q: str, limit: int = 20) -> str:
        """Lookup tickers by prefix or name."""
        return json.dumps({"results": container.queries.search(q, limit)})

    @mcp.tool()
    def query_market(request_json: str) -> str:
        """Aggregations over warehouse tables (whitelist). Same body as POST /v1/query."""
        req = QueryRequest.model_validate(json.loads(request_json))
        rows = container.queries.query(req)
        return json.dumps({"n": len(rows), "rows": rows}, default=str)

    @mcp.tool()
    def run_daily_update(wait: bool = False, phase: str = "all") -> str:
        """Catch-up ingest. phase=all|eod|minutes. Admin. Idempotent."""
        phase = (phase or "all").lower()
        if wait:
            return json.dumps(container.daily.run(phase), default=str)
        import threading

        if not container.daily.can_start(phase):
            return json.dumps({"status": "already_running", "phase": phase})
        threading.Thread(
            target=container.daily.run,
            kwargs={"phase": phase},
            name=f"daily-{phase}",
            daemon=True,
        ).start()
        return json.dumps({"status": "started", "phase": phase})

    return mcp
