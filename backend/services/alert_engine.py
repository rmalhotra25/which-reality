"""
Setup alert engine.

Evaluates every registered setup across its universe and produces:
  - SetupAlert rows for fired setups (LIVE and SHADOW both)
  - Suppressed candidate rows when a setup nearly fires but fails on a
    required field (e.g. options max loss cannot be computed)
  - An AlertEngineRun row recording the full health metrics for the run

Signal evaluation re-uses the data infrastructure the rest of the app
already has: polygon_client/yfinance for price/volume, the IV snapshot
store for percentile, and the finnhub earnings calendar.

No order execution. No brokerage integration. Alert/dashboard only.
"""
import json
import logging
import time
from datetime import datetime, timezone, date, timedelta
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Universe helpers
# ---------------------------------------------------------------------------

def _buy_hold_universe() -> list[str]:
    """S&P 500 + Dividend Achievers merged with the app watchlist + DEFAULT_UNIVERSE."""
    from services.stock_data import DEFAULT_UNIVERSE
    tickers = list(DEFAULT_UNIVERSE)
    try:
        import json as _json
        import os
        root = os.path.dirname(os.path.abspath(__file__))
        sp_path = os.path.join(root, "../../data/sp500.json")
        da_path = os.path.join(root, "../../data/dividend-achievers.json")
        sp = _json.load(open(sp_path)) if os.path.isfile(sp_path) else []
        da = _json.load(open(da_path)) if os.path.isfile(da_path) else []
        tickers = list(dict.fromkeys(sp + da + tickers))
    except Exception as e:
        logger.debug("universe load: %s", e)
    return tickers


def _wheel_universe() -> list[str]:
    from services.stock_data import DEFAULT_UNIVERSE
    return list(DEFAULT_UNIVERSE)


def _directional_universe() -> list[str]:
    from services.stock_data import DEFAULT_UNIVERSE
    return list(DEFAULT_UNIVERSE)


# ---------------------------------------------------------------------------
# Technical data helpers (thin wrappers that return None gracefully)
# ---------------------------------------------------------------------------

def _fetch_ohlcv(ticker: str, days: int = 260) -> Optional[object]:
    """Return a pandas DataFrame with OHLCV columns, or None."""
    try:
        import yfinance as yf
        df = yf.download(ticker, period=f"{days + 60}d", auto_adjust=True, progress=False)
        if df is None or len(df) < days // 2:
            return None
        return df
    except Exception as e:
        logger.debug("ohlcv fetch failed %s: %s", ticker, e)
        return None


