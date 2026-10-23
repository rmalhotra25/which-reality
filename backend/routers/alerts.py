"""
Alerts router.

Endpoints:
  GET  /api/alerts/registry              -- all six setups with status and recipe
  POST /api/alerts/registry/{key}/status -- update a setup's status (enforced)
  GET  /api/alerts/today                 -- today's alerts (LIVE first, then SHADOW)
  GET  /api/alerts/journal               -- journal rows (recent closed + open)
  GET  /api/alerts/stats                 -- per-setup statistics
  POST /api/alerts/run                   -- trigger an immediate engine run (test/manual)
  POST /api/alerts/outcome-job           -- trigger an immediate outcome job
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from database import get_db

router = APIRouter(prefix="/api/alerts", tags=["Alerts"])


class SetStatusBody(BaseModel):
    status: str


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

@router.get("/registry")
def get_registry(db=Depends(get_db)):
    from services.setup_registry_service import get_all_setups
    rows = get_all_setups(db)
    return [
        {
            "id": r.id,
            "setup_key": r.setup_key,
            "name": r.name,
            "job": r.job,
            "recipe": r.recipe,
            "status": r.status,
            "backtest_file": r.backtest_file,
            "backtest_verdict": r.backtest_verdict,
            "backtest_data_source": r.backtest_data_source,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in rows
    ]


@router.post("/registry/{setup_key}/status")
def update_status(setup_key: str, body: SetStatusBody, db=Depends(get_db)):
    from services.setup_registry_service import set_setup_status
    try:
        return set_setup_status(db, setup_key, body.status.upper())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ---------------------------------------------------------------------------
# Today's alerts
# ---------------------------------------------------------------------------

@router.get("/today")
def get_today_alerts(db=Depends(get_db)):
    from models.setup_alert import SetupAlert
    from datetime import datetime, timezone, timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(hours=36)
    alerts = (
        db.query(SetupAlert)
        .filter(
            SetupAlert.fired_at >= cutoff,
            SetupAlert.is_suppressed == False,  # noqa: E712
        )
        .order_by(SetupAlert.fired_at.desc())
        .all()
    )
    suppressed = (
        db.query(SetupAlert)
        .filter(
            SetupAlert.fired_at >= cutoff,
            SetupAlert.is_suppressed == True,  # noqa: E712
        )
        .order_by(SetupAlert.fired_at.desc())
        .limit(50)
        .all()
    )

    def _fmt(a):
        return {
            "id": a.id,
            "setup_key": a.setup_key,
            "setup_name": a.setup_name,
            "setup_status": a.setup_status,
            "ticker": a.ticker,
            "fired_at": a.fired_at.isoformat(),
            "is_suppressed": a.is_suppressed,
            "suppressed_reason": a.suppressed_reason,
            "conditions": a.conditions,
            "action": a.action,
            "entry_price": a.entry_price,
            "invalidation_price": a.invalidation_price,
            "target_price": a.target_price,
            "action_summary": a.action_summary,
            "contract_type": a.contract_type,
            "strike": a.strike,
            "expiry": a.expiry,
            "premium": a.premium,
            "max_loss_per_contract": a.max_loss_per_contract,
            "max_loss_per_position": a.max_loss_per_position,
            "max_loss": a.max_loss,
            "earnings_in_window": a.earnings_in_window,
            "iv_percentile": a.iv_percentile,
            "spread_quality": a.spread_quality,
            "invalidation_text": a.invalidation_text,
            "is_open": a.is_open,
        }

    live = [_fmt(a) for a in alerts if a.setup_status == "LIVE"]
    shadow = [_fmt(a) for a in alerts if a.setup_status == "SHADOW"]

    # Last engine run metadata
    from models.setup_alert import AlertEngineRun
    last_run = (
        db.query(AlertEngineRun)
        .order_by(AlertEngineRun.ran_at.desc())
        .first()
    )
    run_meta = None
    if last_run:
        run_meta = {
            "ran_at": last_run.ran_at.isoformat(),
            "tickers_evaluated": last_run.tickers_evaluated,
            "alerts_fired": last_run.alerts_fired,
            "shadow_hits": last_run.shadow_hits,
            "suppressed": last_run.suppressed,
            "errors": last_run.errors,
            "duration_seconds": last_run.duration_seconds,
        }

    return {
        "live_alerts": live,
        "shadow_alerts": shadow,
        "suppressed_candidates": [_fmt(a) for a in suppressed],
        "last_run": run_meta,
        "total_live": len(live),
        "total_shadow": len(shadow),
        "no_alerts": len(live) == 0 and len(shadow) == 0,
    }


# ---------------------------------------------------------------------------
# Journal
# ---------------------------------------------------------------------------

@router.get("/journal")
def get_journal(
    setup_key: str = Query(None),
    limit: int = Query(100, le=500),
    db=Depends(get_db),
):
    from models.setup_alert import SetupAlert

    query = db.query(SetupAlert).filter(SetupAlert.is_suppressed == False)  # noqa: E712
    if setup_key:
        query = query.filter(SetupAlert.setup_key == setup_key)

    rows = query.order_by(SetupAlert.fired_at.desc()).limit(limit).all()

    return [
        {
            "id": r.id,
            "setup_key": r.setup_key,
            "setup_name": r.setup_name,
            "setup_status": r.setup_status,
            "ticker": r.ticker,
            "fired_at": r.fired_at.isoformat(),
            "action": r.action,
            "entry_price": r.entry_price,
            "invalidation_price": r.invalidation_price,
            "target_price": r.target_price,
            "max_loss": r.max_loss,
            "is_open": r.is_open,
            "outcome_pct": r.outcome_pct,
            "outcome_r": r.outcome_r,
            "days_held": r.days_held,
            "closed_at": r.closed_at.isoformat() if r.closed_at else None,
            "close_reason": r.close_reason,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

@router.get("/stats")
def get_stats(setup_key: str = Query(None), db=Depends(get_db)):
    from services.alert_journal_service import get_setup_statistics
    return get_setup_statistics(db, setup_key)


# ---------------------------------------------------------------------------
# Manual trigger (for testing and acceptance verification)
# ---------------------------------------------------------------------------

@router.post("/run")
def trigger_run(db=Depends(get_db)):
    from services.alert_engine import run_alert_engine
    result = run_alert_engine(db)
    return result


@router.post("/outcome-job")
def trigger_outcome_job(db=Depends(get_db)):
    from services.alert_journal_service import run_outcome_job
    result = run_outcome_job(db)
    return result
