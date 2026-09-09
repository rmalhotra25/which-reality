"""
Leveraged ETF MA Signal Service
================================
Tracks 200-day SMA crossings on underlying ETFs (QQQ, SPY, etc.) and
surfaces them as trend-follow or mean-reversion signals for leveraged ETFs
(TQQQ, SPXL, SOXL, TNA, UPRO).

Daily signal engine: run via scheduler after market close.
Dashboard endpoint: adds live intraday prices from Polygon snapshot.
Backtest module: shares crossing-detection logic with the daily engine.
"""

import logging
import time
from datetime import datetime, timezone, date, timedelta
from statistics import mean

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Asset configuration (hardcoded like CEF universe)
# ---------------------------------------------------------------------------

ASSET_CONFIGS = [
    {
        "asset_key": "TQQQ_QQQ",
        "leveraged": "TQQQ",
        "underlying": "QQQ",
        "ma_period": 200,
        "direction": "both",
        "threshold_pct": 0.0,
        "active": True,
        "leverage_multiple": 3,
    },
    {
        "asset_key": "SPXL_SPY",
        "leveraged": "SPXL",
        "underlying": "SPY",
        "ma_period": 200,
        "direction": "both",
        "threshold_pct": 0.0,
        "active": True,
        "leverage_multiple": 3,
    },
    {
        "asset_key": "SOXL_SOXX",
        "leveraged": "SOXL",
        "underlying": "SOXX",
        "ma_period": 200,
        "direction": "both",
        "threshold_pct": 0.0,
        "active": True,
        "leverage_multiple": 3,
    },
    {
        "asset_key": "TNA_IWM",
        "leveraged": "TNA",
        "underlying": "IWM",
        "ma_period": 200,
        "direction": "both",
        "threshold_pct": 0.0,
        "active": True,
        "leverage_multiple": 3,
    },
    {
        "asset_key": "UPRO_SPY",
        "leveraged": "UPRO",
        "underlying": "SPY",
        "ma_period": 200,
        "direction": "both",
        "threshold_pct": 0.0,
        "active": True,
        "leverage_multiple": 3,
    },
]

_DIRECTIONS = ["trend_follow", "mean_reversion"]


# ---------------------------------------------------------------------------
# Pure signal math (shared by daily engine and backtest)
# ---------------------------------------------------------------------------

def compute_sma(prices: list[float], period: int) -> float | None:
    """Simple moving average of the last `period` prices. Returns None if insufficient data."""
    if len(prices) < period:
        return None
    return mean(prices[-period:])


def get_side(price: float, sma: float, threshold_pct: float) -> str:
    """
    Return "above" or "below" based on price vs SMA ± threshold band.

    threshold_pct > 0: price must be threshold_pct% ABOVE sma to count as "above"
    threshold_pct < 0 (e.g. -3): price must be 3% BELOW sma to count as "below"
    threshold_pct == 0: simple above/below
    """
    if threshold_pct == 0:
        return "above" if price >= sma else "below"
    band = sma * (1 + threshold_pct / 100)
    return "above" if price >= band else "below"


def detect_crossing(old_side: str | None, new_side: str) -> bool:
    """True when the side changed (a crossing event occurred)."""
    if old_side is None:
        return False  # no prior state — first check, not a crossing
    return old_side != new_side


def signal_label(direction: str, new_side: str) -> str:
    """Human-readable signal label for a crossing event."""
    if direction == "trend_follow":
        return "RISK-ON" if new_side == "above" else "RISK-OFF"
    else:  # mean_reversion
        return "BUY SETUP" if new_side == "below" else "EXIT SETUP"


# ---------------------------------------------------------------------------
# Daily signal engine (called by scheduler)
# ---------------------------------------------------------------------------

