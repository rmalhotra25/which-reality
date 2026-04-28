import logging
from fastapi import APIRouter, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from database import get_db
from models.champion import Champion

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/champions", tags=["Champions"])

STRATEGY_ORDER = ["wheel", "options", "longterm"]


def _serialize(row: Champion) -> dict:
    return {
        "strategy": row.strategy,
        "ticker": row.ticker,
        "score": row.score,
        "grade": row.grade,
        "reason": row.reason,
        "universe_size": row.universe_size,
        "survivors_count": row.survivors_count,
        "run_at": row.run_at.isoformat() if row.run_at else None,
    }


@router.get("")
def get_champions(db: Session = Depends(get_db)):
    rows = db.query(Champion).order_by(Champion.run_at.desc()).limit(10).all()
    if not rows:
        return {"champions": [], "run_at": None}

    latest_run = rows[0].run_at
    # Only return champions from the latest run
    latest = [r for r in rows if r.run_at == latest_run]
    ordered = sorted(latest, key=lambda r: STRATEGY_ORDER.index(r.strategy) if r.strategy in STRATEGY_ORDER else 99)
    return {
        "champions": [_serialize(r) for r in ordered],
        "run_at": latest_run.isoformat(),
    }


def _run_champions_job():
    from database import SessionLocal
    from services.champions_engine import run as run_champions
    db = SessionLocal()
    try:
        run_champions(db)
    except Exception as e:
        logger.error("Champions refresh failed: %s", e, exc_info=True)
    finally:
        db.close()


@router.post("/refresh")
def refresh_champions(background_tasks: BackgroundTasks):
    background_tasks.add_task(_run_champions_job)
    return {"status": "Champions scan started in background — check back in ~60 seconds"}
