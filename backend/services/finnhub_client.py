"""
Thin wrapper around the Finnhub REST API.
Used for reliable stock data (prices, candles, fundamentals, earnings).
Replaces yfinance bulk downloads which get rate-limited on cloud server IPs.
"""
import logging
import time
from datetime import datetime, timezone, timedelta

import finnhub

from config import settings

logger = logging.getLogger(__name__)

_client = None


def _get_client() -> finnhub.Client:
    global _client
    if _client is None:
        key = settings.finnhub_api_key or ""
        if not key:
            raise RuntimeError("FINNHUB_API_KEY is not set")
        _client = finnhub.Client(api_key=key)
    return _client


def get_quote(symbol: str) -> dict:
    """Current price, open, high, low, prev close, change %."""
    try:
        return _get_client().quote(symbol) or {}
    except Exception as e:
        logger.warning("Finnhub quote failed for %s: %s", symbol, e)
        return {}


def get_candles(symbol: str, days: int = 90) -> dict:
    """
    Daily OHLCV candles going back `days` calendar days.
    Returns dict with keys: c (close), h, l, o, v (volume), t (timestamps), s (status).
    """
    to_ts = int(time.time())
    from_ts = to_ts - days * 24 * 3600
    try:
        data = _get_client().stock_candles(symbol, "D", from_ts, to_ts)
        return data or {}
    except Exception as e:
        logger.warning("Finnhub candles failed for %s: %s", symbol, e)
        return {}


def get_basic_financials(symbol: str) -> dict:
    """PE ratio, dividend yield, 52-week high/low, beta, etc."""
    try:
        data = _get_client().company_basic_financials(symbol, "all")
        return data.get("metric", {}) or {}
    except Exception as e:
        logger.warning("Finnhub financials failed for %s: %s", symbol, e)
        return {}


def get_company_profile(symbol: str) -> dict:
    """Sector, industry, name, market cap."""
    try:
        return _get_client().company_profile2(symbol=symbol) or {}
    except Exception as e:
        logger.warning("Finnhub profile failed for %s: %s", symbol, e)
        return {}


def get_earnings_this_month(symbol: str) -> int | None:
    """
    Returns days until next earnings announcement, or None if unknown.
    Only checks the next 30 days.
    """
    try:
        today = datetime.now(timezone.utc).date()
        end = today + timedelta(days=30)
        cal = _get_client().earnings_calendar(
            _from=today.strftime("%Y-%m-%d"),
            to=end.strftime("%Y-%m-%d"),
            symbol=symbol,
        )
        earnings = cal.get("earningsCalendar", [])
        if not earnings:
            return None
        dates = []
        for e in earnings:
            try:
                d = datetime.strptime(e["date"], "%Y-%m-%d").date()
                days_away = (d - today).days
                if days_away >= 0:
                    dates.append(days_away)
            except Exception:
                pass
        return min(dates) if dates else None
    except Exception as e:
        logger.debug("Finnhub earnings failed for %s: %s", symbol, e)
        return None
