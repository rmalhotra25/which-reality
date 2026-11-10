"""Router-level tests for the 36-hour wheel batch expiry in GET /api/today.

A stale wheel batch must not surface as live trades, and the staleness
must be visible in the response: sources.wheel_stale and a note in
data_note, which the tab renders at the top.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models import directional_candidate  # noqa: F401  (registers directional_candidates)
from models import setup_alert  # noqa: F401  (registers setup_alerts table)
from models import wheel as wheel_models  # noqa: F401  (registers wheel tables)
from routers.today import get_today
from services.wheel_scanner_service import persist_wheel_candidates
from test_wheel_scanner_persist import _result


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_today_shows_no_wheel_trades_for_stale_batch():
    old = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    db = _session()
    persist_wheel_candidates(db, _result(run_at=old))
    resp = get_today(db=db)
    assert resp["sources"]["wheel_stale"] is True
    assert resp["sources"]["wheel_run_at"] is not None
    assert "stale" in resp["data_note"]
    assert [i for i in resp["items"] if i["kind"] == "wheel"] == []
    assert [b for b in resp["blocked"] if b["kind"] == "wheel"] == []


def test_today_shows_fresh_wheel_trades():
    recent = (datetime.now(timezone.utc) - timedelta(hours=20)).isoformat()
    db = _session()
    persist_wheel_candidates(db, _result(run_at=recent))
    resp = get_today(db=db)
    assert resp["sources"]["wheel_stale"] is False
    assert "stale" not in resp["data_note"]
    wheel_items = [i for i in resp["items"] if i["kind"] == "wheel"]
    assert [i["ticker"] for i in wheel_items] == ["FLEX", "BE", "RKLB", "HOOD"]
    assert wheel_items[0]["contracts"] == 2
    assert wheel_items[0]["risk_dollars"] == 800.0
