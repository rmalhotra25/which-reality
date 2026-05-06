"""
Options Flow Scanner — detects unusual activity on the real options chain.

For each ticker in the universe:
  1. Fetch the next 1-2 expiries (≤ 45 DTE) via yfinance
  2. Fetch earnings date context (upcoming / just passed / none)
  3. Scan every call and put for abnormal volume vs open interest
  4. Compute notional premium (volume × mid × 100)
  5. Flag contracts where vol/OI ≥ 3x or brand-new OI
  6. Pass top alerts + earnings context to Claude for interpretation
"""
import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

import yfinance as yf

logger = logging.getLogger(__name__)

# Most liquid US equity options — highest volume, tightest spreads
FLOW_UNIVERSE = [
    # Mega-cap tech
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA",
    # Semiconductors
    "AMD", "INTC", "MU", "SMCI", "AVGO", "ARM",
    # High-IV momentum
    "PLTR", "COIN", "HOOD", "MSTR", "SOFI", "RIVN", "RBLX", "DKNG",
    # Financials
    "JPM", "GS", "BAC", "MS", "V",
    # ETFs (highest options volume)
    "SPY", "QQQ", "IWM", "SOXL", "TQQQ", "SQQQ", "XLE", "GLD", "ARKK",
    # Other liquid names
    "NFLX", "DIS", "UBER", "SQ", "SHOP", "CRWD", "NOW", "CRM",
    # Biotech
    "LLY", "MRNA", "BNTX",
]

MIN_VOLUME = 200
MIN_VOL_OI_RATIO = 3.0
MIN_NOTIONAL = 25_000
MAX_ALERTS_PER_TICKER = 2


def _earnings_context(t: "yf.Ticker") -> str | None:
    """Return a short string describing earnings proximity, or None if unavailable."""
    try:
        cal = t.calendar
        if cal is None:
            return None
        # yfinance returns calendar as a dict; 'Earnings Date' may be a list or single value
        ed_raw = cal.get("Earnings Date") if isinstance(cal, dict) else None
        if ed_raw is None:
            return None
        if hasattr(ed_raw, "__iter__") and not isinstance(ed_raw, str):
            ed_list = [d for d in ed_raw if d is not None]
            ed_raw = ed_list[0] if ed_list else None
        if ed_raw is None:
            return None
        import pandas as pd
        earnings_date = pd.Timestamp(ed_raw).date()
        days = (earnings_date - date.today()).days
        if -14 <= days <= 0:
            return f"Earnings {abs(days)}d ago ({earnings_date})"
        elif 1 <= days <= 30:
            return f"Earnings in {days}d ({earnings_date})"
        return None
    except Exception:
        return None


