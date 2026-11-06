"""AI Picks router: POST /api/ai-picks/generate, GET /api/ai-picks/latest.

Strictly separate from the quant system. This router imports nothing
from the setup registry, the backtest harness, or the Book scoreboard,
and its payloads carry no LIVE status and no setup key. Generation
runs in a background thread (a Claude call plus Polygon context takes
tens of seconds); POST returns immediately with the run id, and the
frontend polls GET /api/ai-picks/latest until the run completes.
"""

import json
import logging
import threading
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import SessionLocal, get_db
from models.ai_pick_run import AIPickRun
from services import ai_picks as ap

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ai-picks", tags=["AI Picks"])


class GenerateBody(BaseModel):
    tickers: list[str] | None = None


def _run_generation(run_id: int, tickers: list[str]):
    db = SessionLocal()
    try:
        run = db.query(AIPickRun).filter(AIPickRun.id == run_id).first()
        if run is None:
            return
        try:
            context = ap.build_context(tickers)
            from services.claude_analyst import ClaudeAnalyst

            payload = ClaudeAnalyst().generate_ai_picks(context)
            prices = {}
            for row in context.get("tickers", []):
                if row.get("price"):
                    prices[row["ticker"]] = row["price"]
            # Prices for long-term tickers Claude added beyond the
            # context list: one batch snapshot, best-effort.
            extra = [i["ticker"] for i in payload.get("long_term_ideas", []) if i["ticker"] not in prices]
            if extra:
                try:
                    from services.polygon_client import get_snapshots_batch

                    for t, snap in (get_snapshots_batch(extra) or {}).items():
                        if snap.get("price"):
                            prices[t] = snap["price"]
                except Exception as exc:
                    logger.warning("ai picks extra prices failed: %s", exc)
            payload = ap.apply_polygon_prices(payload, prices)
            payload["context_as_of"] = datetime.now(timezone.utc).isoformat()
            run.payload = json.dumps(payload)
            run.status = "completed" if not payload.get("parse_error") else "completed_with_warnings"
            run.error = payload.get("parse_error")
        except Exception as exc:
            logger.warning("ai picks generation failed: %s", exc)
            run.status = "failed"
            run.error = f"Generation failed: {type(exc).__name__}."
        db.commit()
    finally:
        db.close()


@router.post("/generate")
def generate(body: GenerateBody, db: Session = Depends(get_db)):
    tickers = ap._clean_tickers(body.tickers) or list(ap.DEFAULT_TICKERS)
    run = AIPickRun(tickers=json.dumps(tickers), status="generating")
    db.add(run)
    db.commit()
    db.refresh(run)
    thread = threading.Thread(target=_run_generation, args=(run.id, tickers), daemon=True)
    thread.start()
    return {"run_id": run.id, "status": "generating", "tickers": tickers}


@router.get("/latest")
def latest(db: Session = Depends(get_db)):
    run = db.query(AIPickRun).order_by(AIPickRun.id.desc()).first()
    if run is None:
        return {"run": None, "generating": False}
    return {"run": ap.serialize_run(run), "generating": run.status == "generating"}


@router.get("/runs")
def runs(db: Session = Depends(get_db)):
    rows = db.query(AIPickRun).order_by(AIPickRun.id.desc()).limit(5).all()
    return {"runs": [ap.serialize_run(r) for r in rows]}
