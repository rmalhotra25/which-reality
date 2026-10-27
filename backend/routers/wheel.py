import json
import re
import threading
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
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
from services.wheel_modes import (
    WHEEL_MODE,
    VALID_MODES,
    MANAGEMENT_RULES_TEXT,
    get_management_guidance,
)

router = APIRouter()
logger = logging.getLogger(__name__)
_TICKER_RE = re.compile(r'^[A-Z]{1,5}$')


def _parse_mode(mode: str | None) -> str:
    return mode if mode in VALID_MODES else WHEEL_MODE


def _dte_for(expiry: str | None):
    """Days from today to the expiry date, or None if unparseable."""
    if not expiry:
        return None
    try:
        from datetime import date
        return (date.fromisoformat(str(expiry)) - date.today()).days
    except Exception:
        return None


def _current_put_mark(ticker: str, put_strike: float, put_expiry: str | None):
    """
    Best-effort live mark for the position's put: the mid premium of the
    chain tier whose strike is nearest the position strike, used only
    when the chain expiry matches the position expiry. Returns None
    when no matching mark exists. Never fabricates a mark.
    """
    try:
        from services.stock_data import StockDataService
        tiers = StockDataService().get_put_tiers(ticker)
        if not tiers or tiers.get("expiry") != put_expiry:
            return None
        best = None
        best_gap = None
        for tier in (tiers.get("likely"), tiers.get("moderate"), tiers.get("unlikely")):
            if not isinstance(tier, dict):
                continue
            strike = tier.get("strike")
            mid = tier.get("mid_premium")
            if strike is None or not mid:
                continue
            gap = abs(strike - put_strike)
            if best_gap is None or gap < best_gap:
                best = mid
                best_gap = gap
        return best
    except Exception:
        return None


def _position_guidance(pos: WheelPosition) -> dict:
    """Compute management guidance for one position, failure-isolated."""
    mode = (getattr(pos, "mode", None) or WHEEL_MODE)
    if mode not in VALID_MODES:
        mode = WHEEL_MODE
    dte = _dte_for(pos.put_expiry)
    current_price = None
    current_mark = None
    try:
        if pos.status == WheelStatus.put_active:
            from services.finnhub_client import get_quote
            q = get_quote(pos.ticker)
            current_price = q.get("c") or q.get("pc")
            if current_price:
                current_price = float(current_price)
            current_mark = _current_put_mark(pos.ticker, pos.put_strike, pos.put_expiry)
    except Exception:
        current_price = None
        current_mark = None
    guidance = get_management_guidance(
        mode, pos.status.value, pos.put_premium_rcvd, dte, current_mark
    )
    guidance["dte"] = dte
    guidance["current_price"] = current_price
    guidance["current_mark"] = current_mark
    guidance["mode"] = mode
    return guidance


def _position_with_guidance(pos: WheelPosition) -> dict:
    d = WheelPositionSchema.model_validate(pos).model_dump()
    d["mode"] = getattr(pos, "mode", None) or WHEEL_MODE
    try:
        d["guidance"] = _position_guidance(pos)
    except Exception as e:
        logger.debug("guidance failed for position %d: %s", pos.id, e)
        d["guidance"] = {
            "action": "hold",
            "title": "Hold and monitor",
            "reason": "Live guidance unavailable right now.",
            "detail": MANAGEMENT_RULES_TEXT.get(d["mode"], MANAGEMENT_RULES_TEXT[WHEEL_MODE]),
            "mark_known": False,
            "dte": _dte_for(pos.put_expiry),
            "current_price": None,
            "current_mark": None,
            "mode": d["mode"],
        }
    return d


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


@router.get("/recommendations")
def get_wheel_recommendations(db: Session = Depends(get_db)):
    from services.finnhub_client import get_earnings_this_month
    from services.iv_rank_service import get_iv_rank
    recs = _latest_wheel_batch(db)

    # Fetch IV rank concurrently for all tickers
    tickers = [rec.ticker for rec in recs]
    iv_rank_cache = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(get_iv_rank, t): t for t in set(tickers)}
        for fut in as_completed(futures, timeout=30):
            t = futures[fut]
            try:
                iv_rank_cache[t] = fut.result(timeout=10)
            except Exception:
                iv_rank_cache[t] = {}

    result = []
    for rec in recs:
        d = WheelRecommendationSchema.model_validate(rec).model_dump()
        try:
            d["earnings_days"] = get_earnings_this_month(rec.ticker)
        except Exception:
            d["earnings_days"] = None
        d["iv_rank"] = iv_rank_cache.get(rec.ticker, {})
        result.append(d)
    return result


