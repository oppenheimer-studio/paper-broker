from paper_broker.api.http import create_app
from paper_broker.composition import build
from paper_broker.config import Settings


def test_screener_meta_lists_open_relvol(tmp_path):
    from fastapi.testclient import TestClient

    app = create_app(build(Settings(lake_path=tmp_path, cors_origins="http://localhost:5173")))
    client = TestClient(app)
    r = client.get("/v1/screener/meta")
    assert r.status_code == 200
    body = r.json()
    assert "open_relvol" in body["presets"]
    assert "rel_vol_at" in body["fields"]
    assert "gt" in body["ops"]


def test_root_is_404_without_web_dist(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from paper_broker.adapters.yahoo import YahooFeed

    monkeypatch.setattr(YahooFeed, "fetch_eod", lambda self, ticker, start, end: [])
    monkeypatch.setattr(YahooFeed, "fetch_session", lambda self, ticker, start, end: ([], []))
    app = create_app(
        build(Settings(lake_path=tmp_path, cors_origins="http://localhost:5173", web_dist=tmp_path / "nope"))
    )
    client = TestClient(app)
    assert client.get("/").status_code == 404
    assert client.get("/v1/clock").status_code == 200


def test_mcp_allows_coolify_host(tmp_path):
    from paper_broker.api.mcp_app import build_mcp

    mcp = build_mcp(build(Settings(lake_path=tmp_path, cors_origins="http://localhost:5173")))
    hosts = mcp.settings.transport_security.allowed_hosts
    assert "paper-broker-mcp.oppenheimer.studio" in hosts


def test_notifications_endpoint(tmp_path):
    from fastapi.testclient import TestClient

    container = build(Settings(lake_path=tmp_path, cors_origins="http://localhost:5173"))
    container.warehouse.append_event(
        level="warning",
        source="daily",
        code="universe.fallback",
        title="Universe fallback: seed",
        detail="Nasdaq 406",
        data={"source": "seed"},
    )
    client = TestClient(create_app(container))
    r = client.get("/v1/notifications")
    assert r.status_code == 200
    body = r.json()
    assert body["n"] == 1
    ev = body["events"][0]
    assert ev["code"] == "universe.fallback"
    assert ev["data"]["source"] == "seed"
