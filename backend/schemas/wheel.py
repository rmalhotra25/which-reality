from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


class WheelRecommendationSchema(BaseModel):
    id: int
    ticker: str
    rank: int
    score: float
    grade: str
    explanation: str
    put_strike: Optional[float] = None
    put_expiry: Optional[str] = None
    put_premium: Optional[float] = None
    iv_rank: Optional[float] = None
    run_at: datetime
    accepted: bool
    accepted_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class WheelHistorySchema(BaseModel):
    id: int
    from_status: Optional[str] = None
    to_status: str
    note: Optional[str] = None
    changed_at: datetime

    model_config = {"from_attributes": True}


class WheelPositionSchema(BaseModel):
    id: int
    recommendation_id: int
    ticker: str
    status: str
    put_strike: float
    put_expiry: str
    put_premium_rcvd: Optional[float] = None
    put_opened_at: Optional[datetime] = None
    assigned_at: Optional[datetime] = None
    cost_basis: Optional[float] = None
    shares: int
    call_strike: Optional[float] = None
    call_expiry: Optional[str] = None
    call_premium_rcvd: Optional[float] = None
    call_opened_at: Optional[datetime] = None
    call_suggestion: Optional[str] = None
    call_suggestion_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    total_pnl: Optional[float] = None
    notes: Optional[str] = None
    history: List[WheelHistorySchema] = []

    model_config = {"from_attributes": True}


class AcceptWheelBody(BaseModel):
    put_strike: Optional[float] = None
    put_expiry: Optional[str] = None
    put_premium_rcvd: Optional[float] = None


class UpdateStatusBody(BaseModel):
    new_status: str
    note: Optional[str] = None
    assigned_at: Optional[datetime] = None
    call_strike: Optional[float] = None
    call_expiry: Optional[str] = None
    call_premium_rcvd: Optional[float] = None
    total_pnl: Optional[float] = None
    notes: Optional[str] = None