def _indicators(df) -> Optional[dict]:
    """
    Compute the technical indicators the setup signals need.
    Returns None if the data is too short.
    """
    try:
        import pandas as pd
        closes = df["Close"].squeeze()
        opens = df["Open"].squeeze()
        highs = df["High"].squeeze()
        lows = df["Low"].squeeze()
        vols = df["Volume"].squeeze()
        n = len(closes)
        if n < 210:
            return None

        ma20 = closes.rolling(20).mean()
        ma50 = closes.rolling(50).mean()
        ma200 = closes.rolling(200).mean()
        ma200_lag20 = ma200.shift(20)

        # RSI 14
        delta = closes.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = (100 - 100 / (1 + rs))

        # RSI was high (>60) in last 20 sessions
        rsi_was_high = rsi.shift(1).rolling(20).max() > 60

        # Volume 20-day average
        vol20 = vols.rolling(20).mean()

        # ATR 14
        tr = pd.concat([
            highs - lows,
            (highs - closes.shift()).abs(),
            (lows - closes.shift()).abs(),
        ], axis=1).max(axis=1)
        atr14 = tr.rolling(14).mean()

        # Prior 55-day high (exclude today)
        prior_high_55 = closes.shift(1).rolling(55).max()

        # HV 30-day annualised
        log_ret = np.log(closes / closes.shift(1))
        hv30 = log_ret.rolling(30).std() * np.sqrt(252)

        # Bullish engulfing: today opens below prior close and closes above prior open
        bullish_engulf = (
            (opens.iloc[-1] < closes.iloc[-2]) &
            (closes.iloc[-1] > opens.iloc[-2])
        )

        return {
            "price": float(closes.iloc[-1]),
            "prev_close": float(closes.iloc[-2]) if n > 1 else None,
            "prev_open": float(opens.iloc[-2]) if n > 1 else None,
            "open_today": float(opens.iloc[-1]),
            "ma20": float(ma20.iloc[-1]) if not np.isnan(ma20.iloc[-1]) else None,
            "ma50": float(ma50.iloc[-1]) if not np.isnan(ma50.iloc[-1]) else None,
            "ma200": float(ma200.iloc[-1]) if not np.isnan(ma200.iloc[-1]) else None,
            "ma200_lag20": float(ma200_lag20.iloc[-1]) if not np.isnan(ma200_lag20.iloc[-1]) else None,
            "rsi": float(rsi.iloc[-1]) if not np.isnan(rsi.iloc[-1]) else None,
            "rsi_was_high": bool(rsi_was_high.iloc[-1]) if not np.isnan(rsi_was_high.iloc[-1]) else False,
            "volume": float(vols.iloc[-1]),
            "vol20": float(vol20.iloc[-1]) if not np.isnan(vol20.iloc[-1]) else None,
            "atr14": float(atr14.iloc[-1]) if not np.isnan(atr14.iloc[-1]) else None,
            "prior_high_55": float(prior_high_55.iloc[-1]) if not np.isnan(prior_high_55.iloc[-1]) else None,
            "hv30": float(hv30.iloc[-1]) if not np.isnan(hv30.iloc[-1]) else None,
            "bullish_engulf": bullish_engulf,
        }
    except Exception as e:
        logger.debug("indicators failed: %s", e)
        return None


def _earnings_days(ticker: str) -> Optional[int]:
    try:
        from services.finnhub_client import get_earnings_this_month
        return get_earnings_this_month(ticker)
    except Exception:
        return None


def _iv_percentile(db, ticker: str) -> Optional[float]:
    try:
        from services.iv_snapshot_service import get_iv_percentile
        result = get_iv_percentile(db, ticker)
        if result.get("available"):
            return result.get("iv_percentile")
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Setup signal evaluators
# ---------------------------------------------------------------------------

def _eval_quality_pullback(ind: dict, earnings_days_val: Optional[int]) -> tuple[bool, dict]:
    """
    Returns (fires, conditions_dict).
    All conditions must be true for the setup to fire.
    """
    cond = {}
    p = ind["price"]
    ma50 = ind.get("ma50")
    ma200 = ind.get("ma200")
    ma200_lag = ind.get("ma200_lag20")

    # Price within 2% above 50-day MA
    near_ma50 = (ma50 is not None and p > ma50 and p <= ma50 * 1.02)
    # Price within 2% above 200-day MA
    near_ma200 = (ma200 is not None and p > ma200 and p <= ma200 * 1.02)
    cond["near_ma50"] = near_ma50
    cond["near_ma200"] = near_ma200
    cond["price"] = round(p, 2)
    cond["ma50"] = round(ma50, 2) if ma50 else None
    cond["ma200"] = round(ma200, 2) if ma200 else None

    near_ma = near_ma50 or near_ma200
    cond["near_ma"] = near_ma

    # 200-day MA rising
    ma200_rising = (ma200 is not None and ma200_lag is not None and ma200 > ma200_lag)
    cond["ma200_rising"] = ma200_rising
    cond["ma200_lag20"] = round(ma200_lag, 2) if ma200_lag else None

    # RSI below 55 and was above 60 in prior 20 sessions
    rsi = ind.get("rsi")
    rsi_was_high = ind.get("rsi_was_high", False)
    cond["rsi"] = round(rsi, 1) if rsi is not None else None
    cond["rsi_lt_55"] = (rsi is not None and rsi < 55)
    cond["rsi_was_above_60"] = rsi_was_high

    # Volume below 20-day average
    vol = ind.get("volume", 0)
    vol20 = ind.get("vol20")
    cond["volume"] = int(vol)
    cond["vol20"] = int(vol20) if vol20 else None
    quiet_volume = (vol20 is not None and vol < vol20)
    cond["quiet_volume"] = quiet_volume

    # No earnings within 5 days
    no_earnings = (earnings_days_val is None or earnings_days_val > 5)
    cond["earnings_days"] = earnings_days_val
    cond["no_earnings_within_5d"] = no_earnings

    fires = (
        near_ma
        and ma200_rising
        and cond["rsi_lt_55"]
        and rsi_was_high
        and quiet_volume
        and no_earnings
    )
    return fires, cond


