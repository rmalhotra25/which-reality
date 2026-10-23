"""
Wheel scanner service.

Runs the put and covered-call tiers across the universe in
data/wheel_universe.json and ranks candidates by risk-adjusted
premium per day on secured capital.

Ranking formula (stated here and echoed in each result payload):
  raw_pppd = mid_premium / (strike * 100) / dte
  score = raw_pppd
          * (0.50 if earnings_in_window else 1.0)
          * (0.80 if iv_pct_bottom_third else 1.0)
          * (0.90 if below_ma200 else 1.0)
          * (0.85 if spread_pct > 10 else 1.0)

Filters that exclude before ranking:
  - spread_pct > 15%       (spread_too_wide)
  - open_interest < 100    (insufficient_liquidity)

Hard flags that do NOT auto-exclude but apply the 0.50 penalty:
  - earnings inside the options window  (earnings_in_window)
"""
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Optional

import services.run_status as run_status

logger = logging.getLogger(__name__)

_UNIVERSE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "wheel_universe.json"
)

# In-memory result cache
_put_cache: Optional[dict] = None
_call_cache: Optional[dict] = None

RANKING_FORMULA = (
    "raw_pppd = mid_premium / (strike * 100) / dte; "
    "score = raw_pppd"
    " * (0.50 if earnings_in_window else 1.0)"
    " * (0.80 if iv_pct_bottom_third else 1.0)"
    " * (0.90 if below_ma200 else 1.0)"
    " * (0.85 if spread_pct > 10 else 1.0)"
)


def _load_universe() -> list[str]:
    try:
        with open(_UNIVERSE_PATH) as f:
            tickers = json.load(f)
        if not isinstance(tickers, list):
            raise ValueError("wheel_universe.json must be a JSON array")
        valid = [t for t in tickers if isinstance(t, str) and t.strip()]
        bad = [t for t in tickers if t not in valid]
        if bad:
            logger.warning("wheel_scanner: ignoring invalid universe entries: %s", bad)
        return [t.strip().upper() for t in valid]
    except Exception as e:
        logger.error("wheel_scanner: failed to load universe: %s", e)
        return []


def _get_iv_percentile(db, ticker: str) -> dict:
    try:
        from services.iv_snapshot_service import get_iv_percentile
        return get_iv_percentile(db, ticker) or {}
    except Exception:
        return {}


def _earnings_in_window(ticker: str, dte: int) -> bool:
    """Return True if earnings are scheduled within the option's DTE window."""
    try:
        from services.finnhub_client import get_earnings_this_month
        days_away = get_earnings_this_month(ticker)
        if days_away is not None and 0 <= days_away <= dte:
            return True
    except Exception:
        pass
    return False


def _div_exdate_flag(ticker: str) -> Optional[str]:
    """Return ex-dividend date string if it falls within the next 30 days, else None."""
    try:
        from services.finnhub_client import get_basic_financials
        metrics = get_basic_financials(ticker)
        exdate = metrics.get("exDividendDate")
        if not exdate:
            return None
        from datetime import date
        ex = date.fromisoformat(str(exdate))
        days_away = (ex - date.today()).days
        if 0 <= days_away <= 30:
            return exdate
    except Exception:
        pass
    return None


def _above_ma200(ticker: str) -> Optional[bool]:
    """Return True/False based on whether price is above 200-day MA, or None if unavailable."""
    try:
        from services.stock_data import StockDataService
        tech = StockDataService().get_price_and_technicals(ticker)
        ma = (tech.get("moving_averages") or {})
        return ma.get("above_ma200")
    except Exception:
        return None


def _quality_gate(ticker: str) -> dict:
    """
    Returns {"verdict": str, "quant_score": int|None, "source": str}
    verdict: "PASS" | "FAIL" | "UNGATED"
    """
    try:
        from services.stock_data import StockDataService
        from services.quant_scorer import compute_wheel_quant_score
        tech = StockDataService().get_price_and_technicals(ticker)
        if not tech:
            return {"verdict": "UNGATED", "quant_score": None, "source": "no_data"}
        qs = compute_wheel_quant_score(tech)
        score = qs.get("total_score") if qs else None
        if score is None:
            return {"verdict": "UNGATED", "quant_score": None, "source": "scorer_unavailable"}
        verdict = "PASS" if score >= 55 else "FAIL"
        return {"verdict": verdict, "quant_score": int(score), "source": "quant_scorer"}
    except Exception as e:
        logger.debug("quality_gate failed for %s: %s", ticker, e)
        return {"verdict": "UNGATED", "quant_score": None, "source": "error"}


