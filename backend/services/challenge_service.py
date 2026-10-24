"""
Challenge account accounting.

Money is stored as integer cents in the models; this service computes cash
effects with round() and exposes dollar floats to the API. The core honesty
rule: trading equity excludes net post-start external flows (deposits,
withdrawals, adjustments), so adding money never counts as trading progress.
Dividends and interest are account earnings and stay in trading progress.
"""
import json
import logging
import math
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy.orm import Session

from models.challenge import (
    ChallengeAccount,
    ChallengeAlert,
    ChallengeCashFlow,
    ChallengeSnapshot,
    ChallengeStage,
    ChallengeTrade,
)

logger = logging.getLogger(__name__)

EXTERNAL_FLOW_TYPES = ("deposit", "withdrawal", "adjustment")
FLOW_TYPES = ("initial_funding",) + EXTERNAL_FLOW_TYPES + ("dividend", "interest", "fee")
ASSET_KINDS = ("stock", "call", "put", "spread")
SIDES = ("long", "short")

# Never put more than 10% of starting capital in a single position. This
# mirrors MAX_POSITION_PCT in routers/account.py, which previously was
# read only by GET responses and enforced nowhere.
MAX_POSITION_PCT = 0.10


def _per_trade_cap_cents(account: ChallengeAccount) -> int:
    """Per-trade risk cap, pinned to starting capital (review M27).

    The cap must not float with equity: a losing account would get a
    smaller cap and a winning account a larger one, with no floor.
    """
    return int(round(account.starting_capital_cents * account.risk_per_trade_pct / 100))


def _max_position_cents(account: ChallengeAccount) -> int:
    """Max cost of one position, pinned to starting capital."""
    return int(round(account.starting_capital_cents * MAX_POSITION_PCT))


def _open_risk_cap_cents(trading_equity_cents: int, account: ChallengeAccount) -> int:
    return int(round(trading_equity_cents * account.max_open_risk_pct / 100))


def _cents(dollars: float) -> int:
    return int(round(float(dollars) * 100))


def _dollars(cents: int | None) -> float | None:
    if cents is None:
        return None
    return round(cents / 100, 2)


# ---------------------------------------------------------------------------
# Cash effects
# ---------------------------------------------------------------------------

def open_cash_effect_cents(side: str, quantity: float, entry_price: float,
                           multiplier: float, fees_open_cents: int) -> int:
    gross = quantity * entry_price * multiplier
    if side == "long":
        return int(round(-gross * 100)) - fees_open_cents
    return int(round(gross * 100)) - fees_open_cents


def close_cash_effect_cents(side: str, quantity: float, exit_price: float,
                            multiplier: float, fees_close_cents: int) -> int:
    gross = quantity * exit_price * multiplier
    if side == "long":
        return int(round(gross * 100)) - fees_close_cents
    return int(round(-gross * 100)) - fees_close_cents


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def get_account(db: Session) -> ChallengeAccount | None:
    return db.query(ChallengeAccount).order_by(ChallengeAccount.id).first()


def _current_stage(db: Session, account_id: int) -> ChallengeStage | None:
    active = (
        db.query(ChallengeStage)
        .filter(ChallengeStage.account_id == account_id, ChallengeStage.status == "active")
        .order_by(ChallengeStage.stage_number)
        .first()
    )
    if active:
        return active
    return (
        db.query(ChallengeStage)
        .filter(ChallengeStage.account_id == account_id)
        .order_by(ChallengeStage.stage_number.desc())
        .first()
    )


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _stage_dict(s: ChallengeStage) -> dict:
    return {
        "id": s.id,
        "stage_number": s.stage_number,
        "start_date": s.start_date.isoformat() if s.start_date else None,
        "starting_equity": _dollars(s.starting_equity_cents),
        "target": _dollars(s.target_cents),
        "status": s.status,
        "end_date": s.end_date.isoformat() if s.end_date else None,
        "ending_equity": _dollars(s.ending_equity_cents),
    }


def _flow_dict(f: ChallengeCashFlow) -> dict:
    return {
        "id": f.id,
        "occurred_at": f.occurred_at.isoformat() if f.occurred_at else None,
        "flow_type": f.flow_type,
        "amount": _dollars(f.amount_cents),
        "note": f.note,
    }


def _snapshot_dict(s: ChallengeSnapshot) -> dict:
    return {
        "id": s.id,
        "stage_id": s.stage_id,
        "taken_at": s.taken_at.isoformat() if s.taken_at else None,
        "cash": _dollars(s.cash_cents),
        "open_value": _dollars(s.open_value_cents),
        "equity": _dollars(s.equity_cents),
        "trading_equity": _dollars(s.trading_equity_cents),
        "open_risk": _dollars(s.open_risk_cents),
    }


def _resolve_mark(trade: ChallengeTrade) -> tuple[float, str]:
    """Return (mark_price, mark_source) for an open trade."""
    if trade.current_price is not None:
        return float(trade.current_price), "manual"
    if trade.asset_kind == "stock":
        try:
            from services.stock_data import StockDataService
            price = StockDataService().get_current_price(trade.symbol)
            if price:
                return float(price), "live"
        except Exception as e:
            logger.debug("Challenge live mark failed for %s: %s", trade.symbol, e)
    return float(trade.entry_price), "entry_fallback"


