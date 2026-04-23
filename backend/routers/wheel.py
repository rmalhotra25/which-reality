import json
import re
import threading
import logging
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import desc

from database import get_db
from models.wheel import WheelRecommendation, WheelPosition, WheelHistory, WheelStatus
from schemas.wheel import (
    WheelRecommendationSchema,
    WheelPositionSchema,
    AcceptWheelBody,
    UpdateStatusBody,
)

router = APIRouter()
logger = logging.getLogger(__name__)
_TICKER_RE = re.compile(r'^[A-Z]{1,5}$')


class CustomAnalyzeRequest(BaseModel):
    ticker: str

VALID_TRANSITIONS = {
    WheelStatus.put_active: [WheelStatus.assigned, WheelStatus.closed],
    WheelStatus.assigned: [WheelStatus.call_active, WheelStatus.closed],
    WheelStatus.call_active: [WheelStatus.assigned, WheelStatus.closed],
    WheelStatus.closed: [],
}


def _latest_wheel_batch(db: Session) -> List[WheelRecommendation]:
    latest = (
        db.query(WheelRecommendation.run_at)
        .order_by(desc(WheelRecommendation.run_at))
        .first()
    )
    if not latest:
        return []
    return (
        db.query(WheelRecommendation)
        .filter(WheelRecommendation.run_at == latest[0])
        .order_by(WheelRecommendation.rank)
        .all()
    )


@router.get("/recommendations", response_model=List[WheelRecommendationSchema])
def get_wheel_recommendations(db: Session = Depends(get_db)):
    return _latest_wheel_batch(db)


@router.post("/recommendations/{rec_id}/accept", response_model=WheelPositionSchema)
def accept_wheel_recommendation(
    rec_id: int, body: AcceptWheelBody, db: Session = Depends(get_db)
):
    rec = db.get(WheelRecommendation, rec_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    if rec.accepted:
        raise HTTPException(status_code=400, detail="Already accepted")

    put_strike = body.put_strike or rec.put_strike
    put_expiry = body.put_expiry or rec.put_expiry or ""
    if not put_strike:
        raise HTTPException(status_code=400, detail="put_strike is required")

    position = WheelPosition(
        recommendation_id=rec.id,
        ticker=rec.ticker,
        status=WheelStatus.put_active,
        put_strike=put_strike,
        put_expiry=put_expiry,
        put_premium_rcvd=body.put_premium_rcvd or rec.put_premium,
    )
    db.add(position)
    rec.accepted = True
    rec.accepted_at = datetime.now(timezone.utc)
    db.flush()

    history = WheelHistory(
        position_id=position.id,
        from_status=None,
        to_status=WheelStatus.put_active,
        note="Position opened via Accept",
    )
    db.add(history)
    db.commit()
    db.refresh(position)
    return position


@router.get("/positions", response_model=List[WheelPositionSchema])
def get_wheel_positions(include_closed: bool = False, db: Session = Depends(get_db)):
    q = db.query(WheelPosition)
    if not include_closed:
        q = q.filter(WheelPosition.status != WheelStatus.closed)
    return q.order_by(desc(WheelPosition.put_opened_at)).all()


@router.get("/positions/{pos_id}", response_model=WheelPositionSchema)
def get_wheel_position(pos_id: int, db: Session = Depends(get_db)):
    pos = db.get(WheelPosition, pos_id)
    if not pos:
        raise HTTPException(status_code=404, detail="Position not found")
    return pos


@router.patch("/positions/{pos_id}/status", response_model=WheelPositionSchema)
def update_position_status(
    pos_id: int, body: UpdateStatusBody, db: Session = Depends(get_db)
):
    pos = db.get(WheelPosition, pos_id)
    if not pos:
        raise HTTPException(status_code=404, detail="Position not found")

    try:
        new_status = WheelStatus(body.new_status)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid status: {body.new_status}")

    allowed = VALID_TRANSITIONS.get(pos.status, [])
    if new_status not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot transition from {pos.status} to {new_status}. Allowed: {[s.value for s in allowed]}",
        )

    old_status = pos.status
    pos.status = new_status
    now = datetime.now(timezone.utc)

    if new_status == WheelStatus.assigned:
        pos.assigned_at = body.assigned_at or now
        if pos.put_strike and pos.put_premium_rcvd:
            pos.cost_basis = round(pos.put_strike - pos.put_premium_rcvd, 4)
        # Trigger call suggestion in background
        threading.Thread(target=_generate_call_suggestion_bg, args=(pos_id,), daemon=True).start()

    elif new_status == WheelStatus.call_active:
        if body.call_strike:
            pos.call_strike = body.call_strike
        if body.call_expiry:
            pos.call_expiry = body.call_expiry
        if body.call_premium_rcvd:
            pos.call_premium_rcvd = body.call_premium_rcvd
        pos.call_opened_at = now

    elif new_status == WheelStatus.closed:
        pos.closed_at = now
        if body.total_pnl is not None:
            pos.total_pnl = body.total_pnl
        if body.notes:
            pos.notes = body.notes

    # If going back to assigned from call_active (call expired worthless), clear call fields
    if new_status == WheelStatus.assigned and old_status == WheelStatus.call_active:
        pos.call_strike = None
        pos.call_expiry = None
        pos.call_premium_rcvd = None
        pos.call_opened_at = None

    history = WheelHistory(
        position_id=pos.id,
        from_status=old_status,
        to_status=new_status,
        note=body.note,
    )
    db.add(history)
    db.commit()
    db.refresh(pos)
    return pos