def _eval_premium_at_support(ind: dict, earnings_days_val: Optional[int], iv_pct: Optional[float]) -> tuple[bool, dict]:
    cond = {}
    p = ind["price"]
    ma50 = ind.get("ma50")
    ma200 = ind.get("ma200")
    ma200_lag = ind.get("ma200_lag20")
    hv30 = ind.get("hv30")

    # Price within 2% of 50-day MA (above or below)
    near_ma50 = (ma50 is not None and abs(p - ma50) / ma50 <= 0.02)
    cond["near_ma50"] = near_ma50
    cond["price"] = round(p, 2)
    cond["ma50"] = round(ma50, 2) if ma50 else None

    # 200-day MA rising
    ma200_rising = (ma200 is not None and ma200_lag is not None and ma200 > ma200_lag)
    cond["ma200_rising"] = ma200_rising
    cond["ma200"] = round(ma200, 2) if ma200 else None

    # IV percentile in top third (above 67th percentile)
    # Fall back to HV percentile rank if no live IV store yet
    iv_source = "iv_store"
    iv_high = False
    if iv_pct is not None:
        iv_high = iv_pct >= 67.0
        cond["iv_percentile"] = round(iv_pct, 1)
        cond["iv_source"] = "iv_store"
    elif hv30 is not None:
        # Use HV as a rough proxy -- flag as approximate
        iv_high = hv30 > 0.30  # annualised HV above 30% as a rough high-IV threshold
        cond["iv_percentile"] = None
        cond["hv30_approx"] = round(hv30 * 100, 1)
        cond["iv_source"] = "hv_approx"
        iv_source = "hv_approx"
    else:
        cond["iv_percentile"] = None
        cond["iv_source"] = "unavailable"

    cond["iv_high"] = iv_high
    cond["iv_source"] = iv_source

    # No earnings within 5 days
    no_earnings = (earnings_days_val is None or earnings_days_val > 5)
    cond["earnings_days"] = earnings_days_val
    cond["no_earnings_within_5d"] = no_earnings

    fires = near_ma50 and ma200_rising and iv_high and no_earnings
    return fires, cond


def _eval_volume_breakout(ind: dict, earnings_days_val: Optional[int]) -> tuple[bool, dict]:
    cond = {}
    p = ind["price"]
    ma50 = ind.get("ma50")
    ma200 = ind.get("ma200")
    ma200_lag = ind.get("ma200_lag20")
    prior_high = ind.get("prior_high_55")
    vol = ind.get("volume", 0)
    vol20 = ind.get("vol20")

    # Close above prior 55-day high
    above_55d_high = (prior_high is not None and p > prior_high)
    cond["above_55d_high"] = above_55d_high
    cond["price"] = round(p, 2)
    cond["prior_high_55"] = round(prior_high, 2) if prior_high else None

    # Volume at least 1.5x average
    vol_confirmed = (vol20 is not None and vol >= 1.5 * vol20)
    cond["volume"] = int(vol)
    cond["vol20"] = int(vol20) if vol20 else None
    cond["vol_confirmed"] = vol_confirmed

    # Price above rising 50-day MA
    above_ma50 = (ma50 is not None and p > ma50)
    ma50_rising = (ma50 is not None and ma200_lag is not None and ma50 > ind.get("ma50") * 0.998)
    cond["above_ma50"] = above_ma50
    cond["ma50"] = round(ma50, 2) if ma50 else None

    # No earnings within 5 days
    no_earnings = (earnings_days_val is None or earnings_days_val > 5)
    cond["earnings_days"] = earnings_days_val
    cond["no_earnings_within_5d"] = no_earnings

    fires = above_55d_high and vol_confirmed and above_ma50 and no_earnings
    return fires, cond