@router.post("/recommendations/{rec_id}/accept", response_model=WheelPositionSchema)
def accept_wheel_recommendation(
    rec_id: int, body: AcceptWheelBody, db: Session = Depends(get_db)
):
    # W9 (P2): WheelEngine is RESEARCH_ONLY. Its recommendations cannot
    # open a live position. Canonical wheel positions come from the
    # wheel scanner (backend/services/wheel_scanner_service.py).
    raise HTTPException(
        status_code=410,
        detail="WheelEngine recommendations are research only and cannot be accepted. "
        "Use a wheel scanner candidate instead.",
    )
    rec = db.get(WheelRecommendation, rec_id)
    if not rec:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    if rec.accepted:
        raise HTTPException(status_code=400, detail="Already accepted")

    put_strike = body.put_strike or rec.put_strike
    put_expiry = body.put_expiry or rec.put_expiry or ""
    if not put_strike:
        raise HTTPException(status_code=400, detail="put_strike is required")

    mode = _parse_mode(body.mode)

    position = WheelPosition(
        recommendation_id=rec.id,
        ticker=rec.ticker,
        status=WheelStatus.put_active,
        mode=mode,
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
        note=f"Position opened via Accept (mode={mode})",
    )
    db.add(history)
    db.commit()
    db.refresh(position)
    return _position_with_guidance(position)


@router.get("/positions")
def get_wheel_positions(include_closed: bool = False, db: Session = Depends(get_db)):
    q = db.query(WheelPosition)
    if not include_closed:
        q = q.filter(WheelPosition.status != WheelStatus.closed)
    positions = q.order_by(desc(WheelPosition.put_opened_at)).all()
    return [_position_with_guidance(p) for p in positions]


@router.get("/positions/{pos_id}")
def get_wheel_position(pos_id: int, db: Session = Depends(get_db)):
    pos = db.get(WheelPosition, pos_id)
    if not pos:
        raise HTTPException(status_code=404, detail="Position not found")
    return _position_with_guidance(pos)


@router.patch("/positions/{pos_id}/status")
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
    return _position_with_guidance(pos)


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


@router.get("/positions/export")
def export_positions(db: Session = Depends(get_db)):
    """Export all wheel positions and their full history as JSON for backup purposes."""
    positions = db.query(WheelPosition).order_by(WheelPosition.put_opened_at).all()
    result = []
    for pos in positions:
        history = [
            {
                "from_status": h.from_status.value if h.from_status else None,
                "to_status": h.to_status.value,
                "note": h.note,
                "changed_at": h.changed_at.isoformat() if h.changed_at else None,
            }
            for h in pos.history
        ]
        result.append({
            "id": pos.id,
            "ticker": pos.ticker,
            "status": pos.status.value,
            "mode": getattr(pos, "mode", None) or WHEEL_MODE,
            "put_strike": pos.put_strike,
            "put_expiry": pos.put_expiry,
            "put_premium_rcvd": pos.put_premium_rcvd,
            "put_opened_at": pos.put_opened_at.isoformat() if pos.put_opened_at else None,
            "assigned_at": pos.assigned_at.isoformat() if pos.assigned_at else None,
            "cost_basis": pos.cost_basis,
            "shares": pos.shares,
            "call_strike": pos.call_strike,
            "call_expiry": pos.call_expiry,
            "call_premium_rcvd": pos.call_premium_rcvd,
            "call_opened_at": pos.call_opened_at.isoformat() if pos.call_opened_at else None,
            "closed_at": pos.closed_at.isoformat() if pos.closed_at else None,
            "total_pnl": pos.total_pnl,
            "notes": pos.notes,
            "history": history,
        })
    return {"exported_at": datetime.now(timezone.utc).isoformat(), "positions": result}


@router.post("/positions/{pos_id}/call-suggestion/refresh")
def refresh_call_suggestion(pos_id: int, db: Session = Depends(get_db)):
    pos = db.get(WheelPosition, pos_id)
    if not pos:
        raise HTTPException(status_code=404, detail="Position not found")
    threading.Thread(target=_generate_call_suggestion_bg, args=(pos_id,), daemon=True).start()
    return {"status": "queued"}