def _trade_dict(t: ChallengeTrade, mark: float | None = None,
                mark_source: str | None = None,
                contribution_cents: int | None = None) -> dict:
    realized = None
    r_multiple = None
    if t.status == "closed" and t.close_cash_effect_cents is not None:
        realized_cents = t.open_cash_effect_cents + t.close_cash_effect_cents
        realized = _dollars(realized_cents)
        if t.planned_max_loss_cents:
            r_multiple = round(realized_cents / t.planned_max_loss_cents, 2)
    unrealized = None
    if t.status == "open" and contribution_cents is not None:
        unrealized = _dollars(t.open_cash_effect_cents + contribution_cents)
    return {
        "id": t.id,
        "opened_at": t.opened_at.isoformat() if t.opened_at else None,
        "closed_at": t.closed_at.isoformat() if t.closed_at else None,
        "status": t.status,
        "asset_kind": t.asset_kind,
        "side": t.side,
        "symbol": t.symbol,
        "underlying": t.underlying,
        "quantity": t.quantity,
        "multiplier": t.multiplier,
        "entry_price": t.entry_price,
        "exit_price": t.exit_price,
        "current_price": t.current_price,
        "mark_price": mark,
        "mark_source": mark_source,
        "value": _dollars(contribution_cents) if contribution_cents is not None else None,
        "unrealized_pnl": unrealized,
        "realized_pnl": realized,
        "r_multiple": r_multiple,
        "fees_open": _dollars(t.fees_open_cents),
        "fees_close": _dollars(t.fees_close_cents),
        "planned_max_loss": _dollars(t.planned_max_loss_cents),
        "target_price": t.target_price,
        "stop_price": t.stop_price,
        "expiry_date": t.expiry_date.isoformat() if t.expiry_date else None,
        "setup_key": t.setup_key,
        "thesis": t.thesis,
        "invalidation": t.invalidation,
        "legs_note": t.legs_note,
        "notes": t.notes,
    }


# ---------------------------------------------------------------------------
# State computation
# ---------------------------------------------------------------------------

def _telegram_configured() -> bool:
    from services import telegram_notifier

    return telegram_notifier.telegram_configured()