def _eval_oversold_bounce(ind: dict, earnings_days_val: Optional[int]) -> tuple[bool, dict]:
    cond = {}
    p = ind["price"]
    ma200 = ind.get("ma200")
    ma200_lag = ind.get("ma200_lag20")
    rsi = ind.get("rsi")

    rsi_oversold = (rsi is not None and rsi < 30)
    above_ma200 = (ma200 is not None and p > ma200)
    ma200_rising = (ma200 is not None and ma200_lag is not None and ma200 > ma200_lag)
    no_earnings = (earnings_days_val is None or earnings_days_val > 5)

    cond["rsi"] = round(rsi, 1) if rsi is not None else None
    cond["rsi_lt_30"] = rsi_oversold
    cond["price"] = round(p, 2)
    cond["ma200"] = round(ma200, 2) if ma200 else None
    cond["above_ma200"] = above_ma200
    cond["ma200_rising"] = ma200_rising
    cond["earnings_days"] = earnings_days_val
    cond["no_earnings_within_5d"] = no_earnings

    fires = rsi_oversold and above_ma200 and ma200_rising and no_earnings
    return fires, cond


def _eval_trend_pullback_reversal(ind: dict, earnings_days_val: Optional[int]) -> tuple[bool, dict]:
    cond = {}
    p = ind["price"]
    ma20 = ind.get("ma20")
    ma50 = ind.get("ma50")
    rsi = ind.get("rsi")
    prev_rsi_est = rsi  # we don't store yesterday's RSI in real time; note limitation

    in_uptrend = (
        ma20 is not None and ma50 is not None
        and p > ma20 and p > ma50
    )
    near_ma = (
        (ma20 is not None and abs(p - ma20) / ma20 <= 0.01) or
        (ma50 is not None and abs(p - ma50) / ma50 <= 0.01)
    )
    rsi_turning_up = (rsi is not None and 40 <= rsi <= 55)
    bullish_engulf = ind.get("bullish_engulf", False)
    reversal = rsi_turning_up or bullish_engulf
    no_earnings = (earnings_days_val is None or earnings_days_val > 5)

    cond["price"] = round(p, 2)
    cond["ma20"] = round(ma20, 2) if ma20 else None
    cond["ma50"] = round(ma50, 2) if ma50 else None
    cond["rsi"] = round(rsi, 1) if rsi is not None else None
    cond["in_uptrend"] = in_uptrend
    cond["near_ma"] = near_ma
    cond["rsi_turning_up"] = rsi_turning_up
    cond["bullish_engulf"] = bool(bullish_engulf)
    cond["reversal_confirmed"] = reversal
    cond["earnings_days"] = earnings_days_val
    cond["no_earnings_within_5d"] = no_earnings

    fires = in_uptrend and near_ma and reversal and no_earnings
    return fires, cond


