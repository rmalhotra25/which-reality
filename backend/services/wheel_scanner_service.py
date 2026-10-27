"""
Wheel scanner service.

Runs the put and covered-call tiers across the universe in
data/wheel_universe.json and ranks put candidates by expected value
per dollar of secured capital.

Ranking formula (stated here and echoed in each result payload):
  EV per contract = (1 - p) * premium - p * assignment_loss
  p = assignment chance (delta_abs, or assignment_chance_pct / 100)
  premium = sale_price * 100, where sale_price is the bid, what the
  seller actually collects. A last trade is never the premium (TXN
  Nov 13 $270 put, Oct 26 2026: bid $1.55, mid $2.50, last trade
  $5.00, app showed $500 per contract and breakeven $265.00, real
  sale is $155 and breakeven $268.45).
  assignment_loss = max(0, strike - 0.9 * current_price) * 100
  rank = EV / (strike * 100), times the mode penalties

Modes
-----
wheel:    classic wheel. Moderate (~0.30 delta) tier. Soft penalty
          multipliers: 0.50 earnings in window, 0.80 IV in bottom
          third, 0.90 below the 200-day MA, 0.85 spread over 10%.
harvest:  premium harvesting. Low-delta tier nearest 0.13 (bounded
          0.08-0.20). Hard gates instead of penalties: earnings in
          window excludes, below the 200-day excludes, IV percentile
          under 50 excludes.

Dropped from the old formula: the old ranking was raw premium per day
on secured capital (raw_pppd). It is kept in the payload for display
only and no longer drives the order. The old spread penalty is kept
only when the spread is known; when bid and ask are both 0 there is
no live quote on this data plan, so no spread check runs at all and
the result says spread_known=false instead of implying a check passed.

Filters that exclude before ranking (both modes):
  - open_interest < 100    (insufficient_liquidity)
  - spread_pct > 15%       (spread_too_wide, only when spread is known)
  - no executable bid      (no_executable_bid: bid is 0, so there is no
                            sale price. A last trade is never used instead.)

Hard gates in harvest mode only:
  - earnings inside the options window  (earnings_in_window)
  - price below the 200-day MA         (below_ma200)
  - IV percentile under 50, or unknown (iv_too_low)
  - no tier with delta in 0.08-0.20    (no_low_delta_tier)
"""
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Optional

import services.run_status as run_status
from services.wheel_modes import (
    WHEEL_MODE,
    HARVEST_MODE,
    VALID_MODES,
    RANKING_FORMULA_TEXT,
    compute_assignment_loss,
    compute_ev,
    select_harvest_tier,
)

logger = logging.getLogger(__name__)

_UNIVERSE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "wheel_universe.json"
)

# In-memory result caches, one per mode
_put_cache: dict = {}
_call_cache: Optional[dict] = None

