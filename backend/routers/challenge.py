"""
Challenge router: the $1k to $10k campaign ledger and scoreboard.

GET  /api/challenge                  full challenge state
POST /api/challenge/account          initialize the account and Stage 1
POST /api/challenge/cash-flows       record a cash flow
POST /api/challenge/trades           open a trade (manual fill entry)
PATCH /api/challenge/trades/{id}/mark   set a manual mark on an open trade
POST /api/challenge/trades/{id}/close   close a trade at an exit price
POST /api/challenge/snapshot         snapshot state, run the graduation check
POST /api/challenge/alerts/refresh   generate alerts now, return state
POST /api/challenge/alerts/test      send a Telegram test message, return status
PATCH /api/challenge/alerts/{id}     set an alert status (read/dismissed/acted)
"""
import logging
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from services import challenge_service as svc
from services.telegram_notifier import send_telegram_message, telegram_configured

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/challenge", tags=["Challenge"])


class AccountIn(BaseModel):
    start_date: date
    starting_capital: float = 1000
    risk_per_trade_pct: float = 5
    max_open_risk_pct: float = 20
    pause_drawdown_pct: float = 40


class CashFlowIn(BaseModel):
    flow_type: str
    amount: float  # dollars; sign rules applied in the service by flow type
    occurred_at: datetime | None = None
    note: str | None = None


class TradeIn(BaseModel):
    asset_kind: str = "stock"
    side: str = "long"
    symbol: str
    underlying: str | None = None
    quantity: float
    multiplier: float | None = None
    entry_price: float
    current_price: float | None = None
    fees_open: float = 0
    planned_max_loss: float | None = None
    target_price: float | None = None
    stop_price: float | None = None
    expiry_date: date | None = None
    setup_key: str | None = None
    thesis: str | None = None
    invalidation: str | None = None
    legs_note: str | None = None
    notes: str | None = None
    opened_at: datetime | None = None


class MarkIn(BaseModel):
    current_price: float


class CloseIn(BaseModel):
    exit_price: float
    fees_close: float = 0
    closed_at: datetime | None = None


@router.get("")
def get_state(db: Session = Depends(get_db)):
    return svc.compute_state(db)


@router.post("/account")
def init_account(body: AccountIn, db: Session = Depends(get_db)):
    try:
        return svc.init_account(
            db,
            start_date=body.start_date,
            starting_capital_cents=int(round(body.starting_capital * 100)),
            risk_per_trade_pct=body.risk_per_trade_pct,
            max_open_risk_pct=body.max_open_risk_pct,
            pause_drawdown_pct=body.pause_drawdown_pct,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/cash-flows")
def add_cash_flow(body: CashFlowIn, db: Session = Depends(get_db)):
    try:
        return svc.add_cash_flow(
            db, body.flow_type, body.amount,
            occurred_at=body.occurred_at, note=body.note,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/trades")
def add_trade(body: TradeIn, db: Session = Depends(get_db)):
    try:
        return svc.add_trade(db, body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/trades/{trade_id}/mark")
def update_mark(trade_id: int, body: MarkIn, db: Session = Depends(get_db)):
    try:
        return svc.update_mark(db, trade_id, body.current_price)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/trades/{trade_id}/close")
def close_trade(trade_id: int, body: CloseIn, db: Session = Depends(get_db)):
    try:
        return svc.close_trade(
            db, trade_id, body.exit_price,
            fees_close_dollars=body.fees_close, closed_at=body.closed_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/snapshot")
def snapshot(db: Session = Depends(get_db)):
    try:
        return svc.take_snapshot(db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


class AlertStatusIn(BaseModel):
    status: str


@router.post("/alerts/refresh")
def refresh_alerts(db: Session = Depends(get_db)):
    svc.generate_challenge_alerts(db)
    return svc.compute_state(db)


@router.post("/alerts/test")
def test_alert():
    sent = send_telegram_message(
        "TradeIQ Challenge alerts are connected. This is a test."
    )
    return {"telegram_configured": telegram_configured(), "sent": sent}


@router.patch("/alerts/{alert_id}")
def set_alert_status(alert_id: int, body: AlertStatusIn, db: Session = Depends(get_db)):
    try:
        return svc.set_alert_status(db, alert_id, body.status)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
