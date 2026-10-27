"""
Rule registry model.

One row per alert or notification rule in the app: the 9 setups from the
setup registry and the 5 Challenge alert types. A rule that is not in
this table cannot fire and cannot notify. Statuses are LIVE, SHADOW, or
RETIRED, enforced the same way the setup registry enforces LIVE: a LIVE
rule must have a real implementing function whose thresholds match the
row (checked at startup by services.rule_registry.verify_rules).

Thresholds are numbers in trigger_json, not literals buried in
functions, so the row and the code can be compared instead of drifted.
"""
from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.sql import func
from database import Base


class RuleRegistry(Base):
    __tablename__ = "rule_registry"

    id = Column(Integer, primary_key=True, index=True)
    rule_key = Column(String(80), unique=True, nullable=False, index=True)
    name = Column(String(120), nullable=False)
    category = Column(String(30), nullable=False)  # setup | challenge
    # Plain-language trigger, plus the exact condition as numbers.
    trigger_text = Column(Text, nullable=False)
    trigger_json = Column(Text, nullable=False, default="{}")
    universe = Column(String(200), nullable=True)
    # Exact imperative the alert carries, with placeholders.
    action_template = Column(Text, nullable=False)
    size_rule = Column(Text, nullable=False)
    # Fallback when size cannot be computed: always "suppress".
    size_fallback = Column(String(20), nullable=False, default="suppress")
    invalidation = Column(Text, nullable=False)
    expiry = Column(Text, nullable=False)
    cooldown_days = Column(Integer, nullable=False, default=1)
    dedupe_key_format = Column(String(120), nullable=False)
    status = Column(String(10), nullable=False, default="SHADOW")  # LIVE|SHADOW|RETIRED
    # Dotted path of the implementing function, e.g.
    # services.alert_engine._eval_quality_pullback
    source_function = Column(String(200), nullable=False)
    last_fired_at = Column(DateTime(timezone=True), nullable=True)
    fired_count = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
