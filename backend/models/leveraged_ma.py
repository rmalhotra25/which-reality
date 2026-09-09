from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, UniqueConstraint
from database import Base


def _utcnow():
    return datetime.now(timezone.utc)


class LeveragedMASignalState(Base):
    __tablename__ = "leveraged_ma_signal_state"

    id = Column(Integer, primary_key=True)
    asset_key = Column(String(20), nullable=False)
    # "ma_crossover" for all rows (replaces old trend_follow/mean_reversion split)
    direction = Column(String(20), nullable=False)
    # Raw daily trigger zone: "buy_zone" | "sell_zone" | "neutral"
    last_side = Column(String(12), nullable=True)
    last_checked_at = Column(DateTime, nullable=True)
    # Most recent confirmed position change
    last_cross_at = Column(DateTime, nullable=True)
    last_cross_side = Column(String(10), nullable=True)
    sma_at_check = Column(String(20), nullable=True)
    # Confirmation state machine (new columns)
    confirmed_position = Column(String(5), nullable=True)   # "in" | "out"
    pending_signal = Column(String(5), nullable=True)       # "buy" | "sell"
    pending_days = Column(Integer, nullable=True, default=0)

    __table_args__ = (
        UniqueConstraint("asset_key", "direction", name="uq_leveraged_ma_key_dir"),
    )