def run_daily_signal_engine() -> None:
    """
    Compute SMA crossings for all active configs and persist state to DB.
    Creates its own DB session (safe to call from background thread or scheduler).
    """
    from database import SessionLocal
    from models.leveraged_ma import LeveragedMASignalState
    from services import polygon_client

    db = SessionLocal()
    try:
        # Deduplicate underlying tickers — SPXL and UPRO both track SPY
        underlying_to_closes: dict[str, list[float]] = {}
        for cfg in ASSET_CONFIGS:
            if not cfg["active"]:
                continue
            underlying = cfg["underlying"]
            if underlying not in underlying_to_closes:
                logger.info("Leveraged MA: fetching %d-day closes for %s", cfg["ma_period"] + 10, underlying)
                closes = polygon_client.get_close_prices(underlying, days=cfg["ma_period"] + 10)
                underlying_to_closes[underlying] = closes
                time.sleep(0.3)  # respect Polygon rate limits

        now = datetime.now(timezone.utc)
        today = date.today()

        for cfg in ASSET_CONFIGS:
            if not cfg["active"]:
                continue

            closes = underlying_to_closes.get(cfg["underlying"], [])
            sma = compute_sma(closes, cfg["ma_period"])
            if sma is None or not closes:
                logger.warning("Leveraged MA: insufficient close data for %s", cfg["underlying"])
                continue

            current_price = closes[-1]
            directions = _DIRECTIONS if cfg["direction"] == "both" else [cfg["direction"]]

            for direction in directions:
                new_side = get_side(current_price, sma, cfg["threshold_pct"])

                # Load or create state row
                state = (
                    db.query(LeveragedMASignalState)
                    .filter_by(asset_key=cfg["asset_key"], direction=direction)
                    .first()
                )
                if state is None:
                    state = LeveragedMASignalState(
                        asset_key=cfg["asset_key"],
                        direction=direction,
                    )
                    db.add(state)

                old_side = state.last_side
                crossed = detect_crossing(old_side, new_side)

                if crossed:
                    label = signal_label(direction, new_side)
                    logger.info(
                        "Leveraged MA CROSSING: %s / %s → %s (%s) [was %s]",
                        cfg["asset_key"], direction, new_side, label, old_side,
                    )
                    state.last_cross_at = now
                    state.last_cross_side = new_side

                state.last_side = new_side
                state.last_checked_at = now
                state.sma_at_check = str(round(sma, 4))

        db.commit()
        logger.info("Leveraged MA: daily signal engine complete for %s", today)
    except Exception as e:
        db.rollback()
        logger.error("Leveraged MA: daily signal engine failed: %s", e, exc_info=True)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Dashboard endpoint data (daily state + live intraday prices)
# ---------------------------------------------------------------------------

def get_signals_dashboard() -> list[dict]:
    """
    Returns one row per (asset_config × direction) with:
    - Daily signal state from DB
    - Live intraday price from Polygon snapshot (for current % distance from SMA)
    """
    from database import SessionLocal
    from models.leveraged_ma import LeveragedMASignalState
    from services import polygon_client

    db = SessionLocal()
    try:
        # Batch-fetch live prices for all tickers (leveraged + underlying)
        all_tickers = list({t for cfg in ASSET_CONFIGS for t in (cfg["leveraged"], cfg["underlying"])})
        snapshots = polygon_client.get_snapshots_batch(all_tickers)

        today = datetime.now(timezone.utc).date()
        rows: list[dict] = []

        for cfg in ASSET_CONFIGS:
            if not cfg["active"]:
                continue

            underlying_snap = snapshots.get(cfg["underlying"], {})
            leveraged_snap = snapshots.get(cfg["leveraged"], {})

            live_underlying_price = underlying_snap.get("price") or None
            live_leveraged_price = leveraged_snap.get("price") or None

            directions = _DIRECTIONS if cfg["direction"] == "both" else [cfg["direction"]]
            for direction in directions:
                state = (
                    db.query(LeveragedMASignalState)
                    .filter_by(asset_key=cfg["asset_key"], direction=direction)
                    .first()
                )

                sma = float(state.sma_at_check) if (state and state.sma_at_check) else None
                last_side = state.last_side if state else None
                last_checked_at = state.last_checked_at if state else None
                last_cross_at = state.last_cross_at if state else None
                last_cross_side = state.last_cross_side if state else None

                # Is the crossing from today?
                crossed_today = False
                if last_cross_at:
                    cross_date = last_cross_at.date() if isinstance(last_cross_at, datetime) else last_cross_at
                    crossed_today = (cross_date == today)

                # Live % distance from SMA using intraday price
                live_dist_pct = None
                if live_underlying_price and sma:
                    live_dist_pct = round((live_underlying_price - sma) / sma * 100, 2)

                # Determine live side (may differ from last daily side if price moved a lot intraday)
                live_side = None
                if live_underlying_price and sma:
                    live_side = get_side(live_underlying_price, sma, cfg["threshold_pct"])

                rows.append({
                    "asset_key": cfg["asset_key"],
                    "leveraged": cfg["leveraged"],
                    "underlying": cfg["underlying"],
                    "ma_period": cfg["ma_period"],
                    "direction": direction,
                    "threshold_pct": cfg["threshold_pct"],
                    "leverage_multiple": cfg["leverage_multiple"],
                    # Daily state
                    "sma": sma,
                    "last_side": last_side,
                    "last_checked_at": last_checked_at.isoformat() if last_checked_at else None,
                    "last_cross_at": last_cross_at.isoformat() if last_cross_at else None,
                    "last_cross_side": last_cross_side,
                    "signal_label": signal_label(direction, last_cross_side) if last_cross_side else None,
                    "crossed_today": crossed_today,
                    # Live intraday
                    "live_underlying_price": live_underlying_price,
                    "live_leveraged_price": live_leveraged_price,
                    "live_dist_pct": live_dist_pct,
                    "live_side": live_side,
                    "underlying_change_pct": underlying_snap.get("change_pct"),
                    "leveraged_change_pct": leveraged_snap.get("change_pct"),
                    # State availability
                    "has_state": state is not None,
                    "never_run": state is None,
                })

        # Sort: crossed_today rows first, then by asset_key
        rows.sort(key=lambda r: (0 if r["crossed_today"] else 1, r["asset_key"], r["direction"]))
        return rows
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Backtest module (uses same crossing-detection logic as daily engine)
# ---------------------------------------------------------------------------

