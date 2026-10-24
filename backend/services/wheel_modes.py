"""
Wheel dual modes: classic wheel and premium harvesting.

Pure math and rules functions. No DB, no API calls.

Modes
-----
wheel:    classic cash-secured put selling. Assignment is fine, then sell
          covered calls. Uses the moderate (~0.30 delta) tier.
harvest:  premium harvesting. Assignment is the failure case. Uses the
          low-delta tier nearest 0.13 delta (bounded 0.08 to 0.20).

Expectancy ranking (both modes, printed on every card)
-------------------------------------------------------
  EV per contract = (1 - p) * premium - p * assignment_loss
  p = assignment chance (delta_abs, or assignment_chance_pct / 100)
  premium = mid_premium * 100
  assignment_loss = max(0, strike - 0.9 * current_price) * 100
  rank = EV / (strike * 100), times the mode penalties

Wheel mode keeps the soft penalty multipliers on the EV rank. Harvest
mode replaces the earnings, trend and IV penalties with hard gates, so
no multiplier is needed for those. The spread multiplier is applied
only when the spread is known; when bid and ask are both 0 there is
no live quote, so no spread check runs at all.

Management rules
----------------
Close at 50% of premium collected. Roll for a credit when the put is
worth 2x the premium collected. Never hold into expiry week: close or
roll at 7 days out. Wheel mode accepts assignment and moves to covered
calls. Harvest mode treats assignment as the failure case and rolls
down and out to defend the strike.
"""

WHEEL_MODE = "wheel"
HARVEST_MODE = "harvest"
VALID_MODES = (WHEEL_MODE, HARVEST_MODE)

MODE_LABELS = {
    WHEEL_MODE: "Wheel",
    HARVEST_MODE: "Premium Harvesting",
}

HARVEST_DELTA_TARGET = 0.13
HARVEST_DELTA_MIN = 0.08
HARVEST_DELTA_MAX = 0.20

CLOSE_PROFIT_FRAC = 0.50
ROLL_MARK_MULTIPLE = 2.0
EXPIRY_WEEK_DTE = 7

RANKING_FORMULA_TEXT = (
    "EV = (1 - p) * premium - p * assignment_loss  |  "
    "p = assignment chance (delta);  "
    "premium = mid * 100;  "
    "assignment_loss = max(0, strike - 0.9 * price) * 100;  "
    "rank = EV / (strike * 100), times mode penalties"
)

MANAGEMENT_RULES_TEXT = {
    WHEEL_MODE: (
        "Wheel rules: close at 50% of premium collected. Roll for a credit "
        "if the put doubles in value. Never hold into expiry week, close or "
        "roll at 7 days out. If assigned, sell covered calls."
    ),
    HARVEST_MODE: (
        "Harvest rules: close at 50% of premium collected. Roll down and out "
        "for a credit if the put doubles in value. Never hold into expiry "
        "week, close or roll at 7 days out. Assignment is the failure case, "
        "defend the strike early."
    ),
}


def compute_assignment_loss(strike: float, current_price: float) -> float:
    """Dollars lost per contract if assigned after a 10% drop."""
    if not strike or not current_price:
        return 0.0
    return max(0.0, strike - 0.9 * current_price) * 100.0


def compute_ev(premium_per_contract: float, p_assign: float,
               assignment_loss: float) -> float:
    """Expected value per contract in dollars."""
    p = min(max(p_assign or 0.0, 0.0), 1.0)
    return (1.0 - p) * (premium_per_contract or 0.0) - p * (assignment_loss or 0.0)


def select_harvest_tier(tiers: dict) -> dict | None:
    """
    Pick the put tier whose delta_abs is nearest 0.13, bounded 0.08-0.20.
    Returns None when no tier qualifies.
    """
    best = None
    best_gap = None
    for tier in (tiers or {}).values():
        if not isinstance(tier, dict):
            continue
        delta = tier.get("delta_abs")
        if delta is None:
            continue
        if delta < HARVEST_DELTA_MIN or delta > HARVEST_DELTA_MAX:
            continue
        gap = abs(delta - HARVEST_DELTA_TARGET)
        if best_gap is None or gap < best_gap:
            best = tier
            best_gap = gap
    return best