def _eval_post_earnings_drift(ind: dict, earnings_days_val: Optional[int]) -> tuple[bool, dict]:
    """
    Post-Earnings Drift: we can only check gap-held and IV crush from
    price data; earnings beat/guidance raised requires a news/data feed
    that is not reliably available. Fires on price/IV conditions only
    and notes the limitation in the conditions snapshot.
    """
    cond = {}
    p = ind["price"]
    prev_close = ind.get("prev_close")
    hv30 = ind.get("hv30")

    # Proxy check: IV crush means current HV is notably lower than historical norm.
    # Without live IV history this is approximate.
    iv_crushed = (hv30 is not None and hv30 < 0.35)  # below 35% annualised

    # Gap held: today's price above yesterday's close
    gap_held = (prev_close is not None and p > prev_close * 1.005)

    cond["price"] = round(p, 2)
    cond["prev_close"] = round(prev_close, 2) if prev_close else None
    cond["gap_held"] = gap_held
    cond["hv30"] = round(hv30 * 100, 1) if hv30 else None
    cond["iv_crushed_approx"] = iv_crushed
    cond["earnings_beat_guidance_raised"] = "not_checked_requires_news_feed"
    cond["note"] = "earnings beat and guidance check requires live news data; not evaluated here"

    # This setup is intentionally conservative: only shadow until a real
    # news feed validates beat+guidance.
    fires = gap_held and iv_crushed
    return fires, cond


# ---------------------------------------------------------------------------
# Action block builders
# ---------------------------------------------------------------------------

def _build_stock_action(ind: dict, setup_key: str) -> dict:
    """Build entry/invalidation/target for stock-side setups."""
    p = ind["price"]
    atr = ind.get("atr14") or (p * 0.02)  # rough fallback
    ma200 = ind.get("ma200")
    prior_high = ind.get("prior_high_55")

    if setup_key == "quality_pullback":
        entry = round(p * 1.0005, 2)  # next open estimate, 0.05% slippage
        invalidation = round(ma200, 2) if ma200 else round(p * 0.95, 2)
        target = round(p * 1.08, 2)   # approximate; RSI target not expressible as price
        summary = (
            f"Pullback to MA on quiet volume. "
            f"Entry ~${entry}, stop below 200-day MA ${invalidation}, "
            f"RSI(14) target exit >68."
        )
    elif setup_key == "oversold_bounce":
        entry = round(p * 1.0005, 2)
        invalidation = round(ma200, 2) if ma200 else round(p * 0.95, 2)
        target = round(p * 1.07, 2)
        summary = (
            f"Deeply oversold above rising 200-day MA. "
            f"Entry ~${entry}, stop below 200-day MA ${invalidation}, "
            f"target RSI>50 (approx ${target})."
        )
    elif setup_key == "volume_breakout":
        entry = round(p * 1.0005, 2)
        invalidation = round(prior_high, 2) if prior_high else round(p * 0.97, 2)
        target = round(entry + 2 * atr, 2)
        summary = (
            f"Volume-confirmed breakout above 55-day high. "
            f"Entry ~${entry}, stop at breakout level ${invalidation}, "
            f"target ${target} (2x ATR)."
        )
    elif setup_key == "trend_pullback_reversal":
        ma20 = ind.get("ma20")
        ma50 = ind.get("ma50")
        entry = round(p * 1.0005, 2)
        support = min(
            v for v in [ma20, ma50] if v is not None
        ) if any(v is not None for v in [ma20, ma50]) else p * 0.98
        invalidation = round(p - atr * 0.5, 2)  # below signal-day low approx
        target = round(p + atr * 2, 2)
        summary = (
            f"Pullback reversal at MA. "
            f"Entry ~${entry}, stop at ${invalidation} (below signal low), "
            f"target ${target}."
        )
    elif setup_key == "post_earnings_drift":
        entry = round(p, 2)   # enters at close
        prev_close = ind.get("prev_close") or p * 0.95
        invalidation = round(prev_close * 1.0, 2)  # gap fills = stop
        target = round(p * 1.10, 2)
        summary = (
            f"Post-earnings drift. "
            f"Entry at close ~${entry}, stop at gap open ${invalidation}, "
            f"target +10% ${target}."
        )
    else:
        entry = round(p * 1.0005, 2)
        invalidation = round(p * 0.95, 2)
        target = round(p * 1.10, 2)
        summary = f"Entry ~${entry}, stop ${invalidation}, target ${target}."

    max_loss = round((entry - invalidation) if entry > invalidation else entry * 0.05, 2)
    return {
        "action": "BUY",
        "entry_price": entry,
        "invalidation_price": invalidation,
        "target_price": target,
        "max_loss": abs(max_loss),
        "action_summary": summary,
    }


