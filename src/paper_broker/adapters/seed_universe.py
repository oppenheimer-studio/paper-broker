from __future__ import annotations

from paper_broker.domain.models import AssetType, SecurityDraft

# Small liquid US set so the first daily can produce as_of when Nasdaq is down.
SEED: list[tuple[str, str, str]] = [
    ("QQQ", "Invesco QQQ Trust", "NASDAQ"),
    ("SPY", "SPDR S&P 500 ETF Trust", "NYSEARCA"),
    ("AAPL", "Apple Inc", "NASDAQ"),
    ("MSFT", "Microsoft Corp", "NASDAQ"),
    ("NVDA", "NVIDIA Corp", "NASDAQ"),
    ("AMZN", "Amazon.com Inc", "NASDAQ"),
    ("GOOGL", "Alphabet Inc Class A", "NASDAQ"),
    ("META", "Meta Platforms Inc", "NASDAQ"),
    ("TSLA", "Tesla Inc", "NASDAQ"),
    ("AVGO", "Broadcom Inc", "NASDAQ"),
    ("BRK.B", "Berkshire Hathaway Inc Class B", "NYSE"),
    ("JPM", "JPMorgan Chase & Co", "NYSE"),
    ("V", "Visa Inc", "NYSE"),
    ("UNH", "UnitedHealth Group Inc", "NYSE"),
    ("XOM", "Exxon Mobil Corp", "NYSE"),
    ("JNJ", "Johnson & Johnson", "NYSE"),
    ("WMT", "Walmart Inc", "NYSE"),
    ("MA", "Mastercard Inc", "NYSE"),
    ("PG", "Procter & Gamble Co", "NYSE"),
    ("HD", "Home Depot Inc", "NYSE"),
    ("COST", "Costco Wholesale Corp", "NASDAQ"),
    ("ABBV", "AbbVie Inc", "NYSE"),
    ("NFLX", "Netflix Inc", "NASDAQ"),
    ("CRM", "Salesforce Inc", "NYSE"),
    ("AMD", "Advanced Micro Devices Inc", "NASDAQ"),
    ("ORCL", "Oracle Corp", "NYSE"),
    ("KO", "Coca-Cola Co", "NYSE"),
    ("PEP", "PepsiCo Inc", "NASDAQ"),
    ("ADBE", "Adobe Inc", "NASDAQ"),
    ("CSCO", "Cisco Systems Inc", "NASDAQ"),
    ("INTC", "Intel Corp", "NASDAQ"),
    ("QCOM", "Qualcomm Inc", "NASDAQ"),
    ("INTU", "Intuit Inc", "NASDAQ"),
    ("AMAT", "Applied Materials Inc", "NASDAQ"),
    ("TXN", "Texas Instruments Inc", "NASDAQ"),
    ("IBM", "International Business Machines Corp", "NYSE"),
    ("GE", "GE Aerospace", "NYSE"),
    ("CAT", "Caterpillar Inc", "NYSE"),
    ("BA", "Boeing Co", "NYSE"),
    ("DIS", "Walt Disney Co", "NYSE"),
    ("NKE", "Nike Inc", "NYSE"),
    ("GS", "Goldman Sachs Group Inc", "NYSE"),
]


def seed_drafts() -> list[SecurityDraft]:
    out: list[SecurityDraft] = []
    for ticker, name, exchange in SEED:
        etf = ticker in {"QQQ", "SPY"}
        out.append(
            SecurityDraft(
                ticker=ticker,
                name=name,
                exchange=exchange,
                asset_type=AssetType.ETF if etf else AssetType.STOCK,
                listing_status="benchmark" if ticker == "QQQ" else "active",
                market="US",
            )
        )
    return out
