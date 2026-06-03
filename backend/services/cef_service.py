"""
CEF (Closed-End Fund) Scanner — scores popular CEFs using Polygon + Finnhub.

Score (0-100):
  Distribution Yield : 40 pts  (annualized div / price — key income metric)
  Price vs 52W Low   : 30 pts  (how close to 52-week low — value entry proxy)
  Dividend Streak    : 20 pts  (months of consistent monthly distributions)
  Yield Momentum     : 10 pts  (yield rising vs 6 months ago — discount widening)

Cache TTL: 4 hours (/tmp/cache_cef_scan.json)
"""
import json
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_CACHE_FILE = "/tmp/cache_cef_scan.json"
_CACHE_TTL = 4 * 3600

_CEF_UNIVERSE = [
    # PIMCO income
    "PDI", "PTY", "PCI", "PHK", "RCS",
    # Multi-sector / corp bond
    "GOF", "AWF", "GHY", "EHI", "GLO", "RIV",
    # Senior loans / CLO
    "BGT", "EFT", "XFLT", "JRO",
    # Equity income
    "CII", "CSQ", "EXG", "ETJ", "BOE",
    # Preferred / hybrid
    "FPF", "JPS", "JPC", "HPI", "DFP",
    # Municipal
    "NVG", "NAD", "NEA", "NMZ", "BKN",
    # Infrastructure / utilities
    "UTF", "UTG",
    # Real estate
    "RNP", "NRO", "JRS",
    # MLP / energy
    "NTG", "CEM", "KYN",
    # Global income
    "FAX", "EDD",
]


def _get_dividends(ticker: str, days: int = 400) -> list[dict]:
    """Fetch recent dividend history from Polygon."""
    try:
        from services.polygon_client import _client
        c = _client()
        ex_from = (date.today() - timedelta(days=days)).isoformat()
        items = list(c.list_dividends(
            ticker=ticker,
            ex_dividend_date_gte=ex_from,
            limit=50,
            order="desc",
        ))
        return [
            {
                "ex_date": str(getattr(d, "ex_dividend_date", "") or ""),
                "amount": float(getattr(d, "cash_amount", 0) or 0),
                "frequency": int(getattr(d, "frequency", 12) or 12),
            }
            for d in (items or [])
        ]
    except Exception as e:
        logger.debug("dividends fetch failed for %s: %s", ticker, e)
        return []


def _get_snapshot(ticker: str) -> dict:
    """Price snapshot and 52w high/low from Polygon."""
    try:
        from services.polygon_client import _client
        c = _client()
        snap = c.get_snapshot_ticker("stocks", ticker)
        if not snap:
            return {}
        day = snap.day
        prev = snap.prev_day
        price = float(day.close or 0) if day else 0
        if price <= 0:
            price = float(prev.close or 0) if prev else 0

        # 52-week range from Polygon aggregates
        to_dt = date.today().isoformat()
        from_dt = (date.today() - timedelta(days=380)).isoformat()
        aggs = list(c.get_aggs(ticker, 1, "day", from_dt, to_dt,
                               adjusted=True, sort="asc", limit=400))
        closes = [float(a.close) for a in aggs if a.close and float(a.close) > 0]

        high_52w = max(closes[-252:]) if len(closes) >= 20 else None
        low_52w = min(closes[-252:]) if len(closes) >= 20 else None

        # 6-month-ago price for yield momentum
        price_6m = closes[-126] if len(closes) >= 126 else None

        return {
            "price": price,
            "high_52w": high_52w,
            "low_52w": low_52w,
            "price_6m_ago": price_6m,
        }
    except Exception as e:
        logger.debug("snapshot failed for %s: %s", ticker, e)
        return {}


def _calculate_score(
    annual_yield_pct: float | None,
    pct_above_52w_low: float | None,
    dividend_streak_months: int,
    yield_6m_ago_pct: float | None,
    annual_yield_now_pct: float | None,
) -> tuple[int, dict]:
    """Score CEF 0-100 and return component breakdown."""
    score = 0
    breakdown = {}

    # Distribution yield (40 pts)
    if annual_yield_pct is not None:
        if annual_yield_pct >= 12:
            dy = 40
        elif annual_yield_pct >= 10:
            dy = 34
        elif annual_yield_pct >= 8:
            dy = 26
        elif annual_yield_pct >= 6:
            dy = 18
        elif annual_yield_pct >= 4:
            dy = 10
        else:
            dy = 4
        score += dy
        breakdown["distribution_yield"] = dy
    else:
        breakdown["distribution_yield"] = 0

    # Price vs 52w low (30 pts) — lower = closer to 52w low = better entry
    if pct_above_52w_low is not None:
        if pct_above_52w_low <= 5:
            pv = 30
        elif pct_above_52w_low <= 12:
            pv = 24
        elif pct_above_52w_low <= 20:
            pv = 16
        elif pct_above_52w_low <= 35:
            pv = 8
        else:
            pv = 2
        score += pv
        breakdown["price_vs_52w_low"] = pv
    else:
        breakdown["price_vs_52w_low"] = 0

    # Dividend streak (20 pts) — consistent monthly distributions = reliable fund
    if dividend_streak_months >= 12:
        ds = 20
    elif dividend_streak_months >= 9:
        ds = 16
    elif dividend_streak_months >= 6:
        ds = 12
    elif dividend_streak_months >= 3:
        ds = 7
    else:
        ds = 2
    score += ds
    breakdown["dividend_streak"] = ds

    # Yield momentum (10 pts) — yield rising vs 6 months ago means discount widening
    if annual_yield_now_pct is not None and yield_6m_ago_pct is not None and yield_6m_ago_pct > 0:
        yield_delta = annual_yield_now_pct - yield_6m_ago_pct
        if yield_delta >= 1.5:
            ym = 10
        elif yield_delta >= 0.5:
            ym = 7
        elif yield_delta >= 0:
            ym = 4
        else:
            ym = 1
        score += ym
        breakdown["yield_momentum"] = ym
    else:
        score += 4  # neutral
        breakdown["yield_momentum"] = 4

    return min(score, 100), breakdown