def _score_put_candidate(tier: dict, iv_pct: float, iv_percentile_val: Optional[float],
                          earnings_flag: bool, above200: Optional[bool]) -> float:
    """
    Compute risk-adjusted score from the raw premium-per-day-on-capital.
    Returns the score (higher = better candidate).
    """
    mid = tier.get("mid_premium", 0)
    strike = tier.get("strike", 0)
    dte = tier.get("dte", 0)
    bid = tier.get("bid", 0)
    ask = tier.get("ask", 0)

    if not strike or not dte or not mid:
        return 0.0

    raw_pppd = mid / (strike * 100) / dte

    spread_pct = ((ask - bid) / mid * 100) if mid > 0 else 0.0

    # Penalty multipliers
    m_earnings = 0.50 if earnings_flag else 1.0
    m_iv_low = 0.80 if (iv_percentile_val is not None and iv_percentile_val < 33.0) else 1.0
    m_below200 = 0.90 if (above200 is False) else 1.0
    m_spread = 0.85 if spread_pct > 10.0 else 1.0

    return raw_pppd * m_earnings * m_iv_low * m_below200 * m_spread


def _evaluate_put_ticker(ticker: str, db) -> dict:
    """
    Evaluate a single ticker for put-selling candidacy.
    Returns a result dict with either candidate data or an exclusion reason.
    """
    try:
        from services.stock_data import StockDataService
        svc = StockDataService()
        tiers = svc.get_put_tiers(ticker)
    except Exception as e:
        return {"ticker": ticker, "excluded": True, "reason": f"data_error: {e}"}

    if not tiers:
        return {"ticker": ticker, "excluded": True, "reason": "no_options_data"}

    tier = tiers.get("moderate")
    if not tier:
        tier = tiers.get("likely") or tiers.get("unlikely")
    if not tier:
        return {"ticker": ticker, "excluded": True, "reason": "no_30delta_tier"}

    mid = tier.get("mid_premium", 0)
    strike = tier.get("strike", 0)
    dte = tier.get("dte", 0)
    bid = tier.get("bid", 0)
    ask = tier.get("ask", 0)
    oi = tier.get("open_interest", 0)
    volume = tier.get("volume", 0)

    if not mid or not strike or not dte:
        return {"ticker": ticker, "excluded": True, "reason": "incomplete_tier_data"}

    spread_pct = round(((ask - bid) / mid * 100) if mid > 0 else 0.0, 1)

    # Spread quality gate: disqualify if spread_pct > 15%
    if spread_pct > 15.0:
        return {
            "ticker": ticker,
            "excluded": True,
            "reason": "spread_too_wide",
            "spread_pct": spread_pct,
        }

    # Liquidity floor: OI must be >= 100
    if oi < 100:
        return {
            "ticker": ticker,
            "excluded": True,
            "reason": "insufficient_liquidity",
            "open_interest": oi,
        }

    # Gather additional context
    iv_pct_val = tiers.get("atm_iv_pct") or tier.get("iv_pct") or 0.0
    iv_snap = _get_iv_percentile(db, ticker)
    iv_percentile = iv_snap.get("iv_percentile")
    iv_pct_source = "historical" if iv_snap.get("history_building") else "stored"

    above200 = _above_ma200(ticker)
    current_price = tiers.get("current_price")

    earnings_flag = _earnings_in_window(ticker, dte)
    quality = _quality_gate(ticker)

    raw_pppd = round(mid / (strike * 100) / dte, 7)
    score = _score_put_candidate(tier, iv_pct_val, iv_percentile, earnings_flag, above200)

    # Penalties applied (for display)
    penalties = []
    if earnings_flag:
        penalties.append({"reason": "earnings_in_window", "multiplier": 0.50})
    if iv_percentile is not None and iv_percentile < 33.0:
        penalties.append({"reason": "iv_pct_bottom_third", "multiplier": 0.80})
    if above200 is False:
        penalties.append({"reason": "below_ma200", "multiplier": 0.90})
    spread_pct_val = round(((ask - bid) / mid * 100) if mid > 0 else 0.0, 1)
    if spread_pct_val > 10.0:
        penalties.append({"reason": "wide_spread", "multiplier": 0.85})

    return {
        "ticker": ticker,
        "excluded": False,
        "rank_score": round(score, 9),
        "ranking_formula": RANKING_FORMULA,
        "raw_pppd": raw_pppd,
        "penalties": penalties,
        # Option details
        "strike": strike,
        "expiry": tier.get("expiry"),
        "dte": dte,
        "bid": bid,
        "ask": ask,
        "mid_premium": mid,
        "premium_per_contract": tier.get("premium_per_contract"),
        "iv_pct": iv_pct_val,
        "iv_percentile": iv_percentile,
        "iv_pct_source": iv_pct_source,
        "delta_abs": tier.get("delta_abs"),
        "assignment_chance_pct": tier.get("assignment_chance_pct"),
        "open_interest": oi,
        "volume": volume,
        "spread_pct": spread_pct_val,
        # Underlying context
        "current_price": current_price,
        "above_ma200": above200,
        "trend_state": (
            "above_200ma" if above200 is True
            else "below_200ma" if above200 is False
            else "unknown"
        ),
        # Flags
        "earnings_in_window": earnings_flag,
        "quality_verdict": quality["verdict"],
        "quant_score": quality["quant_score"],
        "quality_source": quality["source"],
        "data_source": tiers.get("data_source", "unknown"),
    }


