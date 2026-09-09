from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, DateTime, UniqueConstraint
from database import Base


def _utcnow():
    return datetime.now(timezone.utc)


class LeveragedMASignalState(Base):
    __tablename__ = "leveraged_ma_signal_state"

    id = Column(Integer, primary_key=True)
    asset_key = Column(String(20), nullable=False)    # e.g. "TQQQ_QQQ"
    direction = Column(String(20), nullable=False)    # "trend_follow" | "mean_reversion"
    last_side = Column(String(10), nullable=True)     # "above" | "below"
    last_checked_at = Column(DateTime, nullable=True)
    last_cross_at = Column(DateTime, nullable=True)
    last_cross_side = Column(String(10), nullable=True)  # side it crossed TO
    sma_at_check = Column(String(20), nullable=True)      # stored as string to avoid Float precision issues

    __table_args__ = (
        UniqueConstraint("asset_key", "direction", name="uq_leveraged_ma_key_dir"),
    )
