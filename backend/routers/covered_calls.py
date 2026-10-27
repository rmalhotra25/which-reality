import re
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/covered-calls", tags=["Covered Calls"])
logger = logging.getLogger(__name__)
_TICKER_RE = re.compile(r'^[A-Z]{1,6}$')


class CoveredCallRequest(BaseModel):
    ticker: str
    cost_basis: float | None = None


def _evaluate_covered_call_tiers(call_tiers: dict, current_price: float, ticker: str) -> dict:
    """Deterministic tier checks (review M39, M43) for the covered-call router.

    Runs the 0.3%-per-week premium test and the earnings/ex-div calendar
    check from services.covered_call_service over each named tier. A tier
    whose threshold cannot be verified (no live bid/ask on this data plan)
    is flagged threshold_unverified, not abstained: an unverifiable
    threshold must not disable the analyzer, but it must be labeled. A tier
    that fails a verifiable threshold, or is calendar-blocked, abstains.
    """
    from services.covered_call_service import evaluate_tier, get_earnings_and_exdiv_dates

    try:
        dates = get_earnings_and_exdiv_dates(ticker)
    except Exception:
        dates = {"earnings_date": None, "next_ex_div_date": None}
    earnings_date = dates.get("earnings_date")
    next_ex_div_date = dates.get("next_ex_div_date")

    evaluations = {}
    blocked_all = True
    block_reasons: list[str] = []
    for name in ("aggressive", "balanced", "conservative"):
        tier = (call_tiers or {}).get(name)
        if tier is None:
            evaluations[name] = {
                "strike": None,
                "abstain": True,
                "threshold_unverified": False,
                "abstain_reasons": ["No suitable option found for this tier."],
                "notes": [],
                "warnings": [],
                "threshold": None,
                "calendar": None,
            }
            continue
        ev = evaluate_tier(tier, current_price, earnings_date, next_ex_div_date)
        threshold = ev.get("threshold") or {}
        calendar = ev.get("calendar") or {}
        threshold_unverified = bool(threshold.get("spread_unknown"))
        if threshold_unverified:
            # The threshold reason explains why it cannot be verified; it is
            # a note, not a block reason.
            notes = [threshold["reason"]] if threshold.get("reason") else []
            abstain = bool(calendar.get("blocked"))
            reasons = list(calendar.get("reasons") or [])
        else:
            notes = []
            abstain = bool(ev.get("abstain"))
            reasons = list(ev.get("abstain_reasons") or [])
        evaluations[name] = {
            "strike": tier.get("strike"),
            "abstain": abstain,
            "threshold_unverified": threshold_unverified,
            "abstain_reasons": reasons,
            "notes": notes,
            "warnings": ev.get("warnings") or [],
            "threshold": threshold,
            "calendar": calendar,
        }
        if not abstain:
            blocked_all = False
        else:
            block_reasons.extend(reasons)
    return {
        "evaluations": evaluations,
        "blocked_all": blocked_all,
        "block_reasons": block_reasons,
        "earnings_date": earnings_date.isoformat() if earnings_date else None,
        "next_ex_div_date": next_ex_div_date.isoformat() if next_ex_div_date else None,
    }


def _annotate_recommendations(claude_tiers: list, evaluations: dict, call_tiers: dict | None = None) -> list:
    """Mark Claude's recommended tiers against the deterministic evaluations.

    A recommendation whose strike matches an abstained tier is marked
    abstained with reasons. A recommendation whose strike matches no listed
    tier is marked strike_unverified and abstained: the strike was not on
    the chain the analyzer fetched, so it cannot be validated.
    """
    # W9/W8: the listed chain wins. Any strike, premium, or call-away
    # chance Claude returns is dropped and replaced with the chain
    # tier's own values; a strike not on the chain is abstained.
    by_strike = {}
    for name, ev in (evaluations or {}).items():
        strike = ev.get("strike")
        if strike is not None:
            by_strike[float(strike)] = (name, ev)
    annotated = []
    for rec in (claude_tiers or []):
        rec = dict(rec)
        strike = rec.get("strike")
        entry = by_strike.get(float(strike)) if strike is not None else None
        ev = entry[1] if entry else None
        if entry:
            # Overwrite Claude's numbers with the chain tier's numbers.
            tier_name, _ev = entry
            tier = (call_tiers or {}).get(tier_name) or {}
            rec["strike"] = float(strike)
            if tier.get("expiry"):
                rec["expiry"] = tier["expiry"]
            if tier.get("dte") is not None:
                rec["dte"] = tier["dte"]
            if tier.get("premium_per_contract") is not None:
                rec["premium_per_contract"] = tier["premium_per_contract"]
            if tier.get("call_away_chance_pct") is not None:
                rec["call_away_chance_pct"] = tier["call_away_chance_pct"]
        if ev is None:
            rec["abstain"] = True
            rec["strike_unverified"] = True
            rec["abstain_reasons"] = ["Strike not found on the listed chain: cannot validate this recommendation."]
        elif ev.get("abstain"):
            rec["abstain"] = True
            rec["abstain_reasons"] = ev.get("abstain_reasons") or []
        else:
            rec["abstain"] = False
            rec["abstain_reasons"] = []
            if ev.get("threshold_unverified"):
                rec["threshold_unverified"] = True
        annotated.append(rec)
    return annotated