def analyze_cef(ticker: str) -> dict:
    """Fetch Polygon data and return a scored CEF result dict."""
    ticker = ticker.upper().strip()

    snap = _get_snapshot(ticker)
    price = snap.get("price", 0)
    if price <= 0:
        raise ValueError(f"No price data for {ticker}")

    divs = _get_dividends(ticker, days=400)

    # Most recent dividend for yield calculation
    recent_div = divs[0] if divs else None
    div_amount = recent_div["amount"] if recent_div else None
    frequency = recent_div["frequency"] if recent_div else 12
    annual_div = div_amount * frequency if div_amount else None
    annual_yield_pct = round((annual_div / price) * 100, 2) if annual_div and price > 0 else None

    # Dividend streak: count consecutive months with a payment
    streak_months = 0
    if divs:
        today = date.today()
        for i in range(min(len(divs), 13)):
            d = divs[i]
            if d["amount"] > 0:
                streak_months += 1
            else:
                break

    # 52w metrics
    high_52w = snap.get("high_52w")
    low_52w = snap.get("low_52w")
    pct_above_52w_low = None
    pct_below_52w_high = None
    if low_52w and low_52w > 0 and price > 0:
        pct_above_52w_low = round((price - low_52w) / low_52w * 100, 1)
    if high_52w and high_52w > 0 and price > 0:
        pct_below_52w_high = round((high_52w - price) / high_52w * 100, 1)

    # Yield 6 months ago
    price_6m = snap.get("price_6m_ago")
    yield_6m_ago_pct = round((annual_div / price_6m) * 100, 2) if annual_div and price_6m and price_6m > 0 else None

    score, breakdown = _calculate_score(
        annual_yield_pct,
        pct_above_52w_low,
        streak_months,
        yield_6m_ago_pct,
        annual_yield_pct,
    )

    return {
        "ticker": ticker,
        "score": score,
        "price": round(price, 2),
        "annual_yield_pct": annual_yield_pct,
        "monthly_div": round(div_amount, 4) if div_amount else None,
        "div_frequency": frequency,
        "dividend_streak_months": streak_months,
        "high_52w": round(high_52w, 2) if high_52w else None,
        "low_52w": round(low_52w, 2) if low_52w else None,
        "pct_above_52w_low": pct_above_52w_low,
        "pct_below_52w_high": pct_below_52w_high,
        "yield_6m_ago_pct": yield_6m_ago_pct,
        "score_breakdown": breakdown,
    }


def _cache_read() -> dict | None:
    try:
        if not os.path.exists(_CACHE_FILE):
            return None
        with open(_CACHE_FILE) as f:
            data = json.load(f)
        if time.time() - data.get("cached_at", 0) > _CACHE_TTL:
            return None
        return data
    except Exception:
        return None


def _cache_write(data: dict) -> None:
    try:
        data["cached_at"] = time.time()
        with open(_CACHE_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        logger.warning("CEF cache write failed: %s", e)


def scan_universe(force: bool = False) -> dict:
    """Scan all CEFs and return sorted results. Uses 4-hour file cache."""
    if not force:
        cached = _cache_read()
        if cached:
            logger.info("CEF scan: returning cached results")
            return cached

    results = []
    errors = []
    for ticker in _CEF_UNIVERSE:
        try:
            r = analyze_cef(ticker)
            results.append(r)
        except Exception as e:
            errors.append(ticker)
            logger.debug("CEF scan error for %s: %s", ticker, e)
        time.sleep(0.3)  # respect Polygon rate limits

    results.sort(key=lambda x: x["score"], reverse=True)

    output = {
        "scanned_at": datetime.now(tz=timezone.utc).isoformat(),
        "universe_count": len(_CEF_UNIVERSE),
        "scored_count": len(results),
        "top": results[:20],
        "all": results,
        "errors": errors,
    }
    _cache_write(output)
    logger.info("CEF scan complete: %d scored, %d errors", len(results), len(errors))
    return output
