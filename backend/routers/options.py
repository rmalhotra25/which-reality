import threading
import logging
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import desc

from database import get_db
from models.recommendation import Recommendation, TabType
from models.directional_candidate import DirectionalCandidate
from schemas.recommendation import RecommendationSchema

router = APIRouter()
logger = logging.getLogger(__name__)


def _latest_batch(db: Session, tab: TabType) -> List[Recommendation]:
    """Return the 5 recommendations from the most recent run_at batch."""
    latest = (
        db.query(Recommendation.run_at)
        .filter(Recommendation.tab == tab)
        .order_by(desc(Recommendation.run_at))
        .first()
    )
    if not latest:
        return []
    return (
        db.query(Recommendation)
        .filter(Recommendation.tab == tab, Recommendation.run_at == latest[0])
        .order_by(Recommendation.rank)
        .all()
    )


@router.get("/recommendations", response_model=List[RecommendationSchema])
def get_options_recommendations(db: Session = Depends(get_db)):
    return _latest_batch(db, TabType.options)


@router.post("/refresh")
def refresh_options(db: Session = Depends(get_db)):
    from services.options_engine import OptionsEngine

    def _run():
        from database import SessionLocal
        s = SessionLocal()
        try:
            OptionsEngine(s).run()
        finally:
            s.close()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return {"status": "queued", "message": "Options analysis started in background"}


# ---------------------------------------------------------------------------
# Phase 3A: directional candidates (cache-only GET; POST to refresh)
# ---------------------------------------------------------------------------

@router.get("/directional")
def get_directional_candidates(db: Session = Depends(get_db)):
    """Return the latest directional candidates batch (cache-only, never triggers a run)."""
    from services.directional_engine import get_latest_directional_candidates
    import json

    rows = get_latest_directional_candidates(db)
    if not rows:
        return {"run_at": None, "regime": None, "candidates": [], "suppressed": []}

    run_at = rows[0].run_at.isoformat() if rows[0].run_at else None
    regime = rows[0].regime_verdict if rows else None
    data_complete = rows[0].regime_data_complete if rows else None

    def _serialize(c: DirectionalCandidate) -> dict:
        try:
            components = json.loads(c.ranking_components_json or "{}")
        except Exception:
            components = {}
        try:
            flow_signals = json.loads(c.flow_signals_json or "null")
        except Exception:
            flow_signals = None
        return {
            "id": c.id,
            "ticker": c.ticker,
            "rank": c.rank,
            "score": c.score,
            "prob_score": c.prob_score,
            "rr_score": c.rr_score,
            "iv_context_score": c.iv_context_score,
            "trend_score": c.trend_score,
            "ranking_components": components,
            "option_type": c.option_type,
            "strike": c.strike,
            "expiry": c.expiry,
            "dte": c.dte,
            "entry_premium": c.entry_premium,
            "max_loss_per_contract": c.max_loss_per_contract,
            "underlying_entry": c.underlying_entry,
            "underlying_target": c.underlying_target,
            "underlying_stop": c.underlying_stop,
            "delta_abs": c.delta_abs,
            "current_price": c.current_price,
            "atm_iv_pct": c.atm_iv_pct,
            "expected_move_dollars": c.expected_move_dollars,
            "expected_move_pct": c.expected_move_pct,
            "payoff_at_target": c.payoff_at_target,
            "payoff_at_stop": c.payoff_at_stop,
            "payoff_at_unchanged": c.payoff_at_unchanged,
            "iv_percentile": c.iv_percentile,
            "iv_history_building": c.iv_history_building,
            "iv_percentile_available": c.iv_percentile_available,
            "above_ma50": c.above_ma50,
            "above_ma200": c.above_ma200,
            "earnings_in_window": c.earnings_in_window,
            "earnings_days_away": c.earnings_days_away,
            "earnings_unavailable": c.earnings_unavailable,
            "iv_crush_risk": c.iv_crush_risk,
            "regime_verdict": c.regime_verdict,
            "regime_data_complete": c.regime_data_complete,
            "is_suppressed": c.is_suppressed,
            "suppressed_reason": c.suppressed_reason,
            "ai_explanation": c.ai_explanation,
            "ai_available": c.ai_available,
            "journal_id": c.journal_id,
            "momentum_score_raw": c.momentum_score_raw,
            "flow_signals": flow_signals,
            "run_at": c.run_at.isoformat() if c.run_at else None,
        }

    active = [_serialize(c) for c in rows if not c.is_suppressed]
    suppressed = [_serialize(c) for c in rows if c.is_suppressed]

    return {
        "run_at": run_at,
        "regime": regime,
        "data_complete": data_complete,
        "candidates": active,
        "suppressed": suppressed,
    }


@router.post("/directional/refresh")
def refresh_directional(db: Session = Depends(get_db)):
    """Trigger a fresh directional analysis run in the background."""
    from services import run_status as rs

    all_status = rs.get_all()
    if all_status.get("directional", {}).get("status") == "running":
        return {"status": "already_running", "message": "Directional analysis already in progress"}

    def _run():
        from database import SessionLocal
        s = SessionLocal()
        try:
            from services.directional_engine import DirectionalEngine
            DirectionalEngine(s).run()
        finally:
            s.close()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return {"status": "queued", "message": "Directional analysis started in background"}
