from datetime import datetime, timezone
import os

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from models.account import AccountBalance, AccountTransaction
from models.wheel import WheelPosition, WheelStatus

router = APIRouter(prefix="/api/account", tags=["Account"])

MAX_POSITION_PCT = 0.10  # never risk more than 10% on a single wheel trade
DEFAULT_ACCOUNT_EQUITY = 100000.0
ACCOUNT_EQUITY_ENV_VAR = "TRADEIQ_ACCOUNT_EQUITY"


def _resolve_equity(db: Session) -> tuple[float, str]:
    """
    Account equity for wheel position limits, in priority order:
    1. Challenge account trading equity, when an initialized Challenge
       account exists in this db.
    2. Configurable account equity from TRADEIQ_ACCOUNT_EQUITY.
    3. Default $100,000, matching the portfolio simulator and the
       Priority 2 alert sizing.
    Returns (equity_dollars, source) where source is one of
    "challenge", "env", "default".

    The old code used the manually stored AccountBalance row, which is
    created at 0.0 when it does not exist, so the wheel card showed a
    10% position limit of $0 and null% of the account for every trade.
    A resolved equity is always positive, so a $0 limit can no longer
    appear. The stored manual balance is still returned as
    stored_balance for the AccountWidget, it just no longer drives the
    position limit.
    """
    if db is not None:
        try:
            from services.challenge_service import compute_state
            state = compute_state(db)
            if state.get("initialized"):
                equity = state.get("trading_equity")
                if equity is not None and float(equity) > 0:
                    return float(equity), "challenge"
        except Exception:
            pass
    env_val = os.environ.get(ACCOUNT_EQUITY_ENV_VAR)
    if env_val:
        try:
            parsed = float(env_val)
            if parsed > 0:
                return parsed, "env"
        except ValueError:
            pass
    return DEFAULT_ACCOUNT_EQUITY, "default"


def _account_payload(db: Session, row: AccountBalance) -> dict:
    at_risk = _capital_at_risk(db)
    equity, equity_source = _resolve_equity(db)
    max_position = round(equity * MAX_POSITION_PCT, 2)
    return {
        "balance": round(row.balance, 2),
        "stored_balance": round(row.balance, 2),
        "equity": round(equity, 2),
        "equity_source": equity_source,
        "capital_at_risk": round(at_risk, 2),
        "available_capital": round(equity - at_risk, 2),
        "max_single_position": max_position,
        "max_position_pct": MAX_POSITION_PCT * 100,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _get_or_create(db: Session) -> AccountBalance:
    row = db.query(AccountBalance).filter(AccountBalance.id == 1).first()
    if row:
        return row
    try:
        row = AccountBalance(id=1, balance=0.0)
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    except Exception:
        db.rollback()
        row = db.query(AccountBalance).filter(AccountBalance.id == 1).first()
        if row:
            return row
        raise


def _capital_at_risk(db: Session) -> float:
    """Sum of capital committed across all non-closed wheel positions.
    put_active: collateral = strike × shares (cost_basis not yet set).
    assigned/call_active: cost_basis × shares (effective purchase price).
    """
    positions = (
        db.query(WheelPosition)
        .filter(WheelPosition.status != WheelStatus.closed)
        .all()
    )
    total = 0.0
    for p in positions:
        shares = p.shares or 100
        if p.cost_basis:
            total += p.cost_basis * shares
        elif p.put_strike:
            total += p.put_strike * shares
    return total


@router.get("")
def get_balance(db: Session = Depends(get_db)):
    row = _get_or_create(db)
    return _account_payload(db, row)


class DepositBody(BaseModel):
    amount: float = Field(..., description="Positive to deposit, negative to withdraw")
    note: str = Field("", max_length=300)


@router.post("/deposit")
def deposit(body: DepositBody, db: Session = Depends(get_db)):
    row = _get_or_create(db)
    row.balance = round(row.balance + body.amount, 2)
    row.updated_at = datetime.now(timezone.utc)

    txn = AccountTransaction(amount=body.amount, note=body.note or None)
    db.add(txn)
    db.commit()
    db.refresh(row)

    payload = _account_payload(db, row)
    payload["transaction"] = {"amount": body.amount, "note": body.note}
    return payload


class SetBalanceBody(BaseModel):
    balance: float = Field(..., gt=0)
    note: str = Field("Manual balance update", max_length=300)


@router.patch("")
def set_balance(body: SetBalanceBody, db: Session = Depends(get_db)):
    row = _get_or_create(db)
    diff = round(body.balance - row.balance, 2)
    row.balance = round(body.balance, 2)
    row.updated_at = datetime.now(timezone.utc)

    txn = AccountTransaction(amount=diff, note=body.note)
    db.add(txn)
    db.commit()
    db.refresh(row)

    return _account_payload(db, row)


@router.get("/transactions")
def get_transactions(db: Session = Depends(get_db)):
    txns = (
        db.query(AccountTransaction)
        .order_by(AccountTransaction.created_at.desc())
        .limit(50)
        .all()
    )
    return [
        {
            "id": t.id,
            "amount": t.amount,
            "note": t.note,
            "created_at": t.created_at.isoformat(),
        }
        for t in txns
    ]