@router.get("/positions/{pos_id}/call-suggestion")
def get_call_suggestion(pos_id: int, db: Session = Depends(get_db)):
    pos = db.get(WheelPosition, pos_id)
    if not pos:
        raise HTTPException(status_code=404, detail="Position not found")
    if pos.status not in (WheelStatus.assigned, WheelStatus.call_active):
        raise HTTPException(status_code=400, detail="Position must be assigned or call_active")
    return {
        "suggestion": json.loads(pos.call_suggestion) if pos.call_suggestion else None,
        "generated_at": pos.call_suggestion_at,
    }


@router.post("/positions/{pos_id}/call-suggestion/refresh")
def refresh_call_suggestion(pos_id: int, db: Session = Depends(get_db)):
    pos = db.get(WheelPosition, pos_id)
    if not pos:
        raise HTTPException(status_code=404, detail="Position not found")
    threading.Thread(target=_generate_call_suggestion_bg, args=(pos_id,), daemon=True).start()
    return {"status": "queued"}


@router.post("/custom-analyze")
def custom_analyze_wheel(req: CustomAnalyzeRequest, db: Session = Depends(get_db)):
    """On-demand wheel strategy analysis for any ticker with real options chain data."""
    ticker = req.ticker.strip().upper()
    if not _TICKER_RE.match(ticker):
        raise HTTPException(status_code=400, detail="Invalid ticker. Use 1-5 letters (e.g. AAPL).")

    from services.stock_data import StockDataService
    from services.news_scraper import NewsScraper
    from services.claude_analyst import ClaudeAnalyst

    stock_data = StockDataService()
    scraper = NewsScraper()
    analyst = ClaudeAnalyst()

    tech = stock_data.get_price_and_technicals(ticker)
    current_price = tech.get("price")
    if not current_price:
        raise HTTPException(status_code=404,
                            detail=f"No price data for {ticker}. Check the symbol and try again.")

    put_tiers = stock_data.get_put_tiers(ticker)
    if not put_tiers:
        raise HTTPException(status_code=503,
                            detail=f"Could not fetch options chain for {ticker}. "
                                   "Check the symbol and try again.")

    try:
        fund_map = stock_data.get_fundamentals([ticker])
        fundamentals = fund_map.get(ticker) or {}
    except Exception:
        fundamentals = {}

    try:
        news_items = scraper.fetch_all([ticker])
        news_bullets = "\n".join(
            f"- [{it.ticker or 'MARKET'}] {it.source}: {it.headline}"
            for it in news_items[:20]
        ) or "No recent news available."
    except Exception:
        news_bullets = "News unavailable — base analysis on technicals."

    try:
        result = analyst.analyze_wheel_custom(
            ticker=ticker,
            current_price=current_price,
            put_tiers=put_tiers,
            fundamentals=fundamentals,
            technicals=tech,
            news_bullets=news_bullets,
        )
        result["ticker"] = ticker
        result["current_price"] = current_price
        result["data_source"] = put_tiers.get("data_source", "last_trade")
        result["put_tiers_raw"] = put_tiers
        return result
    except Exception as e:
        logger.error("Wheel custom analysis failed for %s: %s", ticker, e)
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@router.post("/refresh")
def refresh_wheel():
    def _run():
        from database import SessionLocal
        from services.wheel_engine import WheelEngine
        s = SessionLocal()
        try:
            WheelEngine(s).run()
        finally:
            s.close()

    threading.Thread(target=_run, daemon=True).start()
    return {"status": "queued", "message": "Wheel analysis started in background"}


def _generate_call_suggestion_bg(pos_id: int) -> None:
    from database import SessionLocal
    from services.wheel_engine import WheelEngine
    from datetime import datetime, timezone
    s = SessionLocal()
    try:
        pos = s.get(WheelPosition, pos_id)
        if not pos:
            return
        engine = WheelEngine(s)
        suggestion = engine.generate_call_suggestion(pos)
        if suggestion:
            pos.call_suggestion = suggestion
            pos.call_suggestion_at = datetime.now(timezone.utc)
            s.commit()
    except Exception as e:
        logger.error("Background call suggestion error for pos %d: %s", pos_id, e)
    finally:
        s.close()
