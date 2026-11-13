"""Tests for persisting wheel-mode scanner candidates to WheelRecommendation.

Today's Book reads the latest WheelRecommendation batch. Since the Oct 27
2026 W9 change the old WheelEngine no longer writes that table on any
schedule, so each wheel-mode scanner run persists its candidates here.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models.wheel import WheelRecommendation
from services.today_book import wheel_candidates
from services.wheel_scanner_service import persist_wheel_candidates


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _result(run_at="2026-11-10T15:32:10.884939+00:00"):
    return {
        "candidates": [
            {
                "ticker": "FLEX", "strike": 70.0, "expiry": "2026-12-18",
                "dte": 38, "sale_price": 4.0, "premium_source": "bid",
                "premium_per_contract": 400.0, "breakeven": 66.0,
                "iv_pct": 75.8, "iv_percentile": None, "delta_abs": 0.27,
                "assignment_chance_pct": 27, "open_interest": 725,
                "spread_pct": 2.5, "current_price": 78.57,
                "rank_score": 0.0375, "ev_per_contract": 292.0,
                "raw_pppd": 0.000015, "tier_name": "moderate",
                "mode": "wheel", "penalties": [],
            },
            {
                "ticker": "BE", "strike": 175.0, "expiry": "2026-11-27",
                "dte": 17, "sale_price": 7.65, "premium_source": "bid",
                "premium_per_contract": 765.0, "breakeven": 167.35,
                "iv_pct": 82.5, "iv_percentile": None, "delta_abs": 0.30,
                "assignment_chance_pct": 30, "open_interest": 662,
                "spread_pct": 8.7, "current_price": 188.91,
                "rank_score": 0.0199, "ev_per_contract": 386.07,
                "raw_pppd": 0.0000257, "tier_name": "moderate",
                "mode": "wheel", "penalties": [],
            },
            {
                "ticker": "RKLB", "strike": 55.0, "expiry": "2026-11-27",
                "dte": 17, "sale_price": 2.28, "premium_source": "bid",
                "premium_per_contract": 228.0, "breakeven": 52.72,
                "iv_pct": 79.6, "iv_percentile": None, "delta_abs": 0.30,
                "assignment_chance_pct": 30, "open_interest": 476,
                "spread_pct": 7.2, "current_price": 59.38,
                "rank_score": 0.0185, "ev_per_contract": 112.86,
                "raw_pppd": 0.0000244, "tier_name": "moderate",
                "mode": "wheel", "penalties": [],
            },
            {
                "ticker": "HOOD", "strike": 77.0, "expiry": "2026-11-27",
                "dte": 17, "sale_price": 2.45, "premium_source": "bid",
                "premium_per_contract": 245.0, "breakeven": 74.55,
                "iv_pct": 58.2, "iv_percentile": None, "delta_abs": 0.31,
                "assignment_chance_pct": 31, "open_interest": 142,
                "spread_pct": 4.4, "current_price": 81.6,
                "rank_score": 0.0069, "ev_per_contract": 58.69,
                "raw_pppd": 0.0000187, "tier_name": "moderate",
                "mode": "wheel", "penalties": [],
            },
        ],
        "excluded": [],
        "run_at": run_at,
        "universe_size": 607,
        "mode": "wheel",
    }


def test_persist_writes_rows_with_scanner_run_at():
    db = _session()
    assert persist_wheel_candidates(db, _result()) == 4
    rows = db.query(WheelRecommendation).order_by(WheelRecommendation.rank).all()
    assert [r.ticker for r in rows] == ["FLEX", "BE", "RKLB", "HOOD"]
    assert rows[0].put_strike == 70.0
    assert rows[0].put_premium == 4.0
    assert rows[0].put_expiry == "2026-12-18"
    assert rows[0].premium_source == "bid"
    assert rows[0].breakeven == 66.0
    # SQLite drops tzinfo on round-trip; Postgres keeps it. Compare the
    # timestamp itself, not the offset suffix.
    assert rows[0].run_at.isoformat().startswith("2026-11-10T15:32:10.884939")
    # Scores store the raw EV rank, not the old 0-100 composite.
    assert rows[0].quant_score == 0.0375
    assert rows[0].combined_score == 0.0375
    # Grades are relative within the batch: top quarter A, then B, C, D.
    assert [r.grade for r in rows] == ["A", "B", "C", "D"]


def test_persist_empty_result_writes_nothing():
    db = _session()
    assert persist_wheel_candidates(db, {"candidates": [], "run_at": None}) == 0
    assert db.query(WheelRecommendation).count() == 0


def test_todays_book_reads_persisted_batch_by_premium_at_risk():
    from datetime import datetime, timedelta, timezone

    # Use a recent run_at: the 36-hour staleness rule would mark the
    # original hardcoded Nov 10 timestamp as stale once time passes.
    recent = (datetime.now(timezone.utc) - timedelta(hours=20)).isoformat()
    db = _session()
    persist_wheel_candidates(db, _result(run_at=recent))
    cands, run_at, stale = wheel_candidates(db)
    assert stale is False
    assert [c["ticker"] for c in cands] == ["FLEX", "BE", "RKLB", "HOOD"]
    flex = cands[0]
    assert flex["premium_net_per_contract"] == 400.0
    assert flex["risk_per_contract"] == 400.0
    assert flex["risk_measure"] == "premium_at_risk"
    # Assignment worst case is still reported, not sized on.
    assert flex["max_loss_per_contract"] == 6600.0
    assert flex["notional_per_contract"] == 7000.0


# --- 36-hour wheel batch expiry -----------------------------------------
# A batch older than 36 hours is stale and returns no candidates, so a
# weeks-old pick is never presented as a live trade. QCOM Nov 10 2026:
# the Oct 27 batch still offered a $175 put after QCOM had closed at
# $171.47, below its own invalidation level.

def test_wheel_candidates_expires_batch_older_than_36h():
    from datetime import datetime, timedelta, timezone

    old = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    db = _session()
    persist_wheel_candidates(db, _result(run_at=old))
    cands, run_at, stale = wheel_candidates(db)
    assert cands == []
    assert stale is True
    assert run_at is not None


def test_wheel_candidates_keeps_yesterdays_batch():
    from datetime import datetime, timedelta, timezone

    recent = (datetime.now(timezone.utc) - timedelta(hours=20)).isoformat()
    db = _session()
    persist_wheel_candidates(db, _result(run_at=recent))
    cands, run_at, stale = wheel_candidates(db)
    assert stale is False
    assert [c["ticker"] for c in cands] == ["FLEX", "BE", "RKLB", "HOOD"]


def test_wheel_candidates_empty_when_no_batch():
    db = _session()
    cands, run_at, stale = wheel_candidates(db)
    assert cands == []
    assert run_at is None
    assert stale is False