@router.post("/analyze")
def analyze_covered_calls(req: CoveredCallRequest):
    """
    Generate three weekly covered call recommendations for a ticker the user owns 100 shares of.
    Tiers: aggressive (high premium, likely called away), balanced, conservative (keeps shares).
    """
    ticker = req.ticker.strip().upper()
    if not _TICKER_RE.match(ticker):
        raise HTTPException(status_code=400, detail="Invalid ticker. Use 1-6 letters (e.g. SCHD, QQQM).")

    from services.stock_data import StockDataService
    from services.iv_rank_service import get_iv_rank

    stock_data = StockDataService()

    tech = stock_data.get_price_and_technicals(ticker)
    tech_price = tech.get("price")
    if not tech_price:
        raise HTTPException(
            status_code=404,
            detail=f"No price data found for {ticker}. Check the symbol and try again.",
        )

    call_tiers = stock_data.get_call_tiers(ticker)
    if not call_tiers:
        raise HTTPException(
            status_code=503,
            detail=(
                f"Could not fetch options data for {ticker}. "
                "Possible reasons: this ETF/stock has no listed options, "
                "yfinance is temporarily rate-limited, or all near-term strikes have zero volume. "
                "Try a different ticker or wait a few minutes and try again."
            ),
        )

    # Prefer the live price from call_tiers (fast_info / Polygon) over the daily-close from history
    current_price = call_tiers.get("current_price") or tech_price

    # Deterministic checks first: threshold and calendar. When the calendar
    # blocks every tier (shared expiry), there is nothing to recommend, so
    # return the blocked state without asking Claude.
    tier_check = _evaluate_covered_call_tiers(call_tiers, current_price, ticker)
    if tier_check["blocked_all"]:
        return {
            "ticker": ticker,
            "current_price": current_price,
            "data_source": call_tiers.get("data_source", "last_trade"),
            "expiry": call_tiers.get("expiry"),
            "dte": call_tiers.get("dte"),
            "atm_iv_pct": call_tiers.get("atm_iv_pct"),
            "options_type": call_tiers.get("options_type", "weekly"),
            "iv_rank": get_iv_rank(ticker),
            "call_tiers": call_tiers,
            "tiers": [],
            "covered_call_blocked": True,
            "block_reasons": tier_check["block_reasons"],
            "tier_evaluations": tier_check["evaluations"],
            "earnings_date": tier_check["earnings_date"],
            "next_ex_div_date": tier_check["next_ex_div_date"],
        }

    # W8 (P2): tiers come from the listed chain, Claude explains only.
    # Strike, premium, and call-away chance are the chain tier's own
    # values; Claude text is attached per tier and never changes them.
    result = {"tiers": [], "iv_environment": None, "ai_unavailable": False}
    for name in ("aggressive", "balanced", "conservative"):
        tier = (call_tiers or {}).get(name) or {}
        if not tier.get("strike"):
            continue
        ev = tier_check["evaluations"].get(name) or {}
        result["tiers"].append({
            "tier": name,
            "strike": tier.get("strike"),
            "expiry": tier.get("expiry"),
            "dte": tier.get("dte"),
            "premium_per_contract": tier.get("premium_per_contract"),
            "call_away_chance_pct": tier.get("call_away_chance_pct"),
            "abstain": bool(ev.get("abstain")),
            "abstain_reasons": ev.get("abstain_reasons") or [],
        })
    try:
        from services.claude_analyst import ClaudeAnalyst
        notes = ClaudeAnalyst().explain_covered_calls(ticker, call_tiers)
        result["iv_environment"] = notes.get("iv_environment")
        by_tier = {t.get("tier"): t for t in (notes.get("tiers") or [])}
        for rec in result["tiers"]:
            text = by_tier.get(rec["tier"]) or {}
            rec["premium_plain"] = text.get("premium_plain", "")
            rec["callaway_plain"] = text.get("callaway_plain", "")
            rec["if_called_plain"] = text.get("if_called_plain", "")
            rec["if_not_called_plain"] = text.get("if_not_called_plain", "")
            rec["best_for"] = text.get("best_for", "")
    except Exception as e:
        logger.warning("Claude unavailable for %s covered calls: %s", ticker, e)
        result["ai_unavailable"] = True

    result["tiers"] = _annotate_recommendations(result["tiers"], tier_check["evaluations"], call_tiers)
    result["covered_call_blocked"] = False
    result["tier_evaluations"] = tier_check["evaluations"]
    result["earnings_date"] = tier_check["earnings_date"]
    result["next_ex_div_date"] = tier_check["next_ex_div_date"]
    result["ticker"] = ticker
    result["current_price"] = current_price
    result["data_source"] = call_tiers.get("data_source", "last_trade")
    result["expiry"] = call_tiers.get("expiry")
    result["dte"] = call_tiers.get("dte")
    result["atm_iv_pct"] = call_tiers.get("atm_iv_pct")
    result["options_type"] = call_tiers.get("options_type", "weekly")
    result["iv_rank"] = get_iv_rank(ticker)
    result["call_tiers"] = call_tiers
    return result