def run_backtest(
    asset_key: str,
    direction: str = "trend_follow",
    ma_period: int = 200,
    threshold_pct: float = 0.0,
) -> dict:
    """
    Backtest a leveraged MA signal strategy using historical daily closes.

    Signal is generated from the UNDERLYING's price vs its SMA.
    Returns are computed from the LEVERAGED ETF's actual closing prices.
    Sub-period breakdowns: 2018-Q4, 2020, 2022, and full history.
    """
    from services import polygon_client

    cfg = next((c for c in ASSET_CONFIGS if c["asset_key"] == asset_key), None)
    if cfg is None:
        raise ValueError(f"Unknown asset_key: {asset_key}")

    # Fetch ~12 years of history (4500 calendar days ≈ 3000 trading days)
    HISTORY_DAYS = 4500

    logger.info("Backtest: fetching %d days of closes for %s and %s", HISTORY_DAYS, cfg["underlying"], cfg["leveraged"])
    underlying_closes = polygon_client.get_close_prices(cfg["underlying"], days=HISTORY_DAYS)
    time.sleep(0.3)
    leveraged_closes = polygon_client.get_close_prices(cfg["leveraged"], days=HISTORY_DAYS)

    if len(underlying_closes) < ma_period + 10:
        return {"error": f"Insufficient historical data for {cfg['underlying']}"}
    if len(leveraged_closes) < 50:
        return {"error": f"Insufficient historical data for {cfg['leveraged']} (ETF may not have enough history)"}

    # Align series: build a simple day-indexed timeline.
    # We have no dates from get_close_prices — use a synthetic date range working backwards.
    # Both tickers should have approximately the same number of trading days.
    # Use the SHORTER of the two series for alignment.
    n_underlying = len(underlying_closes)
    n_leveraged = len(leveraged_closes)

    # Build synthetic dates (trading days, approximate) from today backwards
    today = date.today()
    all_trade_days = []
    d = today
    count = 0
    while count < max(n_underlying, n_leveraged) + 10:
        if d.weekday() < 5:
            all_trade_days.append(d)
            count += 1
        d -= timedelta(days=1)
    all_trade_days.reverse()  # ascending

    # Align: use the last n_underlying days for underlying, last n_leveraged for leveraged
    underlying_dates = all_trade_days[-n_underlying:]
    leveraged_dates = all_trade_days[-n_leveraged:]

    # Find common date range
    u_start = underlying_dates[0]
    l_start = leveraged_dates[0]
    common_start = max(u_start, l_start)
    common_end = min(underlying_dates[-1], leveraged_dates[-1])

    # Build date→close maps
    u_map = {underlying_dates[i]: underlying_closes[i] for i in range(n_underlying)}
    l_map = {leveraged_dates[i]: leveraged_closes[i] for i in range(n_leveraged)}

    # Compute SMA signals over common date range (need ma_period warmup)
    # Collect underlying prices in common range + warmup
    warmup_start = common_start - timedelta(days=ma_period * 2)
    all_underlying_in_range = [(d, p) for d, p in u_map.items() if d >= warmup_start]
    all_underlying_in_range.sort()

    # Build (date, price, sma, side) series
    series: list[tuple] = []
    price_window: list[float] = []
    for d, price in all_underlying_in_range:
        price_window.append(price)
        if len(price_window) < ma_period:
            continue
        sma = mean(price_window[-ma_period:])
        side = get_side(price, sma, threshold_pct)
        if d >= common_start:
            series.append((d, price, sma, side))

    if len(series) < 20:
        return {"error": "Insufficient overlapping data for backtest"}

    # Generate crossing signals
    crossings: list[dict] = []
    for i in range(1, len(series)):
        prev_side = series[i - 1][3]
        cur_date, cur_price, cur_sma, cur_side = series[i]
        if cur_side != prev_side:
            label = signal_label(direction, cur_side)
            crossings.append({"date": cur_date, "side": cur_side, "label": label, "underlying_price": cur_price})

    # Simulate trades: enter leveraged on signal, exit on next opposing signal
    def _sim_trades(crossings, direction, l_map, common_end):
        trades = []
        in_position = False
        entry_date = None
        entry_price = None

        for cross in crossings:
            d = cross["date"]
            side = cross["side"]

            # Determine if this crossing is an entry or exit for this direction
            is_entry = (
                (direction == "trend_follow" and side == "above") or
                (direction == "mean_reversion" and side == "below")
            )
            is_exit = (
                (direction == "trend_follow" and side == "below") or
                (direction == "mean_reversion" and side == "above")
            )

            if is_entry and not in_position:
                lev_price = l_map.get(d)
                if lev_price:
                    in_position = True
                    entry_date = d
                    entry_price = lev_price
            elif is_exit and in_position:
                lev_price = l_map.get(d)
                if lev_price and entry_price:
                    ret = (lev_price - entry_price) / entry_price
                    days_held = (d - entry_date).days
                    trades.append({
                        "entry_date": entry_date.isoformat(),
                        "exit_date": d.isoformat(),
                        "entry_price": round(entry_price, 2),
                        "exit_price": round(lev_price, 2),
                        "return_pct": round(ret * 100, 2),
                        "days_held": days_held,
                    })
                    in_position = False
                    entry_date = None
                    entry_price = None

        # Close any open position at end of data
        if in_position and entry_price:
            last_date = common_end
            lev_price = l_map.get(last_date)
            if lev_price:
                ret = (lev_price - entry_price) / entry_price
                trades.append({
                    "entry_date": entry_date.isoformat(),
                    "exit_date": last_date.isoformat(),
                    "entry_price": round(entry_price, 2),
                    "exit_price": round(lev_price, 2),
                    "return_pct": round(ret * 100, 2),
                    "days_held": (last_date - entry_date).days,
                    "open_position": True,
                })
        return trades

    trades = _sim_trades(crossings, direction, l_map, common_end)

    def _compute_stats(trades_subset: list[dict]) -> dict:
        if not trades_subset:
            return {"total_return_pct": None, "max_drawdown_pct": None, "num_trades": 0, "calmar_ratio": None, "win_rate_pct": None}
        compounded = 1.0
        peak = 1.0
        max_dd = 0.0
        wins = 0
        for t in trades_subset:
            compounded *= (1 + t["return_pct"] / 100)
            if compounded > peak:
                peak = compounded
            dd = (peak - compounded) / peak
            if dd > max_dd:
                max_dd = dd
            if t["return_pct"] > 0:
                wins += 1
        total_ret = (compounded - 1) * 100
        calmar = round(total_ret / (max_dd * 100), 2) if max_dd > 0 else None
        return {
            "total_return_pct": round(total_ret, 1),
            "max_drawdown_pct": round(max_dd * 100, 1),
            "num_trades": len(trades_subset),
            "calmar_ratio": calmar,
            "win_rate_pct": round(wins / len(trades_subset) * 100, 1) if trades_subset else None,
        }

    def _trades_in_period(trades, start_str, end_str):
        s = date.fromisoformat(start_str)
        e = date.fromisoformat(end_str)
        return [t for t in trades if date.fromisoformat(t["entry_date"]) >= s and date.fromisoformat(t["entry_date"]) <= e]

    full_stats = _compute_stats(trades)

    sub_periods = []
    period_defs = [
        ("2007–2009 (Financial Crisis)", "2007-01-01", "2009-12-31"),
        ("2018 Q4 (Rate Shock)", "2018-10-01", "2018-12-31"),
        ("2020 (COVID Crash + Recovery)", "2020-01-01", "2020-12-31"),
        ("2022 (Rate Hike Bear)", "2022-01-01", "2022-12-31"),
    ]
    for label, start_str, end_str in period_defs:
        sub = _trades_in_period(trades, start_str, end_str)
        note = None
        if not sub:
            start_d = date.fromisoformat(start_str)
            if common_start > start_d:
                note = f"{cfg['leveraged']} data starts {common_start.isoformat()} — period predates ETF launch"
            else:
                note = "No trades generated in this period"
        period_stats = _compute_stats(sub)
        period_stats["period"] = label
        period_stats["note"] = note
        sub_periods.append(period_stats)

    return {
        "asset_key": asset_key,
        "leveraged": cfg["leveraged"],
        "underlying": cfg["underlying"],
        "direction": direction,
        "ma_period": ma_period,
        "threshold_pct": threshold_pct,
        "data_start": series[0][0].isoformat() if series else None,
        "data_end": series[-1][0].isoformat() if series else None,
        "total_crossings": len(crossings),
        "full_period": full_stats,
        "sub_periods": sub_periods,
        "trades": trades,
    }
