from __future__ import annotations

import csv
import io

import httpx

from paper_broker.domain.models import AssetType, SecurityDraft
from paper_broker.logging import get_logger

log = get_logger("nasdaq")

NASDAQ_LISTED = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"

_SKIP_CHARS = set("^/+")


class NasdaqUniverse:
    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def fetch_us_stocks(self) -> list[SecurityDraft]:
        nasdaq = self._parse(self._get(NASDAQ_LISTED), nasdaq=True)
        other = self._parse(self._get(OTHER_LISTED), nasdaq=False)
        by_ticker: dict[str, SecurityDraft] = {}
        for d in nasdaq + other:
            by_ticker[d.ticker] = d
        # Calendar / RS benchmark — not tradable universe, but we need QQQ bars.
        by_ticker["QQQ"] = SecurityDraft(
            ticker="QQQ",
            name="Invesco QQQ Trust",
            exchange="NASDAQ",
            asset_type=AssetType.ETF,
            listing_status="benchmark",
            market="US",
        )
        log.info("universe_loaded", n=len(by_ticker))
        return list(by_ticker.values())

    def _get(self, url: str) -> str:
        res = self._client.get(url)
        res.raise_for_status()
        return res.text

    def _parse(self, text: str, *, nasdaq: bool) -> list[SecurityDraft]:
        # File ends with a File Creation Time row.
        lines = [ln for ln in text.splitlines() if ln and not ln.startswith("File Creation")]
        if not lines:
            return []
        reader = csv.DictReader(io.StringIO("\n".join(lines)), delimiter="|")
        out: list[SecurityDraft] = []
        for row in reader:
            symbol = (row.get("Symbol") or row.get("ACT Symbol") or "").strip().upper()
            if not symbol or any(ch in symbol for ch in _SKIP_CHARS):
                continue
            if (row.get("Test Issue") or "N").upper() == "Y":
                continue
            if (row.get("ETF") or "N").upper() == "Y":
                continue
            name = (row.get("Security Name") or symbol).strip()
            lower = name.lower()
            if any(w in lower for w in ("warrant", " unit", "right", "preferred")):
                continue
            if nasdaq:
                exchange = "NASDAQ"
            else:
                exchange = {"A": "NYSEAMERICAN", "N": "NYSE", "P": "NYSEARCA", "Z": "BATS"}.get(
                    (row.get("Exchange") or "").strip(), row.get("Exchange") or "US"
                )
            asset = AssetType.ADR if "adr" in lower else AssetType.STOCK
            out.append(
                SecurityDraft(
                    ticker=symbol,
                    name=name,
                    exchange=exchange,
                    asset_type=asset,
                    listing_status="active",
                    market="US",
                )
            )
        return out
