"""
Directional score grading: bucket settled journal entries by the EV per $ risked
they were picked with, and report win rate and average return per bucket.

Reads SetupAlert rows with setup_key='directional_options' (the Phase 2B
outcome journal the directional engine writes). Settled means closed
(is_open False) with a graded option P&L outcome: the score is graded
against OPTION P&L (premium paid, intrinsic value at close), not the
underlying stock move (review C13). Rows settled by the old stock-basis
job carry an option trade spec but no settlement record; they are
excluded from the grade and counted as ungraded_legacy instead of being
mixed into an option profit factor. No outcomes are invented: with fewer
than MIN_SETTLED settled entries the function reports "not enough settled
outcomes yet" instead of printing stats, and stats on a small sample are
labeled preliminary, not confident (review M53).
"""
import json
import logging

from sqlalchemy.orm import Session

from services.alert_journal_service import graded_outcome

logger = logging.getLogger(__name__)

DIRECTIONAL_SETUP_KEY = "directional_options"
MIN_SETTLED = 5  # same minimum as the Book scoreboard

# Stats stay preliminary until this many settled outcomes.
PRELIMINARY_MIN = 30

PRELIMINARY_NOTE = (
    "Preliminary: fewer than 30 settled outcomes. A 4-of-5 win rate of 80% "
    "has a standard error of about 18 points, so 5 settled outcomes is not "
    "a confident read."
)

# Buckets on the EV per $ risked recorded at pick time.
BUCKETS = [
    ("negative", None, 0.0, "EV per $ risked below 0"),
    ("low", 0.0, 0.5, "EV per $ risked 0 to 0.5"),
    ("mid", 0.5, 1.0, "EV per $ risked 0.5 to 1.0"),
    ("high", 1.0, None, "EV per $ risked above 1.0"),
]


def _bucket_for(ev_per_dollar: float | None) -> str | None:
    if ev_per_dollar is None:
        return None
    for key, lo, hi, _label in BUCKETS:
        if (lo is None or ev_per_dollar >= lo) and (hi is None or ev_per_dollar < hi):
            return key
    return None


def _bucket_stats(rows: list) -> dict:
    graded = []
    for r in rows:
        g = graded_outcome(r)
        if g is not None and g["basis"] == "option" and g["pct"] is not None:
            graded.append(g)
    outcomes = [g["pct"] for g in graded]
    n = len(outcomes)
    wins = [v for v in outcomes if v > 0]
    r_values = [g["r"] for g in graded if g.get("r") is not None]
    pnl_dollars = [g["pnl_dollars"] for g in graded if g.get("pnl_dollars") is not None]
    return {
        "settled_count": n,
        "win_rate_pct": round(len(wins) / n * 100, 1) if n else None,
        "avg_return_pct": round(sum(outcomes) / n, 2) if n else None,
        "avg_outcome_r": round(sum(r_values) / len(r_values), 2) if r_values else None,
        "option_pnl_dollars_total": round(sum(pnl_dollars), 2) if pnl_dollars else None,
    }


def grade_directional_journal(db: Session, min_settled: int = MIN_SETTLED) -> dict:
    """Grade settled Directional picks by their EV per $ risked at pick time."""
    from models.setup_alert import SetupAlert

    rows = (
        db.query(SetupAlert)
        .filter(
            SetupAlert.setup_key == DIRECTIONAL_SETUP_KEY,
            SetupAlert.is_suppressed == False,  # noqa: E712
        )
        .all()
    )
    settled = []
    ungraded_legacy = 0
    for r in rows:
        if r.is_open:
            continue
        g = graded_outcome(r)
        if g is None or g["basis"] != "option":
            ungraded_legacy += 1
            continue
        if g["pct"] is None:
            ungraded_legacy += 1
            continue
        settled.append(r)
    n = len(settled)

    base = {
        "source": "Directional Options",
        "picks_made": len(rows),
        "settled_count": n,
        "min_settled": min_settled,
        "outcome_basis": "option_pnl",
        "ungraded_legacy_settled": ungraded_legacy,
        "preliminary": n < PRELIMINARY_MIN,
        "generated_note": "Buckets use the EV per $ risked recorded when the pick was journaled. Outcomes are option P&L (premium paid, intrinsic value at close), not the underlying stock move.",
    }
    if n < PRELIMINARY_MIN:
        base["confidence_note"] = PRELIMINARY_NOTE
    if n < min_settled:
        base["not_enough"] = True
        base["message"] = "not enough settled outcomes yet"
        return base

    buckets: dict[str, list] = {key: [] for key, _lo, _hi, _label in BUCKETS}
    unbucketed = 0
    for r in settled:
        try:
            cond = json.loads(r.conditions_json or "{}")
        except Exception:
            cond = {}
        ev_per_dollar = cond.get("ev_per_dollar_risked")
        key = _bucket_for(ev_per_dollar)
        if key is None:
            unbucketed += 1
        else:
            buckets[key].append(r)

    out_buckets = []
    for key, _lo, _hi, label in BUCKETS:
        stats = _bucket_stats(buckets[key])
        stats.update({"bucket": key, "label": label})
        out_buckets.append(stats)

    overall = _bucket_stats(settled)
    base.update({
        "buckets": out_buckets,
        "unbucketed_settled": unbucketed,
        "win_rate_pct": overall["win_rate_pct"],
        "avg_return_pct": overall["avg_return_pct"],
        "avg_outcome_r": overall["avg_outcome_r"],
        "option_pnl_dollars_total": overall["option_pnl_dollars_total"],
    })
    return base
