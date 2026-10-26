"""
Champion pick journal and outcome settlement.

Settlement rule: Champions emits no targets or stops, so each pick is settled
on a fixed calendar-day horizon by strategy:
  wheel    -> 30 days  (one covered-call cycle)
  options  -> 21 days  (standard three-week options cycle)
  longterm -> 90 days  (quarterly thesis check)

Entry is the OPEN price on the run date, not yesterday's close (review
M49). The prescreener only sees completed bars, so the close it passes in
is provisional: record_picks uses the open when the market is already
open, and the outcome job corrects the entry to the run-date open at
settlement time.

Settlement uses the CLOSE on or after the horizon date, never an
intraday price (review M49). A pick whose horizon date has not closed
yet stays open, however often the job runs.

Grading basis: a Champion pick carries no contract (no strike, expiry,
or premium), so its outcome is the underlying stock move. That is
labeled outcome_basis "stock_price" in get_stats, with a note that the
wheel and options strategies cannot be graded on option P&L until the
engine records a contract at pick time.

Sample size (review M53): 5 settled outcomes is the minimum to print
stats at all, and those stats are labeled preliminary, not confident. An
80% win rate on 5 picks has a standard error of about 18 points, so a
5-settled win rate is a hint, not a verdict.
"""
import logging
from datetime import datetime, timezone, date, timedelta

logger = logging.getLogger(__name__)

# Mirrors CHAMPION_HORIZONS in models/champion_pick.py
_HORIZONS = {"wheel": 30, "options": 21, "longterm": 90}

# Stats stay preliminary until this many settled outcomes.
PRELIMINARY_MIN = 30

PRELIMINARY_NOTE = (
    "Preliminary: fewer than 30 settled outcomes. A 4-of-5 win rate of 80% "
    "has a standard error of about 18 points, so 5 settled outcomes is not "
    "a confident read."
)


def _daily_bars(ticker: str, start: date, end: date) -> list:
    """
    Daily bars for a ticker in [start, end). Returns a list of dicts
    {"date": date, "open": float, "close": float} sorted by date.
    Only completed bars are returned by the source; an in-progress
    today bar is excluded by callers that need a final close.
    """
    try:
        import yfinance as yf

        hist = yf.Ticker(ticker).history(start=start, end=end, auto_adjust=False)
        if hist is None or hist.empty:
            return []
        bars = []
        for idx, row in hist.iterrows():
            try:
                bars.append({
                    "date": idx.date(),
                    "open": float(row["Open"]),
                    "close": float(row["Close"]),
                })
            except Exception:
                continue
        bars.sort(key=lambda b: b["date"])
        return bars
    except Exception as e:
        logger.debug("champion_journal: history fetch failed %s: %s", ticker, e)
        return []


def open_price_on(ticker: str, day: date, lookahead_days: int = 7) -> float | None:
    """
    Open price on the given date, or on the next trading day after it
    when the date itself is not a trading day. Returns None when no open
    is available (weekend run with no later bar yet, or a failed fetch).
    """
    bars = _daily_bars(ticker, day, day + timedelta(days=lookahead_days + 1))
    for bar in bars:
        if bar["date"] >= day:
            return bar["open"]
    return None


def close_on_or_after(ticker: str, day: date, today: date, lookahead_days: int = 10):
    """
    First final close on or after the given date. Returns (bar_date,
    close) or None when no final close exists yet: a bar dated today is
    still trading, so it never settles a pick. This is what makes
    settlement happen at the close, not intraday.
    """
    bars = _daily_bars(ticker, day, day + timedelta(days=lookahead_days + 1))
    for bar in bars:
        if bar["date"] >= day and bar["date"] < today:
            return bar["date"], bar["close"]
    return None


def _current_price(ticker: str) -> float | None:
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        p = t.fast_info.last_price or t.fast_info.previous_close
        return float(p) if p else None
    except Exception as e:
        logger.debug("champion_journal: price fetch failed %s: %s", ticker, e)
        return None


def record_picks(db, picks: dict, entry_prices: dict, run_at: datetime) -> None:
    """
    Write one ChampionPick row per strategy.
    picks: {strategy: {ticker, score, grade, reason, ...}}
    entry_prices: {ticker: price}, populated from prescreener output.
    The prescreener price is yesterday's close; where the run-date open
    is already available it is used as the entry instead, and the
    outcome job corrects any remaining provisional entry to the open at
    settlement time.
    """
    from models.champion_pick import ChampionPick

    run_date = run_at.date() if isinstance(run_at, datetime) else run_at

    for strategy, data in picks.items():
        if not data or not data.get("ticker"):
            continue
        ticker = data["ticker"]
        entry = entry_prices.get(ticker)
        try:
            open_price = open_price_on(ticker, run_date)
        except Exception:
            open_price = None
        if open_price is not None:
            entry = open_price
        row = ChampionPick(
            strategy=strategy,
            ticker=ticker,
            run_at=run_at,
            entry_price=entry,
            score=data.get("score"),
            grade=data.get("grade"),
            reason=data.get("reason"),
            is_open=True,
        )
        db.add(row)
    db.commit()


