# Paper broker (backend)

Warehouse US + screener HTTP/MCP + UI del screener. Sin paper trading.

Docs: [docs/README.md](docs/README.md)

```bash
cd paper-broker
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
pytest
python -m paper_broker
```

Frontend (producción: mismo HTTP que la API):

```bash
cd web && npm install && npm run build
python -m paper_broker   # sirve web/dist en :8080
# o: cd web && npm run dev   # :5173
```

- HTTP + UI: `http://127.0.0.1:8080`
- MCP: `http://127.0.0.1:8081/mcp`

- HTTP: `http://127.0.0.1:8080`
- MCP: `http://127.0.0.1:8081/mcp`

```bash
curl -s http://127.0.0.1:8080/health
curl -s -X POST http://127.0.0.1:8080/v1/admin/daily?wait=true \
  -H "Authorization: Bearer changeme"
curl -s -X POST http://127.0.0.1:8080/v1/screener \
  -H "Content-Type: application/json" \
  -d '{"preset":"open_relvol"}'
```

`INGEST_MAX_TICKERS=0` (todo el universo US filtrado). El job recorre por market cap (o dollar volume si aún no hay shares). Catch-up desde el último `success`. Re-run el mismo día solo completa huecos.
