from __future__ import annotations

import threading
from datetime import date

from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from paper_broker.application.daily_update import PHASES
from paper_broker.composition import Container
from paper_broker.domain.models import QueryRequest, ScreenerRequest
from paper_broker.domain.screener_spec import PRESETS, SNAPSHOT_FIELDS
from paper_broker.logging import get_logger

log = get_logger("http")


def _parse_event_data(raw: str) -> dict:
    import json

    try:
        data = json.loads(raw or "{}")
        return data if isinstance(data, dict) else {"value": data}
    except json.JSONDecodeError:
        return {}


def create_app(container: Container) -> FastAPI:
    app = FastAPI(title="paper-broker", version="0.1.0")
    settings = container.settings

    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins if origins != ["*"] else ["*"],
            allow_credentials=origins != ["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

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
    def daily(
        wait: bool = False,
        phase: str = Query(default="all"),
        _: None = Depends(admin),
    ):
        phase = (phase or "all").lower()
        if phase not in PHASES:
            raise HTTPException(status_code=400, detail=f"phase must be one of {sorted(PHASES)}")
        if wait:
            return container.daily.run(phase)
        if not container.daily.can_start(phase):
            return JSONResponse(container.daily.note_already_running(phase))
        threading.Thread(
            target=container.daily.run,
            kwargs={"phase": phase},
            name=f"daily-{phase}",
            daemon=True,
        ).start()
        log.info("daily_started_background", phase=phase)
        return JSONResponse({"status": "started", "phase": phase}, status_code=202)

    @app.get("/v1/admin/daily")
    def daily_status(_: None = Depends(admin)):
        return container.daily.status()

    @app.get("/v1/notifications")
    def notifications(limit: int = Query(default=50, ge=1, le=200)):
        events = container.warehouse.list_events(limit)
        return {
            "n": len(events),
            "events": [
                {
                    **e.model_dump(mode="json"),
                    "data": _parse_event_data(e.data),
                }
                for e in events
            ],
        }

    @app.get("/v1/screener/meta")
    def screener_meta():
        return {
            "fields": sorted(SNAPSHOT_FIELDS),
            "ops": ["gt", "gte", "lt", "lte", "eq"],
            "presets": {
                name: [f.model_dump() for f in filters] for name, filters in PRESETS.items()
            },
        }

    @app.post("/v1/screener")
    def screener(req: ScreenerRequest):
        try:
            rows = container.screener.run(req, container.daily.clock().as_of)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            log.exception("screener_failed")
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {
            "as_of": req.as_of.isoformat() if req.as_of else None,
            "n": len(rows),
            "rows": [r.model_dump(mode="json") for r in rows],
        }

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

    _mount_web(app, settings.web_dist)
    return app


def _mount_web(app: FastAPI, web_dist: Path) -> None:
    dist = Path(web_dist)
    index = dist / "index.html"
    if not index.is_file():
        log.info("web_dist_skip", path=str(dist))
        return
    assets = dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/")
    def spa_root():
        return FileResponse(index)

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        if full_path.startswith("v1/") or full_path in {"health", "docs", "openapi.json", "redoc"}:
            raise HTTPException(status_code=404, detail="Not Found")
        target = dist / full_path
        if target.is_file():
            return FileResponse(target)
        return FileResponse(index)