RANKING_FORMULA = RANKING_FORMULA_TEXT


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
        cleaned = [t.strip().upper() for t in valid]
        # Dot tickers (BRK.B, BF.B) are stored in canonical Wikipedia form in
        # the JSON file, but yfinance returns no option expiries and no price
        # for them (verified Oct 26 2026: BRK.B/BF.B return nothing, BRK-B/BF-B
        # return chains), so they would silently never produce candidates.
        # Normalize to the hyphen form the data providers need. A hyphen
        # ticker that Polygon does not recognise simply falls back to
        # yfinance, which does return a chain, so the name still scans.
        normalized = []
        for t in cleaned:
            if "." in t:
                logger.info("wheel_scanner: normalizing dot ticker %s to %s", t, t.replace(".", "-"))
                normalized.append(t.replace(".", "-"))
            else:
                normalized.append(t)
        return normalized
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
                          earnings_flag: bool, above200: Optional[bool],
                          current_price: Optional[float], mode: str = WHEEL_MODE) -> dict:
    """
    Compute expectancy-based score for a put candidate.
    Returns a dict with ev_per_contract, ev_per_capital, assignment_loss,
    p_assign and the final rank score (EV per capital times the mode
    multipliers). Wheel mode keeps the soft penalty multipliers; harvest
    mode has no multipliers because its gates are hard exclusions.
    The spread multiplier applies only when the spread is known.
    The premium is the sale price, the bid. Production tiers carry
    sale_price / premium_source; a tier dict with neither sale_price
    nor bid/ask at all (legacy test fixtures) falls back to its
    mid_premium and is labelled legacy_mid, so those fixtures keep
    working. A tier with a bid of 0 is never priced at its mid.
    """
    sale_price = tier.get("sale_price")
    if sale_price is None:
        sale_price = tier.get("bid", 0) or 0
    if sale_price is None or sale_price <= 0:
        if "bid" not in tier and "ask" not in tier and tier.get("mid_premium"):
            sale_price = tier.get("mid_premium")
            premium_source = "legacy_mid"
        else:
            return {
                "ev_per_contract": 0.0,
                "ev_per_capital": 0.0,
                "assignment_loss": 0.0,
                "p_assign": 0.0,
                "rank_score": 0.0,
                "spread_known": False,
                "spread_pct": 0.0,
                "penalties": [],
                "premium_source": "no_executable_bid",
            }
    else:
        premium_source = tier.get("premium_source") or "bid"
    mid = tier.get("mid_premium", 0)
    strike = tier.get("strike", 0)
    dte = tier.get("dte", 0)
    bid = tier.get("bid", 0)
    ask = tier.get("ask", 0)

    if not strike or not dte or not sale_price:
        return {
            "ev_per_contract": 0.0,
            "ev_per_capital": 0.0,
            "assignment_loss": 0.0,
            "p_assign": 0.0,
            "rank_score": 0.0,
            "spread_known": False,
            "spread_pct": 0.0,
            "penalties": [],
            "premium_source": premium_source,
        }

    premium = sale_price * 100
    p_assign = tier.get("assignment_chance_pct")
    if p_assign is not None:
        p_assign = p_assign / 100.0
    else:
        p_assign = tier.get("delta_abs") or 0.0
    assignment_loss = compute_assignment_loss(strike, current_price)
    ev = compute_ev(premium, p_assign, assignment_loss)
    ev_per_capital = ev / (strike * 100) if strike else 0.0

    spread_known = not (bid == 0 and ask == 0)
    spread_pct = ((ask - bid) / mid * 100) if (mid > 0 and spread_known) else 0.0

    penalties = []
    multiplier = 1.0
    if mode == WHEEL_MODE:
        if earnings_flag:
            multiplier *= 0.50
            penalties.append({"reason": "earnings_in_window", "multiplier": 0.50})
        if iv_percentile_val is not None and iv_percentile_val < 33.0:
            multiplier *= 0.80
            penalties.append({"reason": "iv_pct_bottom_third", "multiplier": 0.80})
        if above200 is False:
            multiplier *= 0.90
            penalties.append({"reason": "below_ma200", "multiplier": 0.90})
    if spread_known and spread_pct > 10.0:
        multiplier *= 0.85
        penalties.append({"reason": "wide_spread", "multiplier": 0.85})

    return {
        "ev_per_contract": round(ev, 2),
        "ev_per_capital": round(ev_per_capital, 6),
        "assignment_loss": round(assignment_loss, 2),
        "p_assign": round(p_assign, 4),
        "rank_score": ev_per_capital * multiplier,
        "spread_known": spread_known,
        "spread_pct": round(spread_pct, 1),
        "penalties": penalties,
        "premium_source": premium_source,
    }


def _select_tier(tiers: dict, mode: str) -> tuple:
    """Return (tier, tier_name) for the mode, or (None, reason)."""
    if mode == HARVEST_MODE:
        tier = select_harvest_tier(tiers)
        if not tier:
            return None, "no_low_delta_tier"
        return tier, "harvest"
    tier = tiers.get("moderate")
    if not tier:
        tier = tiers.get("likely") or tiers.get("unlikely")
    if not tier:
        return None, "no_30delta_tier"
    return tier, "moderate"