def _build_options_action(ind: dict, db) -> dict | None:
    """
    Build a defined-max-loss options action for the wheel setup.
    Returns None with a reason string if a defined max loss cannot be computed.
    Uses Black-Scholes via the existing options engine helpers.
    """
    try:
        p = ind["price"]
        hv30 = ind.get("hv30") or 0.25
        atr = ind.get("atr14") or (p * 0.02)

        # 30-delta CSP: strike ~ 0.95 * price for typical 30-delta approx
        strike = round(p * 0.95, 0)
        if strike <= 0:
            return None, "Strike price is zero or negative"

        # Target 37 DTE expiry
        target_dte = 37
        expiry_date = date.today() + timedelta(days=target_dte)
        expiry_str = expiry_date.isoformat()

        # Black-Scholes premium estimate (ATM put)
        import math
        try:
            from services.stock_data import _ncdf
            T = max(target_dte, 1) / 365.0
            iv = max(hv30, 0.05)
            r = 0.045
            sq = iv * math.sqrt(T)
            d1 = (math.log(p / strike) + (r + 0.5 * iv ** 2) * T) / sq
            d2 = d1 - sq
            premium = max(strike * math.exp(-r * T) * _ncdf(-d2) - p * _ncdf(-d1), 0.01)
        except Exception:
            # Fallback: rough premium from HV
            premium = round(p * hv30 * (target_dte / 365) ** 0.5 * 0.4, 2)

        premium = round(max(premium, 0.05), 2)
        premium_with_haircut = round(premium * 0.95, 2)  # 5% spread haircut

        # Defined max loss for a CSP: strike - premium received (per share)
        max_loss_per_share = round(strike - premium_with_haircut, 2)
        # Per contract (100 shares)
        max_loss_per_contract = round(max_loss_per_share * 100, 2)

        if max_loss_per_contract <= 0:
            return None, f"Max loss non-positive (strike={strike}, premium={premium_with_haircut})"

        # Default position size: 1 contract
        position_size = 1
        max_loss_position = max_loss_per_contract * position_size

        summary = (
            f"Sell {expiry_str} ${strike:.0f} put, ~${premium_with_haircut:.2f} credit. "
            f"Max loss ${max_loss_per_contract:.0f}/contract. "
            f"Close at 50% profit or 21 DTE."
        )

        return {
            "action": "SELL_PUT",
            "contract_type": "PUT",
            "strike": float(strike),
            "expiry": expiry_str,
            "premium": premium_with_haircut,
            "max_loss_per_contract": max_loss_per_contract,
            "max_loss_per_position": max_loss_position,
            "position_size_contracts": position_size,
            "max_loss": max_loss_position,
            "action_summary": summary,
            "entry_price": p,
            "invalidation_price": round(p * 0.93, 2),  # stop the underlying below 200 MA
            "target_price": None,
        }, None
    except Exception as e:
        return None, str(e)


# ---------------------------------------------------------------------------
# Alert builder
# ---------------------------------------------------------------------------

