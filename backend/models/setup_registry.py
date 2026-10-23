"""
Setup registry model.

Each row is one named trading setup. Statuses are LIVE, SHADOW, or RETIRED.
The status enforcement rule is: a setup may be LIVE only if its backtest
results file is stamped with real data (not synthetic, not modeled-only) and
its verdict is PASSES. Anything else caps at SHADOW.
"""
from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.sql import func
from database import Base


class SetupRegistry(Base):
    __tablename__ = "setup_registry"

    id = Column(Integer, primary_key=True, index=True)
    setup_key = Column(String(60), unique=True, nullable=False, index=True)
    name = Column(String(120), nullable=False)
    job = Column(String(30), nullable=False)   # buy_and_hold | wheel | directional
    recipe = Column(Text, nullable=False)       # human-readable conditions
    status = Column(String(10), nullable=False, default="SHADOW")  # LIVE|SHADOW|RETIRED
    backtest_file = Column(String(200), nullable=True)   # path relative to repo root
    backtest_verdict = Column(String(20), nullable=True) # PASSES|SHADOW ONLY|FAILS
    backtest_data_source = Column(String(200), nullable=True)  # stamp from report line 3
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
