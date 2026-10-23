"""
Champion pick journal and outcome settlement.

Settlement rule: Champions emits no targets or stops, so each pick is settled
on a fixed calendar-day horizon by strategy:
  wheel    -> 30 days  (one covered-call cycle)
  options  -> 21 days  (standard three-week options cycle)
  longterm -> 90 days  (quarterly thesis check)

A pick is settled by comparing the closing price on or after the horizon
to the entry price recorded at emission.
"""
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Mirrors CHAMPION_HORIZONS in models/champion_pick.py
_HORIZONS = {"wheel": 30, "options": 21, "longterm": 90}


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
    entry_prices: {ticker: price} — populated from prescreener output
    """
    from models.champion_pick import ChampionPick

    for strategy, data in picks.items():
        if not data or not data.get("ticker"):
            continue
        ticker = data["ticker"]
        row = ChampionPick(
            strategy=strategy,
            ticker=ticker,
            run_at=run_at,
            entry_price=entry_prices.get(ticker),
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
    Returns {"settled": int, "still_open": int, "errors": int}.
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

    for pick in open_picks:
        try:
            run_at = pick.run_at
            if run_at.tzinfo is None:
                run_at = run_at.replace(tzinfo=timezone.utc)
            days_held = (now - run_at).days
            horizon = _HORIZONS.get(pick.strategy, 30)

            if days_held < horizon:
                still_open += 1
                continue

            price = _current_price(pick.ticker)
            if price is None:
                still_open += 1
                continue

            entry = pick.entry_price
            outcome_pct = (
                round((price - entry) / entry * 100, 2)
                if entry and entry > 0
                else None
            )

            pick.is_open = False
            pick.settlement_price = price
            pick.outcome_pct = outcome_pct
            pick.settled_at = now
            pick.days_held = days_held
            pick.close_reason = "time_stop"
            settled += 1

        except Exception as e:
            logger.warning("champion_journal: error settling pick %s: %s", pick.id, e)
            errors += 1
            still_open += 1

    try:
        db.commit()
    except Exception as e:
        logger.error("champion_journal: commit failed: %s", e)
        db.rollback()
        return {"settled": 0, "still_open": 0, "errors": 1}

    logger.info("champion_journal: settled=%d still_open=%d errors=%d", settled, still_open, errors)
    return {"settled": settled, "still_open": still_open, "errors": errors}


def get_stats(db) -> dict:
    """
    Compute scoreboard stats for Champions picks across all strategies combined,
    then per strategy.
    Returns {combined: {...}, by_strategy: {strategy: {...}}}.
    """
    from models.champion_pick import ChampionPick

    all_picks = db.query(ChampionPick).all()
    closed = [p for p in all_picks if not p.is_open and p.outcome_pct is not None]

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
        return {
            "picks_made": fired,
            "settled_count": n,
            "win_rate_pct": win_rate,
            "expectancy_pct": expectancy,
            "profit_factor": profit_factor,
        }

    combined = _tile(all_picks, closed)

    by_strategy = {}
    for strategy in ("wheel", "options", "longterm"):
        s_all = [p for p in all_picks if p.strategy == strategy]
        s_closed = [p for p in closed if p.strategy == strategy]
        by_strategy[strategy] = _tile(s_all, s_closed)
        by_strategy[strategy]["horizon_days"] = _HORIZONS.get(strategy)

    return {"combined": combined, "by_strategy": by_strategy}