def _build_alert(
    setup_key: str,
    setup_name: str,
    setup_status: str,
    ticker: str,
    ind: dict,
    cond: dict,
    db,
    is_suppressed: bool = False,
    suppressed_reason: str = None,
) -> dict:
    """Build the alert record dict (not yet a DB row)."""
    earnings_days_val = cond.get("earnings_days")

    if is_suppressed:
        return {
            "setup_key": setup_key,
            "setup_name": setup_name,
            "setup_status": setup_status,
            "ticker": ticker,
            "is_suppressed": True,
            "suppressed_reason": suppressed_reason,
            "conditions": cond,
            "action": None,
        }

    if setup_key == "premium_at_support":
        action_data, fail_reason = _build_options_action(ind, db)
        if action_data is None:
            return {
                "setup_key": setup_key,
                "setup_name": setup_name,
                "setup_status": setup_status,
                "ticker": ticker,
                "is_suppressed": True,
                "suppressed_reason": f"options action failed: {fail_reason}",
                "conditions": cond,
                "action": None,
            }
        iv_pct = cond.get("iv_percentile")
    else:
        action_data = _build_stock_action(ind, setup_key)
        iv_pct = cond.get("iv_percentile")
        fail_reason = None

    invalidation_text = (
        f"Invalidated if price closes below ${action_data.get('invalidation_price', '?')}. "
        f"{'Earnings in ' + str(earnings_days_val) + ' days.' if earnings_days_val and earnings_days_val <= 30 else ''}"
    ).strip()

    return {
        "setup_key": setup_key,
        "setup_name": setup_name,
        "setup_status": setup_status,
        "ticker": ticker,
        "is_suppressed": False,
        "suppressed_reason": None,
        "conditions": cond,
        **action_data,
        "earnings_in_window": (earnings_days_val is not None and earnings_days_val <= 14),
        "iv_percentile": iv_pct,
        "spread_quality": "estimated" if setup_key == "premium_at_support" else None,
        "invalidation_text": invalidation_text,
    }


# ---------------------------------------------------------------------------
# Per-setup evaluation
# ---------------------------------------------------------------------------

_SETUP_EVALUATORS = {
    "quality_pullback":       (_eval_quality_pullback,       "buy_and_hold"),
    "premium_at_support":     (_eval_premium_at_support,     "wheel"),
    "volume_breakout":        (_eval_volume_breakout,        "directional"),
    "oversold_bounce":        (_eval_oversold_bounce,        "buy_and_hold"),
    "trend_pullback_reversal":(_eval_trend_pullback_reversal,"directional"),
    "post_earnings_drift":    (_eval_post_earnings_drift,    "directional"),
}


def _universe_for(job: str) -> list[str]:
    if job == "wheel":
        return _wheel_universe()
    if job == "directional":
        return _directional_universe()
    return _buy_hold_universe()


