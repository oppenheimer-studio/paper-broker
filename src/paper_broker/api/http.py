from __future__ import annotations

import threading
from datetime import date

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse

from paper_broker.composition import Container
from paper_broker.domain.models import QueryRequest, ScreenerRequest
from paper_broker.logging import get_logger

log = get_logger("http")


def create_app(container: Container) -> FastAPI:
    app = FastAPI(title="paper-broker", version="0.1.0")
    settings = container.settings

    def admin(authorization: str | None = Header(default=None)) -> None:
        if not authorization or authorization != f"Bearer {settings.admin_key}":
            raise HTTPException(status_code=401, detail="admin key required")

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/v1/clock")
    def clock():
        return container.daily.clock().model_dump()

    @app.post("/v1/admin/daily")
    def daily(wait: bool = False, _: None = Depends(admin)):
        if wait:
            return container.daily.run()
        if container.daily.running:
            return JSONResponse({"status": "already_running", "report": container.daily.last_report})
        threading.Thread(target=container.daily.run, name="daily-update", daemon=True).start()
        log.info("daily_started_background")
        return JSONResponse({"status": "started"}, status_code=202)

    @app.get("/v1/admin/daily")
    def daily_status(_: None = Depends(admin)):
        return {
            "running": container.daily.running,
            "report": container.daily.last_report,
            "clock": container.daily.clock().model_dump(),
        }

    @app.post("/v1/screener")
    def screener(req: ScreenerRequest):
        as_of = container.daily.clock().as_of
        try:
            rows = container.screener.run(req, as_of)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"as_of": as_of, "n": len(rows), "rows": [r.model_dump() for r in rows]}

    @app.get("/v1/securities")
    def securities(q: str = Query(min_length=1), limit: int = 20):
        return {"results": container.queries.search(q, limit)}

    @app.get("/v1/bars/{ticker}")
    def bars(
        ticker: str,
        start: date | None = None,
        end: date | None = None,
        limit: int = 120,
    ):
        return {"ticker": ticker.upper(), "bars": container.queries.bars(ticker, start, end, limit)}

    @app.post("/v1/query")
    def query(req: QueryRequest):
        try:
            rows = container.queries.query(req)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"n": len(rows), "rows": rows}

    return app
