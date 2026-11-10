"""Today's Book: aggregate the day's best setups into one ranked list.

Quant decides, AI explains. Everything in this module is deterministic
code operating on numbers already computed by the engines and stored in
the database. No Claude value is read here, and no new signal is
computed here.

Sources (all cache-only, no new engine run on request, so a page load
never pays for a fresh Polygon scan and never re-runs a signal):
  - Wheel: latest WheelRecommendation batch (LIVE, Quality Pullback /
    Volume Breakout only; the registry is the authority on LIVE).
  - Setup Alerts: SetupAlert rows fired in the last 36 hours
    (/api/alerts/today), LIVE and SHADOW kept separate.
  - Directional: latest DirectionalCandidate batch. Directional is
    SHADOW in the registry, so candidates go to research_only, are
    never ranked as today's best, and are never sized.
  - Covered Calls: middle tier only, for tickers in settings (shares
    the user already owns) plus tickers with assigned wheel positions.
    One chain fetch per ticker, capped at 5, on request.

Pricing rules (non-negotiable):
  - A seller collects the bid, never the mid and never the last trade.
  - A buyer pays the ask, never the mid.
  - A mid with a zero bid or zero ask is not a tradable price. On the
    Massive Options Starter plan bid/ask can be 0.0; such an item is
    marked unavailable and is never sized.
  - Estimated premium applies a spread haircut: half the spread, taken
    against the trader (bid minus half the spread for a sale, ask plus
    half the spread for a buy). A spread wider than 25% of the mid
    makes the item untradable.
  - Directional candidates store a mid premium, so they are never
    sized from it. They stay research-only until the engine stores a
    real bid/ask.

Sizing rules (portfolio simulator, backtest_harness.SimulatorParams):
  - risk_budget = equity * risk_pct, halved once equity is at least
    10% below its saved peak, zero (paused) at 15% below peak.
  - contracts = floor(risk_budget / risk_per_contract), capped so
    one position's risk never exceeds max_position_pct of equity.
    risk_per_contract is the premium at risk for a wheel put (the
    premium collected per contract) and the max loss for anything
    else. The assignment worst case for a wheel put is still shown
    as max_loss_per_contract; it is not the sizing risk.
  - Heat = sum of risk dollars on open positions plus the new
    items, capped at max_heat_pct of equity; concurrency capped at
    max_positions. Anything that would breach a cap goes to `blocked`
    with the reason, never silently shrunk to fit.

Signals use the close of day T; entries are modeled at the next open.
Nothing here is a live order: this is decision support only.
"""

import json
import logging
import math
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Spread wider than this share of the mid is untradable: the quoted
# price is not a price you can actually get.
MAX_SPREAD_PCT = 25.0

# Delayed-data note shown wherever a chain quote is used. Massive
# Starter has no live quotes entitlement; CBOE delayed quotes lag
# about 15 minutes.
DELAY_NOTE = (
    "Option quotes are delayed about 15 minutes (CBOE delayed). "
    "Massive Options Starter has no live quotes entitlement."
)
DATA_NOTE = (
    "Signals use the close of day T; entries are modeled at the next "
    "open. " + DELAY_NOTE
)

REDUCE_DD_PCT = 10.0  # simulator default: halve risk at this drawdown
PAUSE_DD_PCT = 15.0   # simulator default: pause new entries at this drawdown


def _num(value):
    try:
        if value is None:
            return None
        out = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(out) or math.isinf(out):
        return None
    return out


def net_sell_premium(bid, ask):
    """Premium a seller can realistically collect, per share.

    Returns (premium_net, tradable, reason, spread_pct). The seller
    collects the bid, less half the spread as a slippage haircut.
    A zero bid or zero ask means no tradable price exists (not a mid).
    """
    bid = _num(bid)
    ask = _num(ask)
    if bid is None or bid <= 0:
        return None, False, "no_executable_bid", None
    if ask is None or ask <= 0 or ask < bid:
        return None, False, "no_executable_ask", None
    spread = ask - bid
    mid = (ask + bid) / 2.0
    spread_pct = round(spread / mid * 100, 1) if mid > 0 else None
    if spread_pct is not None and spread_pct > MAX_SPREAD_PCT:
        return None, False, "spread_too_wide", spread_pct
    premium = round(bid - spread / 2.0, 2)
    if premium <= 0:
        return None, False, "premium_not_positive_after_haircut", spread_pct
    return premium, True, None, spread_pct


