"""Covered call picks router, standalone from ticker lookup.

No Nash scoring, no verdict gating, no SPY gate, no earnings
fail-closed gating, and no Challenge sizing are applied here. This
endpoint only prices listed calls against shares, by delta band, on
one expiry. News headlines are shown as headlines only, never as a
buy or sell signal and never counted as support for a pick.
"""

import re
from datetime import date

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/covered-call-picks", tags=["Covered Call Picks"])
_TICKER_RE = re.compile(r"^[A-Z]{1,6}$")
_SYMBOL_RE = re.compile(r"^[A-Z]+(\d{6})[CP]\d{8}$")


def _expiries_from_yfinance(ticker):
    try:
        import yfinance as yf

        expiries = yf.Ticker(ticker).options or []
    except Exception:
        return []
    today = date.today()
    out = []
    for exp in expiries:
        try:
            dte = (date.fromisoformat(str(exp)) - today).days
        except ValueError:
            continue
        if dte > 0:
            out.append({"expiry": str(exp), "dte": dte})
    return sorted(out, key=lambda e: e["dte"])


def _expiries_from_cboe(provider, ticker):
    try:
        options = provider._fetch_cboe_payload(ticker)
    except Exception:
        return []
    today = date.today()
    seen = {}
    for opt in options or []:
        match = _SYMBOL_RE.match(str(opt.get("option") or ""))
        if not match:
            continue
        raw = match.group(1)
        try:
            exp = date(2000 + int(raw[0:2]), int(raw[2:4]), int(raw[4:6]))
        except ValueError:
            continue
        dte = (exp - today).days
        if dte > 0:
            seen[exp.isoformat()] = dte
    return [{"expiry": exp, "dte": dte} for exp, dte in sorted(seen.items(), key=lambda kv: kv[1])]


def _history(ticker):
    try:
        import yfinance as yf

        hist = yf.Ticker(ticker).history(period="6mo")
        points = []
        for idx, row in hist.iterrows():
            try:
                close = float(row["Close"])
            except (KeyError, TypeError, ValueError):
                continue
            points.append({"date": idx.strftime("%Y-%m-%d"), "close": round(close, 2)})
        return points or None
    except Exception:
        return None


def _news(ticker):
    try:
        from services.polygon_client import get_news

        items = get_news(ticker, limit=5) or []
        return [
            {
                "title": item.get("title") or "",
                "published_at": item.get("published_at"),
                "publisher": item.get("publisher"),
                "url": item.get("url"),
            }
            for item in items
            if item.get("title")
        ], None
    except Exception as exc:
        return [], f"news_unavailable: {type(exc).__name__}"


@router.get("/{ticker}")
def covered_call_picks(
    ticker: str,
    expiry: str | None = Query(default=None),
    shares: int = Query(default=100, ge=0),
    cost_basis: float | None = Query(default=None),
):
    from services.chain_provider import ChainProvider
    from services.covered_call_picks import build_picks, default_expiry

    ticker = (ticker or "").strip().upper()
    if not _TICKER_RE.match(ticker):
        raise HTTPException(status_code=400, detail="Ticker must be 1-6 letters.")

    provider = ChainProvider()
    price = provider.fetch_price(ticker)
    expiries = _expiries_from_yfinance(ticker)
    expiries_source = "yfinance" if expiries else None
    if not expiries:
        expiries = _expiries_from_cboe(provider, ticker)
        expiries_source = "cboe_delayed" if expiries else None

    selected = None
    if expiry:
        for item in expiries:
            if item["expiry"] == expiry:
                selected = item
                break
        if selected is None:
            try:
                dte = (date.fromisoformat(expiry) - date.today()).days
                if dte > 0:
                    selected = {"expiry": expiry, "dte": dte}
            except ValueError:
                selected = None
    if selected is None:
        selected = default_expiry(expiries)

    news, news_error = _news(ticker)
    history = _history(ticker)

    if selected is None or price is None:
        return {
            "ticker": ticker,
            "available": False,
            "reason": (
                "No listed expiry could be found for this ticker."
                if selected is None
                else "No current price could be found for this ticker."
            ),
            "price": price,
            "expiries": expiries,
            "expiries_source": expiries_source,
            "selected_expiry": None,
            "selected_dte": None,
            "chain_source": None,
            "chain_delay_note": None,
            "picks": {"aggressive": None, "middle": None, "conservative": None},
            "band_fallback_tiers": [],
            "shares_owned": shares,
            "cost_basis": cost_basis,
            "news": news,
            "news_error": news_error,
            "news_note": "Headlines only. News is never a buy or sell signal and never counts as support for a pick.",
            "history": history,
            "history_note": None if history else "Price chart unavailable: no price history could be fetched. The strike ladder below still shows the trade-off.",
        }

    dte = selected["dte"]
    result = provider.fetch(ticker, "call", dte, dte, near_price=price)
    if not hasattr(result, "rows"):
        return {
            "ticker": ticker,
            "available": False,
            "reason": getattr(result, "reason", "No listed options chain was available."),
            "price": price,
            "expiries": expiries,
            "expiries_source": expiries_source,
            "selected_expiry": selected["expiry"],
            "selected_dte": dte,
            "chain_source": None,
            "chain_delay_note": None,
            "picks": {"aggressive": None, "middle": None, "conservative": None},
            "band_fallback_tiers": [],
            "shares_owned": shares,
            "cost_basis": cost_basis,
            "news": news,
            "news_error": news_error,
            "news_note": "Headlines only. News is never a buy or sell signal and never counts as support for a pick.",
            "history": history,
            "history_note": None if history else "Price chart unavailable: no price history could be fetched. The strike ladder below still shows the trade-off.",
        }

    chain_source = result.source
    delay_note = (
        "Chain quotes are delayed about 15 minutes (CBOE delayed)."
        if chain_source == "cboe_delayed"
        else None
    )
    picks, fallback_tiers = build_picks(result.rows, price, dte, shares, cost_basis)
    return {
        "ticker": ticker,
        "available": True,
        "reason": None,
        "price": round(price, 2),
        "expiries": expiries,
        "expiries_source": expiries_source,
        "selected_expiry": selected["expiry"],
        "selected_dte": dte,
        "chain_source": chain_source,
        "chain_delay_note": delay_note,
        "picks": picks,
        "band_fallback_tiers": fallback_tiers,
        "shares_owned": shares,
        "cost_basis": cost_basis,
        "news": news,
        "news_error": news_error,
        "news_note": "Headlines only. News is never a buy or sell signal and never counts as support for a pick.",
        "history": history,
        "history_note": None if history else "Price chart unavailable: no price history could be fetched. The strike ladder below still shows the trade-off.",
    }
