"""
Alert outcome journal service.

Daily job: for every open alert in the journal, check current price
against the alert's target, invalidation, and time stop. Closes alerts
when any exit condition is met and records the outcome.

Grading basis (review C13): options alerts are graded on OPTION P&L,
stock alerts on STOCK P&L, in separate columns. They are never mixed
into one profit factor.

Option P&L at close is valued on intrinsic value only: a long option is
worth max(stock - strike, 0) for a call or max(strike - stock, 0) for a
put, minus the premium paid; a short option keeps the premium received
minus the intrinsic value it owes. Time value is treated as zero at
settlement, which matches the review's worked cases exactly (QCOM at
target: +$577 on $460 at risk, about +125%; a call at expiry with stock
at $180, strike $177.50, premium $4.60: -$2.10 per share). The value
basis is recorded on every settled row as "intrinsic_only", so the
number is reproducible without a live option quote. A cash-secured put
whose stock rises is therefore capped at the premium received, and a
flat stock with a put expired worthless grades as the premium kept.

Directional alerts settle on or before expiry, never on the flat 22-day
time stop: the effective time stop is the earlier of 22 days and the
days to the listed expiry, and reaching expiry closes the alert.

Each settled row carries a "settlement" record inside conditions_json
with the outcome basis, the trade spec (strike, expiry, premium), the
open risk recorded at fire time, and the per-trade cap in force at fire
time. Rows settled by the old stock-basis job carry no settlement
record and are excluded from option stats, counted as legacy.

Statistics endpoint: per-setup aggregates computed from the journal rows,
each group labeled with its outcome basis.
"""
import json
import logging
from datetime import datetime, timezone, timedelta, date

logger = logging.getLogger(__name__)

# Trading-day time stop by job type (approximate: calendar days * 1.4)
_TIME_STOP_CALENDAR = {
    "buy_and_hold": 42,   # 30 trading days ~ 42 calendar days
    "wheel": 42,
    "directional": 22,    # 15 trading days ~ 22 calendar days
}

# Setups whose alerts are option trades, graded on option P&L.
OPTION_SETUP_KEYS = {"premium_at_support", "directional_options"}

# One option contract covers 100 shares.
CONTRACT_MULTIPLIER = 100


def _current_price(ticker: str) -> float | None:
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        p = t.fast_info.last_price or t.fast_info.previous_close
        return float(p) if p else None
    except Exception as e:
        logger.debug("price fetch failed %s: %s", ticker, e)
        return None


def _job_for_setup(setup_key: str) -> str:
    mapping = {
        "quality_pullback": "buy_and_hold",
        "premium_at_support": "wheel",
        "volume_breakout": "directional",
        "oversold_bounce": "buy_and_hold",
        "trend_pullback_reversal": "directional",
        "post_earnings_drift": "directional",
    }
    return mapping.get(setup_key, "directional")


def _parse_expiry(expiry) -> date | None:
    """Parse an expiry stored as a date, datetime, or ISO string."""
    if expiry is None:
        return None
    if isinstance(expiry, datetime):
        return expiry.date()
    if isinstance(expiry, date):
        return expiry
    if isinstance(expiry, str):
        text = expiry.strip()
        if not text:
            return None
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None
    return None


def effective_time_stop_days(fired_at: datetime, expiry, default_days: int) -> int:
    """
    Days from fire time until the alert must settle. For an option alert
    with a known expiry this is the earlier of the default time stop and
    the days to expiry, so a Directional alert settles on or before
    expiry, never on the flat 22-day stop. Without an expiry the default
    applies unchanged.
    """
    expiry_date = _parse_expiry(expiry)
    if expiry_date is None:
        return default_days
    fired_date = fired_at.date() if isinstance(fired_at, datetime) else fired_at
    days_to_expiry = (expiry_date - fired_date).days
    return min(default_days, days_to_expiry)


def intrinsic_per_share(contract_type: str | None, strike: float, price: float) -> float | None:
    """Intrinsic value per share of the option at the settlement price."""
    if contract_type == "CALL":
        return max(price - strike, 0.0)
    if contract_type == "PUT":
        return max(strike - price, 0.0)
    return None