def net_buy_cost(ask, bid):
    """Cost a buyer realistically pays, per share. Ask plus half spread."""
    ask = _num(ask)
    bid = _num(bid)
    if ask is None or ask <= 0:
        return None, False, "no_executable_ask", None
    if bid is None or bid <= 0 or bid > ask:
        return None, False, "no_executable_bid", None
    spread = ask - bid
    mid = (ask + bid) / 2.0
    spread_pct = round(spread / mid * 100, 1) if mid > 0 else None
    if spread_pct is not None and spread_pct > MAX_SPREAD_PCT:
        return None, False, "spread_too_wide", spread_pct
    return round(ask + spread / 2.0, 2), True, None, spread_pct


def drawdown_pct(equity, peak_equity):
    """Drawdown of the Today book against its saved peak, in percent."""
    equity = _num(equity)
    peak = _num(peak_equity)
    if not equity or not peak or peak <= 0:
        return 0.0
    return round(max(peak - equity, 0.0) / peak * 100, 1)


def risk_budget_dollars(equity, risk_pct, dd_pct):
    """Per-trade risk budget, halved at REDUCE_DD_PCT, zero at PAUSE."""
    equity = _num(equity) or 0.0
    budget = equity * (_num(risk_pct) or 0.0) / 100.0
    if dd_pct >= PAUSE_DD_PCT:
        return 0.0
    if dd_pct >= REDUCE_DD_PCT:
        budget *= 0.5
    return round(budget, 2)