def _evaluate_put_ticker(ticker: str, db, mode: str = WHEEL_MODE) -> dict:
    """
    Evaluate a single ticker for put-selling candidacy in the given mode.
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

    tier, tier_name = _select_tier(tiers, mode)
    if not tier:
        return {"ticker": ticker, "excluded": True, "reason": tier_name}

    mid = tier.get("mid_premium", 0)
    strike = tier.get("strike", 0)
    dte = tier.get("dte", 0)
    bid = tier.get("bid", 0)
    ask = tier.get("ask", 0)
    oi = tier.get("open_interest", 0)
    volume = tier.get("volume", 0)
    sale_price = tier.get("sale_price", bid if bid else 0) or 0
    premium_source = tier.get("premium_source") or ("bid" if bid else "no_executable_bid")

    if not mid and not sale_price and not strike and not dte:
        return {"ticker": ticker, "excluded": True, "reason": "incomplete_tier_data"}

    # No executable bid: there is no sale price. Exclude, never price
    # the candidate at a last trade. TXN Nov 13 $270 put is the case
    # that caught this: last trade $5.00, bid $1.55.
    if not sale_price or premium_source == "no_executable_bid":
        return {
            "ticker": ticker,
            "excluded": True,
            "reason": "no_executable_bid",
            "bid": bid,
            "ask": ask,
            "mid_premium": mid,
            "premium_source": "no_executable_bid",
        }

    if not strike or not dte:
        return {"ticker": ticker, "excluded": True, "reason": "incomplete_tier_data"}

    # Spread honesty: with no live quotes bid and ask are both 0, so no
    # spread check runs at all. Only exclude on a measured wide spread.
    spread_known = not (bid == 0 and ask == 0)
    spread_pct = round(((ask - bid) / mid * 100) if (mid > 0 and spread_known) else 0.0, 1)
    if spread_known and spread_pct > 15.0:
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

    # Harvest mode hard gates (wheel mode keeps soft penalties instead)
    if mode == HARVEST_MODE:
        if earnings_flag:
            return {"ticker": ticker, "excluded": True, "reason": "earnings_in_window"}
        if above200 is not True:
            return {"ticker": ticker, "excluded": True, "reason": "below_ma200"}
        if iv_percentile is None or iv_percentile < 50:
            return {"ticker": ticker, "excluded": True, "reason": "iv_too_low"}

    raw_pppd = round(sale_price / (strike * 100) / dte, 7)
    scored = _score_put_candidate(
        tier, iv_pct_val, iv_percentile, earnings_flag, above200, current_price, mode
    )

    return {
        "ticker": ticker,
        "excluded": False,
        "mode": mode,
        "tier_name": tier_name,
        "rank_score": round(scored["rank_score"], 9),
        "ranking_formula": RANKING_FORMULA,
        "raw_pppd": raw_pppd,
        "penalties": scored["penalties"],
        # Expectancy
        "ev_per_contract": scored["ev_per_contract"],
        "ev_per_capital": scored["ev_per_capital"],
        "assignment_loss": scored["assignment_loss"],
        "p_assign": scored["p_assign"],
        # Option details
        "strike": strike,
        "expiry": tier.get("expiry"),
        "dte": dte,
        "bid": bid,
        "ask": ask,
        "mid_premium": mid,
        "sale_price": sale_price,
        "premium_source": premium_source,
        "premium_per_contract": round(sale_price * 100, 2),
        "breakeven": tier.get("breakeven"),
        "iv_pct": iv_pct_val,
        "iv_percentile": iv_percentile,
        "iv_pct_source": iv_pct_source,
        "delta_abs": tier.get("delta_abs"),
        "assignment_chance_pct": tier.get("assignment_chance_pct"),
        "open_interest": oi,
        "volume": volume,
        "spread_pct": scored["spread_pct"],
        "spread_known": scored["spread_known"],
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
    sale_price = tier.get("sale_price", bid if bid else 0) or 0
    premium_source = tier.get("premium_source") or ("bid" if bid else "no_executable_bid")

    # No executable bid: no sale price, exclude, never price at a
    # last trade.
    if not sale_price or premium_source == "no_executable_bid":
        return {
            "ticker": ticker,
            "excluded": True,
            "reason": "no_executable_bid",
            "bid": bid,
            "ask": ask,
            "mid_premium": mid,
            "premium_source": "no_executable_bid",
        }

    if not strike or not dte or not current_price:
        return {"ticker": ticker, "excluded": True, "reason": "incomplete_tier_data"}

    spread_known = not (bid == 0 and ask == 0)
    spread_pct = round(((ask - bid) / mid * 100) if (mid > 0 and spread_known) else 0.0, 1)
    if spread_known and spread_pct > 15.0:
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

    raw_pppd = round(sale_price / (current_price * 100) / dte, 7)
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
        "sale_price": sale_price,
        "premium_source": premium_source,
        "premium_per_contract": round(sale_price * 100, 2),
        "iv_pct": tiers.get("atm_iv_pct") or tier.get("iv_pct"),
        "delta": tier.get("delta"),
        "call_away_chance_pct": tier.get("call_away_chance_pct"),
        "open_interest": oi,
        "volume": tier.get("volume", 0),
        "spread_pct": spread_pct,
        "spread_known": spread_known,
        "upside_to_strike_pct": upside_pct,
        "current_price": current_price,
        "cost_basis": cost_basis,
        "ex_dividend_date": ex_date,
        "early_assignment_risk": ex_date is not None,
        "data_source": tiers.get("data_source", "unknown"),
    }


def run_put_scanner(db, max_workers: int = 8, mode: str = WHEEL_MODE) -> dict:
    """
    Run the put-seller scanner across the full universe in the given mode.
    Updates run_status["wheel_scanner"] and populates the per-mode cache.
    """
    global _put_cache
    if mode not in VALID_MODES:
        mode = WHEEL_MODE
    run_status.set_running("wheel_scanner")

    universe = _load_universe()
    if not universe:
        run_status.set_error("wheel_scanner", "universe empty or failed to load")
        return {"candidates": [], "excluded": [], "run_at": None, "mode": mode}

    candidates = []
    excluded = []
    errors = 0

    logger.info("wheel_scanner: evaluating %d tickers for put-selling (mode=%s)", len(universe), mode)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_evaluate_put_ticker, t, db, mode): t for t in universe}
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

    # Sort candidates by EV-based rank_score descending
    candidates.sort(key=lambda c: c.get("rank_score", 0), reverse=True)
    excluded.sort(key=lambda e: e.get("ticker", ""))

    run_at = datetime.now(timezone.utc).isoformat()
    result = {
        "candidates": candidates,
        "excluded": excluded,
        "run_at": run_at,
        "universe_size": len(universe),
        "mode": mode,
        "ranking_formula": RANKING_FORMULA,
    }

    _put_cache[mode] = result
    run_status.set_success_with_counts("wheel_scanner", {
        "candidates": len(candidates),
        "excluded": len(excluded),
        "errors": errors,
        "universe_size": len(universe),
        "mode": mode,
    })
    logger.info(
        "wheel_scanner: complete. mode=%s candidates=%d excluded=%d errors=%d",
        mode, len(candidates), len(excluded), errors,
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


def get_put_cache(mode: str = WHEEL_MODE) -> Optional[dict]:
    return _put_cache.get(mode if mode in VALID_MODES else WHEEL_MODE)


def get_call_cache() -> Optional[dict]:
    return _call_cache