def compute_state(db: Session) -> dict:
    account = get_account(db)
    if account is None:
        return {"initialized": False, "telegram_configured": _telegram_configured()}

    stages = (
        db.query(ChallengeStage)
        .filter(ChallengeStage.account_id == account.id)
        .order_by(ChallengeStage.stage_number)
        .all()
    )
    stage = _current_stage(db, account.id)
    flows = (
        db.query(ChallengeCashFlow)
        .filter(ChallengeCashFlow.account_id == account.id)
        .order_by(ChallengeCashFlow.occurred_at, ChallengeCashFlow.id)
        .all()
    )
    trades = (
        db.query(ChallengeTrade)
        .filter(ChallengeTrade.account_id == account.id)
        .order_by(ChallengeTrade.opened_at, ChallengeTrade.id)
        .all()
    )
    snapshots = (
        db.query(ChallengeSnapshot)
        .filter(ChallengeSnapshot.account_id == account.id)
        .order_by(ChallengeSnapshot.taken_at.desc(), ChallengeSnapshot.id.desc())
        .limit(365)
        .all()
    )

    # Cash: every cash flow plus every trade cash effect
    cash_cents = sum(f.amount_cents for f in flows)
    for t in trades:
        cash_cents += t.open_cash_effect_cents
        if t.status == "closed" and t.close_cash_effect_cents is not None:
            cash_cents += t.close_cash_effect_cents

    # Open positions at liquidation value
    open_value_cents = 0
    open_risk_cents = 0
    open_trade_dicts = []
    for t in trades:
        if t.status != "open":
            continue
        mark, source = _resolve_mark(t)
        sign = 1 if t.side == "long" else -1
        contribution = int(round(sign * t.quantity * mark * t.multiplier * 100))
        open_value_cents += contribution
        if t.planned_max_loss_cents:
            open_risk_cents += t.planned_max_loss_cents
        open_trade_dicts.append(_trade_dict(t, mark, source, contribution))

    equity_cents = cash_cents + open_value_cents

    net_external_cents = sum(
        f.amount_cents for f in flows if f.flow_type in EXTERNAL_FLOW_TYPES
    )
    trading_equity_cents = equity_cents - net_external_cents
    trading_pnl_cents = trading_equity_cents - account.starting_capital_cents

    # Peak and drawdown from snapshots plus current values
    peak_cents = max(
        [account.starting_capital_cents, trading_equity_cents]
        + [s.trading_equity_cents for s in snapshots]
    )
    drawdown_cents = peak_cents - trading_equity_cents
    drawdown_pct = round(drawdown_cents / peak_cents * 100, 1) if peak_cents > 0 else 0.0

    # Progress within the current stage
    progress = None
    if stage is not None:
        start = stage.starting_equity_cents
        target = stage.target_cents
        multiple = round(trading_equity_cents / start, 3) if start > 0 else None
        if trading_equity_cents > 0 and start > 0 and target > start:
            log_progress = math.log(trading_equity_cents / start) / math.log(target / start)
            log_progress = max(0.0, min(1.0, log_progress))
        else:
            log_progress = 0.0
        progress = {
            "multiple": multiple,
            "log_progress_pct": round(log_progress * 100, 1),
            "remaining": _dollars(max(target - trading_equity_cents, 0)),
        }

    risk_caps = {
        "risk_per_trade_pct": account.risk_per_trade_pct,
        "max_open_risk_pct": account.max_open_risk_pct,
        "pause_drawdown_pct": account.pause_drawdown_pct,
        # Pinned to starting capital, not floating with equity (review M27).
        "per_trade_cap": _dollars(_per_trade_cap_cents(account)),
        "open_risk_cap": _dollars(_open_risk_cap_cents(trading_equity_cents, account)),
        "max_position_pct": MAX_POSITION_PCT * 100,
        "max_single_position": _dollars(_max_position_cents(account)),
        "paused": drawdown_pct >= account.pause_drawdown_pct if account.pause_drawdown_pct else False,
    }

    closed_dicts = [
        _trade_dict(t) for t in trades if t.status == "closed"
    ]

    alerts = (
        db.query(ChallengeAlert)
        .filter(ChallengeAlert.account_id == account.id)
        .order_by(ChallengeAlert.created_at.desc(), ChallengeAlert.id.desc())
        .limit(50)
        .all()
    )
    unread_count = (
        db.query(ChallengeAlert)
        .filter(
            ChallengeAlert.account_id == account.id,
            ChallengeAlert.status == "unread",
        )
        .count()
    )

    return {
        "initialized": True,
        "account": {
            "id": account.id,
            "start_date": account.start_date.isoformat() if account.start_date else None,
            "starting_capital": _dollars(account.starting_capital_cents),
            "risk_per_trade_pct": account.risk_per_trade_pct,
            "max_open_risk_pct": account.max_open_risk_pct,
            "pause_drawdown_pct": account.pause_drawdown_pct,
            "created_at": account.created_at.isoformat() if account.created_at else None,
        },
        "current_stage": _stage_dict(stage) if stage else None,
        "stages": [_stage_dict(s) for s in stages],
        "cash": _dollars(cash_cents),
        "open_value": _dollars(open_value_cents),
        "equity": _dollars(equity_cents),
        "trading_equity": _dollars(trading_equity_cents),
        "trading_pnl": _dollars(trading_pnl_cents),
        "open_risk": _dollars(open_risk_cents),
        "risk_caps": risk_caps,
        "peak_trading_equity": _dollars(peak_cents),
        "drawdown": _dollars(drawdown_cents),
        "drawdown_pct": drawdown_pct,
        "progress": progress,
        "cash_flows": [_flow_dict(f) for f in flows],
        "open_trades": open_trade_dicts,
        "closed_trades": closed_dicts,
        "snapshots": [_snapshot_dict(s) for s in snapshots],
        "scoreboard": _scoreboard(trades),
        "alerts": [_alert_dict(a) for a in alerts],
        "unread_alert_count": unread_count,
        "telegram_configured": _telegram_configured(),
    }


def _alert_dict(a: ChallengeAlert) -> dict:
    data = None
    if a.data_json:
        try:
            data = json.loads(a.data_json)
        except Exception:
            data = None
    return {
        "id": a.id,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "alert_type": a.alert_type,
        "source_type": a.source_type,
        "source_id": a.source_id,
        "ticker": a.ticker,
        "title": a.title,
        "body": a.body,
        "severity": a.severity,
        "status": a.status,
        "data": data,
    }


def _scoreboard(trades: list[ChallengeTrade]) -> dict:
    closed = [t for t in trades if t.status == "closed" and t.close_cash_effect_cents is not None]
    closed.sort(key=lambda t: (t.closed_at or t.opened_at, t.id))
    pnls = [t.open_cash_effect_cents + t.close_cash_effect_cents for t in closed]
    n = len(pnls)
    if n == 0:
        return {
            "count": 0, "wins": 0, "losses": 0, "total_pnl": 0.0,
            "expectancy": None, "expectancy_r": None, "profit_factor": None,
            "avg_win": None, "avg_loss": None, "best": None, "worst": None,
            "losing_streak": 0,
        }
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    rs = [
        (t.open_cash_effect_cents + t.close_cash_effect_cents) / t.planned_max_loss_cents
        for t in closed if t.planned_max_loss_cents
    ]
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    streak = 0
    for p in reversed(pnls):
        if p < 0:
            streak += 1
        else:
            break
    return {
        "count": n,
        "wins": len(wins),
        "losses": len(losses),
        "total_pnl": _dollars(sum(pnls)),
        "expectancy": _dollars(int(round(sum(pnls) / n))),
        "expectancy_r": round(sum(rs) / len(rs), 2) if rs else None,
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else None,
        "avg_win": _dollars(int(round(gross_win / len(wins)))) if wins else None,
        "avg_loss": _dollars(int(round(-gross_loss / len(losses)))) if losses else None,
        "best": _dollars(max(pnls)),
        "worst": _dollars(min(pnls)),
        "losing_streak": streak,
    }


