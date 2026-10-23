"""
Alert outcome journal service.

Daily job: for every open alert in the journal, check current price
against the alert's target, invalidation, and time stop. Closes alerts
when any exit condition is met and records outcome in percent and R.

Statistics endpoint: per-setup aggregates computed from the journal rows.
"""
import logging
from datetime import datetime, timezone, timedelta, date

logger = logging.getLogger(__name__)

# Trading-day time stop by job type (approximate: calendar days * 1.4)
_TIME_STOP_CALENDAR = {
    "buy_and_hold": 42,   # 30 trading days ~ 42 calendar days
    "wheel": 42,
    "directional": 22,    # 15 trading days ~ 22 calendar days
}


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


def run_outcome_job(db) -> dict:
    """
    Close open alerts when target, stop, or time stop is hit.
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

            # Determine exit
            close_reason = None
            if alert.target_price and price >= alert.target_price:
                close_reason = "target"
            elif alert.invalidation_price and price <= alert.invalidation_price:
                close_reason = "stop"
            elif days_held >= time_stop_days:
                close_reason = "time_stop"

            if close_reason is None:
                still_open += 1
                continue

            # Compute P&L
            entry = alert.entry_price
            if entry and entry > 0:
                outcome_pct = round((price - entry) / entry * 100, 2)
                planned_risk = entry - (alert.invalidation_price or entry * 0.95)
                outcome_r = round((price - entry) / planned_risk, 2) if planned_risk > 0 else None
            else:
                outcome_pct = None
                outcome_r = None

            alert.is_open = False
            alert.outcome_pct = outcome_pct
            alert.outcome_r = outcome_r
            alert.days_held = days_held
            alert.closed_at = now
            alert.close_reason = close_reason
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
    Compute per-setup journal statistics.
    If setup_key is given, returns stats for that setup only.
    """
    from models.setup_alert import SetupAlert
    from sqlalchemy import func

    query = db.query(SetupAlert).filter(SetupAlert.is_suppressed == False)  # noqa: E712
    if setup_key:
        query = query.filter(SetupAlert.setup_key == setup_key)

    all_alerts = query.all()

    # Group by (setup_key, setup_status_at_fire)
    groups: dict[tuple, list] = {}
    for a in all_alerts:
        key = (a.setup_key, a.setup_name, a.setup_status)
        groups.setdefault(key, []).append(a)

    stats_list = []
    for (sk, sn, ss), alerts in sorted(groups.items()):
        fired = len(alerts)
        closed_alerts = [a for a in alerts if not a.is_open]
        open_count = fired - len(closed_alerts)

        closed_pcts = [a.outcome_pct for a in closed_alerts if a.outcome_pct is not None]
        wins = [v for v in closed_pcts if v > 0]
        losses = [v for v in closed_pcts if v <= 0]

        win_rate = round(len(wins) / len(closed_pcts) * 100, 1) if closed_pcts else None
        avg_win = round(sum(wins) / len(wins), 2) if wins else None
        avg_loss = round(sum(losses) / len(losses), 2) if losses else None
        expectancy = round(sum(closed_pcts) / len(closed_pcts), 3) if closed_pcts else None

        gross_win = sum(v for v in closed_pcts if v > 0)
        gross_loss = abs(sum(v for v in closed_pcts if v <= 0))
        profit_factor = round(gross_win / gross_loss, 2) if gross_loss > 0 else None

        stats_list.append({
            "setup_key": sk,
            "setup_name": sn,
            "setup_status_label": ss,
            "alerts_fired": fired,
            "alerts_closed": len(closed_alerts),
            "alerts_open": open_count,
            "win_rate_pct": win_rate,
            "expectancy_pct": expectancy,
            "avg_win_pct": avg_win,
            "avg_loss_pct": avg_loss,
            "profit_factor": profit_factor,
        })

    return stats_list
