from datetime import datetime, timezone
from sqlalchemy import Column, Integer, Float, String, Date, DateTime, ForeignKey, Text
from database import Base


def _utcnow():
    return datetime.now(timezone.utc)


class ChallengeAccount(Base):
    """The $1k to $10k challenge account. Singleton in practice (one row)."""
    __tablename__ = "challenge_accounts"

    id = Column(Integer, primary_key=True, index=True)
    start_date = Column(Date, nullable=False)
    starting_capital_cents = Column(Integer, nullable=False, default=100000)
    # Risk budget (percent values; the tab warns against them, never blocks)
    risk_per_trade_pct = Column(Float, nullable=False, default=5)
    max_open_risk_pct = Column(Float, nullable=False, default=20)
    pause_drawdown_pct = Column(Float, nullable=False, default=40)
    created_at = Column(DateTime, default=_utcnow)


class ChallengeStage(Base):
    """One leg of the ladder. Each stage targets 10x its starting equity."""
    __tablename__ = "challenge_stages"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("challenge_accounts.id"), nullable=False, index=True)
    stage_number = Column(Integer, nullable=False)
    start_date = Column(Date, nullable=False)
    starting_equity_cents = Column(Integer, nullable=False)
    target_cents = Column(Integer, nullable=False)
    status = Column(String(12), nullable=False, default="active")  # active | graduated
    end_date = Column(Date, nullable=True)
    ending_equity_cents = Column(Integer, nullable=True)


class ChallengeCashFlow(Base):
    """Money moving in or out of the account outside of trades.

    amount_cents is signed: money in is positive, money out is negative.
    flow_type is one of: initial_funding, deposit, withdrawal, dividend,
    interest, fee, adjustment. Dividends and interest are account earnings
    (they count toward trading progress); deposits, withdrawals, and
    adjustments are external flows (they do not).
    """
    __tablename__ = "challenge_cash_flows"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("challenge_accounts.id"), nullable=False, index=True)
    occurred_at = Column(DateTime, nullable=False, default=_utcnow)
    flow_type = Column(String(20), nullable=False)
    amount_cents = Column(Integer, nullable=False)
    note = Column(String(500), nullable=True)


class ChallengeTrade(Base):
    """One manually entered position in the challenge account.

    Money is stored as integer cents for the cash effects; prices are
    dollars per share (stock) or per contract share unit (options).
    multiplier is 1 for stock and 100 for options and spreads.
    """
    __tablename__ = "challenge_trades"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("challenge_accounts.id"), nullable=False, index=True)
    opened_at = Column(DateTime, nullable=False, default=_utcnow)
    closed_at = Column(DateTime, nullable=True)
    status = Column(String(8), nullable=False, default="open")  # open | closed
    asset_kind = Column(String(8), nullable=False, default="stock")  # stock | call | put | spread
    side = Column(String(6), nullable=False, default="long")  # long | short
    symbol = Column(String(20), nullable=False)
    underlying = Column(String(20), nullable=True)
    quantity = Column(Float, nullable=False)
    multiplier = Column(Float, nullable=False, default=1)
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=True)
    current_price = Column(Float, nullable=True)  # manual mark
    fees_open_cents = Column(Integer, nullable=False, default=0)
    fees_close_cents = Column(Integer, nullable=False, default=0)
    open_cash_effect_cents = Column(Integer, nullable=False)
    close_cash_effect_cents = Column(Integer, nullable=True)
    planned_max_loss_cents = Column(Integer, nullable=True)
    target_price = Column(Float, nullable=True)
    stop_price = Column(Float, nullable=True)
    expiry_date = Column(Date, nullable=True)
    setup_key = Column(String(50), nullable=True)
    thesis = Column(Text, nullable=True)
    invalidation = Column(Text, nullable=True)
    legs_note = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)


class ChallengeAlert(Base):
    """An in-app challenge alert: an opportunity that fits the risk budget,
    a position that needs review, a milestone, or a drawdown warning."""
    __tablename__ = "challenge_alerts"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("challenge_accounts.id"), nullable=False, index=True)
    stage_id = Column(Integer, ForeignKey("challenge_stages.id"), nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    alert_type = Column(String(30), nullable=False)  # eligible_setup | eligible_directional | position_review | milestone | drawdown_warning
    source_type = Column(String(25), nullable=False)  # setup_alert | directional_candidate | challenge_trade | snapshot | account
    source_id = Column(Integer, nullable=True)
    ticker = Column(String(20), nullable=True)
    title = Column(String(300), nullable=False)
    body = Column(Text, nullable=True)
    severity = Column(String(12), nullable=False, default="info")  # opportunity | info | warning | action
    status = Column(String(12), nullable=False, default="unread")  # unread | read | dismissed | acted
    dedupe_key = Column(String(200), nullable=False, unique=True)
    data_json = Column(Text, nullable=True)  # JSON payload for pre-filling the trade form


class ChallengeSnapshot(Base):
    """End-of-day (or on-demand) account state, one row per snapshot."""
    __tablename__ = "challenge_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("challenge_accounts.id"), nullable=False, index=True)
    stage_id = Column(Integer, ForeignKey("challenge_stages.id"), nullable=True)
    taken_at = Column(DateTime, nullable=False, default=_utcnow)
    cash_cents = Column(Integer, nullable=False)
    open_value_cents = Column(Integer, nullable=False)
    equity_cents = Column(Integer, nullable=False)
    trading_equity_cents = Column(Integer, nullable=False)
    open_risk_cents = Column(Integer, nullable=False, default=0)
