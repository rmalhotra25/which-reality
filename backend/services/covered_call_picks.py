"""Covered call indicator and recommender, standalone quant only.

This tab is deliberately separate from ticker lookup, Nash scoring,
the SPY gate, earnings gating, and Challenge sizing. Nothing here
judges whether a stock is a good buy, and nothing here is a trade
instruction. It answers one narrow question for shares already owned
(or planned to be owned): which listed call, sold against those
shares, gives up how much upside for how much premium.

The tab is built for a weekly income seller: premium the seller
would most likely keep, with limited risk of losing the shares.
That means out-of-the-money strikes only, a real bid, and a liquid
strike. An in-the-money strike is never a pick: selling it means
the shares are almost certainly called away, and most of the
"premium" is intrinsic value the seller gives back.

Tier selection, by delta bands on one expiry:
  aggressive:    delta roughly 0.55 to 0.75, near the money, best
                 premium, most likely to be called away.
  middle:       delta roughly 0.30 to 0.45, balanced premium and
                 assignment risk.
  conservative: delta roughly 0.15 to 0.25, the keep-the-premium
                 tier: far out of the money, small premium, low
                 chance of being called away.

Delta is an assignment-risk proxy only, labelled as a rough proxy,
never as a probability guarantee. If a band has no listed strike,
the nearest listed strike to that band is used and flagged as a
fallback, but only when it sits within MAX_FALLBACK_DELTA_GAP of
the band edge; a strike far from the band is a different trade,
not a fallback. In-band picks are made before fallbacks, so a
strike that sits squarely in one tier's band is never stolen as
another tier's fallback. If there is no chain at all, the tab reads
unavailable with the named reason, never invented strikes.

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
    "conservative": "Keep the premium: far out of the money, small premium, low chance of being called away",
}

# Sanity guards for a candidate row. A strike more than 10% from the
# price is not a covered-call candidate, and an in-the-money strike
# is never a pick: selling it hands the shares over and most of the
# "premium" is intrinsic value. A bid under $0.20 a share is not
# worth selling, a strike with under 10 contracts of open interest
# has no real market, and an IV above 150% is a bad quote, not a
# real market (the ABT Dec 18 2026 case showed 168% IV on a $82.50
# strike). Without these, a thin chain hands every tier the same
# deep in-the-money strike.
MAX_STRIKE_DISTANCE_PCT = 10.0
MIN_BID_PER_SHARE = 0.20
MIN_OPEN_INTEREST = 10
MAX_IV_PCT = 150.0
MAX_FALLBACK_DELTA_GAP = 0.10


def _num(value):
    try:
        if value is None:
            return None
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out


def _row_is_sane(row, price):
    """True when a chain row is a plausible covered-call candidate.

    Rejects in-the-money strikes outright, strikes more than
    MAX_STRIKE_DISTANCE_PCT from the price, bids under
    MIN_BID_PER_SHARE, strikes with under MIN_OPEN_INTEREST of
    open interest (when open interest is reported), and IV above
    MAX_IV_PCT. A missing price disables the price checks, and a
    missing open interest does not fail the row.
    """
    strike = _num(row.get("strike"))
    bid = _num(row.get("bid"))
    if strike is None or bid is None:
        return False
    if bid < MIN_BID_PER_SHARE:
        return False
    iv = _num(row.get("iv_pct"))
    if iv is not None and iv > MAX_IV_PCT:
        return False
    oi = row.get("open_interest")
    if oi is not None:
        try:
            if int(oi) < MIN_OPEN_INTEREST:
                return False
        except (TypeError, ValueError):
            pass
    if not price or price <= 0:
        return True
    if strike < price:
        return False
    if abs(strike - price) / price > MAX_STRIKE_DISTANCE_PCT / 100.0:
        return False
    return True


def select_tier(rows, low, high, target, price=None, used_strikes=None, in_band_only=False):
    """Pick one call row for a delta band, or None with a reason.

    Returns (row, is_fallback, reason). Rows inside the band win,
    ranked by premium (bid) first, then by closeness to the band
    target. If no row is inside the band, the nearest row to the
    band edge is used and flagged as a fallback, but only when it
    sits within MAX_FALLBACK_DELTA_GAP of the edge. With
    in_band_only=True, no fallback is offered: only a row inside
    the band qualifies. Rows with no positive bid, no delta, or
    that fail the sanity guards are never candidates. A strike
    already used by another tier is never reused: when only used
    strikes remain, the tier is empty with reason
    "strike_used_by_another_tier" instead of repeating a trade
    under a different label.

    Reasons when no row is picked:
      "no_bid": no row carries a positive bid.
      "no_otm_bid": bids exist, but no out-of-the-money strike
        with a real bid passes the guards.
      "no_band_strike": sane strikes exist, but none sits in or
        near this delta band.
      "strike_used_by_another_tier": the only strikes in or near
        the band are already used by another tier.
    """
    used = set(used_strikes or [])
    any_bid = False
    sane = []
    for row in rows or []:
        bid = _num(row.get("bid"))
        delta = _num(row.get("delta"))
        if bid is not None and bid > 0:
            any_bid = True
        if bid is None or bid <= 0 or delta is None:
            continue
        if not _row_is_sane(row, price):
            continue
        sane.append((row, bid, abs(delta)))
    if not sane:
        return None, False, ("no_bid" if not any_bid else "no_otm_bid")

    def _gap(delta):
        if low <= delta <= high:
            return 0.0
        return low - delta if delta < low else delta - high

    def _pick(pool):
        in_band = [(r, b, d) for (r, b, d) in pool if low <= d <= high]
        if in_band:
            in_band.sort(key=lambda item: (-item[1], abs(item[2] - target)))
            return in_band[0][0], False
        if in_band_only:
            return None, False
        near = [(r, b, d) for (r, b, d) in pool if _gap(d) <= MAX_FALLBACK_DELTA_GAP]
        if not near:
            return None, False
        near.sort(key=lambda item: (_gap(item[2]), -item[1]))
        return near[0][0], True

    unused = [c for c in sane if c[0].get("strike") not in used]
    if unused:
        row, is_fallback = _pick(unused)
        if row is not None:
            return row, is_fallback, None
        return None, False, "no_band_strike"
    row, is_fallback = _pick(sane)
    if row is not None:
        return None, False, "strike_used_by_another_tier"
    return None, False, "no_band_strike"


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

    Returns (picks, fallback_tiers, tier_reasons). In-band picks
    are made for all three tiers first, so a strike that sits
    squarely in one tier's band is never stolen as another tier's
    fallback; fallbacks are only offered to the tiers still empty.
    A strike already used by another tier is never reused: that
    tier stays empty with a reason instead of repeating a trade
    under a different label. tier_reasons maps each empty tier to
    the reason select_tier reported, or None when the tier has a
    pick.
    """
    picks = {}
    fallback_tiers = []
    tier_reasons = {}
    used_strikes = set()
    pending = []
    for tier, (low, high, target) in BANDS.items():
        row, _, _ = select_tier(
            rows, low, high, target, price=price, used_strikes=used_strikes,
            in_band_only=True,
        )
        if row is None:
            pending.append((tier, low, high, target))
            continue
        pick = enrich_pick(tier, row, price, dte, shares_owned, cost_basis)
        pick["band_fallback"] = False
        pick["band"] = [low, high]
        picks[tier] = pick
        tier_reasons[tier] = None
        used_strikes.add(row.get("strike"))
    for tier, low, high, target in pending:
        row, is_fallback, reason = select_tier(
            rows, low, high, target, price=price, used_strikes=used_strikes
        )
        if row is None:
            picks[tier] = None
            tier_reasons[tier] = reason
            continue
        tier_reasons[tier] = None
        if is_fallback:
            fallback_tiers.append(tier)
        pick = enrich_pick(tier, row, price, dte, shares_owned, cost_basis)
        pick["band_fallback"] = is_fallback
        pick["band"] = [low, high]
        picks[tier] = pick
        used_strikes.add(row.get("strike"))
    return picks, fallback_tiers, tier_reasons


def default_expiry(expiries):
    """Pick the listed expiry for weekly income first, then 30-45 DTE.

    The tab is for selling premium every week and keeping it, so the
    nearest weekly expiry wins: any expiry 4 to 14 days out, nearest
    first. When no weekly is listed, fall back to the 30-45 day
    window (closest to 37), then to the nearest listed expiry.
    Returns None when no expiry is listed.
    """
    today_dte = []
    for item in expiries or []:
        dte = item.get("dte") if isinstance(item, dict) else None
        if dte is None or dte <= 0:
            continue
        today_dte.append(item)
    if not today_dte:
        return None
    weekly = [e for e in today_dte if 4 <= e["dte"] <= 14]
    if weekly:
        return min(weekly, key=lambda e: e["dte"])
    in_window = [e for e in today_dte if 30 <= e["dte"] <= 45]
    pool = in_window if in_window else today_dte
    return min(pool, key=lambda e: abs(e["dte"] - 37))
