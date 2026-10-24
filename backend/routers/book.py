"""
Book router — aggregated scoreboard and income calendar.

GET /api/book/scoreboard  — four tiles: Setup Alerts, Directional, Champions, Wheel
GET /api/book/income-calendar  — projected dividend payments for next 90 days
"""
import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/book", tags=["Book"])

MIN_SETTLED = 5  # minimum settled outcomes before printing stats at all.
# Stats at this minimum are preliminary, never confident: a 4-of-5 win
# rate of 80% has a standard error of about 18 points (review M53).
PRELIMINARY_MIN = 30  # settled outcomes before stats stop being preliminary

PRELIMINARY_NOTE = (
    "Preliminary: fewer than 30 settled outcomes. A 4-of-5 win rate of 80% "
    "has a standard error of about 18 points, so 5 settled outcomes is not "
    "a confident read."
)


def _not_enough(count: int) -> dict:
    return {"not_enough": True, "settled_count": count}


def _preliminary(n: int) -> dict:
    """Preliminary flag and note for a settled count below PRELIMINARY_MIN."""
    if n < PRELIMINARY_MIN:
        return {"preliminary": True, "confidence_note": PRELIMINARY_NOTE}
    return {"preliminary": False}


def _wheel_tile(db: Session) -> dict:
    """Stats from closed WheelPosition rows, in dollars throughout (review M51)."""
    from models.wheel import WheelPosition, WheelStatus

    positions = db.query(WheelPosition).all()
    closed = [
        p for p in positions
        if p.status == WheelStatus.closed and p.total_pnl is not None
    ]
    total = len(positions)
    n = len(closed)

    if n < MIN_SETTLED:
        result = {
            "source": "Wheel Strategy",
            "recs_made": total,
            "not_enough": True,
            "settled_count": n,
        }
        result.update(_preliminary(n))
        return result

    wins = [p for p in closed if p.total_pnl > 0]
    losses = [p for p in closed if p.total_pnl <= 0]
    win_rate = round(len(wins) / n * 100, 1)

    # Expectancy in dollars over ALL closed positions, premium wins
    # included: a put expired worthless is a win of the premium received,
    # and it used to be dropped by the cost-basis filter. One unit
    # (dollars) for expectancy and profit factor alike; no percent mixed in.
    pnls = [p.total_pnl for p in closed]
    expectancy_dollars = round(sum(pnls) / len(pnls), 2)

    gross_win = sum(p.total_pnl for p in wins)
    gross_loss = abs(sum(p.total_pnl for p in losses))
    profit_factor = round(gross_win / gross_loss, 2) if gross_loss > 0 else None

    result = {
        "source": "Wheel Strategy",
        "recs_made": total,
        "settled_count": n,
        "win_rate_pct": win_rate,
        "expectancy_dollars": expectancy_dollars,
        "expectancy_unit": "dollars",
        "profit_factor": profit_factor,
        "premium_wins_included": True,
        "outcome_basis": "option_pnl_dollars",
        "pnl_source": "recorded_position_pnl",
    }
    result.update(_preliminary(n))
    return result


def _directional_tile(db: Session) -> dict:
    """Stats from SetupAlert rows with setup_key='directional_options'.

    Graded on option P&L (premium paid, intrinsic value at close), never
    on the underlying stock move (review C13). Rows settled by the old
    stock-basis job are excluded and counted, not mixed in.
    """
    from models.setup_alert import SetupAlert
    from services.alert_journal_service import graded_outcome

    rows = (
        db.query(SetupAlert)
        .filter(
            SetupAlert.setup_key == "directional_options",
            SetupAlert.is_suppressed == False,  # noqa: E712
        )
        .all()
    )
    graded = []
    legacy_excluded = 0
    for r in rows:
        if r.is_open:
            continue
        g = graded_outcome(r)
        if g is None or g["basis"] != "option" or g["pct"] is None:
            legacy_excluded += 1
            continue
        graded.append(g)
    n = len(graded)

    if n < MIN_SETTLED:
        result = {
            "source": "Directional Options",
            "recs_made": len(rows),
            "not_enough": True,
            "settled_count": n,
            "status_label": "SHADOW",
            "outcome_basis": "option_pnl",
            "legacy_stock_basis_excluded": legacy_excluded,
        }
        result.update(_preliminary(n))
        return result

    outcomes = [g["pct"] for g in graded]
    wins = [v for v in outcomes if v > 0]
    losses = [v for v in outcomes if v <= 0]
    win_rate = round(len(wins) / n * 100, 1)
    expectancy = round(sum(outcomes) / n, 3)
    gross_win = sum(v for v in outcomes if v > 0)
    gross_loss = abs(sum(v for v in outcomes if v <= 0))
    profit_factor = round(gross_win / gross_loss, 2) if gross_loss > 0 else None
    dollars = [g["pnl_dollars"] for g in graded if g.get("pnl_dollars") is not None]
    option_pnl_total = round(sum(dollars), 2) if dollars else None

    result = {
        "source": "Directional Options",
        "recs_made": len(rows),
        "settled_count": n,
        "win_rate_pct": win_rate,
        "expectancy_pct": expectancy,
        "profit_factor": profit_factor,
        "status_label": "SHADOW",
        "outcome_basis": "option_pnl",
        "option_pnl_dollars_total": option_pnl_total,
        "legacy_stock_basis_excluded": legacy_excluded,
    }
    result.update(_preliminary(n))
    return result