# ---------------------------------------------------------------------------
# Alert generation
#
# Event alerts (an eligible setup, a milestone) dedupe permanently per
# source. Condition alerts (position review, drawdown) dedupe per day, so
# a condition that persists can remind once a day but never more.
# A section that fails (missing source table, bad row) is skipped and
# logged; generation never breaks the snapshot flow.
# ---------------------------------------------------------------------------

def _create_alert(db: Session, existing: set, account_id: int, **kw) -> int:
    key = kw["dedupe_key"]
    if key in existing:
        return 0
    db.add(ChallengeAlert(
        account_id=account_id,
        stage_id=kw.get("stage_id"),
        alert_type=kw["alert_type"],
        source_type=kw["source_type"],
        source_id=kw.get("source_id"),
        ticker=kw.get("ticker"),
        title=kw["title"],
        body=kw.get("body"),
        severity=kw.get("severity", "info"),
        status="unread",
        dedupe_key=key,
        data_json=json.dumps(kw["data"]) if kw.get("data") else None,
    ))
    existing.add(key)
    return 1


def _gen_eligible_setups(db: Session, account, state, existing) -> int:
    from models.setup_alert import SetupAlert

    cap = state["risk_caps"]["per_trade_cap"] or 0
    cash = state["cash"] or 0
    if cap <= 0 or cash <= 0:
        return 0
    # Stop alerting once the open-risk cap is reached, and keep a running
    # total across this run so several ideas cannot be alerted at once
    # for more risk than the cap allows (review C15).
    open_risk = state["open_risk"] or 0
    open_cap = state["risk_caps"]["open_risk_cap"] or 0
    if open_cap > 0 and open_risk >= open_cap:
        return 0
    position_cap = state["risk_caps"]["max_single_position"] or 0
    running_risk = open_risk
    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
    rows = (
        db.query(SetupAlert)
        .filter(
            SetupAlert.setup_status == "LIVE",
            SetupAlert.is_suppressed == False,  # noqa: E712
            SetupAlert.is_open == True,  # noqa: E712
        )
        .order_by(SetupAlert.fired_at.desc())
        .limit(200)
        .all()
    )
    created = 0
    for r in rows:
        fired = r.fired_at
        if fired is not None:
            if fired.tzinfo is None:
                fired = fired.replace(tzinfo=timezone.utc)
            if fired < cutoff:
                continue
        entry, stop, target = r.entry_price, r.invalidation_price, r.target_price
        if not entry or not stop or not (entry > stop > 0):
            continue
        risk_per_share = entry - stop
        shares = math.floor(cap / risk_per_share)
        if shares < 1:
            continue
        # Size the position so it fits the max single position as well as
        # the per-trade risk cap, or the alert would suggest a trade the
        # write path must refuse.
        if position_cap > 0:
            shares = min(shares, math.floor(position_cap / entry))
            if shares < 1:
                continue
        required = shares * entry
        if required > cash:
            continue
        risk_dollars = round(shares * risk_per_share, 2)
        if open_cap > 0 and running_risk + risk_dollars > open_cap:
            continue
        payload = {
            "asset_kind": "stock", "side": "long", "symbol": r.ticker,
            "setup_key": r.setup_key, "quantity": shares,
            "entry_price": entry, "stop_price": stop, "target_price": target,
            "planned_max_loss": risk_dollars, "required_cash": round(required, 2),
        }
        body = (
            f"LIVE setup fired recently. {shares} shares at ${entry:.2f} risks about "
            f"${risk_dollars:.2f} to the ${stop:.2f} stop, inside your ${cap:.2f} per-trade cap."
        )
        if target:
            body += f" Target ${target:.2f}."
        if r.action_summary:
            body += f" {r.action_summary}"
        made = _create_alert(
            db, existing, account.id,
            alert_type="eligible_setup", source_type="setup_alert", source_id=r.id,
            ticker=r.ticker, severity="opportunity",
            dedupe_key=f"eligible_setup:{r.id}",
            title=f"{r.ticker}: {r.setup_name} fits your risk budget",
            body=body, data=payload,
        )
        created += made
        if made:
            running_risk += risk_dollars
    return created


