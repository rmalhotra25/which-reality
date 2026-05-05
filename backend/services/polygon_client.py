import logging
import requests

logger = logging.getLogger(__name__)
BASE = "https://api.polygon.io"


def _get(path, params=None):
    from config import settings
    key = settings.polygon_api_key
    if not key:
        raise RuntimeError("POLYGON_API_KEY is not configured")
    p = {"apiKey": key}
    if params:
        p.update(params)
    r = requests.get(f"{BASE}{path}", params=p, timeout=15)
    r.raise_for_status()
    return r.json()


def get_movers(direction: str = "gainers", limit: int = 25) -> list[dict]:
    """Top gainers or losers by % change today."""
    data = _get(f"/v2/snapshot/locale/us/markets/stocks/{direction}")
    return data.get("tickers", [])[:limit]


def get_ticker_snapshot(ticker: str) -> dict:
    data = _get(f"/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}")
    return data.get("ticker", {})


def get_aggregates(
    ticker: str,
    from_date: str,
    to_date: str,
    timespan: str = "day",
    multiplier: int = 1,
) -> list[dict]:
    """OHLCV bars for a ticker."""
    data = _get(
        f"/v2/aggs/ticker/{ticker}/range/{multiplier}/{timespan}/{from_date}/{to_date}",
        params={"adjusted": "true", "sort": "asc", "limit": 50},
    )
    return data.get("results", [])


def get_news(ticker: str | None = None, limit: int = 5) -> list[dict]:
    """Recent news articles, optionally filtered by ticker."""
    params = {"limit": limit, "order": "desc"}
    if ticker:
        params["ticker"] = ticker
    data = _get("/v2/reference/news", params)
    return data.get("results", [])
