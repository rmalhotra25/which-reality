"""
Options Flow Scanner — detects unusual activity using yfinance options chains.

For each ticker in the universe:
  1. Fetch the nearest 2 expiry dates via yfinance
  2. For each expiry, scan calls and puts for vol/OI anomalies
  3. Compute notional premium (volume × mid × 100)
  4. Flag contracts where vol/OI ≥ 2x with meaningful volume
  5. Optionally enrich with Polygon Greeks if available
  6. Pass top alerts to Claude for interpretation
"""
import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

# Most liquid US equity options — highest volume, tightest spreads
FLOW_UNIVERSE = [
    # ETFs first — highest options volume, most reliable yfinance data
    "SPY", "QQQ", "IWM", "SOXL", "TQQQ", "GLD",
    # Mega-cap tech
    "AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA",
    # Semiconductors
    "AMD", "AVGO", "MU",
    # High-IV momentum
    "PLTR", "COIN", "MSTR", "HOOD",
    # Financials
    "JPM", "GS", "BAC",
    # Other liquid names
    "NFLX", "UBER", "CRWD", "NOW",
    # Biotech
    "LLY", "MRNA",
]

MIN_VOLUME = 200
MIN_VOL_OI_RATIO = 2.0
MIN_NOTIONAL = 10_000
MAX_ALERTS_PER_TICKER = 2


def _earnings_context(ticker: str) -> str | None:
    try:
        cal = yf.Ticker(ticker).calendar
        if not isinstance(cal, dict):
            return None
        ed_raw = cal.get("Earnings Date")
        if ed_raw is None:
            return None
        if hasattr(ed_raw, "__iter__") and not isinstance(ed_raw, str):
            ed_list = [d for d in ed_raw if d is not None]
            ed_raw = ed_list[0] if ed_list else None
        if ed_raw is None:
            return None
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
    """Return unusual flow alerts for a single ticker using yfinance options chains."""
    try:
        t = yf.Ticker(ticker)

        # Current price
        price = None
        try:
            price = float(t.fast_info.last_price or 0)
        except Exception:
            pass
        if not price or price <= 0:
            return []

        # Available expiry dates — scan nearest 2
        expiries = t.options
        if not expiries:
            return []
        expiries_to_scan = expiries[:2]

        earnings_ctx = _earnings_context(ticker)
        today = date.today()
        alerts = []

        for expiry_str in expiries_to_scan:
            try:
                chain = t.option_chain(expiry_str)
            except Exception:
                continue

            expiry_dt = date.fromisoformat(expiry_str)
            dte = (expiry_dt - today).days

            for opt_type, df in [("call", chain.calls), ("put", chain.puts)]:
                if df is None or df.empty:
                    continue
                for _, row in df.iterrows():
                    try:
                        strike = float(row.get("strike") or 0)
                        if strike <= 0:
                            continue

                        volume = int(row.get("volume") or 0)
                        if volume < MIN_VOLUME:
                            continue

                        oi = int(row.get("openInterest") or 0)
                        vol_oi_ratio = round(volume / oi, 1) if oi > 0 else 99.0
                        is_new_contract = oi == 0

                        if vol_oi_ratio < MIN_VOL_OI_RATIO and oi >= 500:
                            continue

                        bid = float(row.get("bid") or 0)
                        ask = float(row.get("ask") or 0)
                        mid = round((bid + ask) / 2, 2) if bid > 0 else float(row.get("lastPrice") or 0)
                        if mid <= 0:
                            continue

                        notional = round(volume * mid * 100)
                        if notional < MIN_NOTIONAL:
                            continue

                        iv_pct = round(float(row.get("impliedVolatility") or 0) * 100, 1) or None

                        if opt_type == "call":
                            pct_otm = round((strike - price) / price * 100, 1)
                            breakeven = round(strike + mid, 2)
                            pct_move_needed = round((breakeven - price) / price * 100, 1)
                        else:
                            pct_otm = round((price - strike) / price * 100, 1)
                            breakeven = round(strike - mid, 2)
                            pct_move_needed = round((price - breakeven) / price * 100, 1)

                        alerts.append({
                            "ticker": ticker,
                            "price": round(price, 2),
                            "option_type": opt_type,
                            "strike": strike,
                            "expiry": expiry_str,
                            "dte": dte,
                            "volume": volume,
                            "open_interest": oi,
                            "vol_oi_ratio": vol_oi_ratio,
                            "is_new_contract": is_new_contract,
                            "mid_premium": mid,
                            "bid": bid,
                            "ask": ask,
                            "notional": notional,
                            "pct_otm": pct_otm,
                            "sentiment": "bullish" if opt_type == "call" else "bearish",
                            "earnings_context": earnings_ctx,
                            "breakeven": breakeven,
                            "pct_move_needed": pct_move_needed,
                            "iv_pct": iv_pct,
                            "hv_pct": None,
                            "iv_hv_ratio": None,
                            "premium_rating": None,
                            "delta": None,
                            "gamma": None,
                            "theta": None,
                            "vega": None,
                        })
                    except Exception:
                        continue

        # Try to enrich top alerts with Polygon Greeks
        alerts.sort(key=lambda x: x["notional"], reverse=True)
        top = alerts[:MAX_ALERTS_PER_TICKER]
        for alert in top:
            try:
                from services.polygon_client import get_options_chain_snapshot
                snaps = get_options_chain_snapshot(
                    ticker, dte_max=alert["dte"] + 2,
                    contract_type=alert["option_type"],
                    near_price=price, strike_pct_range=0.05,
                )
                best = None
                for snap in snaps:
                    if not snap.details:
                        continue
                    if abs(float(snap.details.strike_price or 0) - alert["strike"]) < 0.01:
                        best = snap
                        break
                if best and best.greeks:
                    alert["delta"] = round(float(best.greeks.delta), 2) if best.greeks.delta is not None else None
                    alert["gamma"] = round(float(best.greeks.gamma), 4) if best.greeks.gamma is not None else None
                    alert["theta"] = round(float(best.greeks.theta), 2) if best.greeks.theta is not None else None
                    alert["vega"] = round(float(best.greeks.vega), 2) if best.greeks.vega is not None else None
                if best and best.implied_volatility:
                    alert["iv_pct"] = round(float(best.implied_volatility) * 100, 1)
            except Exception:
                pass

        logger.info("flow scan %s: %d alerts from %d expiries", ticker, len(top), len(expiries_to_scan))
        return top

    except Exception as e:
        logger.warning("flow scan failed for %s: %s", ticker, e)
        return []