def _evaluate_call_ticker(ticker: str, cost_basis: Optional[float] = None) -> dict:
    """
    Evaluate a single ticker for covered-call candidacy.
    Returns result dict with either candidate data or an exclusion reason.
    """
    try:
        from services.stock_data import StockDataService
        svc = StockDataService()
        tiers = svc.get_call_tiers(ticker)
    except Exception as e:
        return {"ticker": ticker, "excluded": True, "reason": f"data_error: {e}"}

    if not tiers:
        return {"ticker": ticker, "excluded": True, "reason": "no_options_data"}

    # Use balanced tier (~45 delta) as the primary covered call tier
    tier = tiers.get("balanced")
    if not tier:
        tier = tiers.get("aggressive") or tiers.get("conservative")
    if not tier:
        return {"ticker": ticker, "excluded": True, "reason": "no_call_tier"}

    mid = tier.get("mid_premium", 0)
    strike = tier.get("strike", 0)
    dte = tier.get("dte", 0)
    bid = tier.get("bid", 0)
    ask = tier.get("ask", 0)
    oi = tier.get("open_interest", 0)
    current_price = tiers.get("current_price")

    if not mid or not strike or not dte or not current_price:
        return {"ticker": ticker, "excluded": True, "reason": "incomplete_tier_data"}

    spread_pct = round(((ask - bid) / mid * 100) if mid > 0 else 0.0, 1)
    if spread_pct > 15.0:
        return {
            "ticker": ticker,
            "excluded": True,
            "reason": "spread_too_wide",
            "spread_pct": spread_pct,
        }

    if oi < 100:
        return {
            "ticker": ticker,
            "excluded": True,
            "reason": "insufficient_liquidity",
            "open_interest": oi,
        }

    # Dividend ex-date flag for early assignment risk
    ex_date = _div_exdate_flag(ticker)

    raw_pppd = round(mid / (current_price * 100) / dte, 7)
    upside_pct = round((strike - current_price) / current_price * 100, 1)

    return {
        "ticker": ticker,
        "excluded": False,
        "rank_score": round(raw_pppd, 9),
        "raw_pppd": raw_pppd,
        # Option details
        "strike": strike,
        "expiry": tier.get("expiry"),
        "dte": dte,
        "bid": bid,
        "ask": ask,
        "mid_premium": mid,
        "premium_per_contract": tier.get("premium_per_contract"),
        "iv_pct": tiers.get("atm_iv_pct") or tier.get("iv_pct"),
        "delta": tier.get("delta"),
        "call_away_chance_pct": tier.get("call_away_chance_pct"),
        "open_interest": oi,
        "volume": tier.get("volume", 0),
        "spread_pct": spread_pct,
        "upside_to_strike_pct": upside_pct,
        "current_price": current_price,
        "cost_basis": cost_basis,
        "ex_dividend_date": ex_date,
        "early_assignment_risk": ex_date is not None,
        "data_source": tiers.get("data_source", "unknown"),
    }


