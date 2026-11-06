"""AI Picks run: one persisted Claude generation for the AI Picks section.

AI Picks is strictly separate from the quant system. A run never touches
the setup registry, the backtest harness, or the Book scoreboard, and
nothing in a run is ever marked LIVE. Runs are stored so the page can
show the last generation without re-calling Claude on every load.
"""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, Text

from database import Base


class AIPickRun(Base):
    __tablename__ = "ai_pick_runs"

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    tickers = Column(Text, nullable=False, default="[]")
    status = Column(Text, nullable=False, default="generating")
    payload = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