def run_outcome_job(db) -> dict:
    """
    Settle open ChampionPick rows that have reached their horizon.
    Entry is corrected to the open on the run date; settlement is the
    first final close on or after the horizon date. Returns {"settled":
    int, "still_open": int, "errors": int, "settled_at": iso|None}.
    """
    from models.champion_pick import ChampionPick

    open_picks = (
        db.query(ChampionPick)
        .filter(ChampionPick.is_open == True)  # noqa: E712
        .all()
    )

    settled = 0
    still_open = 0
    errors = 0
    now = datetime.now(timezone.utc)
    today = now.date()
    settled_at = None

    for pick in open_picks:
        try:
            run_at = pick.run_at
            if run_at.tzinfo is None:
                run_at = run_at.replace(tzinfo=timezone.utc)
            run_date = run_at.date()
            days_held = (now - run_at).days
            horizon = _HORIZONS.get(pick.strategy, 30)
            horizon_date = run_date + timedelta(days=horizon)

            if days_held < horizon:
                still_open += 1
                continue

            # Entry is the open on the run date, not yesterday's close.
            try:
                entry_open = open_price_on(pick.ticker, run_date)
            except Exception:
                entry_open = None
            if entry_open is not None:
                pick.entry_price = entry_open
            entry = pick.entry_price
            if not entry or entry <= 0:
                still_open += 1
                continue

            # Settlement is the first final close on or after the horizon
            # date. If that close does not exist yet, the pick stays open.
            found = close_on_or_after(pick.ticker, horizon_date, today)
            if found is None:
                still_open += 1
                continue
            bar_date, price = found

            outcome_pct = round((price - entry) / entry * 100, 2)

            pick.is_open = False
            pick.settlement_price = price
            pick.outcome_pct = outcome_pct
            pick.settled_at = now
            pick.days_held = (bar_date - run_date).days
            pick.close_reason = "time_stop"
            settled += 1
            settled_at = now

        except Exception as e:
            logger.warning("champion_journal: error settling pick %s: %s", pick.id, e)
            errors += 1
            still_open += 1

    try:
        db.commit()
    except Exception as e:
        logger.error("champion_journal: commit failed: %s", e)
        db.rollback()
        return {"settled": 0, "still_open": 0, "errors": 1, "settled_at": None}

    logger.info("champion_journal: settled=%d still_open=%d errors=%d", settled, still_open, errors)
    return {
        "settled": settled,
        "still_open": still_open,
        "errors": errors,
        "settled_at": settled_at.isoformat() if settled_at else None,
    }


def get_stats(db) -> dict:
    """
    Compute scoreboard stats for Champions picks across all strategies combined,
    then per strategy.
    Returns {combined: {...}, by_strategy: {strategy: {...}},
    last_settled_at: iso|None}.
    Stats with fewer than PRELIMINARY_MIN settled outcomes are labeled
    preliminary, never confident.
    """
    from models.champion_pick import ChampionPick

    all_picks = db.query(ChampionPick).all()
    closed = [p for p in all_picks if not p.is_open and p.outcome_pct is not None]

    settled_dates = [p.settled_at for p in closed if p.settled_at is not None]
    last_settled_at = None
    if settled_dates:
        latest = max(settled_dates)
        last_settled_at = latest.isoformat() if hasattr(latest, "isoformat") else str(latest)

    def _tile(picks_all, picks_closed):
        fired = len(picks_all)
        n = len(picks_closed)
        outcomes = [p.outcome_pct for p in picks_closed]
        wins = [v for v in outcomes if v > 0]
        losses = [v for v in outcomes if v <= 0]
        win_rate = round(len(wins) / n * 100, 1) if n else None
        expectancy = round(sum(outcomes) / n, 3) if n else None
        gross_win = sum(v for v in outcomes if v > 0)
        gross_loss = abs(sum(v for v in outcomes if v <= 0))
        profit_factor = round(gross_win / gross_loss, 2) if gross_loss > 0 else None
        tile = {
            "picks_made": fired,
            "settled_count": n,
            "win_rate_pct": win_rate,
            "expectancy_pct": expectancy,
            "profit_factor": profit_factor,
            "outcome_basis": "stock_price",
            "preliminary": n < PRELIMINARY_MIN,
        }
        if n < PRELIMINARY_MIN:
            tile["confidence_note"] = PRELIMINARY_NOTE
        return tile

    combined = _tile(all_picks, closed)

    by_strategy = {}
    for strategy in ("wheel", "options", "longterm"):
        s_all = [p for p in all_picks if p.strategy == strategy]
        s_closed = [p for p in closed if p.strategy == strategy]
        by_strategy[strategy] = _tile(s_all, s_closed)
        by_strategy[strategy]["horizon_days"] = _HORIZONS.get(strategy)

    return {
        "combined": combined,
        "by_strategy": by_strategy,
        "last_settled_at": last_settled_at,
        "status_label": "SHADOW",
        "status_note": (
            "Champions AI picks are SHADOW until they pass the same harness "
            "as the stock setups (a real-data backtest with a PASSES verdict). "
            "Picks are graded here for observation only and are never sent "
            "as LIVE Challenge alerts."
        ),
        "outcome_basis": "stock_price",
        "outcome_note": (
            "Champions picks carry no contract (no strike, expiry, or "
            "premium), so outcomes are the underlying stock move. The wheel "
            "and options strategies cannot be graded on option P&L until "
            "the engine records a contract at pick time."
        ),
    }
