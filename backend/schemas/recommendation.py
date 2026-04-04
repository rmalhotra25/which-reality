from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class RecommendationSchema(BaseModel):
    id: int
    tab: str
    ticker: str
    rank: int
    score: float
    grade: str
    explanation: str
    option_type: Optional[str] = None
    strike: Optional[float] = None
    expiry: Optional[str] = None
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    stop_loss: Optional[float] = None
    investment_type: Optional[str] = None
    target_price: Optional[float] = None
    time_horizon: Optional[str] = None
    run_at: datetime

    model_config = {"from_attributes": True}
