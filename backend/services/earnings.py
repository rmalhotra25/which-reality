"""Composite next-earnings resolver.

One question, one answer: when does this ticker next report? The
tiered lookup used to ask Finnhub alone, on a 30-day window, so a
name that reported this month (next print a quarter out) read as
"earnings unknown" and fail-closed to CANNOT JUDGE. ZETA was the
case: Finnhub's 30-day calendar had no date, while the Story's
120-day Finnhub window already knew Feb 22, 2027. Two parts of the
same page disagreed.

The resolver tries four sources in order and takes the first future
date found: FMP, Polygon, Yahoo (yfinance), Finnhub. Each source is
individually guarded, so one dead feed never blocks the others, and
a missing API key skips that source silently. Polygon publishes no
earnings calendar endpoint, so its leg always yields; it is kept in
the order so a future Polygon earnings feed has one place to plug
in. Both the tiered lookup and the Story call this resolver, so the
two pages can never disagree about the next earnings date again.
"""

import logging
from datetime import date, timedelta

logger = logging.getLogger(__name__)

_WINDOW_DAYS = 180


def _future_dates(dates):
    """Sorted future dates (today counts) from a mixed list of
    dates, datetimes and Timestamps. Anything unparseable is
    dropped, never guessed."""
    today = date.today()
    out = []
    for d in dates or []:
        if d is None:
            continue
        try:
            dd = d.date() if hasattr(d, "date") else d
        except Exception:
            continue
        if isinstance(dd, date) and dd >= today:
            out.append(dd)
    return sorted(out)


def _from_fmp(ticker):
    """Next earnings date from the FMP earnings calendar, or None.

    Uses the FMP client's _get, which returns None when no key is
    configured, so the sandbox (no FMP key) skips this source
    silently.
    """
    try:
        from services.fmp_client import _get

        start = date.today()
        end = start + timedelta(days=_WINDOW_DAYS)
        rows = _get(f"/earning_calendar/{ticker}",
                    {"from": start.isoformat(), "to": end.isoformat()})
        if not isinstance(rows, list):
            return None
        dates = []
        for row in rows:
            raw = (row or {}).get("date")
            if not raw:
                continue
            try:
                dates.append(date.fromisoformat(str(raw)[:10]))
            except ValueError:
                continue
        future = _future_dates(dates)
        return future[0] if future else None
    except Exception as exc:
        logger.debug("earnings FMP failed for %s: %s", ticker, exc)
        return None


def _from_polygon(ticker):
    """Polygon publishes no earnings calendar endpoint, so this leg
    always yields. It is kept in the source order so a future
    Polygon earnings feed has one place to plug in."""
    return None


def _from_yahoo(ticker):
    """Next earnings date from yfinance, or None.

    Tries the earnings-dates table first (past and future prints),
    then the calendar's Earnings Date list. Both are guarded, and
    a missing yfinance install skips the source.
    """
    try:
        import yfinance as yf

        t = yf.Ticker(ticker)
        dates = []
        try:
            frame = t.get_earnings_dates(limit=8)
            if frame is not None and not frame.empty:
                for idx in frame.index:
                    try:
                        dates.append(idx.date() if hasattr(idx, "date") else idx)
                    except Exception:
                        continue
        except Exception as exc:
            logger.debug("earnings Yahoo dates table failed for %s: %s",
                         ticker, exc)
        if not dates:
            try:
                cal = t.calendar
                raw = None
                if isinstance(cal, dict):
                    raw = cal.get("Earnings Date")
                elif cal is not None:
                    try:
                        row = cal.loc["Earnings Date"]
                        raw = row.iloc[0] if hasattr(row, "iloc") else row
                    except Exception:
                        raw = None
                if raw is not None:
                    items = raw if isinstance(raw, (list, tuple)) else [raw]
                    for item in items:
                        try:
                            dates.append(item.date() if hasattr(item, "date") else item)
                        except Exception:
                            continue
            except Exception as exc:
                logger.debug("earnings Yahoo calendar failed for %s: %s",
                             ticker, exc)
        future = _future_dates(dates)
        return future[0] if future else None
    except Exception as exc:
        logger.debug("earnings Yahoo failed for %s: %s", ticker, exc)
        return None


def _from_finnhub(ticker):
    """Next earnings date from the Finnhub calendar, or None.

    Uses the 180-day window, so a name that reported this month
    still shows its next print a quarter out instead of reading
    unknown. A missing key or a failed call returns None.
    """
    try:
        from services.finnhub_client import get_earnings_within

        days = get_earnings_within(ticker, days=_WINDOW_DAYS)
        if days is None:
            return None
        return date.today() + timedelta(days=int(days))
    except Exception as exc:
        logger.debug("earnings Finnhub failed for %s: %s", ticker, exc)
        return None


_SOURCES = (
    ("fmp", _from_fmp),
    ("polygon", _from_polygon),
    ("yahoo", _from_yahoo),
    ("finnhub", _from_finnhub),
)


def resolve_next_earnings(ticker):
    """Next earnings date for a ticker, from the first source that
    has one.

    Returns (date, source) with source one of "fmp", "polygon",
    "yahoo", "finnhub", or (None, None) when no source knows a
    future date. Never raises: a failed source is logged and the
    next source is tried.
    """
    ticker = (ticker or "").upper().strip()
    if not ticker:
        return None, None
    for source, fn in _SOURCES:
        try:
            found = fn(ticker)
        except Exception as exc:
            logger.debug("earnings %s failed for %s: %s", source, ticker, exc)
            found = None
        if found is not None:
            return found, source
    return None, None
