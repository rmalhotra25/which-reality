"""
Day Trade Scanner — powered by Polygon.io.

Flow:
1. Fetch top gainers + losers from Polygon snapshot
2. Filter by price, volume, and minimum % move
3. Enrich top candidates with recent news headlines
4. Pass to Claude for high-confidence play selection
"""
import logging

logger = logging.getLogger(__name__)

MIN_PRICE = 5.0
MAX_PRICE = 500.0
MIN_VOLUME = 500_000
MIN_CHANGE_PCT = 2.0  # only stocks moving at least 2% qualify


def _extract(t: dict) -> dict | None:
    """Parse a Polygon snapshot ticker object into a clean dict."""
    try:
        ticker = t.get("ticker", "")
        change_pct = t.get("todaysChangePerc", 0) or 0
        day = t.get("day") or {}
        prev = t.get("prevDay") or {}

        price = day.get("c") or day.get("vw") or 0
        volume = day.get("v") or 0
        high = day.get("h") or price
        low = day.get("l") or price
        open_price = day.get("o") or price
        vwap = day.get("vw") or price
        prev_close = prev.get("c") or price
        prev_vol = prev.get("v") or volume

        if not price or price < MIN_PRICE or price > MAX_PRICE:
            return None
        if volume < MIN_VOLUME:
            return None
        if abs(change_pct) < MIN_CHANGE_PCT:
            return None

        vol_ratio = round(volume / prev_vol, 1) if prev_vol > 0 else 1.0

        return {
            "ticker": ticker,
            "price": round(float(price), 2),
            "change_pct": round(float(change_pct), 2),
            "volume_m": round(float(volume) / 1_000_000, 1),
            "vol_ratio": vol_ratio,
            "high": round(float(high), 2),
            "low": round(float(low), 2),
            "open": round(float(open_price), 2),
            "vwap": round(float(vwap), 2),
            "prev_close": round(float(prev_close), 2),
        }
    except Exception as e:
        logger.debug("_extract error for %s: %s", t.get("ticker"), e)
        return None


def run_scan() -> dict:
    """Run the day trade scan and return Claude's top plays."""
    from services.polygon_client import get_movers, get_news
    from services.claude_analyst import ClaudeAnalyst

    gainers_raw = get_movers("gainers", limit=25)
    losers_raw = get_movers("losers", limit=15)

    candidates = []
    for t in gainers_raw:
        d = _extract(t)
        if d:
            d["direction"] = "up"
            candidates.append(d)
    for t in losers_raw:
        d = _extract(t)
        if d:
            d["direction"] = "down"
            candidates.append(d)

    if not candidates:
        return {
            "plays": [],
            "candidates_scanned": 0,
            "error": "No qualifying movers found. Market may be closed or data unavailable.",
        }

    # Sort by volume ratio — highest conviction moves first
    candidates.sort(key=lambda x: x["vol_ratio"], reverse=True)
    top = candidates[:15]

    # Enrich with news
    for c in top:
        try:
            news = get_news(c["ticker"], limit=3)
            c["news"] = [n.get("title", "") for n in news if n.get("title")]
        except Exception:
            c["news"] = []

    analyst = ClaudeAnalyst()
    plays = analyst.scan_day_trades(top)

    return {
        "plays": plays,
        "candidates_scanned": len(candidates),
        "top_movers": top,
        "data_note": "15-minute delayed data (Polygon.io free tier)",
    }