def size_contracts(max_loss_per_contract, risk_budget, notional_per_contract,
                   equity, max_position_pct, risk_per_contract=None,
                   cap_basis="notional"):
    """Contracts for one item, or (0, reason) when it cannot be sized.

    max_loss_per_contract is the worst case per contract in dollars.
    risk_per_contract is the sizing risk per contract: for a wheel put
    it is the premium at risk (the premium collected), for anything
    else it defaults to max_loss_per_contract. notional_per_contract
    is the capital the position ties up per contract (strike x 100
    for a cash-secured put, premium x 100 for a long call, 0 for a
    covered call against shares already owned). cap_basis "risk"
    caps one position by its risk dollars instead of its notional;
    wheel puts use it because their sizing risk is the premium.
    """
    risk = _num(risk_per_contract)
    if risk is None:
        risk = _num(max_loss_per_contract)
    if not risk or risk <= 0:
        return 0, "max_loss_unknown"
    budget = _num(risk_budget) or 0.0
    if budget <= 0:
        return 0, "risk_budget_zero"
    contracts = int(budget // risk)
    if contracts < 1:
        return 0, "risk_budget_too_small"
    cap_base = risk if cap_basis == "risk" else (_num(notional_per_contract) or 0.0)
    if cap_base > 0 and equity:
        cap = int((_num(max_position_pct) / 100.0 * equity) // cap_base)
        contracts = min(contracts, cap)
        if contracts < 1:
            return 0, "single_position_cap"
    return contracts, None


def quant_explanation(item):
    """2-3 short plain-language sentences, from computed numbers only.

    This is the default explanation. Claude may replace the wording
    (see explain_today in the router), never the numbers.
    """
    kind = item.get("kind")
    ticker = item.get("ticker")
    if kind == "wheel":
        return (
            f"This is a cash-secured put on {ticker}. "
            f"The price is near support and the premium is high enough "
            f"to be worth collecting, so the plan is to sell the put and "
            f"keep the premium if the stock stays above the strike. "
            f"If the stock falls below the strike, the shares may be "
            f"assigned at the strike price."
        )
    if kind == "covered_call":
        return (
            f"This sells a call against {ticker} shares already owned. "
            f"The premium is kept whether the shares are called away or "
            f"not, and the strike is where the shares would be sold. "
            f"It caps the upside above the strike and does not protect "
            f"against the stock falling."
        )
    if kind == "setup_alert":
        return (
            f"This setup fired on {ticker} from the close of the last "
            f"trading day, and the entry is modeled at the next open. "
            f"The trade only makes sense if the price stays on the right "
            f"side of the invalidation level. "
            f"If that level breaks, the setup is wrong and the trade "
            f"should not be held."
        )
    if kind == "directional":
        return (
            f"This is a directional option idea on {ticker}, shown for "
            f"research only. It is not a live setup, and its stored "
            f"premium is a mid, not a price you can trade. "
            f"No size is given until a real bid and ask are available."
        )
    return f"This is a {kind or 'trade'} idea on {ticker}."


def _plain_title(item):
    kind = item.get("kind")
    ticker = item.get("ticker")
    strike = item.get("strike")
    expiry = item.get("expiry")
    dte = item.get("dte")
    when = f" expiring {expiry}" if expiry else ""
    when += f" ({dte} days)" if dte else ""
    if kind == "wheel":
        return f"Sell a put on {ticker} at the ${strike:g} strike{when}"
    if kind == "covered_call":
        return f"Sell a call on {ticker} at the ${strike:g} strike{when}"
    if kind == "setup_alert":
        opt = item.get("contract_type") or ""
        if opt.upper() == "PUT":
            return f"Sell a put on {ticker} at the ${strike:g} strike{when}" if strike else f"Setup alert on {ticker}"
        if opt.upper() == "CALL":
            return f"Buy a call on {ticker} at the ${strike:g} strike{when}" if strike else f"Setup alert on {ticker}"
        return f"Setup alert on {ticker}"
    if kind == "directional":
        opt = (item.get("option_type") or "").upper()
        verb = "Buy a call" if opt == "CALL" else "Buy a put" if opt == "PUT" else "Trade an option"
        return f"{verb} on {ticker} at the ${strike:g} strike{when}" if strike else f"Directional idea on {ticker}"
    return f"{ticker} idea"


def _risk_text(item):
    kind = item.get("kind")
    strike = item.get("strike")
    premium = item.get("premium_net_per_share")
    max_loss = item.get("max_loss_per_contract")
    if kind == "wheel":
        return (
            "Sizing uses the premium at risk: the premium collected is "
            "what this trade risks per contract. If the stock falls below "
            "the strike you may still be assigned shares at the strike, "
            "and the worst case is the cost of the shares minus the "
            "premium collected."
        )
    if kind == "covered_call":
        return (
            "A covered call caps upside and does not protect against a "
            "falling stock. If the shares are called away they are sold "
            "at the strike; the premium is kept either way."
        )
    if kind == "setup_alert":
        if (item.get("contract_type") or "").upper() == "PUT":
            return (
                "If the stock falls below the strike you may be assigned "
                "shares at the strike. The maximum loss is the cost of "
                "the shares minus the premium collected."
            )
        return (
            "The most you can lose on a bought call is the premium paid. "
            "If the stock does not move above the strike plus the "
            "premium, the option can expire worthless."
        )
    if kind == "directional":
        return (
            "The most you can lose on a bought option is the premium "
            "paid. This idea is research only and has no size because "
            "no tradable bid or ask is stored for it."
        )
    return "Losses are limited to the amount shown as dollars at risk."


def _invalidation_text(item):
    inv = item.get("invalidation_price")
    if inv:
        return (
            f"Invalidated if the stock closes below ${inv:g}. "
            f"That is the level where the setup is wrong."
        )
    strike = item.get("strike")
    if strike:
        return (
            f"Invalidated if the stock closes below the ${strike:g} "
            f"strike. That is the level where the setup is wrong."
        )
    return "Invalidated if the price breaks the level shown on the card."


def normalize_item(candidate, sizing):
    """Attach plain language, risk, invalidation and sizing to a candidate."""
    item = dict(candidate)
    item["title"] = _plain_title(item)
    item["risk_text"] = _risk_text(item)
    item["invalidation_text"] = _invalidation_text(item)
    item["explanation"] = quant_explanation(item)
    item["explanation_source"] = "quant"
    item.update(sizing)
    return item


def rank_and_size(candidates, settings, current_heat_dollars, open_positions):
    """Rank LIVE candidates by premium per dollar at risk, then size them.

    Returns (items, blocked). Candidates are dicts with at least kind,
    ticker, strike, premium_net_per_share (or premium_net_per_contract),
    max_loss_per_contract, notional_per_contract, status. A wheel
    candidate also carries risk_per_contract (the premium at risk);
    without it the max loss is the sizing risk. SHADOW
    candidates must not be passed here; they go to research_only.
    """
    equity = _num(settings.get("account_equity")) or 0.0
    risk_pct = _num(settings.get("risk_pct")) or 1.0
    max_heat_pct = _num(settings.get("max_heat_pct")) or 10.0
    max_positions = int(settings.get("max_positions") or 10)
    max_position_pct = _num(settings.get("max_position_pct")) or 10.0
    dd = drawdown_pct(equity, settings.get("peak_equity"))
    budget = risk_budget_dollars(equity, risk_pct, dd)
    heat_cap = equity * max_heat_pct / 100.0
    heat = _num(current_heat_dollars) or 0.0

    def risk_per_contract(c):
        risk = _num(c.get("risk_per_contract"))
        if risk is not None:
            return risk
        return _num(c.get("max_loss_per_contract")) or 0.0

    def rank_score(c):
        risk = risk_per_contract(c)
        premium = _num(c.get("premium_net_per_contract")) or 0.0
        if c.get("kind") == "covered_call":
            price = _num(c.get("current_price")) or 0.0
            if price > 0 and premium > 0:
                return premium / (price * 100.0)
            return 0.0
        if risk > 0 and premium > 0:
            return premium / risk
        return 0.0

    ordered = sorted(candidates, key=lambda c: (rank_score(c), _num(c.get("quant_score")) or 0.0), reverse=True)
    items, blocked = [], []
    for cand in ordered:
        base = dict(cand)
        base["rank_score"] = round(rank_score(cand), 4)
        if dd >= PAUSE_DD_PCT:
            blocked.append(normalize_item(base, {
                "contracts": 0, "capital_at_risk": 0.0, "risk_dollars": 0.0,
                "premium_net_total": 0.0, "blocked_reason": "drawdown_pause",
                "blocked_text": "New entries are paused: the book is 15% or more below its saved peak.",
            }))
            continue
        if len(items) + open_positions >= max_positions:
            blocked.append(normalize_item(base, {
                "contracts": 0, "capital_at_risk": 0.0, "risk_dollars": 0.0,
                "premium_net_total": 0.0, "blocked_reason": "concurrency_cap",
                "blocked_text": f"Blocked: already at the limit of {max_positions} open positions.",
            }))
            continue
        # Covered calls are sized by shares already owned, not by risk
        # budget: no new capital goes in, so risk dollars are zero and
        # the heat cap does not apply. The risk is the shares themselves.
        if base.get("kind") == "covered_call" and base.get("contracts_fixed") is not None:
            contracts = int(base.get("contracts_fixed") or 0)
            if contracts < 1:
                blocked.append(normalize_item(base, {
                    "contracts": 0, "capital_at_risk": 0.0, "risk_dollars": 0.0,
                    "premium_net_total": 0.0, "blocked_reason": "no_shares",
                    "blocked_text": "Blocked: fewer than 100 shares owned, so no covered call can be sold.",
                }))
                continue
            premium_net = _num(base.get("premium_net_per_contract")) or 0.0
            items.append(normalize_item(base, {
                "contracts": contracts,
                "capital_at_risk": 0.0,
                "risk_dollars": 0.0,
                "premium_net_total": round(contracts * premium_net, 2),
                "blocked_reason": None,
                "blocked_text": None,
            }))
            continue
        contracts, reason = size_contracts(
            base.get("max_loss_per_contract"), budget,
            base.get("notional_per_contract"), equity, max_position_pct,
            risk_per_contract=risk_per_contract(base),
            cap_basis="risk" if base.get("kind") == "wheel" else "notional")
        if contracts < 1:
            blocked.append(normalize_item(base, {
                "contracts": 0, "capital_at_risk": 0.0, "risk_dollars": 0.0,
                "premium_net_total": 0.0, "blocked_reason": reason or "cannot_size",
                "blocked_text": "Blocked: the risk budget does not cover even one contract at this size.",
            }))
            continue
        risk_dollars = round(contracts * risk_per_contract(base), 2)
        if heat + risk_dollars > heat_cap:
            blocked.append(normalize_item(base, {
                "contracts": 0, "capital_at_risk": 0.0, "risk_dollars": 0.0,
                "premium_net_total": 0.0, "blocked_reason": "heat_cap",
                "blocked_text": "Blocked: adding this trade would take total open risk above the heat limit.",
            }))
            continue
        premium_net = _num(base.get("premium_net_per_contract")) or 0.0
        notional = _num(base.get("notional_per_contract")) or 0.0
        heat += risk_dollars
        items.append(normalize_item(base, {
            "contracts": contracts,
            "capital_at_risk": round(contracts * notional, 2),
            "risk_dollars": risk_dollars,
            "premium_net_total": round(contracts * premium_net, 2),
            "blocked_reason": None,
            "blocked_text": None,
        }))
    for i, item in enumerate(items, start=1):
        item["rank"] = i
    return items, blocked


def build_risk_bar(settings, current_heat_dollars, open_positions):
    """Compact portfolio risk bar for the top of Today's Book."""
    equity = _num(settings.get("account_equity")) or 0.0
    max_heat_pct = _num(settings.get("max_heat_pct")) or 10.0
    dd = drawdown_pct(equity, settings.get("peak_equity"))
    heat = _num(current_heat_dollars) or 0.0
    heat_cap = equity * max_heat_pct / 100.0
    if dd >= PAUSE_DD_PCT:
        brake = "paused"
    elif dd >= REDUCE_DD_PCT:
        brake = "reduced"
    else:
        brake = "none"
    return {
        "account_equity": round(equity, 2),
        "peak_equity": round(_num(settings.get("peak_equity")) or equity, 2),
        "current_heat_dollars": round(heat, 2),
        "current_heat_pct": round(heat / equity * 100, 2) if equity else 0.0,
        "heat_cap_dollars": round(heat_cap, 2),
        "remaining_capacity_dollars": round(max(heat_cap - heat, 0.0), 2),
        "open_positions": int(open_positions),
        "max_positions": int(settings.get("max_positions") or 10),
        "drawdown_pct": dd,
        "drawdown_brake": brake,
        "risk_pct": _num(settings.get("risk_pct")) or 1.0,
        "max_heat_pct": max_heat_pct,
    }


def settings_to_dict(row):
    """Serialize a TodaySettings row, with covered-call tickers parsed."""
    try:
        tickers = json.loads(row.covered_call_tickers or "[]")
    except Exception:
        tickers = []
    return {
        "account_equity": row.account_equity,
        "peak_equity": row.peak_equity,
        "risk_pct": row.risk_pct,
        "max_heat_pct": row.max_heat_pct,
        "max_positions": row.max_positions,
        "max_position_pct": row.max_position_pct,
        "covered_call_tickers": [str(t).upper() for t in tickers if t],
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def open_wheel_heat(db):
    """Worst-case dollars on open wheel positions, plus their count.

    Put-active: (strike minus premium received) x shares. Assigned or
    call-active: cost basis x shares. Missing premium is treated as
    zero, which overstates the loss rather than understating it.
    """
    from models.wheel import WheelPosition, WheelStatus

    positions = (
        db.query(WheelPosition)
        .filter(WheelPosition.status != WheelStatus.closed)
        .all()
    )
    heat = 0.0
    assigned_tickers = {}
    for p in positions:
        shares = p.shares or 100
        if p.cost_basis:
            heat += p.cost_basis * shares
            assigned_tickers[str(p.ticker).upper()] = shares
        elif p.put_strike:
            premium = _num(p.put_premium_rcvd) or 0.0
            heat += max(p.put_strike - premium, 0.0) * shares
    return round(heat, 2), len(positions), assigned_tickers


def wheel_candidates(db):
    """Latest wheel batch as normalized candidates (LIVE only)."""
    from models.wheel import WheelRecommendation
    from sqlalchemy import desc

    latest = (
        db.query(WheelRecommendation.run_at)
        .order_by(desc(WheelRecommendation.run_at))
        .first()
    )
    if not latest:
        return [], None
    rows = (
        db.query(WheelRecommendation)
        .filter(WheelRecommendation.run_at == latest[0])
        .order_by(WheelRecommendation.rank)
        .all()
    )
    out = []
    for r in rows:
        premium = _num(r.put_premium)
        strike = _num(r.put_strike)
        if premium is None or premium <= 0 or not strike:
            continue
        # Stored premium was priced at the bid when the batch ran; no
        # ask was stored, so no spread haircut can be computed. The
        # premium is shown as collected at the bid, with the delay note.
        max_loss = round((strike - premium) * 100, 2)
        out.append({
            "kind": "wheel",
            "ticker": r.ticker,
            "status": "LIVE",
            "setup_key": "wheel",
            "strike": strike,
            "expiry": r.put_expiry,
            "dte": None,
            "delta": None,
            "bid": None,
            "ask": None,
            "mid": None,
            "premium_net_per_share": premium,
            "premium_net_per_contract": round(premium * 100, 2),
            "premium_source": r.premium_source or "bid",
            "chain_source": None,
            # Wheel puts are sized by the premium at risk, not by the
            # assignment worst case: risk_per_contract is the premium
            # collected per contract. max_loss_per_contract below stays
            # the assignment worst case and is shown, not sized on.
            "risk_per_contract": round(premium * 100, 2),
            "risk_measure": "premium_at_risk",
            "max_loss_per_contract": max_loss,
            "notional_per_contract": round(strike * 100, 2),
            "current_price": None,
            "quant_score": _num(r.quant_score),
            "rank_hint": r.rank,
            "invalidation_price": None,
            "iv_rank": _num(r.iv_rank),
            "source_run_at": r.run_at.isoformat() if r.run_at else None,
            "entry_modeled_at": "next open",
            "delay_note": DELAY_NOTE,
        })
    return out, (rows[0].run_at.isoformat() if rows and rows[0].run_at else None)


def alert_candidates(db):
    """SetupAlert rows from the last 36 hours, LIVE and SHADOW split."""
    from datetime import timedelta

    from models.setup_alert import SetupAlert

    cutoff = datetime.now(timezone.utc) - timedelta(hours=36)
    rows = (
        db.query(SetupAlert)
        .filter(
            SetupAlert.fired_at >= cutoff,
            SetupAlert.is_suppressed == False,  # noqa: E712
        )
        .order_by(SetupAlert.fired_at.desc())
        .all()
    )
    live, shadow = [], []
    for a in rows:
        premium = _num(a.premium)
        strike = _num(a.strike)
        max_loss = _num(a.max_loss_per_contract)
        if max_loss is None and premium is not None and strike:
            max_loss = round((strike - premium) * 100, 2)
        cand = {
            "kind": "setup_alert",
            "ticker": a.ticker,
            "status": a.setup_status or "SHADOW",
            "setup_key": a.setup_key,
            "setup_name": a.setup_name,
            "strike": strike,
            "expiry": a.expiry,
            "dte": None,
            "delta": None,
            "bid": None,
            "ask": None,
            "mid": None,
            "premium_net_per_share": premium,
            "premium_net_per_contract": round(premium * 100, 2) if premium is not None else None,
            "premium_source": "bid" if (a.contract_type or "").upper() == "PUT" else "ask",
            "chain_source": None,
            "max_loss_per_contract": max_loss,
            "notional_per_contract": round(strike * 100, 2) if strike else None,
            "current_price": _num(a.entry_price),
            "quant_score": None,
            "invalidation_price": _num(a.invalidation_price),
            "contract_type": a.contract_type,
            "source_run_at": a.fired_at.isoformat() if a.fired_at else None,
            "entry_modeled_at": "next open",
            "delay_note": DELAY_NOTE,
        }
        (live if cand["status"] == "LIVE" else shadow).append(cand)
    return live, shadow


def directional_research(db):
    """Latest directional batch, research only. Never sized: the stored
    premium is a mid, not a tradable bid/ask."""
    from services.directional_engine import get_latest_directional_candidates

    rows = get_latest_directional_candidates(db)
    out = []
    for c in rows:
        if getattr(c, "is_suppressed", False):
            continue
        out.append({
            "kind": "directional",
            "ticker": c.ticker,
            "status": "SHADOW",
            "setup_key": "directional_options",
            "strike": _num(c.strike),
            "expiry": c.expiry,
            "dte": _num(c.dte),
            "delta": _num(c.delta_abs),
            "bid": None,
            "ask": None,
            "mid": _num(c.entry_premium),
            "premium_net_per_share": None,
            "premium_net_per_contract": None,
            "premium_source": "mid_not_tradable",
            "chain_source": None,
            "max_loss_per_contract": _num(c.max_loss_per_contract),
            "notional_per_contract": None,
            "current_price": _num(c.current_price),
            "quant_score": _num(c.score),
            "invalidation_price": _num(c.underlying_stop),
            "option_type": c.option_type,
            "source_run_at": c.run_at.isoformat() if c.run_at else None,
            "entry_modeled_at": "next open",
            "delay_note": DELAY_NOTE,
            "tradable": False,
            "unavailable_reason": "Stored premium is a mid, not a bid or ask. No size is given.",
        })
    return out


def covered_call_candidates(tickers, shares_by_ticker):
    """Middle-tier covered call picks for shares already owned.

    One chain fetch per ticker, capped at 5. A ticker with no chain
    returns an unavailable entry, never an invented strike.
    """
    from services.chain_provider import ChainProvider
    from services.covered_call_picks import build_picks, default_expiry

    out = []
    provider = ChainProvider()
    for ticker in list(tickers or [])[:5]:
        ticker = str(ticker).upper()
        shares = int(shares_by_ticker.get(ticker, 100) or 100)
        try:
            price = provider.fetch_price(ticker)
            expiries = []
            try:
                import yfinance as yf

                tk = yf.Ticker(ticker)
                for exp in tk.options or []:
                    from datetime import date as _date

                    dte = (_date.fromisoformat(exp) - _date.today()).days
                    if dte > 0:
                        expiries.append({"expiry": exp, "dte": dte})
            except Exception:
                expiries = []
            selected = default_expiry(expiries)
            if selected is None or price is None:
                out.append({
                    "kind": "covered_call", "ticker": ticker, "status": "LIVE",
                    "setup_key": "covered_call", "tradable": False,
                    "unavailable_reason": "No listed expiry or price could be found.",
                    "shares_owned": shares,
                })
                continue
            result = provider.fetch(ticker, "call", selected["dte"], selected["dte"], near_price=price)
            if not hasattr(result, "rows"):
                out.append({
                    "kind": "covered_call", "ticker": ticker, "status": "LIVE",
                    "setup_key": "covered_call", "tradable": False,
                    "unavailable_reason": getattr(result, "reason", "No listed options chain was available."),
                    "shares_owned": shares,
                })
                continue
            picks, _ = build_picks(result.rows, price, selected["dte"], shares, None)
            pick = picks.get("middle")
            if pick is None:
                out.append({
                    "kind": "covered_call", "ticker": ticker, "status": "LIVE",
                    "setup_key": "covered_call", "tradable": False,
                    "unavailable_reason": "No middle-tier call strike is listed for this expiry.",
                    "shares_owned": shares,
                })
                continue
            bid = _num(pick.get("bid_per_share"))
            ask = _num(pick.get("ask_per_share"))
            premium, tradable, reason, spread_pct = net_sell_premium(bid, ask)
            if not tradable:
                out.append({
                    "kind": "covered_call", "ticker": ticker, "status": "LIVE",
                    "setup_key": "covered_call", "tradable": False,
                    "unavailable_reason": f"No tradable bid/ask: {reason}.",
                    "shares_owned": shares,
                })
                continue
            contracts = max(shares // 100, 0)
            out.append({
                "kind": "covered_call",
                "ticker": ticker,
                "status": "LIVE",
                "setup_key": "covered_call",
                "strike": _num(pick.get("strike")),
                "expiry": pick.get("expiry"),
                "dte": _num(pick.get("dte")),
                "delta": _num(pick.get("delta")),
                "bid": bid,
                "ask": ask,
                "mid": round((bid + ask) / 2, 2) if bid is not None and ask is not None else None,
                "premium_net_per_share": premium,
                "premium_net_per_contract": round(premium * 100, 2),
                "premium_source": "bid_minus_half_spread",
                "chain_source": getattr(result, "source", None),
                "spread_pct": spread_pct,
                "max_loss_per_contract": 0.0,
                "notional_per_contract": 0.0,
                "current_price": _num(pick.get("current_price")),
                "quant_score": None,
                "invalidation_price": None,
                "shares_owned": shares,
                "contracts_fixed": contracts,
                "source_run_at": None,
                "entry_modeled_at": "next open",
                "delay_note": (
                    "Chain quotes are delayed about 15 minutes (CBOE delayed)."
                    if getattr(result, "source", None) == "cboe_delayed"
                    else DELAY_NOTE
                ),
            })
        except Exception as exc:
            logger.warning("today covered call %s failed: %s", ticker, exc)
            out.append({
                "kind": "covered_call", "ticker": ticker, "status": "LIVE",
                "setup_key": "covered_call", "tradable": False,
                "unavailable_reason": f"Chain lookup failed: {type(exc).__name__}.",
                "shares_owned": shares,
            })
    return out