def _gen_eligible_directional(db: Session, account, state, existing) -> int:
    from models.directional_candidate import DirectionalCandidate

    cap = state["risk_caps"]["per_trade_cap"] or 0
    cash = state["cash"] or 0
    if cap <= 0 or cash <= 0:
        return 0
    # Stop alerting once the open-risk cap is reached, and keep a running
    # total across this run so several ideas cannot be alerted at once
    # for more risk than the cap allows (review C15).
    open_risk = state["open_risk"] or 0
    open_cap = state["risk_caps"]["open_risk_cap"] or 0
    if open_cap > 0 and open_risk >= open_cap:
        return 0
    running_risk = open_risk
    rows = (
        db.query(DirectionalCandidate)
        .filter(DirectionalCandidate.is_suppressed == False)  # noqa: E712
        .order_by(DirectionalCandidate.run_at.desc())
        .limit(100)
        .all()
    )
    if not rows:
        return 0
    latest_run = max(r.run_at for r in rows if r.run_at is not None)
    created = 0
    for r in rows:
        if r.run_at != latest_run:
            continue
        if r.entry_premium is None or r.max_loss_per_contract is None:
            continue
        kind = (r.option_type or "").lower()
        if kind not in ("call", "put"):
            continue
        premium_cost = round(r.entry_premium * 100, 2)
        if r.max_loss_per_contract > cap or premium_cost > cash:
            continue
        if open_cap > 0 and running_risk + r.max_loss_per_contract > open_cap:
            continue
        legs = None
        if r.strike is not None:
            legs = f"{r.option_type} {r.strike} exp {r.expiry}"
        payload = {
            "asset_kind": kind, "side": "long", "symbol": r.ticker,
            "underlying": r.ticker, "quantity": 1,
            "entry_price": r.entry_premium,
            "planned_max_loss": r.max_loss_per_contract,
            "target_price": r.underlying_target, "stop_price": r.underlying_stop,
            "expiry_date": r.expiry, "setup_key": "directional_options",
            "legs_note": legs,
        }
        body = (
            f"One {kind} contract costs about ${premium_cost:.2f} with a stated max loss of "
            f"${r.max_loss_per_contract:.2f}, inside your ${cap:.2f} per-trade cap."
        )
        if r.payoff_at_target is not None:
            body += f" Payoff at target: ${r.payoff_at_target:.2f} per contract."
        if r.underlying_target is not None:
            body += f" Underlying target ${r.underlying_target:.2f}."
        if r.earnings_in_window:
            body += " Earnings fall inside the window."
        made = _create_alert(
            db, existing, account.id,
            alert_type="eligible_directional", source_type="directional_candidate",
            source_id=r.id, ticker=r.ticker, severity="opportunity",
            dedupe_key=f"eligible_directional:{r.id}",
            title=f"{r.ticker} {r.option_type} {r.strike}: one contract fits",
            body=body, data=payload,
        )
        created += made
        if made:
            running_risk += r.max_loss_per_contract
    return created


def _gen_position_reviews(db: Session, account, existing, today_str: str) -> int:
    trades = (
        db.query(ChallengeTrade)
        .filter(
            ChallengeTrade.account_id == account.id,
            ChallengeTrade.status == "open",
        )
        .all()
    )
    today = date.today()
    created = 0
    for t in trades:
        mark, _source = _resolve_mark(t)
        sign = 1 if t.side == "long" else -1
        contribution = int(round(sign * t.quantity * mark * t.multiplier * 100))
        unrealized = t.open_cash_effect_cents + contribution
        if t.planned_max_loss_cents:
            ratio = unrealized / t.planned_max_loss_cents
            if ratio >= 0.75:
                created += _create_alert(
                    db, existing, account.id,
                    alert_type="position_review", source_type="challenge_trade",
                    source_id=t.id, ticker=t.symbol, severity="action",
                    dedupe_key=f"position_review:{t.id}:pnl_up:{today_str}",
                    title=f"{t.symbol}: up {round(ratio * 100)}% of planned risk",
                    body="Unrealized gain has reached 75% of the planned max loss. Review the position: take profit, trail the stop, or hold with intent.",
                )
            elif ratio <= -0.75:
                created += _create_alert(
                    db, existing, account.id,
                    alert_type="position_review", source_type="challenge_trade",
                    source_id=t.id, ticker=t.symbol, severity="action",
                    dedupe_key=f"position_review:{t.id}:pnl_down:{today_str}",
                    title=f"{t.symbol}: down {abs(round(ratio * 100))}% of planned risk",
                    body="Unrealized loss is near the planned max loss. Review the exit before the plan is breached.",
                )
        if t.asset_kind in ("call", "put", "spread") and t.expiry_date:
            days = (t.expiry_date - today).days
            if 0 <= days <= 3:
                created += _create_alert(
                    db, existing, account.id,
                    alert_type="position_review", source_type="challenge_trade",
                    source_id=t.id, ticker=t.symbol, severity="warning",
                    dedupe_key=f"position_review:{t.id}:expiry:{today_str}",
                    title=f"{t.symbol}: expires in {days} day{'s' if days != 1 else ''}",
                    body="This option or spread expires within 3 days. Decide the exit now, not at the close on expiry day.",
                )
        if t.asset_kind == "stock" and t.target_price:
            if abs(mark - t.target_price) / t.target_price <= 0.10:
                created += _create_alert(
                    db, existing, account.id,
                    alert_type="position_review", source_type="challenge_trade",
                    source_id=t.id, ticker=t.symbol, severity="info",
                    dedupe_key=f"position_review:{t.id}:target:{today_str}",
                    title=f"{t.symbol}: within 10% of your target",
                    body=f"Mark is ${mark:.2f} against a target of ${t.target_price:.2f}. Decide the exit before it gets there.",
                )
    return created


