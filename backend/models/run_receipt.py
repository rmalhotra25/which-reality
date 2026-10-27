"""
Run receipt model.

One row per job run, in Postgres, so silence means "ran, nothing
qualified" when a receipt exists. This replaces the in-memory run_status
as the source of truth; run_status is kept as a fallback mirror only.
A job with no receipt is a job that did not run. A failed job leaves a
failed receipt, never silence.
"""
from sqlalchemy import Column, Integer, String, Float, Text, DateTime
from sqlalchemy.sql import func
from database import Base


class RunReceipt(Base):
    __tablename__ = "run_receipts"

    id = Column(Integer, primary_key=True, index=True)
    job_name = Column(String(80), nullable=False, index=True)
    started_at = Column(DateTime(timezone=True), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    # ok | error | skipped
    state = Column(String(10), nullable=False, default="ok")
    tickers_evaluated = Column(Integer, nullable=False, default=0)
    alerts_fired = Column(Integer, nullable=False, default=0)
    suppressed = Column(Integer, nullable=False, default=0)
    duplicates_suppressed = Column(Integer, nullable=False, default=0)
    errors = Column(Text, nullable=True)  # JSON list of error strings
    duration_seconds = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
