from sqlalchemy import Column, Integer, String, Float, DateTime, Index
from sqlalchemy.sql import func
from database import Base


class IVSnapshot(Base):
    """One ATM IV reading per ticker per scheduler run."""
    __tablename__ = "iv_snapshots"

    id           = Column(Integer, primary_key=True, index=True)
    ticker       = Column(String(10), nullable=False)
    captured_at  = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    atm_iv       = Column(Float, nullable=False)          # decimal fraction (0.28 = 28%)
    underlying_price = Column(Float, nullable=False)
    expiry       = Column(String(12), nullable=True)       # ISO date of the option expiry used
    dte          = Column(Integer, nullable=True)
    iv_source    = Column(String(20), nullable=False)      # "polygon" | "yfinance" | "hv_fallback"


# Composite index so percentile queries (filter ticker, order captured_at) stay fast
_idx = Index("ix_iv_snapshots_ticker_time", IVSnapshot.ticker, IVSnapshot.captured_at)