def run_put_scanner(db, max_workers: int = 8) -> dict:
    """
    Run the put-seller scanner across the full universe.
    Updates run_status["wheel_scanner"] and populates _put_cache.
    """
    global _put_cache
    run_status.set_running("wheel_scanner")

    universe = _load_universe()
    if not universe:
        run_status.set_error("wheel_scanner", "universe empty or failed to load")
        return {"candidates": [], "excluded": [], "run_at": None}

    candidates = []
    excluded = []
    errors = 0

    logger.info("wheel_scanner: evaluating %d tickers for put-selling", len(universe))

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_evaluate_put_ticker, t, db): t for t in universe}
        for fut in as_completed(futures, timeout=300):
            ticker = futures[fut]
            try:
                result = fut.result(timeout=60)
                if result.get("excluded"):
                    excluded.append(result)
                else:
                    candidates.append(result)
            except Exception as e:
                logger.warning("wheel_scanner: error evaluating %s: %s", ticker, e)
                excluded.append({"ticker": ticker, "excluded": True, "reason": f"exception: {e}"})
                errors += 1

    # Sort candidates by rank_score descending (raw_pppd is never the sort key directly;
    # the score already incorporates the penalty multipliers)
    candidates.sort(key=lambda c: c.get("rank_score", 0), reverse=True)
    excluded.sort(key=lambda e: e.get("ticker", ""))

    run_at = datetime.now(timezone.utc).isoformat()
    result = {
        "candidates": candidates,
        "excluded": excluded,
        "run_at": run_at,
        "universe_size": len(universe),
        "ranking_formula": RANKING_FORMULA,
    }

    _put_cache = result
    run_status.set_success_with_counts("wheel_scanner", {
        "candidates": len(candidates),
        "excluded": len(excluded),
        "errors": errors,
        "universe_size": len(universe),
    })
    logger.info(
        "wheel_scanner: complete. candidates=%d excluded=%d errors=%d",
        len(candidates), len(excluded), errors,
    )
    return result


def run_call_scanner(db, max_workers: int = 8) -> dict:
    """
    Run the covered-call scanner.
    Scans wheel positions (assigned/call_active) + universe tickers.
    Updates _call_cache.
    """
    global _call_cache

    # Gather tickers: active wheel positions first, then universe
    position_tickers: list[tuple[str, Optional[float]]] = []
    try:
        from models.wheel import WheelPosition, WheelStatus
        positions = db.query(WheelPosition).filter(
            WheelPosition.status.in_([WheelStatus.assigned, WheelStatus.call_active])
        ).all()
        for pos in positions:
            position_tickers.append((pos.ticker, pos.cost_basis))
    except Exception as e:
        logger.warning("wheel_scanner call: could not load positions: %s", e)

    universe = _load_universe()
    # Combine position tickers + universe (no duplicate tickers)
    seen = set()
    eval_list: list[tuple[str, Optional[float]]] = []
    for ticker, cb in position_tickers:
        if ticker not in seen:
            eval_list.append((ticker, cb))
            seen.add(ticker)
    for t in universe:
        if t not in seen:
            eval_list.append((t, None))
            seen.add(t)

    candidates = []
    excluded = []

    logger.info("wheel_scanner call: evaluating %d tickers", len(eval_list))

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(_evaluate_call_ticker, t, cb): t
            for t, cb in eval_list
        }
        for fut in as_completed(futures, timeout=300):
            ticker = futures[fut]
            try:
                result = fut.result(timeout=60)
                if result.get("excluded"):
                    excluded.append(result)
                else:
                    candidates.append(result)
            except Exception as e:
                logger.warning("wheel_scanner call: error evaluating %s: %s", ticker, e)
                excluded.append({"ticker": ticker, "excluded": True, "reason": f"exception: {e}"})

    candidates.sort(key=lambda c: c.get("rank_score", 0), reverse=True)
    excluded.sort(key=lambda e: e.get("ticker", ""))

    run_at = datetime.now(timezone.utc).isoformat()
    result = {
        "candidates": candidates,
        "excluded": excluded,
        "run_at": run_at,
        "universe_size": len(eval_list),
    }
    _call_cache = result
    return result


def get_put_cache() -> Optional[dict]:
    return _put_cache


def get_call_cache() -> Optional[dict]:
    return _call_cache
