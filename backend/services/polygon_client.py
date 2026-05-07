import logging

logger = logging.getLogger(__name__)


def _client():
    from config import settings
    from massive.rest import RESTClient
    if not settings.polygon_api_key:
        raise RuntimeError("POLYGON_API_KEY is not configured")
    return RESTClient(settings.polygon_api_key, read_timeout=30.0, connect_timeout=10.0, pagination=False)


def get_market_status() -> dict:
    """Current trading status of US equity markets."""
    c = _client()
    s = c.get_market_status()
    is_open = (s.market or "").lower() == "open"
    after_hours = s.after_hours or False
    early_hours = s.early_hours or False
    if is_open:
        label = "open"
    elif after_hours:
        label = "after_hours"
    elif early_hours:
        label = "pre_market"
    else:
        label = "closed"
    return {
        "label": label,
        "is_open": is_open,
        "after_hours": after_hours,
        "early_hours": early_hours,
        "server_time": s.server_time,
    }


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


def get_short_data(ticker: str) -> dict:
    """Most recent short interest and short volume ratio for a ticker."""
    c = _client()
    result = {}

    try:
        items = list(c.list_short_interest(ticker=ticker, limit=1, order="desc"))
        if items:
            si = items[0]
            result["short_interest"] = si.short_interest
            result["days_to_cover"] = round(float(si.days_to_cover), 1) if si.days_to_cover else None
            result["settlement_date"] = si.settlement_date
    except Exception as e:
        logger.debug("short_interest failed for %s: %s", ticker, e)

    try:
        vols = list(c.list_short_volume(ticker=ticker, limit=1, order="desc"))
        if vols:
            sv = vols[0]
            if sv.short_volume_ratio is not None:
                result["short_volume_ratio_pct"] = round(float(sv.short_volume_ratio) * 100, 1)
    except Exception as e:
        logger.debug("short_volume failed for %s: %s", ticker, e)

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


def get_options_chain_snapshot(
    ticker: str,
    dte_max: int = 45,
    contract_type: str | None = None,
) -> list:
    """Real-time options chain snapshot with Greeks via Polygon (requires Options plan)."""
    from datetime import date, timedelta
    c = _client()
    today = date.today()
    params = {
        "expiration_date.gte": today.isoformat(),
        "expiration_date.lte": (today + timedelta(days=dte_max)).isoformat(),
        "limit": 250,
    }
    if contract_type:
        params["contract_type"] = contract_type.lower()
    try:
        return list(c.list_snapshot_options_chain(ticker, params=params))
    except Exception as e:
        logger.debug("options_chain_snapshot failed for %s: %s", ticker, e)
        return []


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
