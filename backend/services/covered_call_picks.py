"""Covered call indicator and recommender, standalone quant only.

This tab is deliberately separate from ticker lookup, Nash scoring,
the SPY gate, earnings gating, and Challenge sizing. Nothing here
judges whether a stock is a good buy, and nothing here is a trade
instruction. It answers one narrow question for shares already owned
(or planned to be owned): which listed call, sold against those
shares, gives up how much upside for how much premium.

Tier selection, by delta bands on one expiry:
  aggressive:    delta roughly 0.55 to 0.75, in the money or near it,
                 best premium, most likely to be called away.
  middle:       delta roughly 0.30 to 0.45, balanced premium and
                 assignment risk.
  conservative: delta roughly 0.15 to 0.25, premium that is still
                 decent, limited chance of being called away.

Delta is an assignment-risk proxy only, labelled as a rough proxy,
never as a probability guarantee. If a band has no listed strike, the
nearest listed strike to that band is used and flagged as a fallback.
If there is no chain at all, the tab reads unavailable with the named
reason, never invented strikes.

Pricing: a seller collects the bid, never the mid and never the last
trade. Rows with no positive bid are excluded. Greeks come from the
chain where present; a missing Greek is reported as None and the UI
labels it Missing, never estimated here.
"""

BANDS = {
    "aggressive": (0.55, 0.75, 0.65),
    "middle": (0.30, 0.45, 0.375),
    "conservative": (0.15, 0.25, 0.20),
}

TIER_LABELS = {
    "aggressive": "Aggressive: best premium, likely called away",
    "middle": "Middle of the pack: balanced premium and assignment risk",
    "conservative": "Conservative: decent premium, limited chance of being called away",
}


def _num(value):
    try:
        if value is None:
            return None
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out


def select_tier(rows, low, high, target):
    """Pick one call row for a delta band, or None.

    Rows inside the band win, ranked by premium (bid) first, then by
    closeness to the band target. If no row is inside the band, the
    nearest row to the target delta is used and flagged as a fallback.
    Rows with no positive bid or no delta are never candidates.
    """
    candidates = []
    for row in rows or []:
        bid = _num(row.get("bid"))
        delta = _num(row.get("delta"))
        if bid is None or bid <= 0 or delta is None:
            continue
        candidates.append((row, bid, abs(delta)))
    if not candidates:
        return None, False
    in_band = [(r, b, d) for (r, b, d) in candidates if low <= d <= high]
    if in_band:
        in_band.sort(key=lambda item: (-item[1], abs(item[2] - target)))
        return in_band[0][0], False
    candidates.sort(key=lambda item: abs(item[2] - target))
    return candidates[0][0], True


def enrich_pick(tier, row, price, dte, shares_owned=100, cost_basis=None):
    """Turn one chain row into a full covered call pick.

    Premium yield is bid divided by current price. Annualized yield
    scales that by 365 divided by DTE. Breakeven is strike plus bid
    premium, the price the stock must beat for the covered position
    to lose money on the shares alone, ignoring any prior cost basis
    unless one is supplied. Assignment means the shares are called
    away at the strike; the seller keeps the premium either way.
    """
    bid = _num(row.get("bid")) or 0.0
    ask = _num(row.get("ask"))
    strike = _num(row.get("strike")) or 0.0
    delta = _num(row.get("delta"))
    theta = _num(row.get("theta_seller"))
    gamma = _num(row.get("gamma"))
    vega = _num(row.get("vega"))
    iv = _num(row.get("iv_pct"))
    oi = row.get("open_interest")
    try:
        oi = int(oi) if oi is not None else None
    except (TypeError, ValueError):
        oi = None
    spread = None
    spread_pct = None
    if ask is not None and bid > 0:
        spread = round(ask - bid, 2)
        mid = (ask + bid) / 2.0
        spread_pct = round(spread / mid * 100, 1) if mid > 0 else None
    premium_yield_pct = round(bid / price * 100, 2) if price and price > 0 else None
    annualized_pct = None
    if premium_yield_pct is not None and dte and dte > 0:
        annualized_pct = round(premium_yield_pct * 365.0 / dte, 1)
    distance_pct = round((strike - price) / price * 100, 2) if price and price > 0 else None
    breakeven = round(strike + bid, 2)
    contracts = max(int(shares_owned or 100) // 100, 0)
    total_premium = round(bid * 100 * contracts, 2)
    if tier == "aggressive":
        called_line = (
            "If called: shares are sold at the strike, which is at or near "
            "today's price, so most further upside is given up, and the "
            "premium is kept on top."
        )
    elif tier == "middle":
        called_line = (
            "If called: shares are sold at the strike, keeping the premium "
            "plus the move up to the strike, and giving up any move above it."
        )
    else:
        called_line = (
            "If called: shares are sold at the strike, keeping the premium "
            "plus a larger move up to the strike, and giving up only a move "
            "above that higher strike."
        )
    return {
        "tier": tier,
        "label": TIER_LABELS[tier],
        "strike": strike,
        "expiry": row.get("expiry"),
        "dte": dte,
        "bid_per_share": round(bid, 2),
        "premium_per_contract": round(bid * 100, 2),
        "total_premium_for_shares": total_premium,
        "contracts_covered": contracts,
        "premium_yield_pct": premium_yield_pct,
        "annualized_yield_pct": annualized_pct,
        "delta": delta,
        "theta_seller": theta,
        "gamma": gamma,
        "vega": vega,
        "iv_pct": iv,
        "open_interest": oi,
        "spread_per_share": spread,
        "spread_pct": spread_pct,
        "ask_per_share": round(ask, 2) if ask is not None else None,
        "breakeven": breakeven,
        "distance_to_strike_pct": distance_pct,
        "current_price": round(price, 2) if price else None,
        "cost_basis": cost_basis,
        "called_line": called_line,
        "not_called_line": (
            "If not called: shares are kept, the premium is kept, and the "
            "same shares can be sold against again next expiry."
        ),
        "safety_note": (
            "A covered call caps upside and does not protect against a "
            "falling stock. Assignment means shares are called away at "
            "the strike."
        ),
    }


def build_picks(rows, price, dte, shares_owned=100, cost_basis=None):
    """Build all three tiers from one expiry's call rows.

    Returns (picks, fallback_tiers). A strike used by two tiers is
    allowed only when the chain has no better distinct strike; the
    fallback flag still names the band that had to fall back.
    """
    picks = {}
    fallback_tiers = []
    used_strikes = set()
    for tier, (low, high, target) in BANDS.items():
        row, is_fallback = select_tier(rows, low, high, target)
        if row is None:
            picks[tier] = None
            continue
        if is_fallback:
            fallback_tiers.append(tier)
        pick = enrich_pick(tier, row, price, dte, shares_owned, cost_basis)
        pick["band_fallback"] = is_fallback
        pick["band"] = [low, high]
        picks[tier] = pick
        used_strikes.add(row.get("strike"))
    return picks, fallback_tiers


def default_expiry(expiries):
    """Pick the listed expiry closest to 30-45 DTE.

    Target is 37 days, the middle of the 30-45 window. Expiries inside
    the window win over ones outside it, and the closest to 37 wins
    within each group. Returns None when no expiry is listed.
    """
    today_dte = []
    for item in expiries or []:
        dte = item.get("dte") if isinstance(item, dict) else None
        if dte is None or dte <= 0:
            continue
        today_dte.append(item)
    if not today_dte:
        return None
    in_window = [e for e in today_dte if 30 <= e["dte"] <= 45]
    pool = in_window if in_window else today_dte
    return min(pool, key=lambda e: abs(e["dte"] - 37))