def option_pnl_for_close(
    contract_type: str | None,
    strike: float | None,
    premium: float | None,
    settlement_price: float,
    contracts: int = 1,
    max_loss_per_contract: float | None = None,
    action: str | None = None,
) -> dict | None:
    """
    Grade one option trade at close on intrinsic value only.

    Long (BUY): the trader paid the premium and holds intrinsic value at
    close. Short (SELL_*): the trader received the premium and owes
    intrinsic value at close, so the gain is capped at the premium.

    Returns None when the trade cannot be priced (missing contract type,
    strike, or premium). Otherwise returns P&L dollars per position,
    P&L as a percent of max loss at risk, outcome in R, and the inputs
    used, so the number can be recomputed from the row.
    """
    if contract_type not in ("CALL", "PUT"):
        return None
    if strike is None or strike <= 0 or premium is None or premium < 0:
        return None
    if contracts is None or contracts <= 0:
        contracts = 1

    intrinsic = intrinsic_per_share(contract_type, strike, settlement_price)
    short = bool(action) and action.upper().startswith("SELL")

    if short:
        pnl_per_share = premium - intrinsic
        if max_loss_per_contract and max_loss_per_contract > 0:
            max_loss = max_loss_per_contract
        elif contract_type == "PUT":
            # Cash-secured put: worst case is assignment at the strike
            # less the premium already received.
            max_loss = (strike - premium) * CONTRACT_MULTIPLIER
        else:
            max_loss = None
    else:
        pnl_per_share = intrinsic - premium
        if max_loss_per_contract and max_loss_per_contract > 0:
            max_loss = max_loss_per_contract
        else:
            # Long option: the most that can be lost is the premium paid.
            max_loss = premium * CONTRACT_MULTIPLIER

    pnl_dollars = round(pnl_per_share * CONTRACT_MULTIPLIER * contracts, 2)
    if max_loss and max_loss > 0:
        max_loss_total = round(max_loss * contracts, 2)
        pnl_pct = round(pnl_dollars / max_loss_total * 100, 2)
        outcome_r = round(pnl_dollars / max_loss_total, 4)
    else:
        max_loss_total = None
        pnl_pct = None
        outcome_r = None

    return {
        "side": "short" if short else "long",
        "intrinsic_per_share": round(intrinsic, 2),
        "option_value_basis": "intrinsic_only",
        "pnl_dollars": pnl_dollars,
        "pnl_pct": pnl_pct,
        "outcome_r": outcome_r,
        "max_loss_dollars": max_loss_total,
        "contracts": contracts,
    }


def _conditions_dict(row) -> dict:
    try:
        return json.loads(getattr(row, "conditions_json", None) or "{}")
    except Exception:
        return {}


def _has_trade_spec(row, cond: dict) -> bool:
    """True when the row carries an option contract spec anywhere."""
    if getattr(row, "contract_type", None) or getattr(row, "strike", None) is not None:
        return True
    if getattr(row, "premium", None) is not None:
        return True
    for key in ("option_type", "strike", "entry_premium", "premium"):
        if cond.get(key) is not None:
            return True
    return False


def _backfill_trade_spec(row, cond: dict) -> dict:
    """
    Fill missing trade-spec columns from the fire-time snapshot, and
    return the full trade spec for the settlement record (review M35).
    The row must be reconstructable as a trade: strike, expiry, premium.
    """
    spec = {
        "ticker": getattr(row, "ticker", None),
        "setup_key": getattr(row, "setup_key", None),
        "action": getattr(row, "action", None),
        "contract_type": getattr(row, "contract_type", None) or cond.get("option_type"),
        "strike": getattr(row, "strike", None) if getattr(row, "strike", None) is not None else cond.get("strike"),
        "expiry": getattr(row, "expiry", None) or cond.get("expiry"),
        "premium": getattr(row, "premium", None) if getattr(row, "premium", None) is not None else cond.get("entry_premium", cond.get("premium")),
        "entry_price": getattr(row, "entry_price", None),
        "target_price": getattr(row, "target_price", None),
        "invalidation_price": getattr(row, "invalidation_price", None),
        "max_loss_per_contract": getattr(row, "max_loss_per_contract", None),
        "max_loss_per_position": getattr(row, "max_loss_per_position", None),
        "position_size_contracts": getattr(row, "position_size_contracts", None),
        "fired_at": row.fired_at.isoformat() if getattr(row, "fired_at", None) else None,
    }
    if getattr(row, "contract_type", None) is None and spec["contract_type"]:
        row.contract_type = spec["contract_type"]
    if getattr(row, "strike", None) is None and spec["strike"] is not None:
        row.strike = spec["strike"]
    if getattr(row, "expiry", None) is None and spec["expiry"]:
        row.expiry = spec["expiry"]
    if getattr(row, "premium", None) is None and spec["premium"] is not None:
        row.premium = spec["premium"]
    return spec


