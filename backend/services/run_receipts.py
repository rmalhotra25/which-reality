"""
Persistent run receipts (P1 determinism).

Replaces the in-memory run_status as the source of truth: one row per
job run in the run_receipts table, so silence means "ran, nothing
qualified" when a receipt exists. A failed job leaves a failed receipt,
never silence. run_status is kept as a fallback mirror only.

Covered jobs: alert engine, Challenge snapshot, Challenge alerts after
engine, wheel scanner, directional, dividend path, CEF scan, discovery,
scheduler discovery, alert outcome, champion outcome, analysis runs,
call suggestions.
"""
import json
import logging
import time
from contextlib import contextmanager
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Job names used across the scheduler, engines, and routers. One line per
# job in the system status view comes from these names.
JOB_ALERT_ENGINE = "alert_engine"
JOB_ALERT_OUTCOME = "alert_outcome"
JOB_CHAMPION_OUTCOME = "champion_outcome"
JOB_CHALLENGE_SNAPSHOT = "challenge_snapshot"
JOB_CHALLENGE_ALERTS = "challenge_alerts_after_engine"
JOB_WHEEL_SCANNER = "wheel_scanner"
JOB_DIRECTIONAL = "directional"
JOB_DIVIDEND_PATH = "dividend_path"
JOB_CEF_SCAN = "cef_scan"
JOB_DISCOVERY = "discovery"
JOB_CHAMPIONS = "champions"
JOB_ANALYSIS = "analysis"
JOB_CALL_SUGGESTIONS = "call_suggestions"


def write_receipt(db, job_name: str, started_at: datetime, state: str,
                  tickers_evaluated: int = 0, alerts_fired: int = 0,
                  suppressed: int = 0, duplicates_suppressed: int = 0,
                  errors: list | None = None,
                  duration_seconds: float | None = None) -> None:
    """Write one receipt row and commit. Never raises: a receipt failure
    must not break the job it records. Rolls back first so a failed job
    session cannot poison the receipt write."""
    from models.run_receipt import RunReceipt

    finished_at = datetime.now(timezone.utc)
    if duration_seconds is None:
        duration_seconds = round(
            (finished_at - started_at).total_seconds(), 1
        ) if started_at else None
    try:
        db.rollback()
    except Exception:
        pass
    try:
        # Create the table first so a database built before this phase
        # still records receipts.
        from database import Base
        Base.metadata.create_all(db.bind, tables=[RunReceipt.__table__])
        db.add(RunReceipt(
            job_name=job_name,
            started_at=started_at,
            finished_at=finished_at,
            state=state,
            tickers_evaluated=int(tickers_evaluated or 0),
            alerts_fired=int(alerts_fired or 0),
            suppressed=int(suppressed or 0),
            duplicates_suppressed=int(duplicates_suppressed or 0),
            errors=json.dumps((errors or [])[:50]),
            duration_seconds=duration_seconds,
        ))
        db.commit()
    except Exception as e:
        logger.error("run_receipts: failed to write receipt for %s: %s", job_name, e)
        try:
            db.rollback()
        except Exception:
            pass


@contextmanager
def job_receipt(db, job_name: str):
    """Context manager for one job run. Yields a counts dict the job
    fills; on exit writes an ok receipt, or an error receipt when the
    body raises (the exception is re-raised after the receipt is
    written, so a failed job is visible, not silent).

    Usage:
        with job_receipt(db, JOB_WHEEL_SCANNER) as counts:
            counts["tickers_evaluated"] = ...
            counts["alerts_fired"] = ...
    Set counts["state"] = "skipped" and counts["errors"] = [reason] for
    a skipped run (not a trading day, account not initialized).
    """
    started_at = datetime.now(timezone.utc)
    start = time.time()
    counts: dict = {}
    try:
        yield counts
    except Exception as e:
        write_receipt(
            db, job_name, started_at, "error",
            tickers_evaluated=counts.get("tickers_evaluated", 0),
            alerts_fired=counts.get("alerts_fired", 0),
            suppressed=counts.get("suppressed", 0),
            duplicates_suppressed=counts.get("duplicates_suppressed", 0),
            errors=[str(e)],
            duration_seconds=round(time.time() - start, 1),
        )
        raise
    state = counts.get("state", "ok")
    write_receipt(
        db, job_name, started_at, state,
        tickers_evaluated=counts.get("tickers_evaluated", 0),
        alerts_fired=counts.get("alerts_fired", 0),
        suppressed=counts.get("suppressed", 0),
        duplicates_suppressed=counts.get("duplicates_suppressed", 0),
        errors=counts.get("errors"),
        duration_seconds=round(time.time() - start, 1),
    )


def latest_per_job(db) -> list[dict]:
    """One line per job: last run, last result, counts. The system
    status view reads this. Returns newest first."""
    from models.run_receipt import RunReceipt

    rows = (
        db.query(RunReceipt)
        .order_by(RunReceipt.started_at.desc())
        .limit(500)
        .all()
    )
    seen: dict[str, dict] = {}
    for r in rows:
        if r.job_name in seen:
            continue
        try:
            errors = json.loads(r.errors or "[]")
        except Exception:
            errors = []
        seen[r.job_name] = {
            "job_name": r.job_name,
            "last_run": r.started_at.isoformat() if r.started_at else None,
            "state": r.state,
            "tickers_evaluated": r.tickers_evaluated,
            "alerts_fired": r.alerts_fired,
            "suppressed": r.suppressed,
            "duplicates_suppressed": r.duplicates_suppressed,
            "errors": errors[:5],
            "duration_seconds": r.duration_seconds,
        }
    return [seen[k] for k in sorted(seen)]