def _gen_milestones(db: Session, account, stage, state, existing) -> int:
    if stage is None:
        return 0
    te = state["trading_equity"] or 0
    start = stage.starting_equity_cents / 100
    if start <= 0 or te <= 0:
        return 0
    multiple = te / start
    target_multiple = stage.target_cents / stage.starting_equity_cents
    created = 0
    for m in [1.5, 2, 3, 5, target_multiple]:
        if multiple >= m:
            label = f"{m:g}x"
            created += _create_alert(
                db, existing, account.id,
                alert_type="milestone", source_type="snapshot", source_id=None,
                stage_id=stage.id, severity="opportunity" if m == target_multiple else "info",
                dedupe_key=f"milestone:stage{stage.id}:{label}",
                title=f"Stage {stage.stage_number} crossed {label}",
                body=f"Trading equity is ${te:,.2f}, {multiple:.2f}x the stage start of ${start:,.2f}.",
            )
    return created


def _gen_drawdown(db: Session, account, stage, state, existing, today_str: str) -> int:
    pause = account.pause_drawdown_pct or 0
    dd = state["drawdown_pct"] or 0
    if pause <= 0 or dd <= 0:
        return 0
    stage_id = stage.id if stage else 0
    if dd >= pause:
        return _create_alert(
            db, existing, account.id,
            alert_type="drawdown_warning", source_type="account", source_id=None,
            stage_id=stage.id if stage else None, severity="action",
            dedupe_key=f"drawdown:stage{stage_id}:full:{today_str}",
            title="Drawdown at your pause line",
            body=f"Down {dd}% from peak, at or past your {pause:g}% pause rule. Your plan says stop and review before new trades.",
        )
    if dd >= pause / 2:
        return _create_alert(
            db, existing, account.id,
            alert_type="drawdown_warning", source_type="account", source_id=None,
            stage_id=stage.id if stage else None, severity="warning",
            dedupe_key=f"drawdown:stage{stage_id}:half:{today_str}",
            title="Drawdown past half your pause line",
            body=f"Down {dd}% from peak. Your pause rule trips at {pause:g}%. Consider smaller size until the curve turns.",
        )
    return 0


def _notify_new_alerts(db: Session, account_id: int, new_keys: set) -> None:
    """Best-effort Telegram notification for alerts created in this run.

    Deliberately isolated: a notifier failure can never break alert
    generation, snapshots, or stage graduation. Keys whose rows were
    rolled back by a failed section simply match nothing in the query.
    """
    if not new_keys:
        return
    try:
        from services import telegram_notifier

        rows = (
            db.query(ChallengeAlert)
            .filter(
                ChallengeAlert.account_id == account_id,
                ChallengeAlert.dedupe_key.in_(new_keys),
            )
            .order_by(ChallengeAlert.id)
            .all()
        )
        if rows:
            telegram_notifier.notify_new_alerts(rows)
    except Exception as e:
        logger.warning("Challenge Telegram notify failed: %s", type(e).__name__)


def generate_challenge_alerts(db: Session) -> int:
    """Generate any new challenge alerts. Returns how many were created."""
    account = get_account(db)
    if account is None:
        return 0
    state = compute_state(db)
    existing = {
        k for (k,) in db.query(ChallengeAlert.dedupe_key)
        .filter(ChallengeAlert.account_id == account.id)
        .all()
    }
    existing_before = set(existing)
    stage = _current_stage(db, account.id)
    today_str = date.today().isoformat()
    created = 0
    sections = [
        ("eligible_setups", lambda: _gen_eligible_setups(db, account, state, existing)),
        ("eligible_directional", lambda: _gen_eligible_directional(db, account, state, existing)),
        ("position_reviews", lambda: _gen_position_reviews(db, account, existing, today_str)),
        ("milestones", lambda: _gen_milestones(db, account, stage, state, existing)),
        ("drawdown", lambda: _gen_drawdown(db, account, stage, state, existing, today_str)),
    ]
    for name, fn in sections:
        try:
            created += fn()
        except Exception as e:
            db.rollback()
            logger.warning("Challenge alert section %s failed: %s", name, e)
    db.commit()
    if created:
        logger.info("Challenge alerts: %d new", created)
        _notify_new_alerts(db, account.id, existing - existing_before)
    return created


def set_alert_status(db: Session, alert_id: int, status: str) -> dict:
    if status not in ("unread", "read", "dismissed", "acted"):
        raise ValueError(f"Invalid alert status: {status}")
    alert = db.query(ChallengeAlert).filter(ChallengeAlert.id == alert_id).first()
    if alert is None:
        raise ValueError("Alert not found")
    alert.status = status
    db.commit()
    db.refresh(alert)
    return _alert_dict(alert)


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------

def init_account(db: Session, start_date: date, starting_capital_cents: int,
                 risk_per_trade_pct: float = 5, max_open_risk_pct: float = 20,
                 pause_drawdown_pct: float = 40) -> dict:
    if get_account(db) is not None:
        raise ValueError("Challenge account already initialized")
    account = ChallengeAccount(
        start_date=start_date,
        starting_capital_cents=starting_capital_cents,
        risk_per_trade_pct=risk_per_trade_pct,
        max_open_risk_pct=max_open_risk_pct,
        pause_drawdown_pct=pause_drawdown_pct,
    )
    db.add(account)
    db.flush()
    stage = ChallengeStage(
        account_id=account.id,
        stage_number=1,
        start_date=start_date,
        starting_equity_cents=starting_capital_cents,
        target_cents=starting_capital_cents * 10,
        status="active",
    )
    db.add(stage)
    db.add(ChallengeCashFlow(
        account_id=account.id,
        occurred_at=datetime.combine(start_date, time.min, tzinfo=timezone.utc),
        flow_type="initial_funding",
        amount_cents=starting_capital_cents,
        note="Initial funding",
    ))
    db.commit()
    return compute_state(db)


