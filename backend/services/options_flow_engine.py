"""
Options Flow Scanner — detects unusual activity using Polygon real-time options data.

For each ticker in the universe:
  1. Fetch real-time options chain snapshot via Polygon (Greeks, IV, bid/ask, volume, OI)
  2. Fetch earnings date context via yfinance calendar
  3. Scan every call and put for abnormal volume vs open interest
  4. Compute notional premium (volume × mid × 100)
  5. Flag contracts where vol/OI ≥ 3x or brand-new OI
  6. Pass top alerts + earnings/Greek context to Claude for interpretation
"""
import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

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


def _earnings_context(ticker: str) -> str | None:
    """Return a short string describing earnings proximity, or None."""
    try:
        t = yf.Ticker(ticker)
        cal = t.calendar
        if cal is None:
            return None
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


def _compute_hv(ticker: str) -> float | None:
    """30-day annualised historical volatility — used for IV/HV richness comparison."""
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="40d", interval="1d")
        closes = hist["Close"].dropna()
        if len(closes) < 10:
            return None
        returns = closes.pct_change().dropna()
        hv = float(returns.std() * (252 ** 0.5))
        return round(hv * 100, 1) if hv > 0 else None
    except Exception:
        return None


def _fetch_ticker_flow(ticker: str) -> list[dict]:
    """Return unusual flow alerts for a single ticker using Polygon real-time data."""
    time.sleep(random.uniform(0.2, 0.8))
    try:
        from services.polygon_client import get_options_chain_snapshot
        snapshots = get_options_chain_snapshot(ticker, dte_max=45)
        if not snapshots:
            logger.info("flow scan %s: no snapshots returned", ticker)
            return []

        today = date.today()

        # Try to get underlying price from snapshot first, fall back to yfinance
        underlying_price = None
        for snap in snapshots:
            if snap.underlying_asset and snap.underlying_asset.price:
                underlying_price = float(snap.underlying_asset.price)
                break
        if not underlying_price or underlying_price <= 0:
            try:
                fi = yf.Ticker(ticker).fast_info
                underlying_price = float(fi.last_price or 0)
            except Exception:
                pass
        if not underlying_price or underlying_price <= 0:
            logger.warning("flow scan %s: could not get underlying price, skipping", ticker)
            return []

        logger.info("flow scan %s: %d snapshots, price=%.2f", ticker, len(snapshots), underlying_price)

        earnings_ctx = _earnings_context(ticker)
        hv_pct = _compute_hv(ticker)

        alerts = []
        filtered_vol = filtered_mid = filtered_notional = filtered_ratio = 0
        for snap in snapshots:
            try:
                details = snap.details
                if not details:
                    continue

                opt_type = (details.contract_type or "").lower()
                if opt_type not in ("call", "put"):
                    continue

                strike = float(details.strike_price or 0)
                expiry = str(details.expiration_date or "")
                if not strike or not expiry:
                    continue

                dte = (date.fromisoformat(expiry) - today).days
                if dte < 1 or dte > 45:
                    continue

                volume = int(snap.day.volume or 0) if snap.day else 0
                if volume < MIN_VOLUME:
                    filtered_vol += 1
                    continue

                oi = int(snap.open_interest or 0)

                # Real-time quote from Polygon
                bid = ask = mid = 0.0
                if snap.last_quote:
                    bid = float(snap.last_quote.bid or 0)
                    ask = float(snap.last_quote.ask or 0)
                    mp = snap.last_quote.midpoint
                    mid = float(mp) if mp else (round((bid + ask) / 2, 2) if bid > 0 else 0.0)
                if mid <= 0 and snap.last_trade:
                    mid = float(snap.last_trade.price or 0)
                if mid <= 0:
                    filtered_mid += 1
                    continue

                notional = round(volume * mid * 100)
                if notional < MIN_NOTIONAL:
                    filtered_notional += 1
                    continue

                is_new_contract = oi == 0
                vol_oi_ratio = round(volume / oi, 1) if oi > 0 else 99.0
                if vol_oi_ratio < MIN_VOL_OI_RATIO and oi >= 500:
                    filtered_ratio += 1
                    continue

                if opt_type == "call":
                    pct_otm = round((strike - underlying_price) / underlying_price * 100, 1)
                else:
                    pct_otm = round((underlying_price - strike) / underlying_price * 100, 1)

                # Real Greeks from Polygon
                delta = gamma = theta = vega = None
                if snap.greeks:
                    delta = round(float(snap.greeks.delta), 2) if snap.greeks.delta is not None else None
                    gamma = round(float(snap.greeks.gamma), 4) if snap.greeks.gamma is not None else None
                    theta = round(float(snap.greeks.theta), 2) if snap.greeks.theta is not None else None
                    vega = round(float(snap.greeks.vega), 2) if snap.greeks.vega is not None else None

                iv_pct = round(float(snap.implied_volatility) * 100, 1) if snap.implied_volatility else None

                # Premium richness: IV vs 30-day historical vol
                iv_hv_ratio = premium_rating = None
                if iv_pct and hv_pct and hv_pct > 0:
                    iv_hv_ratio = round(iv_pct / hv_pct, 2)
                    premium_rating = "RICH" if iv_hv_ratio > 1.5 else ("CHEAP" if iv_hv_ratio < 0.8 else "FAIR")

                if opt_type == "call":
                    breakeven = round(strike + mid, 2)
                    pct_move_needed = round((breakeven - underlying_price) / underlying_price * 100, 1)
                else:
                    breakeven = round(strike - mid, 2)
                    pct_move_needed = round((underlying_price - breakeven) / underlying_price * 100, 1)

                alerts.append({
                    "ticker": ticker,
                    "price": round(underlying_price, 2),
                    "option_type": opt_type,
                    "strike": strike,
                    "expiry": expiry,
                    "dte": dte,
                    "volume": volume,
                    "open_interest": oi,
                    "vol_oi_ratio": vol_oi_ratio,
                    "is_new_contract": is_new_contract,
                    "mid_premium": round(mid, 2),
                    "bid": round(bid, 2),
                    "ask": round(ask, 2),
                    "notional": notional,
                    "pct_otm": pct_otm,
                    "sentiment": "bullish" if opt_type == "call" else "bearish",
                    "earnings_context": earnings_ctx,
                    "breakeven": breakeven,
                    "pct_move_needed": pct_move_needed,
                    "iv_pct": iv_pct,
                    "hv_pct": hv_pct,
                    "iv_hv_ratio": iv_hv_ratio,
                    "premium_rating": premium_rating,
                    "delta": delta,
                    "gamma": gamma,
                    "theta": theta,
                    "vega": vega,
                })
            except Exception:
                continue

        logger.info(
            "flow scan %s: %d alerts found | filtered vol=%d mid=%d notional=%d ratio=%d",
            ticker, len(alerts), filtered_vol, filtered_mid, filtered_notional, filtered_ratio,
        )
        alerts.sort(key=lambda x: x["notional"], reverse=True)
        return alerts[:MAX_ALERTS_PER_TICKER]
    except Exception as e:
        logger.warning("flow scan failed for %s: %s", ticker, e)
        return []


def run_flow_scan() -> dict:
    """Scan the options universe and return AI-interpreted unusual flow alerts."""
    from services.claude_analyst import ClaudeAnalyst

    # Quick API connectivity check — bypass the exception-swallowing wrapper
    # so we surface the real error (missing key, wrong plan, 403, etc.)
    try:
        from datetime import timedelta
        from services.polygon_client import _client
        c = _client()
        today = date.today()
        params = {
            "expiration_date.gte": today.isoformat(),
            "expiration_date.lte": (today + timedelta(days=7)).isoformat(),
            "limit": 5,
        }
        list(c.list_snapshot_options_chain("SPY", params=params))
    except Exception as e:
        err = str(e)
        logger.warning("Polygon API connectivity check failed: %s", err)
        return {
            "alerts": [],
            "tickers_scanned": 0,
            "total_alerts_found": 0,
            "error": f"Polygon API error: {err}. Check that POLYGON_API_KEY is set correctly and the Options plan is active.",
        }

    all_alerts: list[dict] = []

    universe = FLOW_UNIVERSE[:]
    random.shuffle(universe)

    with ThreadPoolExecutor(max_workers=3) as pool:
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
        "data_source": "Polygon real-time options data",
    }
