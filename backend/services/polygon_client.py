import logging
from datetime import date, timedelta

logger = logging.getLogger(__name__)


def _client():
    from config import settings
    from massive.rest import RESTClient
    if not settings.polygon_api_key:
        raise RuntimeError("POLYGON_API_KEY is not configured")
    return RESTClient(settings.polygon_api_key)


def get_movers(direction: str = "gainers", limit: int = 25) -> list[dict]:
    """Top gainers or losers by % change today, returned as plain dicts."""
    c = _client()
    snapshots = c.get_snapshot_direction("stocks", direction)
    result = []
    for s in (snapshots or []):
        if len(result) >= limit:
            break
        day = s.day
        prev = s.prev_day
        result.append({
            "ticker": s.ticker,
            "todaysChangePerc": s.todays_change_percent or 0,
            "day": {
                "c": day.close if day else None,
                "h": day.high if day else None,
                "l": day.low if day else None,
                "o": day.open if day else None,
                "v": day.volume if day else None,
                "vw": day.vwap if day else None,
            },
            "prevDay": {
                "c": prev.close if prev else None,
                "v": prev.volume if prev else None,
            },
        })
    return result


def get_aggregates(
    ticker: str,
    from_date: str,
    to_date: str,
    timespan: str = "day",
    multiplier: int = 1,
) -> list[dict]:
    """OHLCV bars, returned as plain dicts."""
    c = _client()
    aggs = c.get_aggs(ticker, multiplier, timespan, from_date, to_date,
                      adjusted=True, sort="asc", limit=50)
    return [
        {"o": a.open, "h": a.high, "l": a.low, "c": a.close,
         "v": a.volume, "vw": a.vwap, "t": a.timestamp}
        for a in (aggs or [])
    ]


def get_news(ticker: str | None = None, limit: int = 5) -> list[dict]:
    """Recent news articles, returned as plain dicts."""
    c = _client()
    kwargs = {"limit": limit, "order": "desc"}
    if ticker:
        kwargs["ticker"] = ticker
    articles = c.list_ticker_news(**kwargs)
    result = []
    for n in (articles or []):
        result.append({"title": getattr(n, "title", "") or ""})
        if len(result) >= limit:
            break
    return result
