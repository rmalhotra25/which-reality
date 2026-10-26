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
from services.directional_ranker import (
    compute_prob_profit,
    compute_reward_risk,
    compute_risk_tier,
    compute_fits_challenge,
)

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

def _challenge_live_state(db: Session) -> dict | None:
    """Live Challenge state for the fits check, or None when unavailable.

    Failure-isolated: an uninitialized Challenge account, a missing state
    field, or any challenge-side error yields None, and the caller falls
    back to the per-trade-only check without breaking this response.
    """
    try:
        from services import challenge_service

        state = challenge_service.compute_state(db)
        if not state.get("initialized"):
            return None
        caps = state.get("risk_caps") or {}
        return {
            "per_trade_cap": caps.get("per_trade_cap"),
            "open_risk_cap": caps.get("open_risk_cap"),
            "open_risk": state.get("open_risk"),
            "cash": state.get("cash"),
            "paused": bool(caps.get("paused")),
        }
    except Exception:
        logger.warning("challenge live-state lookup failed; fits_challenge falls back to per-trade cap", exc_info=True)
        return None


def fits_challenge_live(max_loss_per_contract: float | None, live_state: dict | None) -> tuple[bool, str | None]:
    """Per-trade fit plus live Challenge state (review M28).

    A candidate fits only when the max loss is within the per-trade cap,
    the post-trade open risk stays within the open-risk cap, the cash
    covers the max loss, and the account is not paused. When no live state
    is available, fall back to the per-trade-only check so the tab keeps
    working.
    """
    if max_loss_per_contract is None:
        return False, "max loss unknown"
    if live_state is None:
        fits = compute_fits_challenge(max_loss_per_contract, None)
        return fits, None if fits else "Challenge account not initialized"
    if not compute_fits_challenge(max_loss_per_contract, live_state.get("per_trade_cap")):
        return False, "max loss above the per-trade cap"
    open_risk_cap = live_state.get("open_risk_cap")
    open_risk = live_state.get("open_risk")
    if open_risk_cap is not None and open_risk is not None:
        if open_risk + max_loss_per_contract > open_risk_cap:
            return False, "open risk would exceed the 20% cap"
    cash = live_state.get("cash")
    if cash is not None and max_loss_per_contract > cash:
        return False, "max loss exceeds available cash"
    if live_state.get("paused"):
        return False, "Challenge account is paused"
    return True, None


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
    live_state = _challenge_live_state(db)

    def _serialize(c: DirectionalCandidate) -> dict:
        try:
            components = json.loads(c.ranking_components_json or "{}")
        except Exception:
            components = {}
        try:
            flow_signals = json.loads(c.flow_signals_json or "null")
        except Exception:
            flow_signals = None
        # New fields live in the ranking-components JSON (no model schema
        # change). Legacy rows without them fall back to recomputing from the
        # stored columns, so old batches still serialize.
        prob_profit = components.get("prob_profit")
        if prob_profit is None and c.delta_abs is not None:
            prob_profit = compute_prob_profit(
                c.current_price, c.strike, c.entry_premium, c.dte or 0,
                c.atm_iv_pct or 30.0, c.option_type or "CALL",
            )
        reward_risk = components.get("reward_risk")
        if reward_risk is None:
            reward_risk = compute_reward_risk(c.payoff_at_target, c.payoff_at_stop)
        _fit, _fit_reason = fits_challenge_live(c.max_loss_per_contract, live_state)
        return {
            "id": c.id,
            "ticker": c.ticker,
            "rank": c.rank,
            "score": c.score,
            "status_label": "SHADOW",
            "ev_dollars": components.get("ev_dollars"),
            "ev_per_dollar_risked": components.get("ev_per_dollar_risked"),
            "expected_payoff_given_profit": components.get("expected_payoff_given_profit"),
            "ev_limitation": components.get("ev_limitation"),
            "spread_known": components.get("spread_known"),
            "spread_cost_per_contract": components.get("spread_cost_per_contract"),
            "spread_note": components.get("spread_note"),
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
            "prob_profit": prob_profit,
            "prob_touch_target": components.get("prob_touch_target"),
            "prob_touch_stop": components.get("prob_touch_stop"),
            "reward_risk": reward_risk,
            "risk_tier": compute_risk_tier(prob_profit),
            "fits_challenge": _fit,
            "fits_challenge_reason": _fit_reason,
            "current_price": c.current_price,
            "atm_iv_pct": c.atm_iv_pct,
            "contract_iv_pct": components.get("contract_iv_pct"),
            "iv_source": components.get("iv_source"),
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
            "earnings_date": components.get("earnings_date"),
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
        "status": "SHADOW",
        "status_label": "SHADOW",
        "status_note": (
            "Directional Options are SHADOW: live grading is 64 picks, "
            "11 settled, 0% win rate, -$10,595 as of 2026-10-26. Candidates "
            "are shown for observation only and are never sent as LIVE "
            "Challenge alerts. EV is market-implied from the contract IV, "
            "not a forecast and not an edge."
        ),
        "candidates": active,
        "suppressed": suppressed,
    }


@router.get("/directional/grading")
def get_directional_grading(db: Session = Depends(get_db)):
    """Grade settled Directional picks by the EV per $ risked they were picked with.

    Buckets settled journal entries by EV per $ risked and reports win rate
    and average return per bucket. With fewer than 5 settled outcomes it
    reports "not enough settled outcomes yet" instead of printing stats.
    """
    from services.directional_grading import grade_directional_journal

    return grade_directional_journal(db)


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