def _open_risk_at_fire_dollars(row) -> float | None:
    """Open risk recorded at fire time, in dollars (review M29)."""
    if getattr(row, "max_loss_per_position", None):
        return round(float(row.max_loss_per_position), 2)
    per_contract = getattr(row, "max_loss_per_contract", None)
    if per_contract:
        contracts = getattr(row, "position_size_contracts", None) or 1
        return round(float(per_contract) * contracts, 2)
    if getattr(row, "max_loss", None):
        return round(float(row.max_loss), 2)
    return None


def _per_trade_cap_at_fire_dollars(db) -> tuple[float | None, str | None]:
    """
    Per-trade cap in force at fire time, in dollars (review M29). The cap
    is pinned to starting capital, not live equity, so it is the same cap
    the trade was judged against when it fired. Returns (cap, basis).
    """
    try:
        from models.challenge import ChallengeAccount

        account = db.query(ChallengeAccount).order_by(ChallengeAccount.id).first()
        if account is None:
            return None, None
        starting = float(account.starting_capital_cents) / 100.0
        cap = round(starting * float(account.risk_per_trade_pct) / 100.0, 2)
        return cap, "starting_capital"
    except Exception as e:
        logger.debug("per-trade cap lookup failed: %s", e)
        return None, None


def graded_outcome(row) -> dict | None:
    """
    The graded outcome of one settled row, on the correct basis.

    Returns {"basis": "option"|"stock", "pct": float|None,
    "r": float|None, "pnl_dollars": float|None}, or None when the row was
    settled by the old stock-basis job and must not enter option stats:
    a row that carries an option trade spec but no settlement record was
    graded on the underlying stock move, so it is excluded (counted as
    legacy by callers) instead of being mixed into an option profit
    factor. A row with no trade spec at all is graded on the outcome as
    recorded, since no contract exists to re-price.
    """
    cond = _conditions_dict(row)
    settlement = cond.get("settlement") or {}
    basis = settlement.get("outcome_basis")
    if basis == "option":
        return {
            "basis": "option",
            "pct": settlement.get("option_pnl_pct"),
            "r": settlement.get("option_outcome_r"),
            "pnl_dollars": settlement.get("option_pnl_dollars"),
        }
    if basis == "stock":
        return {
            "basis": "stock",
            "pct": getattr(row, "outcome_pct", None),
            "r": getattr(row, "outcome_r", None),
            "pnl_dollars": None,
        }
    if _has_trade_spec(row, cond):
        return None
    if getattr(row, "setup_key", None) in OPTION_SETUP_KEYS:
        return {
            "basis": "option",
            "pct": getattr(row, "outcome_pct", None),
            "r": getattr(row, "outcome_r", None),
            "pnl_dollars": None,
            "legacy_no_spec": True,
        }
    return {
        "basis": "stock",
        "pct": getattr(row, "outcome_pct", None),
        "r": getattr(row, "outcome_r", None),
        "pnl_dollars": None,
    }


