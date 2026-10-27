"""Quant picks for the remaining W8 paths: quant decides, Claude explains.

Every function here is deterministic: same inputs give the same pick,
score, verdict, strike, or tier. Claude is never called from this
module. Callers attach Claude text only as an explanation, and a
Claude failure never changes, delays, or suppresses the quant pick.
"""
import logging

logger = logging.getLogger(__name__)


def _clamp(value, lo=0.0, hi=100.0):
    return max(lo, min(hi, value))


# ---------------------------------------------------------------------------
# Champions
# ---------------------------------------------------------------------------

def champion_score(survivor: dict) -> float:
    """Deterministic champion score from prescreen fields only.

    Rewards distance from the 60-day low (room to run), distance below
    the 60-day high (not extended), and RSI below 50 (not overbought).
    All inputs are in the prescreen dict, so no enrichment is needed.
    """
    pct_from_low = float(survivor.get("pct_from_low") or 0)
    pct_from_high = float(survivor.get("pct_from_high") or 0)
    rsi = survivor.get("rsi")
    rsi_term = 0.0 if rsi is None else 0.2 * (50.0 - float(rsi))
    return round(_clamp(50.0 + 0.4 * pct_from_low + 0.4 * (-pct_from_high) + rsi_term), 1)


def pick_champions_quant(survivors: list[dict]) -> dict:
    """Pick 3 champions by quant score, in rank order.

    wheel = top-ranked, options = second, longterm = third. The
    assignment is by rank, not by a model, and is recorded in the
    rule registry trigger text for alert.champions_ai_picks.
    """
    from services.ai_boundary import grade_from_quant_score
    ranked = sorted(
        survivors,
        key=lambda s: (-champion_score(s), s.get("ticker", "")),
    )[:3]
    strategies = ("wheel", "options", "longterm")
    picks = {}
    for strategy, s in zip(strategies, ranked):
        score = champion_score(s)
        picks[strategy] = {
            "ticker": s["ticker"],
            "score": score,
            "grade": grade_from_quant_score(score),
            "reason": "",
        }
    return picks


# ---------------------------------------------------------------------------
# Day-trade scanner
# ---------------------------------------------------------------------------

def day_trade_quant_plays(top: list[dict], spy_change=None) -> list[dict]:
    """Build day-trade plays from quant-ranked movers, no model.

    Input is already sorted by (vol_ratio, abs change). Take the top 5,
    direction is the sign of the day's change, entry/target/stop come
    from quant_scorer.compute_entry_exit_options, and the option play
    carries the quant strike and the next Friday expiry. The caller
    snaps the option to the listed chain and drops snap failures.
    """
    from services.ai_boundary import valid_expiry_dates
    from services.quant_scorer import compute_entry_exit_options
    plays = []
    expiries = valid_expiry_dates(1)
    expiry = expiries[0] if expiries else None
    for mover in (top or [])[:5]:
        change = mover.get("change_pct") or 0
        direction = "long" if change >= 0 else "short"
        option_type = "CALL" if change >= 0 else "PUT"
        technicals = {
            "price": mover.get("price"),
            "atr": mover.get("atr"),
            "rsi": mover.get("rsi"),
        }
        ee = compute_entry_exit_options(technicals, option_type) or {}
        vol_ratio = mover.get("vol_ratio") or 0
        if vol_ratio >= 3 and abs(change) >= 3:
            confidence = "high"
        elif vol_ratio >= 2:
            confidence = "medium"
        else:
            confidence = "low"
        plays.append({
            "ticker": mover.get("ticker"),
            "direction": direction,
            "setup": "momentum",
            "confidence": confidence,
            "entry_zone": ee.get("underlying_entry"),
            "target": ee.get("underlying_target"),
            "stop_loss": ee.get("underlying_stop"),
            "timeframe": "intraday",
            "risk_reward": 2.0,
            "catalyst": "; ".join(mover.get("news") or [])[:300],
            "reasoning": "",
            "option_play": {
                "option_type": option_type,
                "strike": ee.get("suggested_strike"),
                "expiry": expiry,
                "entry_premium": ee.get("entry_premium_est"),
                "target_premium": ee.get("target_premium_est"),
                "target_premium_source": "quant_estimate",
                "stop_premium": ee.get("stop_premium_est"),
                "breakeven_stock": ee.get("underlying_target"),
            },
        })
    return plays


# ---------------------------------------------------------------------------
# Options flow
# ---------------------------------------------------------------------------

def flow_verdict(alert: dict) -> dict:
    """Deterministic flow verdict from chain fields only.

    PROCEED: vol/OI at least 2, notional at least $50k, move needed at
    most 5%. CAUTION: vol/OI at least 2, move needed at most 10%.
    Otherwise AVOID. Implied target is the breakeven.
    """
    vol_oi = alert.get("vol_oi_ratio") or 0
    notional = alert.get("notional") or 0
    pct_move = alert.get("pct_move_needed")
    if pct_move is None:
        pct_move = 999.0
    if vol_oi >= 2.0 and notional >= 50000 and pct_move <= 5.0:
        verdict, confidence = "PROCEED", "high"
    elif vol_oi >= 2.0 and pct_move <= 10.0:
        verdict, confidence = "CAUTION", "medium"
    else:
        verdict, confidence = "AVOID", "low"
    return {
        "verdict": verdict,
        "confidence": confidence,
        "implied_target": alert.get("breakeven"),
        "recommendation": "BUY" if verdict == "PROCEED" else "AVOID",
        "action_note": (
            f"Quant verdict {verdict} ({confidence} confidence): "
            f"vol/OI {vol_oi}, notional ${notional:,.0f}, "
            f"move needed {pct_move}%."
        ),
    }


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------

