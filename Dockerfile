FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml /app/pyproject.toml
COPY db /app/db
COPY src /app/src

RUN pip install --no-cache-dir \
    "duckdb>=1.2" "pandas>=2.2" "pyarrow>=17" "httpx>=0.27" \
    "fastapi>=0.115" "uvicorn[standard]>=0.32" "mcp>=1.9,<2" \
    "structlog>=24.4" "pydantic>=2.9" "pydantic-settings>=2.5" "boto3>=1.35" \
    "psycopg[binary]>=3.2"

ENV PYTHONPATH=/app/src
ENV LAKE_PATH=/data/lake

VOLUME ["/data/lake"]

EXPOSE 8080 8081

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD curl -fsS http://127.0.0.1:8080/health || exit 1

CMD ["sh", "-c", "python -m paper_broker.migrate && python -m paper_broker"]