def run_outcome_job(db) -> dict:
    """
    Close open alerts when target, stop, expiry, or time stop is hit.
    Returns a summary {"closed": int, "still_open": int, "errors": int}.
    """
    from models.setup_alert import SetupAlert
    import services.run_status as run_status

    run_status.set_running("alert_journal")

    open_alerts = (
        db.query(SetupAlert)
        .filter(
            SetupAlert.is_open == True,  # noqa: E712
            SetupAlert.is_suppressed == False,  # noqa: E712
        )
        .all()
    )

    closed = 0
    still_open = 0
    errors = 0
    now = datetime.now(timezone.utc)
    cap_at_fire, cap_basis = _per_trade_cap_at_fire_dollars(db)

    for alert in open_alerts:
        try:
            price = _current_price(alert.ticker)
            if price is None:
                still_open += 1
                continue

            fired_at = alert.fired_at
            if fired_at.tzinfo is None:
                fired_at = fired_at.replace(tzinfo=timezone.utc)
            days_held = (now - fired_at).days

            job = _job_for_setup(alert.setup_key)
            time_stop_days = _TIME_STOP_CALENDAR.get(job, 42)

            cond = _conditions_dict(alert)
            spec = _backfill_trade_spec(alert, cond)
            is_option = bool(spec["contract_type"] or spec["strike"] is not None)

            # Directional (and any option alert with a listed expiry)
            # settles on or before expiry, never on the flat time stop.
            if is_option and spec["expiry"]:
                time_stop_days = effective_time_stop_days(
                    fired_at, spec["expiry"], time_stop_days
                )

            # Determine exit: target and stop are underlying-price levels.
            close_reason = None
            if alert.target_price and price >= alert.target_price:
                close_reason = "target"
            elif alert.invalidation_price and price <= alert.invalidation_price:
                close_reason = "stop"
            elif spec["expiry"] and _parse_expiry(spec["expiry"]) and now.date() >= _parse_expiry(spec["expiry"]):
                close_reason = "expiry"
            elif days_held >= time_stop_days:
                close_reason = "time_stop"

            if close_reason is None:
                still_open += 1
                continue

            entry = alert.entry_price
            stock_outcome_pct = (
                round((price - entry) / entry * 100, 2)
                if entry and entry > 0
                else None
            )

            settlement = {
                "settlement_underlying_price": price,
                "settlement_date": now.date().isoformat(),
                "close_reason": close_reason,
                "trade_spec": spec,
                "open_risk_at_fire_dollars": _open_risk_at_fire_dollars(alert),
                "per_trade_cap_at_fire_dollars": cap_at_fire,
                "cap_basis": cap_basis,
            }

            if is_option:
                contracts = getattr(alert, "position_size_contracts", None) or 1
                result = option_pnl_for_close(
                    contract_type=spec["contract_type"],
                    strike=spec["strike"],
                    premium=spec["premium"],
                    settlement_price=price,
                    contracts=contracts,
                    max_loss_per_contract=spec["max_loss_per_contract"],
                    action=spec["action"],
                )
                if result is None:
                    # Option trade without a pricable spec: record the
                    # stock move for reference only, never as the grade.
                    alert.is_open = False
                    alert.outcome_pct = stock_outcome_pct
                    alert.outcome_r = None
                    alert.days_held = days_held
                    alert.closed_at = now
                    alert.close_reason = close_reason
                    settlement["outcome_basis"] = "unpriced_option"
                    settlement["stock_outcome_pct"] = stock_outcome_pct
                    settlement["note"] = (
                        "Option trade could not be priced (missing strike "
                        "or premium); outcome_pct is the stock move, not "
                        "an option grade."
                    )
                    cond["settlement"] = settlement
                    alert.conditions_json = json.dumps(cond)
                    closed += 1
                    continue

                settlement["outcome_basis"] = "option"
                settlement["option_pnl_dollars"] = result["pnl_dollars"]
                settlement["option_pnl_pct"] = result["pnl_pct"]
                settlement["option_outcome_r"] = result["outcome_r"]
                settlement["intrinsic_per_share"] = result["intrinsic_per_share"]
                settlement["option_value_basis"] = result["option_value_basis"]
                settlement["option_side"] = result["side"]
                settlement["contracts"] = result["contracts"]
                settlement["max_loss_dollars"] = result["max_loss_dollars"]
                settlement["stock_outcome_pct"] = stock_outcome_pct
                outcome_pct = result["pnl_pct"]
                outcome_r = result["outcome_r"]
            else:
                settlement["outcome_basis"] = "stock"
                if entry and entry > 0:
                    planned_risk = entry - (alert.invalidation_price or entry * 0.95)
                    outcome_r = round((price - entry) / planned_risk, 2) if planned_risk > 0 else None
                else:
                    outcome_r = None
                outcome_pct = stock_outcome_pct

            alert.is_open = False
            alert.outcome_pct = outcome_pct
            alert.outcome_r = outcome_r
            alert.days_held = days_held
            alert.closed_at = now
            alert.close_reason = close_reason
            cond["settlement"] = settlement
            alert.conditions_json = json.dumps(cond)
            closed += 1

        except Exception as e:
            logger.warning("outcome_job: error on alert %s/%s: %s", alert.setup_key, alert.ticker, e)
            errors += 1
            still_open += 1

    try:
        db.commit()
    except Exception as e:
        logger.error("outcome_job: commit failed: %s", e)
        db.rollback()
        run_status.set_error("alert_journal", str(e))
        return {"closed": 0, "still_open": 0, "errors": 1}

    summary = {"closed": closed, "still_open": still_open, "errors": errors}
    run_status.set_success("alert_journal")
    logger.info("alert_journal: outcome job complete: %s", summary)
    return summary


