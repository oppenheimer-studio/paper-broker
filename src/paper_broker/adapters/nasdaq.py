from __future__ import annotations

import csv
import io
import time
from dataclasses import dataclass, field

import httpx

from paper_broker.adapters.seed_universe import seed_drafts
from paper_broker.domain.models import AssetType, SecurityDraft
from paper_broker.logging import get_logger

log = get_logger("nasdaq")

NASDAQ_LISTED = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"

_SKIP_CHARS = set("^/+")
_BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
_HEADERS = {
    "user-agent": _BROWSER_UA,
    "accept": "text/plain,*/*",
    "accept-language": "en-US,en;q=0.9",
}


@dataclass
class UniverseSnapshot:
    drafts: list[SecurityDraft]
    source: str
    warnings: list[str] = field(default_factory=list)


QQQ = SecurityDraft(
    ticker="QQQ",
    name="Invesco QQQ Trust",
    exchange="NASDAQ",
    asset_type=AssetType.ETF,
    listing_status="benchmark",
    market="US",
)


class NasdaqUniverse:
    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        timeout: float = 30,
        warehouse=None,
        retries: int = 3,
    ) -> None:
        self._own_client = client is None
        self._client = client or httpx.Client(
            timeout=timeout,
            headers=_HEADERS,
            follow_redirects=True,
        )
        self._warehouse = warehouse
        self._retries = max(1, retries)
        self.last: UniverseSnapshot = UniverseSnapshot(drafts=[], source="empty")

    def close(self) -> None:
        if self._own_client:
            self._client.close()

    def fetch_us_stocks(self) -> list[SecurityDraft]:
        return self.fetch_universe().drafts

    def fetch_universe(self) -> UniverseSnapshot:
        warnings: list[str] = []
        nasdaq = self._try_file(NASDAQ_LISTED, nasdaq=True, warnings=warnings)
        other = self._try_file(OTHER_LISTED, nasdaq=False, warnings=warnings)

        by_ticker: dict[str, SecurityDraft] = {}
        for d in nasdaq + other:
            by_ticker[d.ticker] = d

        if nasdaq and other:
            source = "nasdaq"
        elif nasdaq or other:
            source = "partial"
        else:
            cached = self._from_warehouse()
            if cached:
                source = "cache"
                by_ticker = {d.ticker: d for d in cached}
                warnings.append("Nasdaq files failed; using warehouse cache")
            else:
                source = "seed"
                by_ticker = {d.ticker: d for d in seed_drafts()}
                warnings.append("Nasdaq files failed and warehouse empty; using seed universe")

        by_ticker["QQQ"] = QQQ
        snap = UniverseSnapshot(drafts=list(by_ticker.values()), source=source, warnings=warnings)
        self.last = snap
        log.info("universe_loaded", n=len(snap.drafts), source=source, warnings=len(warnings))
        return snap

    def _try_file(self, url: str, *, nasdaq: bool, warnings: list[str]) -> list[SecurityDraft]:
        try:
            text = self._get(url)
            return self._parse(text, nasdaq=nasdaq)
        except Exception as exc:
            msg = f"{url.split('/')[-1]}: {exc}"
            warnings.append(msg)
            log.warning("universe_file_failed", url=url, error=str(exc))
            return []

    def _from_warehouse(self) -> list[SecurityDraft]:
        if self._warehouse is None:
            return []
        try:
            secs = self._warehouse.list_securities(market=None)
        except Exception:
            log.exception("universe_cache_failed")
            return []
        out: list[SecurityDraft] = []
        for s in secs:
            out.append(
                SecurityDraft(
                    ticker=s.ticker,
                    name=s.name,
                    exchange=s.exchange,
                    asset_type=s.asset_type,
                    listing_status=s.listing_status,
                    market=s.market,
                )
            )
        return out

    def _get(self, url: str) -> str:
        last: Exception | None = None
        for attempt in range(self._retries):
            try:
                res = self._client.get(url, headers=_HEADERS)
                res.raise_for_status()
                return res.text
            except Exception as exc:
                last = exc
                log.warning("universe_get_retry", url=url, attempt=attempt + 1, error=str(exc))
                if attempt + 1 < self._retries:
                    time.sleep(0.25 * (attempt + 1))
        assert last is not None
        raise last

    def _parse(self, text: str, *, nasdaq: bool) -> list[SecurityDraft]:
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