def _fetch_ticker_flow(ticker: str) -> list[dict]:
    """Return unusual flow alerts for a single ticker, with earnings context."""
    # Small random stagger so parallel workers don't all hit Yahoo simultaneously
    time.sleep(random.uniform(0.1, 0.6))
    try:
        t = yf.Ticker(ticker)
        expiries = t.options
        if not expiries:
            return []

        today = date.today()
        price = getattr(t.fast_info, "last_price", None)
        if not price or price <= 0:
            return []

        earnings_ctx = _earnings_context(t)

        # Up to 2 nearest expiries within 45 DTE
        targets = []
        for exp in expiries:
            dte = (date.fromisoformat(exp) - today).days
            if 1 <= dte <= 45:
                targets.append(exp)
            if len(targets) >= 2:
                break
        if not targets:
            return []

        alerts = []
        for expiry in targets:
            dte = (date.fromisoformat(expiry) - today).days
            try:
                chain = t.option_chain(expiry)
            except Exception:
                continue

            for opt_type, df in [("call", chain.calls), ("put", chain.puts)]:
                if df.empty:
                    continue
                for _, row in df.iterrows():
                    volume = int(row.get("volume") or 0)
                    if volume < MIN_VOLUME:
                        continue

                    oi = int(row.get("openInterest") or 0)
                    bid = float(row.get("bid") or 0)
                    ask = float(row.get("ask") or 0)
                    last = float(row.get("lastPrice") or 0)
                    mid = round((bid + ask) / 2, 2) if bid > 0 else last
                    if mid <= 0:
                        continue

                    notional = round(volume * mid * 100)
                    if notional < MIN_NOTIONAL:
                        continue

                    # vol_oi_ratio: cap at 99 when OI=0 (brand-new contract, not a ratio)
                    is_new_contract = oi == 0
                    vol_oi_ratio = round(volume / oi, 1) if oi > 0 else 99.0

                    # Skip normal activity — only flag when vol clearly outpaces OI
                    if vol_oi_ratio < MIN_VOL_OI_RATIO and oi >= 500:
                        continue

                    strike = float(row["strike"])
                    if opt_type == "call":
                        pct_otm = round((strike - price) / price * 100, 1)
                    else:
                        pct_otm = round((price - strike) / price * 100, 1)

                    alerts.append({
                        "ticker": ticker,
                        "price": round(price, 2),
                        "option_type": opt_type,
                        "strike": strike,
                        "expiry": expiry,
                        "dte": dte,
                        "volume": volume,
                        "open_interest": oi,
                        "vol_oi_ratio": vol_oi_ratio,
                        "is_new_contract": is_new_contract,
                        "mid_premium": mid,
                        "notional": notional,
                        "pct_otm": pct_otm,
                        "sentiment": "bullish" if opt_type == "call" else "bearish",
                        "earnings_context": earnings_ctx,
                    })

        alerts.sort(key=lambda x: x["notional"], reverse=True)
        return alerts[:MAX_ALERTS_PER_TICKER]
    except Exception as e:
        logger.debug("flow scan failed for %s: %s", ticker, e)
        return []


def run_flow_scan() -> dict:
    """Scan the options universe and return AI-interpreted unusual flow alerts."""
    from services.claude_analyst import ClaudeAnalyst

    all_alerts: list[dict] = []

    # Shuffle so different tickers surface first each scan (avoids rate-limit bias)
    universe = FLOW_UNIVERSE[:]
    random.shuffle(universe)

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_fetch_ticker_flow, t): t for t in universe}
        for fut in as_completed(futures, timeout=90):
            try:
                all_alerts.extend(fut.result(timeout=25))
            except Exception:
                pass

    if not all_alerts:
        return {
            "alerts": [],
            "tickers_scanned": len(FLOW_UNIVERSE),
            "total_alerts_found": 0,
            "error": "No unusual options flow detected. Market may be closed or activity is within normal ranges.",
        }

    # Sort by notional, deduplicate
    all_alerts.sort(key=lambda x: x["notional"], reverse=True)
    seen: set = set()
    deduped = []
    for a in all_alerts:
        key = (a["ticker"], a["option_type"], a["strike"], a["expiry"])
        if key not in seen:
            seen.add(key)
            deduped.append(a)
    top = deduped[:20]

    call_notional = sum(a["notional"] for a in all_alerts if a["option_type"] == "call")
    put_notional = sum(a["notional"] for a in all_alerts if a["option_type"] == "put")
    total_notional = call_notional + put_notional
    sentiment_ratio = round(call_notional / total_notional * 100) if total_notional > 0 else 50
    overall = "bullish" if sentiment_ratio > 55 else ("bearish" if sentiment_ratio < 45 else "neutral")

    analyst = ClaudeAnalyst()
    interpreted = analyst.interpret_options_flow(top, sentiment_ratio, overall)

    return {
        "alerts": interpreted,
        "tickers_scanned": len(FLOW_UNIVERSE),
        "total_alerts_found": len(all_alerts),
        "call_notional": call_notional,
        "put_notional": put_notional,
        "sentiment_ratio": sentiment_ratio,
        "overall_sentiment": overall,
    }
