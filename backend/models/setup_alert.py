"""
Setup alert and outcome journal models.

SetupAlert: one row per fired alert (or suppressed candidate).
AlertOutcome: one row per closed alert with P&L in percent and R.
"""
import json
from sqlalchemy import Column, Integer, String, Float, Boolean, Text, DateTime
from sqlalchemy.sql import func
from database import Base


class SetupAlert(Base):
    __tablename__ = "setup_alerts"

    id = Column(Integer, primary_key=True, index=True)
    setup_key = Column(String(60), nullable=False, index=True)
    setup_name = Column(String(120), nullable=False)
    setup_status = Column(String(10), nullable=False)  # LIVE | SHADOW at fire time
    ticker = Column(String(10), nullable=False, index=True)
    fired_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    is_suppressed = Column(Boolean, nullable=False, default=False)
    suppressed_reason = Column(Text, nullable=True)  # set when is_suppressed=True

    # Condition snapshot: JSON dict of every condition value at fire time
    conditions_json = Column(Text, nullable=False, default="{}")

    # Suggested action fields (stock setups)
    action = Column(String(30), nullable=True)   # BUY | SELL | WATCH
    entry_price = Column(Float, nullable=True)
    invalidation_price = Column(Float, nullable=True)
    target_price = Column(Float, nullable=True)
    action_summary = Column(Text, nullable=True)  # one-line "why now"

    # Options fields (wheel setup)
    contract_type = Column(String(10), nullable=True)   # PUT | CALL
    strike = Column(Float, nullable=True)
    expiry = Column(String(12), nullable=True)
    premium = Column(Float, nullable=True)
    max_loss_per_contract = Column(Float, nullable=True)
    max_loss_per_position = Column(Float, nullable=True)
    position_size_contracts = Column(Integer, nullable=True)

    # Risk block
    max_loss = Column(Float, nullable=True)
    earnings_in_window = Column(Boolean, nullable=True)
    iv_percentile = Column(Float, nullable=True)
    spread_quality = Column(String(20), nullable=True)
    invalidation_text = Column(Text, nullable=True)

    # Journal state
    is_open = Column(Boolean, nullable=False, default=True)
    outcome_pct = Column(Float, nullable=True)    # filled by daily outcome job
    outcome_r = Column(Float, nullable=True)      # outcome / planned risk (R)
    days_held = Column(Integer, nullable=True)
    closed_at = Column(DateTime(timezone=True), nullable=True)
    close_reason = Column(String(30), nullable=True)  # target|stop|time_stop|manual

    @property
    def conditions(self) -> dict:
        try:
            return json.loads(self.conditions_json or "{}")
        except Exception:
            return {}

    @conditions.setter
    def conditions(self, value: dict):
        self.conditions_json = json.dumps(value)


class AlertEngineRun(Base):
    """One row per engine run, for health display in run_status."""
    __tablename__ = "alert_engine_runs"

    id = Column(Integer, primary_key=True, index=True)
    ran_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    tickers_evaluated = Column(Integer, nullable=False, default=0)
    alerts_fired = Column(Integer, nullable=False, default=0)
    shadow_hits = Column(Integer, nullable=False, default=0)
    suppressed = Column(Integer, nullable=False, default=0)
    errors = Column(Text, nullable=True)  # JSON list of "setup_key: error msg"
    duration_seconds = Column(Float, nullable=True)