def watchlist_quant(technicals: dict, fundamentals: dict | None = None) -> dict:
    """Quant watchlist scores, grades, and best strategy, no model."""
    from services.ai_boundary import grade_from_quant_score
    from services.quant_scorer import (
        compute_longterm_quant_score,
        compute_options_quant_score,
        compute_wheel_quant_score,
    )
    fundamentals = fundamentals or {}
    wheel = compute_wheel_quant_score(technicals)
    options = compute_options_quant_score(technicals)
    longterm = compute_longterm_quant_score(technicals, fundamentals)
    scores = {
        "wheel": wheel.get("composite"),
        "options": options.get("composite"),
        "longterm": longterm.get("composite"),
    }
    best = max(scores, key=lambda k: (scores[k] if scores[k] is not None else -1, k))
    return {
        "wheel_score": scores["wheel"],
        "wheel_grade": grade_from_quant_score(scores["wheel"]),
        "options_score": scores["options"],
        "options_grade": grade_from_quant_score(scores["options"]),
        "longterm_score": scores["longterm"],
        "longterm_grade": grade_from_quant_score(scores["longterm"]),
        "best_strategy": best,
        "summary": "",
    }


# ---------------------------------------------------------------------------
# Covered calls
# ---------------------------------------------------------------------------

def covered_call_quant_pick(evaluations: dict) -> str | None:
    """Pick the covered-call tier by a written rule, no model.

    Order is balanced (delta ~0.45), then conservative (~0.20), then
    aggressive (~0.70). First tier that does not abstain wins. None
    when every tier abstains.
    """
    for name in ("balanced", "conservative", "aggressive"):
        ev = (evaluations or {}).get(name) or {}
        if not ev.get("abstain"):
            return name
    return None


# ---------------------------------------------------------------------------
# Wheel custom analysis and roll
# ---------------------------------------------------------------------------

def wheel_custom_quant(technicals: dict, put_tiers: dict) -> dict:
    """Quant wheel score, grade, and tier choice for custom analysis."""
    from services.ai_boundary import grade_from_quant_score
    from services.quant_scorer import compute_wheel_quant_score
    score = compute_wheel_quant_score(technicals).get("composite")
    tier = None
    if put_tiers:
        tier = "moderate" if put_tiers.get("moderate") else (
            "likely" if put_tiers.get("likely") else "unlikely"
        )
    return {
        "wheel_score": score,
        "wheel_grade": grade_from_quant_score(score),
        "wheel_rating": grade_from_quant_score(score),
        "recommended_tier": tier,
    }


def roll_quant(position, current_price: float, put_tiers: dict, computed_nets: dict) -> dict:
    """Quant roll decision from management guidance and computed nets.

    should_roll is True only when the guidance action is close_or_roll
    or roll_for_credit AND at least one tier has a computed credit net.
    The new strike and expiry come from the tier with the best credit
    net, never from a model. Urgency follows pct from strike.
    """
    from services.wheel_modes import get_management_guidance
    mode = getattr(position, "mode", "wheel") or "wheel"
    status = getattr(position, "status", "put_active")
    try:
        dte = None
        from datetime import date
        expiry = getattr(position, "put_expiry", None)
        if expiry:
            dte = (date.fromisoformat(str(expiry)) - date.today()).days
    except Exception:
        dte = None
    guidance = get_management_guidance(
        mode, str(status), getattr(position, "put_premium_rcvd", None), dte, None,
    )
    action = guidance.get("action")
    best_tier = None
    best_net = None
    for tier_name, net in (computed_nets or {}).items():
        if net is None:
            continue
        if best_net is None or net > best_net:
            best_net = net
            best_tier = tier_name
    should_roll = action in ("close_or_roll", "roll_for_credit") and best_net is not None and best_net > 0
    pct_from_strike = None
    strike = getattr(position, "put_strike", None)
    if strike and current_price:
        pct_from_strike = round((current_price - float(strike)) / float(strike) * 100, 1)
    if pct_from_strike is None:
        urgency = "low"
    elif pct_from_strike <= 2:
        urgency = "high"
    elif pct_from_strike <= 5:
        urgency = "medium"
    else:
        urgency = "low"
    new_strike = None
    new_expiry = None
    if should_roll and best_tier and put_tiers:
        tier = (put_tiers or {}).get(best_tier) or {}
        new_strike = tier.get("strike")
        new_expiry = tier.get("expiry")
    return {
        "should_roll": bool(should_roll),
        "urgency": urgency,
        "action": action,
        "new_strike": new_strike,
        "new_expiry": new_expiry,
        "roll_net": best_net,
        "guidance_title": guidance.get("title"),
        "guidance_reason": guidance.get("reason"),
    }