def run_flow_scan() -> dict:
    """Scan the options universe and return AI-interpreted unusual flow alerts."""
    from services.claude_analyst import ClaudeAnalyst

    all_alerts: list[dict] = []

    universe = FLOW_UNIVERSE[:]
    random.shuffle(universe)

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_fetch_ticker_flow, t): t for t in universe}
        try:
            for fut in as_completed(futures, timeout=90):
                try:
                    all_alerts.extend(fut.result(timeout=20))
                except Exception:
                    pass
        except Exception:
            # Timeout — use whatever results came in before the deadline
            for fut in futures:
                if fut.done():
                    try:
                        all_alerts.extend(fut.result())
                    except Exception:
                        pass

    if not all_alerts:
        return {
            "alerts": [],
            "tickers_scanned": len(FLOW_UNIVERSE),
            "total_alerts_found": 0,
            "error": "No unusual options flow detected. Market may be closed or activity is within normal ranges.",
        }

    all_alerts.sort(key=lambda x: x["notional"], reverse=True)
    seen: set = set()
    deduped = []
    for a in all_alerts:
        key = (a["ticker"], a["option_type"], a["strike"], a["expiry"])
        if key not in seen:
            seen.add(key)
            deduped.append(a)
    top = deduped[:20]

    # Enrich top alerts with catalyst data: today's % move + recent news
    seen_tickers: dict = {}
    for alert in top:
        ticker = alert["ticker"]
        if ticker not in seen_tickers:
            catalyst: dict = {"change_pct": None, "news": []}
            try:
                fi = yf.Ticker(ticker).fast_info
                prev = float(fi.previous_close or 0)
                curr = float(fi.last_price or 0)
                if prev > 0:
                    catalyst["change_pct"] = round((curr - prev) / prev * 100, 2)
            except Exception:
                pass
            try:
                from services.polygon_client import get_news
                raw = get_news(ticker, limit=3)
                catalyst["news"] = [n.get("title", "") for n in raw if n.get("title")]
            except Exception:
                pass
            seen_tickers[ticker] = catalyst
        alert["change_pct"] = seen_tickers[ticker]["change_pct"]
        alert["news"] = seen_tickers[ticker]["news"]

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
        "data_source": "yfinance options chains + Polygon Greeks",
    }