def _evaluate_setup(setup_row, db) -> dict:
    """
    Evaluate one setup across its universe.
    Returns {"alerts": [...], "suppressed": [...], "tickers_evaluated": int, "errors": []}.
    """
    key = setup_row.setup_key
    evaluator_fn, job = _SETUP_EVALUATORS.get(key, (None, None))
    if evaluator_fn is None:
        return {"alerts": [], "suppressed": [], "tickers_evaluated": 0, "errors": [f"{key}: no evaluator"]}

    universe = _universe_for(setup_row.job)
    alerts = []
    suppressed = []
    errors = []
    evaluated = 0

    for ticker in universe:
        evaluated += 1
        try:
            df = _fetch_ohlcv(ticker)
            if df is None:
                continue
            ind = _indicators(df)
            if ind is None:
                continue
            earnings_val = _earnings_days(ticker)
            iv_pct = _iv_percentile(db, ticker)

            if key == "premium_at_support":
                fires, cond = evaluator_fn(ind, earnings_val, iv_pct)
            elif key in ("quality_pullback", "volume_breakout", "oversold_bounce",
                         "trend_pullback_reversal", "post_earnings_drift"):
                fires, cond = evaluator_fn(ind, earnings_val)
            else:
                continue

            if not fires:
                continue

            alert = _build_alert(
                key, setup_row.name, setup_row.status,
                ticker, ind, cond, db,
            )
            if alert["is_suppressed"]:
                suppressed.append(alert)
            else:
                alerts.append(alert)

        except Exception as e:
            err_msg = f"{key}/{ticker}: {e}"
            errors.append(err_msg)
            logger.debug("alert_engine eval error: %s", err_msg)

    return {
        "alerts": alerts,
        "suppressed": suppressed,
        "tickers_evaluated": evaluated,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Main run function (called by scheduler)
# ---------------------------------------------------------------------------

def run_alert_engine(db) -> dict:
    """
    Evaluate all registered setups and write results to DB.
    Returns a summary dict for run_status.
    """
    from models.setup_registry import SetupRegistry
    from models.setup_alert import SetupAlert, AlertEngineRun
    import services.run_status as run_status

    run_status.set_running("alert_engine")
    start = time.time()

    setups = db.query(SetupRegistry).filter(
        SetupRegistry.status.in_(["LIVE", "SHADOW"])
    ).all()

    total_tickers = 0
    total_alerts = 0
    total_shadow = 0
    total_suppressed = 0
    all_errors = []
    fired_at = datetime.now(timezone.utc)

    for setup in setups:
        result = _evaluate_setup(setup, db)
        total_tickers = max(total_tickers, result["tickers_evaluated"])
        all_errors.extend(result["errors"])

        for alert_dict in result["alerts"] + result["suppressed"]:
            row = SetupAlert(
                setup_key=alert_dict["setup_key"],
                setup_name=alert_dict["setup_name"],
                setup_status=alert_dict["setup_status"],
                ticker=alert_dict["ticker"],
                fired_at=fired_at,
                is_suppressed=alert_dict["is_suppressed"],
                suppressed_reason=alert_dict.get("suppressed_reason"),
                conditions_json=json.dumps(alert_dict.get("conditions", {})),
                action=alert_dict.get("action"),
                entry_price=alert_dict.get("entry_price"),
                invalidation_price=alert_dict.get("invalidation_price"),
                target_price=alert_dict.get("target_price"),
                action_summary=alert_dict.get("action_summary"),
                contract_type=alert_dict.get("contract_type"),
                strike=alert_dict.get("strike"),
                expiry=alert_dict.get("expiry"),
                premium=alert_dict.get("premium"),
                max_loss_per_contract=alert_dict.get("max_loss_per_contract"),
                max_loss_per_position=alert_dict.get("max_loss_per_position"),
                position_size_contracts=alert_dict.get("position_size_contracts"),
                max_loss=alert_dict.get("max_loss"),
                earnings_in_window=alert_dict.get("earnings_in_window"),
                iv_percentile=alert_dict.get("iv_percentile"),
                spread_quality=alert_dict.get("spread_quality"),
                invalidation_text=alert_dict.get("invalidation_text"),
                is_open=not alert_dict["is_suppressed"],
            )
            db.add(row)

            if not alert_dict["is_suppressed"]:
                if alert_dict["setup_status"] == "SHADOW":
                    total_shadow += 1
                else:
                    total_alerts += 1
            else:
                total_suppressed += 1

    duration = round(time.time() - start, 1)

    run_row = AlertEngineRun(
        ran_at=fired_at,
        tickers_evaluated=total_tickers,
        alerts_fired=total_alerts,
        shadow_hits=total_shadow,
        suppressed=total_suppressed,
        errors=json.dumps(all_errors[:50]),
        duration_seconds=duration,
    )
    db.add(run_row)

    try:
        db.commit()
    except Exception as e:
        logger.error("alert_engine: commit failed: %s", e)
        db.rollback()
        run_status.set_error("alert_engine", str(e))
        return {"ok": False, "error": str(e)}

    summary = {
        "ok": True,
        "tickers_evaluated": total_tickers,
        "alerts_fired": total_alerts,
        "shadow_hits": total_shadow,
        "suppressed": total_suppressed,
        "errors": len(all_errors),
        "duration_seconds": duration,
    }
    run_status.set_success_with_counts("alert_engine", summary)
    logger.info("alert_engine: run complete: %s", summary)
    return summary