def get_management_guidance(mode: str, status: str, entry_premium,
                            dte, current_mark) -> dict:
    """
    Return {action, title, reason, detail} for an open position.

    entry_premium and current_mark are per-share dollars (mid premium
    style). current_mark may be None when no live mark is available;
    mark-based rules are then skipped and DTE rules plus the static
    rules text apply instead. Never fabricates a mark.
    """
    mode = mode if mode in VALID_MODES else WHEEL_MODE
    rules = MANAGEMENT_RULES_TEXT[mode]

    if status == "closed":
        return {
            "action": "none",
            "title": "Position closed",
            "reason": "No further action.",
            "detail": rules,
            "mark_known": current_mark is not None,
        }

    if status == "assigned":
        if mode == HARVEST_MODE:
            return {
                "action": "assigned_recover",
                "title": "Assigned: recover the position",
                "reason": (
                    "Assignment is the failure case in harvest mode. "
                    "Do not open a new put on this name until the shares "
                    "are sold."
                ),
                "detail": (
                    "Sell covered calls above your cost basis to earn the "
                    "shares back down, or sell the shares and move on. "
                    + rules
                ),
                "mark_known": current_mark is not None,
            }
        return {
            "action": "assigned_sell_calls",
            "title": "Assigned: sell covered calls",
            "reason": (
                "You own the shares at your cost basis. The wheel now "
                "earns income from covered calls."
            ),
            "detail": (
                "Use the call suggestion below to pick the next call "
                "strike. " + rules
            ),
            "mark_known": current_mark is not None,
        }

    if status == "call_active":
        return {
            "action": "hold",
            "title": "Hold: call is working",
            "reason": (
                "Shares are covered by a call. If the call expires "
                "worthless, sell the next one."
            ),
            "detail": rules,
            "mark_known": current_mark is not None,
        }

    # put_active from here on
    if dte is not None and dte <= EXPIRY_WEEK_DTE:
        return {
            "action": "close_or_roll",
            "title": "Expiry week: close or roll",
            "reason": (
                f"Only {dte} days to expiry. Do not hold into expiry "
                "week, close the put or roll it out."
            ),
            "detail": rules,
            "mark_known": current_mark is not None,
        }

    if (
        current_mark is not None
        and entry_premium
        and current_mark <= CLOSE_PROFIT_FRAC * entry_premium
    ):
        return {
            "action": "close_50_profit",
            "title": "Take profit: close at 50%",
            "reason": (
                f"The put is now worth ${current_mark:.2f}, half or less "
                f"of the ${entry_premium:.2f} premium collected. Bank the "
                "win and free the capital."
            ),
            "detail": rules,
            "mark_known": True,
        }

    if (
        current_mark is not None
        and entry_premium
        and current_mark >= ROLL_MARK_MULTIPLE * entry_premium
    ):
        if mode == HARVEST_MODE:
            reason = (
                f"The put is now worth ${current_mark:.2f}, twice the "
                f"${entry_premium:.2f} premium collected. Roll down and "
                "out for a credit to defend the strike."
            )
        else:
            reason = (
                f"The put is now worth ${current_mark:.2f}, twice the "
                f"${entry_premium:.2f} premium collected. Roll out for a "
                "credit, or accept assignment if you are happy owning "
                "the shares."
            )
        return {
            "action": "roll_for_credit",
            "title": "Roll for a credit",
            "reason": reason,
            "detail": rules,
            "mark_known": True,
        }

    return {
        "action": "hold",
        "title": "Hold and monitor",
        "reason": "No management trigger has fired yet.",
        "detail": rules,
        "mark_known": current_mark is not None,
    }