@router.get("/put-tiers/{ticker}")
def get_put_tiers(ticker: str):
    """Real options chain put tiers for a ticker (3 delta targets: ~0.45, ~0.30, ~0.16)."""
    ticker = ticker.strip().upper()
    if not _TICKER_RE.match(ticker):
        raise HTTPException(status_code=400, detail="Invalid ticker.")
    from services.stock_data import StockDataService, get_last_chain_error
    tiers = StockDataService().get_put_tiers(ticker)
    if not tiers:
        detail = f"Could not fetch options chain for {ticker}."
        reason = get_last_chain_error()
        if reason:
            detail = f"{detail} {reason}"
        raise HTTPException(status_code=503, detail=detail)
    return tiers


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

    # W8 (P2): quant scores, Claude explains only. Score, grade, rating,
    # and recommended tier come from services.quant_picks.wheel_custom_quant.
    # A Claude failure never blocks the analysis: quant fields are
    # returned with a fallback note.
    from services.quant_picks import wheel_custom_quant
    from services.ai_boundary import quant_fallback_explanation
    quant = wheel_custom_quant(tech, put_tiers)
    result = {
        "ticker": ticker,
        "current_price": current_price,
        "data_source": put_tiers.get("data_source", "last_trade"),
        "put_tiers_raw": put_tiers,
        "wheel_score": quant["wheel_score"],
        "wheel_grade": quant["wheel_grade"],
        "wheel_rating": quant["wheel_rating"],
        "recommended_tier": quant["recommended_tier"],
    }
    try:
        notes = analyst.explain_wheel_custom(ticker, quant, put_tiers)
        result.update({
            "company_assessment": notes.get("company_assessment") or quant_fallback_explanation(ticker),
            "technicals_plain": notes.get("technicals_plain") or quant_fallback_explanation(ticker),
            "iv_environment_plain": notes.get("iv_environment_plain") or quant_fallback_explanation(ticker),
            "overall_verdict": notes.get("overall_verdict") or quant_fallback_explanation(ticker),
        })
    except Exception as e:
        logger.warning("Wheel custom explainer failed for %s: %s", ticker, e)
        note = quant_fallback_explanation(ticker)
        result.update({"company_assessment": note, "technicals_plain": note,
                       "iv_environment_plain": note, "overall_verdict": note})
    return result


@router.get("/positions/{pos_id}/roll-alert")
def get_roll_alert(pos_id: int, db: Session = Depends(get_db)):
    """
    Check if the stock has dropped close to the put strike.
    Uses Finnhub for price (reliable). Only relevant for put_active positions.
    """
    pos = db.get(WheelPosition, pos_id)
    if not pos:
        raise HTTPException(status_code=404, detail="Position not found")
    if pos.status != WheelStatus.put_active:
        return {"alert_level": "none", "current_price": None, "pct_from_strike": None}

    from services.finnhub_client import get_quote
    q = get_quote(pos.ticker)
    current_price = q.get("c") or q.get("pc")  # current or prev close
    if not current_price:
        return {"alert_level": "none", "current_price": None, "pct_from_strike": None,
                "message": "Price unavailable"}

    current_price = float(current_price)
    pct_from_strike = round((current_price - pos.put_strike) / pos.put_strike * 100, 1)

    if pct_from_strike > 5:
        level = "none"
        message = None
    elif pct_from_strike > 2:
        level = "warning"
        message = (
            f"{pos.ticker} is ${round(current_price,2)} — only {pct_from_strike}% above your "
            f"${pos.put_strike} strike. Getting close — worth monitoring."
        )
    else:
        level = "danger"
        if pct_from_strike <= 0:
            message = (
                f"⚠ {pos.ticker} is ${round(current_price,2)} — below your ${pos.put_strike} strike. "
                "Assignment is likely. Consider rolling to avoid owning shares at a loss."
            )
        else:
            message = (
                f"⚠ {pos.ticker} is ${round(current_price,2)} — only {pct_from_strike}% above your "
                f"${pos.put_strike} strike. High assignment risk. Consider rolling now."
            )

    return {
        "alert_level": level,
        "current_price": current_price,
        "put_strike": pos.put_strike,
        "pct_from_strike": pct_from_strike,
        "message": message,
    }


