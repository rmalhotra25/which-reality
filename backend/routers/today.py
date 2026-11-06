"""Today's Book router: GET /api/today and settings.

GET /api/today aggregates the day's best setups from the existing
engines (wheel, setup alerts, directional, covered calls) and sizes
them with the portfolio simulator rules in services.today_book. It is
cache-only except covered calls, which fetch one chain per owned
ticker (capped at 5) on request. It never triggers an engine run and
never places an order.

Explanations: quant template by default. With ?explain=claude the
router also tries ClaudeAnalyst.explain_today; any failure, or any
item Claude does not explain, falls back to the quant text, and the
response labels the source per item. Claude never sets a number.
"""

import json
import logging
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from models.today_settings import TodaySettings
from services import today_book as tb

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/today", tags=["Today"])

DEFAULT_EQUITY = 100000.0
EQUITY_ENV_VAR = "TRADEIQ_ACCOUNT_EQUITY"


def _default_equity() -> float:
    try:
        val = float(os.environ.get(EQUITY_ENV_VAR, "") or 0)
        if val > 0:
            return val
    except ValueError:
        pass
    return DEFAULT_EQUITY


def _get_or_create_settings(db: Session) -> TodaySettings:
    row = db.query(TodaySettings).filter(TodaySettings.id == 1).first()
    if row:
        return row
    row = TodaySettings(
        id=1,
        account_equity=_default_equity(),
        peak_equity=_default_equity(),
        risk_pct=1.0,
        max_heat_pct=10.0,
        max_positions=10,
        max_position_pct=10.0,
        covered_call_tickers="[]",
    )
    try:
        db.add(row)
        db.commit()
        db.refresh(row)
    except Exception:
        db.rollback()
        row = db.query(TodaySettings).filter(TodaySettings.id == 1).first()
        if row:
            return row
        raise
    return row


class SettingsBody(BaseModel):
    account_equity: float | None = Field(default=None, gt=0)
    risk_pct: float | None = Field(default=None, ge=0.1, le=2.0)
    max_heat_pct: float | None = Field(default=None, ge=1.0, le=50.0)
    max_positions: int | None = Field(default=None, ge=1, le=30)
    max_position_pct: float | None = Field(default=None, ge=1.0, le=25.0)
    covered_call_tickers: list[str] | None = None


@router.get("/settings")
def get_settings(db: Session = Depends(get_db)):
    return tb.settings_to_dict(_get_or_create_settings(db))


@router.put("/settings")
def put_settings(body: SettingsBody, db: Session = Depends(get_db)):
    row = _get_or_create_settings(db)
    if body.account_equity is not None:
        row.account_equity = float(body.account_equity)
        # Peak only ever rises on a save: the drawdown brake measures
        # the book against its best saved equity.
        if row.account_equity > row.peak_equity:
            row.peak_equity = float(body.account_equity)
    if body.risk_pct is not None:
        row.risk_pct = float(body.risk_pct)
    if body.max_heat_pct is not None:
        row.max_heat_pct = float(body.max_heat_pct)
    if body.max_positions is not None:
        row.max_positions = int(body.max_positions)
    if body.max_position_pct is not None:
        row.max_position_pct = float(body.max_position_pct)
    if body.covered_call_tickers is not None:
        clean = sorted({str(t).strip().upper() for t in body.covered_call_tickers if str(t).strip()})
        row.covered_call_tickers = json.dumps(clean[:10])
    row.touch()
    db.commit()
    db.refresh(row)
    return tb.settings_to_dict(row)


