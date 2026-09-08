from __future__ import annotations

import threading

import uvicorn

from paper_broker.api.http import create_app
from paper_broker.api.mcp_app import build_mcp
from paper_broker.composition import build
from paper_broker.config import Settings
from paper_broker.logging import configure_logging, get_logger


def main() -> None:
    settings = Settings()
    configure_logging(json=settings.log_json, level=settings.log_level)
    log = get_logger("main")
    container = build(settings)
    app = create_app(container)
    mcp = build_mcp(container)

    def run_mcp() -> None:
        log.info("mcp_start", port=settings.mcp_port)
        mcp.settings.host = settings.host
        mcp.settings.port = settings.mcp_port
        mcp.run(transport="streamable-http")

    threading.Thread(target=run_mcp, name="mcp", daemon=True).start()
    log.info("http_start", host=settings.host, port=settings.port, lake=str(settings.lake_path))
    uvicorn.run(app, host=settings.host, port=settings.port, log_level=settings.log_level)


if __name__ == "__main__":
    main()
