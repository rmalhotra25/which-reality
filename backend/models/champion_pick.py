"""
ChampionPick: persistent per-run record of each daily Champions pick.
One row per strategy per run (three rows per Champions run).
Champion table still stores the latest run for display; this table stores all runs for grading.
"""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, Float, String, Boolean, DateTime
from database import Base


def _utcnow():
    return datetime.now(timezone.utc)


# Fixed settlement horizon by strategy (calendar days, no target/stop available)
CHAMPION_HORIZONS = {
    "wheel": 30,
    "options": 21,
    "longterm": 90,
}


class ChampionPick(Base):
    __tablename__ = "champion_picks"

    id = Column(Integer, primary_key=True, index=True)
    strategy = Column(String(20), nullable=False, index=True)   # wheel|options|longterm
    ticker = Column(String(10), nullable=False, index=True)
    run_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    entry_price = Column(Float, nullable=True)
    score = Column(Float, nullable=True)
    grade = Column(String(2), nullable=True)
    reason = Column(String(1000), nullable=True)

    # Outcome fields — filled by settlement job
    is_open = Column(Boolean, nullable=False, default=True)
    settlement_price = Column(Float, nullable=True)
    outcome_pct = Column(Float, nullable=True)      # (settlement - entry) / entry * 100
    settled_at = Column(DateTime(timezone=True), nullable=True)
    days_held = Column(Integer, nullable=True)
    close_reason = Column(String(30), nullable=True)  # time_stop
