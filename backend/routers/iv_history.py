from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db

router = APIRouter(prefix="/api/iv-history", tags=["IV History"])


@router.get("/{ticker}/percentile")
def get_iv_percentile(ticker: str, db: Session = Depends(get_db)):
    """
    Return the percentile rank of the latest stored ATM IV for a ticker
    within its own stored history.

    When fewer than 30 snapshots exist the response includes
    history_building: true and the sample count so callers can label
    the result honestly as an approximation under construction.
    """
    ticker = ticker.strip().upper()
    if not ticker.isalpha() or len(ticker) > 10:
        raise HTTPException(status_code=400, detail="Invalid ticker.")
    from services.iv_snapshot_service import get_iv_percentile
    result = get_iv_percentile(db, ticker)
    if not result.get("available", True) and result.get("reason"):
        raise HTTPException(status_code=404, detail=result["reason"])
    return result


@router.get("/{ticker}/history")
def get_iv_history(ticker: str, limit: int = 90, db: Session = Depends(get_db)):
    """Return the last N IV snapshots for a ticker, most recent first."""
    ticker = ticker.strip().upper()
    if not ticker.isalpha() or len(ticker) > 10:
        raise HTTPException(status_code=400, detail="Invalid ticker.")
    from models.iv_snapshot import IVSnapshot
    from sqlalchemy import desc
    rows = (
        db.query(IVSnapshot)
        .filter(IVSnapshot.ticker == ticker)
        .order_by(desc(IVSnapshot.captured_at))
        .limit(min(limit, 500))
        .all()
    )
    return [
        {
            "captured_at": r.captured_at.isoformat(),
            "atm_iv_pct": round(r.atm_iv * 100, 1),
            "underlying_price": r.underlying_price,
            "expiry": r.expiry,
            "dte": r.dte,
            "iv_source": r.iv_source,
        }
        for r in rows
    ]
