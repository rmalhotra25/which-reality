import enum
from sqlalchemy import Column, Integer, String, Float, DateTime, Text, Enum
from sqlalchemy.sql import func
from database import Base


class TabType(str, enum.Enum):
    options = "options"
    longterm = "longterm"


class GradeEnum(str, enum.Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    F = "F"


class Recommendation(Base):
    __tablename__ = "recommendations"

    id = Column(Integer, primary_key=True, index=True)
    tab = Column(Enum(TabType), nullable=False, index=True)
    ticker = Column(String(10), nullable=False)
    rank = Column(Integer, nullable=False)
    score = Column(Float, nullable=False)
    grade = Column(Enum(GradeEnum), nullable=False)
    explanation = Column(Text, nullable=False)

    # Options-specific
    option_type = Column(String(4), nullable=True)   # CALL | PUT
    strike = Column(Float, nullable=True)
    expiry = Column(String(12), nullable=True)
    entry_price = Column(Float, nullable=True)
    exit_price = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)

    # Long-term-specific
    investment_type = Column(String(10), nullable=True)  # growth | income
    target_price = Column(Float, nullable=True)
    time_horizon = Column(String(30), nullable=True)

    run_at = Column(DateTime(timezone=True), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