def get_setup_statistics(db, setup_key: str | None = None) -> list[dict]:
    """
    Compute per-setup journal statistics. Option setups are graded on
    option P&L and stock setups on stock P&L; the two are never mixed
    into one profit factor. Each group reports its outcome_basis and
    how many legacy stock-basis rows were excluded.
    """
    from models.setup_alert import SetupAlert
    from sqlalchemy import func

    query = db.query(SetupAlert).filter(SetupAlert.is_suppressed == False)  # noqa: E712
    if setup_key:
        query = query.filter(SetupAlert.setup_key == setup_key)

    all_alerts = query.all()

    # Group by (setup_key, setup_name, setup_status_at_fire)
    groups: dict[tuple, list] = {}
    for a in all_alerts:
        key = (a.setup_key, a.setup_name, a.setup_status)
        groups.setdefault(key, []).append(a)

    stats_list = []
    for (sk, sn, ss), alerts in sorted(groups.items()):
        fired = len(alerts)
        closed_alerts = [a for a in alerts if not a.is_open]
        open_count = fired - len(closed_alerts)
        group_basis = "option" if sk in OPTION_SETUP_KEYS else "stock"

        graded = []
        legacy_excluded = 0
        for a in closed_alerts:
            g = graded_outcome(a)
            if g is None or g["basis"] != group_basis:
                legacy_excluded += 1
                continue
            if g["pct"] is not None:
                graded.append(g)

        closed_pcts = [g["pct"] for g in graded]
        wins = [v for v in closed_pcts if v > 0]
        losses = [v for v in closed_pcts if v <= 0]

        win_rate = round(len(wins) / len(closed_pcts) * 100, 1) if closed_pcts else None
        avg_win = round(sum(wins) / len(wins), 2) if wins else None
        avg_loss = round(sum(losses) / len(losses), 2) if losses else None
        expectancy = round(sum(closed_pcts) / len(closed_pcts), 3) if closed_pcts else None

        gross_win = sum(v for v in closed_pcts if v > 0)
        gross_loss = abs(sum(v for v in closed_pcts if v <= 0))
        profit_factor = round(gross_win / gross_loss, 2) if gross_loss > 0 else None

        option_pnl_total = None
        if group_basis == "option":
            dollars = [g["pnl_dollars"] for g in graded if g.get("pnl_dollars") is not None]
            option_pnl_total = round(sum(dollars), 2) if dollars else None

        stats_list.append({
            "setup_key": sk,
            "setup_name": sn,
            "setup_status_label": ss,
            "alerts_fired": fired,
            "alerts_closed": len(closed_alerts),
            "alerts_open": open_count,
            "outcome_basis": group_basis,
            "legacy_stock_basis_excluded": legacy_excluded,
            "win_rate_pct": win_rate,
            "expectancy_pct": expectancy,
            "avg_win_pct": avg_win,
            "avg_loss_pct": avg_loss,
            "profit_factor": profit_factor,
            "option_pnl_dollars_total": option_pnl_total,
        })

    return stats_list
