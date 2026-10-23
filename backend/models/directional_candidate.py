"""
Directional options candidates.

One row per candidate per run. Suppressed candidates (regime gate, missing data) are
stored with is_suppressed=True and a reason so the UI can display them in a suppressed
section rather than silently dropping them.
"""
import json
from sqlalchemy import Column, Integer, String, Float, Boolean, Text, DateTime
from sqlalchemy.sql import func
from database import Base


class DirectionalCandidate(Base):
    __tablename__ = "directional_candidates"

    id = Column(Integer, primary_key=True, index=True)
    run_at = Column(DateTime(timezone=True), nullable=False, index=True)
    ticker = Column(String(10), nullable=False, index=True)
    rank = Column(Integer, nullable=True)

    # Expectancy ranking components (each 0-100)
    score = Column(Float, nullable=True)               # final weighted score
    prob_score = Column(Float, nullable=True)          # probability component
    rr_score = Column(Float, nullable=True)            # reward-to-risk component
    iv_context_score = Column(Float, nullable=True)    # IV percentile component
    trend_score = Column(Float, nullable=True)         # trend alignment component
    ranking_components_json = Column(Text, nullable=True)  # full breakdown JSON

    # Structure
    option_type = Column(String(4), nullable=True)     # CALL | PUT
    strike = Column(Float, nullable=True)
    expiry = Column(String(12), nullable=True)
    dte = Column(Integer, nullable=True)
    entry_premium = Column(Float, nullable=True)       # mid premium (per share)
    max_loss_per_contract = Column(Float, nullable=True)  # entry_premium * 100
    underlying_entry = Column(Float, nullable=True)
    underlying_target = Column(Float, nullable=True)
    underlying_stop = Column(Float, nullable=True)
    delta_abs = Column(Float, nullable=True)
    open_interest = Column(Integer, nullable=True)
    volume = Column(Integer, nullable=True)

    # Computed numbers
    current_price = Column(Float, nullable=True)
    atm_iv_pct = Column(Float, nullable=True)
    expected_move_dollars = Column(Float, nullable=True)  # ATM straddle approx
    expected_move_pct = Column(Float, nullable=True)
    payoff_at_target = Column(Float, nullable=True)    # net P&L per contract at target
    payoff_at_stop = Column(Float, nullable=True)      # net P&L per contract at stop
    payoff_at_unchanged = Column(Float, nullable=True) # P&L if stock doesn't move

    # IV context
    iv_percentile = Column(Float, nullable=True)
    iv_history_building = Column(Boolean, nullable=True)
    iv_percentile_available = Column(Boolean, nullable=True)

    # Trend context
    above_ma200 = Column(Boolean, nullable=True)
    above_ma50 = Column(Boolean, nullable=True)

    # Flags
    earnings_in_window = Column(Boolean, nullable=True)
    earnings_days_away = Column(Integer, nullable=True)
    iv_crush_risk = Column(Boolean, nullable=True)     # earnings + high IV
    earnings_unavailable = Column(Boolean, nullable=True)  # data fetch failed

    # Regime gate
    regime_verdict = Column(String(10), nullable=True)   # GREEN|YELLOW|RED|UNKNOWN
    regime_data_complete = Column(Boolean, nullable=True)
    is_suppressed = Column(Boolean, nullable=False, default=False)
    suppressed_reason = Column(Text, nullable=True)

    # AI explainer (top 3 only)
    ai_explanation = Column(Text, nullable=True)
    ai_available = Column(Boolean, nullable=True)

    # Journal link (SetupAlert id)
    journal_id = Column(Integer, nullable=True)

    # Untested evidence signals (displayed as context, not ranked inputs)
    momentum_score_raw = Column(Float, nullable=True)
    flow_signals_json = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    @property
    def ranking_components(self) -> dict:
        try:
            return json.loads(self.ranking_components_json or "{}")
        except Exception:
            return {}

    @ranking_components.setter
    def ranking_components(self, value: dict):
        self.ranking_components_json = json.dumps(value)
