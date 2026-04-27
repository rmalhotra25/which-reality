from datetime import datetime
from sqlalchemy import Column, Integer, Float, String, DateTime
from database import Base


class AccountBalance(Base):
    __tablename__ = "account_balance"

    id = Column(Integer, primary_key=True, default=1)
    balance = Column(Float, nullable=False, default=25000.0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AccountTransaction(Base):
    __tablename__ = "account_transactions"

    id = Column(Integer, primary_key=True, index=True)
    amount = Column(Float, nullable=False)       # positive = deposit, negative = withdrawal
    note = Column(String(300), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