@router.get("")
def get_today(explain: str = Query(default="quant"), db: Session = Depends(get_db)):
    settings_row = _get_or_create_settings(db)
    settings = tb.settings_to_dict(settings_row)

    heat, open_positions, assigned = tb.open_wheel_heat(db)
    risk_bar = tb.build_risk_bar(settings, heat, open_positions)

    wheel, wheel_run_at = tb.wheel_candidates(db)
    live_alerts, shadow_alerts = tb.alert_candidates(db)
    directional = tb.directional_research(db)

    # Covered calls: shares the user owns, from settings plus any
    # assigned wheel positions. Unavailable tickers are reported, not
    # silently dropped.
    cc_tickers = list(dict.fromkeys(
        settings["covered_call_tickers"] + list(assigned.keys())
    ))
    cc_raw = tb.covered_call_candidates(cc_tickers, assigned) if cc_tickers else []
    cc_tradable = [c for c in cc_raw if c.get("tradable", True)]
    cc_unavailable = [
        tb.normalize_item(c, {
            "contracts": 0, "capital_at_risk": 0.0, "risk_dollars": 0.0,
            "premium_net_total": 0.0, "blocked_reason": None,
            "blocked_text": None,
        })
        for c in cc_raw if not c.get("tradable", True)
    ]
    # Unavailable covered calls carry no numbers, so give them a plain
    # explanation without pretending a trade exists.
    for item in cc_unavailable:
        item["title"] = f"Covered call on {item.get('ticker')}: unavailable"
        item["risk_text"] = "No trade is shown because no tradable call could be priced."
        item["invalidation_text"] = ""
        item["explanation"] = item.get("unavailable_reason") or "No listed call chain could be priced."
        item["explanation_source"] = "quant"

    # LIVE candidates only are ranked and sized. SHADOW alerts and
    # directional candidates go to research_only, never sized.
    live_candidates = wheel + live_alerts + cc_tradable
    items, blocked = tb.rank_and_size(live_candidates, settings, heat, open_positions)

    research_only = []
    for cand in shadow_alerts:
        research_only.append(tb.normalize_item(cand, {
            "contracts": 0, "capital_at_risk": 0.0, "risk_dollars": 0.0,
            "premium_net_total": 0.0, "blocked_reason": None,
            "blocked_text": "SHADOW: shown for research only, never sized as a live trade.",
        }))
    for cand in directional:
        research_only.append(tb.normalize_item(cand, {
            "contracts": 0, "capital_at_risk": 0.0, "risk_dollars": 0.0,
            "premium_net_total": 0.0, "blocked_reason": None,
            "blocked_text": "SHADOW: shown for research only. Its stored premium is a mid, not a tradable price.",
        }))

    # Scoreboard, reused from the Book router so the journal is the
    # same one the Book tab shows.
    scoreboard = None
    try:
        from routers.book import get_scoreboard

        scoreboard = get_scoreboard(db)
    except Exception as exc:
        logger.warning("today scoreboard unavailable: %s", exc)

    # Claude explanations are wording only. They run after quant has
    # ranked and sized everything, and any failure keeps the quant text.
    if explain == "claude" and items:
        try:
            from services.ai_boundary import explain_or_fallback
            from services.claude_analyst import ClaudeAnalyst

            payload = [
                {
                    "ticker": it["ticker"],
                    "kind": it["kind"],
                    "strike": it.get("strike"),
                    "expiry": it.get("expiry"),
                    "contracts": it.get("contracts"),
                    "premium_net_per_contract": it.get("premium_net_per_contract"),
                    "max_loss_per_contract": it.get("max_loss_per_contract"),
                    "invalidation_price": it.get("invalidation_price"),
                }
                for it in items
            ]
            analyst = ClaudeAnalyst()
            texts = explain_or_fallback(
                analyst.explain_today, payload,
                "Quant-decided setup; see the numbers on the card.",
            )
            for it in items:
                text = texts.get(str(it["ticker"]).upper())
                if text and text != "Quant-decided setup; see the numbers on the card.":
                    it["explanation"] = text
                    it["explanation_source"] = "claude"
        except Exception as exc:
            logger.warning("today Claude explanations unavailable, keeping quant text: %s", exc)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of_date": datetime.now(timezone.utc).date().isoformat(),
        "data_note": tb.DATA_NOTE,
        "settings": settings,
        "risk_bar": risk_bar,
        "items": items,
        "blocked": blocked,
        "unavailable": cc_unavailable,
        "research_only": research_only,
        "scoreboard": scoreboard,
        "sources": {
            "wheel_run_at": wheel_run_at,
            "alerts_window_hours": 36,
            "covered_call_tickers": cc_tickers,
        },
    }