def add_cash_flow(db: Session, flow_type: str, amount_dollars: float,
                  occurred_at: datetime | None = None, note: str | None = None) -> dict:
    account = get_account(db)
    if account is None:
        raise ValueError("Challenge account not initialized")
    if flow_type not in FLOW_TYPES or flow_type == "initial_funding":
        raise ValueError(f"Invalid flow_type: {flow_type}")
    cents = _cents(amount_dollars)
    if flow_type in ("deposit", "dividend", "interest"):
        cents = abs(cents)
    elif flow_type in ("withdrawal", "fee"):
        cents = -abs(cents)
    # adjustment keeps the sign exactly as entered
    flow = ChallengeCashFlow(
        account_id=account.id,
        occurred_at=occurred_at or datetime.now(timezone.utc),
        flow_type=flow_type,
        amount_cents=cents,
        note=note,
    )
    db.add(flow)
    db.commit()
    db.refresh(flow)
    return _flow_dict(flow)


def add_trade(db: Session, data: dict) -> dict:
    """Open a trade, enforcing the risk caps at the write path (review C15).

    Every rejection names the violated rule. Nothing is silently accepted:
    a trade that breaks a cap, would take cash negative, or is entered
    while the account is paused is refused with a ValueError.
    """
    account = get_account(db)
    if account is None:
        raise ValueError("Challenge account not initialized")
    asset_kind = data.get("asset_kind", "stock")
    side = data.get("side", "long")
    if asset_kind not in ASSET_KINDS:
        raise ValueError(f"Invalid asset_kind: {asset_kind}")
    if side not in SIDES:
        raise ValueError(f"Invalid side: {side}")
    try:
        quantity = float(data["quantity"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("quantity is required and must be a number above 0")
    if quantity <= 0:
        raise ValueError(f"quantity must be above 0 (got {quantity})")
    try:
        entry_price = float(data["entry_price"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("entry_price is required and must be a number above 0")
    if entry_price <= 0:
        raise ValueError(f"entry_price must be above 0 (got {entry_price})")
    multiplier = data.get("multiplier")
    if multiplier is None:
        multiplier = 1 if asset_kind == "stock" else 100
    try:
        multiplier = float(multiplier)
    except (TypeError, ValueError):
        raise ValueError("multiplier must be a number above 0")
    if multiplier <= 0:
        raise ValueError(f"multiplier must be above 0 (got {multiplier})")

    # Planned max loss is required for every trade. A short position with
    # no planned max loss has theoretically uncapped loss, so a missing
    # value blocks the trade and is never counted as zero risk.
    planned = data.get("planned_max_loss")
    if planned is None:
        if side == "short":
            raise ValueError(
                "planned_max_loss is required for a short trade: a short "
                "position has uncapped loss without one, so it cannot be "
                "recorded as zero risk"
            )
        raise ValueError(
            "planned_max_loss is required: every trade must state its "
            "planned max loss"
        )
    try:
        planned_cents = _cents(planned)
    except (TypeError, ValueError):
        raise ValueError("planned_max_loss must be a number above 0")
    if planned_cents <= 0:
        raise ValueError(f"planned_max_loss must be above 0 (got {planned})")

    # Caps and current state, all read before the trade is recorded.
    state = compute_state(db)
    per_trade_cap_cents = _per_trade_cap_cents(account)
    if planned_cents > per_trade_cap_cents:
        raise ValueError(
            f"planned_max_loss ${_dollars(planned_cents):.2f} exceeds the "
            f"per-trade cap of ${_dollars(per_trade_cap_cents):.2f} "
            f"({account.risk_per_trade_pct:g}% of starting capital "
            f"${_dollars(account.starting_capital_cents):.2f})"
        )
    if state["risk_caps"]["paused"]:
        raise ValueError(
            f"account is paused at {state['drawdown_pct']}% drawdown "
            f"(pause line {account.pause_drawdown_pct:g}%): no new trades"
        )
    open_risk_cents = _cents(state["open_risk"])
    open_risk_cap_cents = _cents(state["risk_caps"]["open_risk_cap"])
    if open_risk_cents + planned_cents > open_risk_cap_cents:
        raise ValueError(
            f"open risk after this trade would be "
            f"${_dollars(open_risk_cents + planned_cents):.2f}, above the "
            f"open-risk cap of ${_dollars(open_risk_cap_cents):.2f} "
            f"({account.max_open_risk_pct:g}% of trading equity)"
        )
    position_cents = int(round(quantity * entry_price * multiplier * 100))
    max_position_cents = _max_position_cents(account)
    if position_cents > max_position_cents:
        raise ValueError(
            f"position cost ${_dollars(position_cents):.2f} exceeds the max "
            f"single position of ${_dollars(max_position_cents):.2f} "
            f"({MAX_POSITION_PCT * 100:g}% of starting capital "
            f"${_dollars(account.starting_capital_cents):.2f})"
        )
    fees_open_cents = _cents(data.get("fees_open") or 0)
    effect = open_cash_effect_cents(
        side, quantity, entry_price, multiplier, fees_open_cents,
    )
    cash_cents = _cents(state["cash"])
    if cash_cents + effect < 0:
        raise ValueError(
            f"required cash ${_dollars(-effect):.2f} exceeds available cash "
            f"${_dollars(cash_cents):.2f}: this trade would take cash negative"
        )

    trade = ChallengeTrade(
        account_id=account.id,
        opened_at=data.get("opened_at") or datetime.now(timezone.utc),
        status="open",
        asset_kind=asset_kind,
        side=side,
        symbol=str(data["symbol"]).upper(),
        underlying=(str(data["underlying"]).upper() if data.get("underlying") else str(data["symbol"]).upper()),
        quantity=quantity,
        multiplier=multiplier,
        entry_price=entry_price,
        current_price=data.get("current_price"),
        fees_open_cents=fees_open_cents,
        fees_close_cents=0,
        open_cash_effect_cents=effect,
        planned_max_loss_cents=planned_cents,
        target_price=data.get("target_price"),
        stop_price=data.get("stop_price"),
        expiry_date=data.get("expiry_date"),
        setup_key=data.get("setup_key"),
        thesis=data.get("thesis"),
        invalidation=data.get("invalidation"),
        legs_note=data.get("legs_note"),
        notes=data.get("notes"),
    )
    db.add(trade)
    db.commit()
    db.refresh(trade)
    return _trade_dict(trade)


def update_mark(db: Session, trade_id: int, current_price: float) -> dict:
    trade = db.query(ChallengeTrade).filter(ChallengeTrade.id == trade_id).first()
    if trade is None:
        raise ValueError("Trade not found")
    if trade.status != "open":
        raise ValueError("Trade is already closed")
    trade.current_price = float(current_price)
    db.commit()
    db.refresh(trade)
    return _trade_dict(trade)


def close_trade(db: Session, trade_id: int, exit_price: float,
                fees_close_dollars: float = 0, closed_at: datetime | None = None) -> dict:
    trade = db.query(ChallengeTrade).filter(ChallengeTrade.id == trade_id).first()
    if trade is None:
        raise ValueError("Trade not found")
    if trade.status != "open":
        raise ValueError("Trade is already closed")
    fees_close_cents = _cents(fees_close_dollars or 0)
    trade.exit_price = float(exit_price)
    trade.fees_close_cents = fees_close_cents
    trade.close_cash_effect_cents = close_cash_effect_cents(
        trade.side, trade.quantity, float(exit_price), trade.multiplier, fees_close_cents,
    )
    trade.closed_at = closed_at or datetime.now(timezone.utc)
    trade.status = "closed"
    db.commit()
    db.refresh(trade)
    return _trade_dict(trade)


def take_snapshot(db: Session) -> dict:
    """Save a snapshot for the current stage, then run the graduation check."""
    account = get_account(db)
    if account is None:
        raise ValueError("Challenge account not initialized")
    state = compute_state(db)
    stage = _current_stage(db, account.id)
    snap = ChallengeSnapshot(
        account_id=account.id,
        stage_id=stage.id if stage else None,
        taken_at=datetime.now(timezone.utc),
        cash_cents=_cents(state["cash"]),
        open_value_cents=_cents(state["open_value"]),
        equity_cents=_cents(state["equity"]),
        trading_equity_cents=_cents(state["trading_equity"]),
        open_risk_cents=_cents(state["open_risk"]),
    )
    db.add(snap)
    db.commit()

    # Alert generation runs on the pre-graduation state so milestone and
    # target alerts attach to the stage that earned them.
    try:
        generate_challenge_alerts(db)
    except Exception as e:
        logger.warning("Challenge alert generation in snapshot failed: %s", e)

    trading_equity_cents = _cents(state["trading_equity"])
    stage = _current_stage(db, account.id)
    while (
        stage is not None
        and stage.status == "active"
        and trading_equity_cents >= stage.target_cents
        and stage.target_cents > stage.starting_equity_cents
    ):
        stage.status = "graduated"
        stage.end_date = date.today()
        stage.ending_equity_cents = trading_equity_cents
        db.flush()
        next_stage = ChallengeStage(
            account_id=account.id,
            stage_number=stage.stage_number + 1,
            start_date=date.today(),
            starting_equity_cents=trading_equity_cents,
            target_cents=trading_equity_cents * 10,
            status="active",
        )
        db.add(next_stage)
        db.commit()
        logger.info(
            "Challenge stage %d graduated at $%.2f; stage %d started toward $%.2f",
            stage.stage_number, trading_equity_cents / 100,
            next_stage.stage_number, next_stage.target_cents / 100,
        )
        stage = _current_stage(db, account.id)

    return compute_state(db)