@router.post("/positions/{pos_id}/roll-suggestion")
def get_roll_suggestion(pos_id: int, db: Session = Depends(get_db)):
    """
    Generate a specific roll recommendation using current options chain + Claude.
    Uses yfinance for options chain (no free Finnhub alternative).
    """
    pos = db.get(WheelPosition, pos_id)
    if not pos:
        raise HTTPException(status_code=404, detail="Position not found")
    if pos.status != WheelStatus.put_active:
        raise HTTPException(status_code=400, detail="Roll suggestions only apply to put_active positions")

    from services.finnhub_client import get_quote
    from services.stock_data import StockDataService
    from services.claude_analyst import ClaudeAnalyst

    # Current price via Finnhub
    q = get_quote(pos.ticker)
    current_price = float(q.get("c") or q.get("pc") or 0)
    if not current_price:
        raise HTTPException(status_code=503, detail="Could not fetch current price")

    # Options chain via yfinance
    stock_data = StockDataService()
    put_tiers = stock_data.get_put_tiers(pos.ticker)
    if not put_tiers:
        raise HTTPException(
            status_code=503,
            detail="Options chain unavailable. Markets may be closed — try again during trading hours."
        )

    # W8 (P2): quant decides the roll, Claude explains only. should_roll,
    # urgency, new strike, and new expiry come from
    # services.quant_picks.roll_quant, which uses management guidance
    # and computed roll nets (new bid minus buyback ask). A Claude
    # failure never blocks the suggestion.
    from services.claude_analyst import compute_roll_net, fetch_open_put_buyback
    from services.quant_picks import roll_quant
    from services.ai_boundary import quant_fallback_explanation
    buyback_ask = None
    for key in ("buyback_ask", "open_put_ask", "current_put_ask"):
        val = (put_tiers or {}).get(key)
        if val is not None and float(val) > 0:
            buyback_ask = round(float(val), 2)
            break
    if buyback_ask is None:
        try:
            fetched = fetch_open_put_buyback(pos.ticker, pos.put_strike, pos.put_expiry)
            if fetched and fetched.get("ask"):
                buyback_ask = fetched["ask"]
        except Exception:
            buyback_ask = None
    computed_nets = {}
    for name in ("likely", "moderate", "unlikely"):
        t = (put_tiers or {}).get(name)
        computed_nets[name] = compute_roll_net(t.get("bid") if t else None, buyback_ask) if buyback_ask else None
    quant = roll_quant(pos, current_price, put_tiers, computed_nets)
    pct_from_strike = round((current_price - pos.put_strike) / pos.put_strike * 100, 1)
    result = {
        "should_roll": quant["should_roll"],
        "urgency": quant["urgency"],
        "action": quant["action"],
        "new_strike": quant["new_strike"],
        "new_expiry": quant["new_expiry"],
        "estimated_net": quant["roll_net"],
        "roll_net": quant["roll_net"],
        "pct_from_strike": pct_from_strike,
        "current_price": current_price,
        "data_source": put_tiers.get("data_source", "last_trade"),
        "guidance_title": quant["guidance_title"],
    }
    try:
        from services.claude_analyst import ClaudeAnalyst
        notes = ClaudeAnalyst().explain_roll(result)
        result["rationale"] = notes.get("rationale") or quant["guidance_reason"] or quant_fallback_explanation(pos.ticker)
        result["action_plain"] = notes.get("action_plain") or (quant["guidance_title"] or "")
        result["if_no_action"] = notes.get("if_no_action") or ""
    except Exception as e:
        logger.warning("Roll explainer failed for pos %d: %s", pos_id, e)
        result["rationale"] = quant["guidance_reason"] or quant_fallback_explanation(pos.ticker)
        result["action_plain"] = quant["guidance_title"] or ""
        result["if_no_action"] = ""
    return result


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


@router.get("/scanner/candidates")
def get_scanner_candidates(mode: str = Query(WHEEL_MODE)):
    """
    Return the cached wheel scanner results (put + call candidates)
    for the requested mode. This endpoint never triggers a scan --
    consistent with the Phase 1 rule that page loads must not trigger
    analysis runs.
    """
    from services.wheel_scanner_service import get_put_cache, get_call_cache
    put_cache = get_put_cache(_parse_mode(mode))
    call_cache = get_call_cache()
    return {
        "puts": put_cache,
        "calls": call_cache,
        "has_data": put_cache is not None or call_cache is not None,
        "mode": _parse_mode(mode),
    }


@router.post("/scanner/refresh")
def refresh_scanner(mode: str = Query(WHEEL_MODE)):
    """Trigger a full wheel scanner run in the background for the mode."""
    import threading

    mode = _parse_mode(mode)

    def _run():
        from database import SessionLocal
        from services.wheel_scanner_service import run_put_scanner, run_call_scanner
        db = SessionLocal()
        try:
            run_put_scanner(db, mode=mode)
            run_call_scanner(db)
        except Exception as e:
            logger.error("Wheel scanner run failed: %s", e, exc_info=True)
            import services.run_status as run_status
            run_status.set_error("wheel_scanner", str(e))
        finally:
            db.close()

    threading.Thread(target=_run, daemon=True).start()
    return {"status": "queued", "message": f"Wheel scanner started in background (mode={mode})"}


@router.get("/scanner/status")
def get_scanner_status():
    import services.run_status as run_status
    return run_status.get_all().get("wheel_scanner", {"state": "idle"})


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