@router.post("/weekly-analyze")
def analyze_weekly_covered_call(req: CoveredCallRequest):
    """
    Analyze THIS WEEK's covered call options (nearest expiry, ≤9 DTE) for a ticker.
    Returns a single AI-recommended play for the current week, enriched with live news.
    """
    ticker = req.ticker.strip().upper()
    if not _TICKER_RE.match(ticker):
        raise HTTPException(status_code=400, detail="Invalid ticker. Use 1-6 letters (e.g. AAPL, SPY).")

    from services.stock_data import StockDataService
    from services.iv_rank_service import get_iv_rank

    stock_data = StockDataService()

    weekly_tiers = stock_data.get_weekly_call_tiers(ticker)
    if not weekly_tiers:
        raise HTTPException(
            status_code=503,
            detail=(
                f"No weekly options found for {ticker} in the next 16 days. "
                "This ticker may only have monthly options (e.g. SCHD, VTI). "
                "Use the standard Covered Call analyzer above for monthly options."
            ),
        )

    current_price = weekly_tiers.get("current_price")
    if not current_price:
        raise HTTPException(status_code=404, detail=f"No price data found for {ticker}.")

    iv_rank = get_iv_rank(ticker)

    # Deterministic checks first: threshold and calendar. When the calendar
    # blocks every tier (shared expiry), there is nothing to recommend, so
    # return the blocked state without asking Claude.
    tier_check = _evaluate_covered_call_tiers(weekly_tiers, current_price, ticker)
    if tier_check["blocked_all"]:
        return {
            "ticker": ticker,
            "current_price": current_price,
            "expiry": weekly_tiers.get("expiry"),
            "dte": weekly_tiers.get("dte"),
            "atm_iv_pct": weekly_tiers.get("atm_iv_pct"),
            "iv_rank": iv_rank,
            "data_source": weekly_tiers.get("data_source", "last_trade"),
            "call_tiers": weekly_tiers,
            "covered_call_blocked": True,
            "block_reasons": tier_check["block_reasons"],
            "tier_evaluations": tier_check["evaluations"],
            "earnings_date": tier_check["earnings_date"],
            "next_ex_div_date": tier_check["next_ex_div_date"],
        }

    # W8 (P2): quant picks the tier, Claude writes text only. Pick order
    # is balanced, then conservative, then aggressive, first tier that
    # does not abstain. No pick when every tier abstains.
    from services.quant_picks import covered_call_quant_pick
    picked = covered_call_quant_pick(tier_check["evaluations"])
    if picked is None:
        result = {"ai_unavailable": False, "recommended_tier": None, "abstain": True,
                  "abstain_reasons": tier_check["block_reasons"]}
    else:
        tier = weekly_tiers.get(picked) or {}
        result = {
            "recommended_tier": picked,
            "strike": tier.get("strike"),
            "expiry": tier.get("expiry"),
            "dte": tier.get("dte"),
            "premium_per_contract": tier.get("premium_per_contract"),
            "call_away_chance_pct": tier.get("call_away_chance_pct"),
            "weekly_yield_pct": tier.get("pct_of_stock_weekly"),
            "ai_unavailable": False,
        }
        try:
            from services.claude_analyst import ClaudeAnalyst
            notes = ClaudeAnalyst().explain_covered_calls(ticker, weekly_tiers)
            result["recommendation"] = notes.get("iv_environment") or ""
            result["iv_environment"] = notes.get("iv_environment")
        except Exception as e:
            logger.warning("Claude unavailable for %s weekly covered calls: %s", ticker, e)

    if result.get("strike") is not None:
        annotated = _annotate_recommendations([{"strike": result["strike"]}], tier_check["evaluations"])
        result["abstain"] = annotated[0].get("abstain", False)
        result["abstain_reasons"] = annotated[0].get("abstain_reasons", [])
        if annotated[0].get("threshold_unverified"):
            result["threshold_unverified"] = True
        if annotated[0].get("strike_unverified"):
            result["strike_unverified"] = True
    result["covered_call_blocked"] = False
    result["tier_evaluations"] = tier_check["evaluations"]
    result["earnings_date"] = tier_check["earnings_date"]
    result["next_ex_div_date"] = tier_check["next_ex_div_date"]
    result["ticker"] = ticker
    result["current_price"] = current_price
    result["expiry"] = weekly_tiers.get("expiry")
    result["dte"] = weekly_tiers.get("dte")
    result["atm_iv_pct"] = weekly_tiers.get("atm_iv_pct")
    result["iv_rank"] = iv_rank
    result["data_source"] = weekly_tiers.get("data_source", "last_trade")
    result["call_tiers"] = weekly_tiers
    return result