def _alerts_tile(db: Session) -> list[dict]:
    """Stats from alert_journal_service, LIVE and SHADOW shown separately."""
    from services.alert_journal_service import get_setup_statistics

    raw = get_setup_statistics(db)
    tiles = []
    for row in raw:
        n = row["alerts_closed"]
        base = {
            "source": f"Setup Alerts ({row['setup_key']} / {row['setup_status_label']})",
            "setup_key": row["setup_key"],
            "status_label": row["setup_status_label"],
            "recs_made": row["alerts_fired"],
            "settled_count": n,
        }
        if n < MIN_SETTLED:
            base["not_enough"] = True
        else:
            base.update({
                "win_rate_pct": row["win_rate_pct"],
                "expectancy_pct": row["expectancy_pct"],
                "profit_factor": row["profit_factor"],
            })
        base["outcome_basis"] = row["outcome_basis"]
        base["legacy_stock_basis_excluded"] = row["legacy_stock_basis_excluded"]
        base.update(_preliminary(n))
        tiles.append(base)
    return tiles


def _champions_tile(db: Session) -> dict:
    """Stats from ChampionPick rows — all strategies combined."""
    from services.champion_journal_service import get_stats

    stats = get_stats(db)
    combined = stats["combined"]
    n = combined["settled_count"]
    base = {
        "source": "Champions Daily Picks",
        "recs_made": combined["picks_made"],
        "settled_count": n,
        "by_strategy": stats["by_strategy"],
        "last_settled_at": stats.get("last_settled_at"),
        "outcome_basis": stats.get("outcome_basis"),
        "outcome_note": stats.get("outcome_note"),
        "preliminary": combined.get("preliminary", True),
    }
    if combined.get("confidence_note"):
        base["confidence_note"] = combined["confidence_note"]
    if n < MIN_SETTLED:
        base["not_enough"] = True
    else:
        base.update({
            "win_rate_pct": combined["win_rate_pct"],
            "expectancy_pct": combined["expectancy_pct"],
            "profit_factor": combined["profit_factor"],
        })
    return base


@router.get("/scoreboard")
def get_scoreboard(db: Session = Depends(get_db)):
    """Aggregate scoreboard across all four advice sources."""
    return {
        "alerts": _alerts_tile(db),
        "directional": _directional_tile(db),
        "champions": _champions_tile(db),
        "wheel": _wheel_tile(db),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Income calendar
# ---------------------------------------------------------------------------

def _fetch_dividend_info(ticker: str) -> dict | None:
    """
    Fetch last ex-date, last payout amount, and inferred frequency from yfinance.
    Returns None if no dividend data is available.
    """
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        divs = t.dividends
        if divs is None or len(divs) == 0:
            return None

        # Last 4 payments
        recent = divs.tail(4)
        last_amount = float(recent.iloc[-1])
        if last_amount <= 0:
            return None

        last_ex_date = recent.index[-1].date()

        # Infer frequency from gaps between recent payments
        freq = 4  # default quarterly
        if len(recent) >= 2:
            gaps = []
            for i in range(1, len(recent)):
                diff = (recent.index[i] - recent.index[i - 1]).days
                gaps.append(diff)
            avg_gap = sum(gaps) / len(gaps)
            if avg_gap < 45:
                freq = 12   # monthly
            elif avg_gap < 100:
                freq = 4    # quarterly
            elif avg_gap < 200:
                freq = 2    # semi-annual
            else:
                freq = 1    # annual

        return {
            "ticker": ticker,
            "last_amount": round(last_amount, 4),
            "last_ex_date": last_ex_date.isoformat(),
            "freq_per_year": freq,
        }
    except Exception as e:
        logger.debug("income_calendar: dividend fetch failed %s: %s", ticker, e)
        return None


def _project_payments(div_info: dict, horizon_days: int = 90) -> list[dict]:
    """
    Project future ex-dates and estimated payout amounts from last known ex-date.
    Returns list of {ticker, projected_ex_date, amount, is_projection: True}.
    """
    from datetime import date

    freq = div_info["freq_per_year"]
    days_between = round(365 / freq)
    last_ex = datetime.fromisoformat(div_info["last_ex_date"]).date()
    amount = div_info["last_amount"]
    ticker = div_info["ticker"]

    today = date.today()
    cutoff = today + timedelta(days=horizon_days)
    payments = []

    # Walk forward from last ex-date
    next_ex = last_ex
    while next_ex <= today:
        next_ex = next_ex + timedelta(days=days_between)

    while next_ex <= cutoff:
        payments.append({
            "ticker": ticker,
            "projected_ex_date": next_ex.isoformat(),
            "amount_per_share": amount,
            "freq_per_year": freq,
            "is_projection": True,
        })
        next_ex = next_ex + timedelta(days=days_between)

    return payments


@router.get("/income-calendar")
def get_income_calendar(db: Session = Depends(get_db)):
    """
    Projected dividend payments for the next 90 days for watchlist and wheel-held tickers.
    Labeled as projections; amounts are based on the most recent payment.
    """
    from models.watchlist import WatchlistItem
    from models.wheel import WheelPosition, WheelStatus

    watchlist_tickers = {
        row.ticker for row in db.query(WatchlistItem).all()
    }
    held_tickers = {
        p.ticker
        for p in db.query(WheelPosition).all()
        if p.status != WheelStatus.closed
    }
    all_tickers = sorted(watchlist_tickers | held_tickers)

    all_payments = []
    errors = []
    for ticker in all_tickers:
        info = _fetch_dividend_info(ticker)
        if info:
            projected = _project_payments(info, horizon_days=90)
            all_payments.extend(projected)
        # Non-dividend tickers produce nothing silently

    all_payments.sort(key=lambda p: p["projected_ex_date"])

    return {
        "payments": all_payments,
        "tickers_checked": all_tickers,
        "horizon_days": 90,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "note": "All dates and amounts are projections based on the most recent payment. Verify before trading.",
    }
