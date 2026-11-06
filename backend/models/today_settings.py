"""Today's Book settings: one row (id=1) for the main decision-support account.

This is deliberately separate from the $1,000 Challenge account. The
Challenge account is a small, separately tracked experiment; Today's Book
sizes against the account the user actually trades in, defaulting to
$100,000 (the portfolio simulator default) unless TRADEIQ_ACCOUNT_EQUITY
is set or the user saves a different size here.

Drawdown is measured against peak_equity, the highest account equity
saved for this book. The user updates account equity in settings as the
account changes; the brake follows the portfolio simulator thresholds
(halve risk at a 10% drawdown, pause new entries at 15%).
"""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Float, Integer, Text

from database import Base


class TodaySettings(Base):
    __tablename__ = "today_settings"

    id = Column(Integer, primary_key=True)
    account_equity = Column(Float, nullable=False, default=100000.0)
    peak_equity = Column(Float, nullable=False, default=100000.0)
    risk_pct = Column(Float, nullable=False, default=1.0)
    max_heat_pct = Column(Float, nullable=False, default=10.0)
    max_positions = Column(Integer, nullable=False, default=10)
    max_position_pct = Column(Float, nullable=False, default=10.0)
    # JSON list of tickers the user owns shares in, for covered calls.
    # Covered calls only ever cover shares already owned.
    covered_call_tickers = Column(Text, nullable=False, default="[]")
    updated_at = Column(DateTime(timezone=True), nullable=True)

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)
