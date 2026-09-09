"""
Leveraged ETF MA Signal Service
================================
161-day SMA crossover strategy for leveraged ETFs based on their underlying index ETFs.
Entry requires price >= +1% above SMA for 3 consecutive days.
Exit requires price <= -2.5% below SMA for 3 consecutive days.
When out of the leveraged ETF, capital earns the current short-term T-bill yield (SGOV proxy).

Daily signal engine: run via scheduler at 17:00 ET after final close prices settle.
Dashboard endpoint: DB state + live intraday prices from Polygon batch snapshot.
Backtest: day-by-day equity simulation using the same state machine as the live engine.
"""

import logging
import time
from datetime import datetime, timezone, date, timedelta

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Strategy parameters (tune here, everything else derives from these)
# ---------------------------------------------------------------------------

CONFIRMATION_DAYS = 3       # consecutive days required to confirm a signal
ENTRY_BUFFER_PCT = 1.0      # price must be >= +1% above SMA to count toward a buy
EXIT_BUFFER_PCT = -2.5      # price must be <= -2.5% below SMA to count toward a sell
_DIRECTION = "ma_crossover"  # single unified signal per pair (replaces old split)

# ---------------------------------------------------------------------------
# Asset configuration
# ---------------------------------------------------------------------------

ASSET_CONFIGS = [
    {
        "asset_key": "TQQQ_QQQ",
        "leveraged": "TQQQ",
        "underlying": "QQQ",
        "ma_period": 161,
        "entry_buffer_pct": ENTRY_BUFFER_PCT,
        "exit_buffer_pct": EXIT_BUFFER_PCT,
        "active": True,
        "leverage_multiple": 3,
    },
    {
        "asset_key": "SPXL_SPY",
        "leveraged": "SPXL",
        "underlying": "SPY",
        "ma_period": 161,
        "entry_buffer_pct": ENTRY_BUFFER_PCT,
        "exit_buffer_pct": EXIT_BUFFER_PCT,
        "active": True,
        "leverage_multiple": 3,
    },
    {
        "asset_key": "SOXL_SOXX",
        "leveraged": "SOXL",
        "underlying": "SOXX",
        "ma_period": 161,
        "entry_buffer_pct": ENTRY_BUFFER_PCT,
        "exit_buffer_pct": EXIT_BUFFER_PCT,
        "active": True,
        "leverage_multiple": 3,
    },
    {
        "asset_key": "TNA_IWM",
        "leveraged": "TNA",
        "underlying": "IWM",
        "ma_period": 161,
        "entry_buffer_pct": ENTRY_BUFFER_PCT,
        "exit_buffer_pct": EXIT_BUFFER_PCT,
        "active": True,
        "leverage_multiple": 3,
    },
    {
        "asset_key": "UPRO_SPY",
        "leveraged": "UPRO",
        "underlying": "SPY",
        "ma_period": 161,
        "entry_buffer_pct": ENTRY_BUFFER_PCT,
        "exit_buffer_pct": EXIT_BUFFER_PCT,
        "active": True,
        "leverage_multiple": 3,
    },
]


# ---------------------------------------------------------------------------
# Pure signal math (shared by daily engine and backtest)
# ---------------------------------------------------------------------------

def get_raw_trigger(price: float, sma: float, entry_buffer_pct: float, exit_buffer_pct: float) -> str:
    """
    Classify today's price relative to the asymmetric entry/exit bands.

    Returns:
        "buy_zone"  — price >= SMA * (1 + entry_buffer_pct/100)
        "sell_zone" — price <= SMA * (1 + exit_buffer_pct/100)
        "neutral"   — price is inside the band (no action)
    """
    entry_level = sma * (1 + entry_buffer_pct / 100)
    exit_level = sma * (1 + exit_buffer_pct / 100)
    if price >= entry_level:
        return "buy_zone"
    if price <= exit_level:
        return "sell_zone"
    return "neutral"


def apply_confirmation_machine(
    trigger: str,
    confirmed_position: str | None,
    pending_signal: str | None,
    pending_days: int,
) -> tuple[str | None, str | None, int, bool]:
    """
    One step of the confirmation state machine.

    Returns: (new_confirmed_position, new_pending_signal, new_pending_days, position_changed)

    Rules:
    - A BUY fires only after CONFIRMATION_DAYS consecutive "buy_zone" days while OUT.
    - A SELL fires only after CONFIRMATION_DAYS consecutive "sell_zone" days while IN.
    - Any day in "neutral" or the opposite zone resets the pending counter.
    - Already-confirmed side is a no-op (no double-fire).
    """
    position_changed = False

    if trigger == "buy_zone" and confirmed_position != "in":
        if pending_signal == "buy":
            pending_days += 1
        else:
            pending_signal = "buy"
            pending_days = 1
        if pending_days >= CONFIRMATION_DAYS:
            confirmed_position = "in"
            pending_signal = None
            pending_days = 0
            position_changed = True

    elif trigger == "sell_zone" and confirmed_position != "out":
        if pending_signal == "sell":
            pending_days += 1
        else:
            pending_signal = "sell"
            pending_days = 1
        if pending_days >= CONFIRMATION_DAYS:
            confirmed_position = "out"
            pending_signal = None
            pending_days = 0
            position_changed = True

    else:
        # Neutral zone, already confirmed, or opposing zone — reset pending
        pending_signal = None
        pending_days = 0

    return confirmed_position, pending_signal, pending_days, position_changed


# ---------------------------------------------------------------------------
# Cash APY helper (SGOV as T-bill proxy, Finnhub dividend yield)
# ---------------------------------------------------------------------------

def get_current_cash_apy() -> dict:
    """
    Fetch the current short-term T-bill yield using SGOV's TTM dividend yield
    from Finnhub as a proxy. Returns a dict with the apy_pct and source label.
    Falls back to a hardcoded 4.5% if Finnhub is unavailable.
    """
    from services import finnhub_client
    FALLBACK = 4.5

    for proxy in ("SGOV", "BIL"):  # try both short T-bill ETFs
        try:
            metrics = finnhub_client.get_basic_financials(proxy)
            raw = metrics.get("dividendYieldTTM")
            if raw and float(raw) > 0:
                val = float(raw)
                # Finnhub returns decimal (0.05) not percent (5.0) for yield fields
                apy = round(val * 100, 2) if val < 1.0 else round(val, 2)
                if 0.5 <= apy <= 15.0:  # sanity range for a short T-bill yield
                    return {
                        "apy_pct": apy,
                        "source": f"{proxy} TTM dividend yield (Finnhub)",
                        "is_live": True,
                    }
        except Exception as e:
            logger.debug("Cash APY fetch failed for %s: %s", proxy, e)
        time.sleep(0.3)

    return {
        "apy_pct": FALLBACK,
        "source": "Fallback — Finnhub unavailable",
        "is_live": False,
    }


# ---------------------------------------------------------------------------
# Daily signal engine (called by scheduler at 17:00 ET)
# ---------------------------------------------------------------------------

def run_daily_signal_engine() -> None:
    """
    Compute 161-day SMA, classify trigger zone, apply confirmation state machine,
    and persist updated state to DB for all active asset configs.

    Creates its own DB session so it's safe to call from a background thread.
    Deduplicates underlying tickers (SPY is shared by SPXL and UPRO).
    """
    from database import SessionLocal
    from models.leveraged_ma import LeveragedMASignalState
    from services import polygon_client

    db = SessionLocal()
    try:
        # Fetch underlying closes — deduplicate (SPXL + UPRO both use SPY)
        underlying_closes: dict[str, list[float]] = {}
        for cfg in ASSET_CONFIGS:
            if not cfg["active"] or cfg["underlying"] in underlying_closes:
                continue
            warmup = cfg["ma_period"] + 10
            logger.info("Leveraged MA engine: fetching %d-day closes for %s", warmup, cfg["underlying"])
            underlying_closes[cfg["underlying"]] = polygon_client.get_close_prices(
                cfg["underlying"], days=warmup
            )
            time.sleep(0.3)

        now = datetime.now(timezone.utc)

        for cfg in ASSET_CONFIGS:
            if not cfg["active"]:
                continue

            closes = underlying_closes.get(cfg["underlying"], [])
            if len(closes) < cfg["ma_period"]:
                logger.warning("Leveraged MA: insufficient data for %s (%d closes)", cfg["underlying"], len(closes))
                continue

            sma = float(np.mean(closes[-cfg["ma_period"]:]))
            current_price = closes[-1]
            trigger = get_raw_trigger(current_price, sma, cfg["entry_buffer_pct"], cfg["exit_buffer_pct"])
            dist_pct = round((current_price - sma) / sma * 100, 2)

            state = (
                db.query(LeveragedMASignalState)
                .filter_by(asset_key=cfg["asset_key"], direction=_DIRECTION)
                .first()
            )
            if state is None:
                # First run — start OUT (conservative default)
                state = LeveragedMASignalState(
                    asset_key=cfg["asset_key"],
                    direction=_DIRECTION,
                    confirmed_position="out",
                    pending_signal=None,
                    pending_days=0,
                )
                db.add(state)

            old_position = state.confirmed_position
            new_pos, new_pending, new_days, changed = apply_confirmation_machine(
                trigger,
                state.confirmed_position,
                state.pending_signal,
                state.pending_days or 0,
            )

            if changed:
                label = "IN (LONG)" if new_pos == "in" else "OUT (CASH)"
                logger.info(
                    "Leveraged MA SIGNAL: %s → %s [was %s, trigger=%s, dist=%.1f%%]",
                    cfg["asset_key"], label, old_position, trigger, dist_pct,
                )
                state.last_cross_at = now
                state.last_cross_side = new_pos

            state.last_side = trigger
            state.confirmed_position = new_pos
            state.pending_signal = new_pending
            state.pending_days = new_days
            state.last_checked_at = now
            state.sma_at_check = str(round(sma, 4))

        db.commit()
        logger.info("Leveraged MA: daily signal engine complete for %s", date.today())
    except Exception as e:
        db.rollback()
        logger.error("Leveraged MA: daily engine failed: %s", e, exc_info=True)
        raise  # re-raise so the caller (thread wrapper / health) can capture the error
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Dashboard data (DB state + live intraday prices)
# ---------------------------------------------------------------------------

def get_signals_dashboard() -> list[dict]:
    """
    One row per active asset config with confirmed position, pending signal
    progress, and live intraday prices from Polygon batch snapshot.
    """
    from database import SessionLocal
    from models.leveraged_ma import LeveragedMASignalState
    from services import polygon_client

    db = SessionLocal()
    try:
        all_tickers = list({t for cfg in ASSET_CONFIGS for t in (cfg["leveraged"], cfg["underlying"])})
        snapshots = polygon_client.get_snapshots_batch(all_tickers)
        today_utc = datetime.now(timezone.utc).date()
        rows: list[dict] = []

        for cfg in ASSET_CONFIGS:
            if not cfg["active"]:
                continue

            u_snap = snapshots.get(cfg["underlying"], {})
            l_snap = snapshots.get(cfg["leveraged"], {})
            live_u_price = u_snap.get("price") or None
            live_l_price = l_snap.get("price") or None

            state = (
                db.query(LeveragedMASignalState)
                .filter_by(asset_key=cfg["asset_key"], direction=_DIRECTION)
                .first()
            )

            sma = float(state.sma_at_check) if (state and state.sma_at_check) else None
            confirmed_position = state.confirmed_position if state else None
            pending_signal = state.pending_signal if state else None
            pending_days = state.pending_days or 0 if state else 0
            last_checked_at = state.last_checked_at if state else None
            last_cross_at = state.last_cross_at if state else None
            last_cross_side = state.last_cross_side if state else None

            # Live intraday trigger zone
            live_trigger = None
            live_dist_pct = None
            if live_u_price and sma:
                live_trigger = get_raw_trigger(live_u_price, sma, cfg["entry_buffer_pct"], cfg["exit_buffer_pct"])
                live_dist_pct = round((live_u_price - sma) / sma * 100, 2)

            # Signal changed today?
            signal_today = False
            if last_cross_at:
                cross_date = last_cross_at.date() if isinstance(last_cross_at, datetime) else last_cross_at
                signal_today = (cross_date == today_utc)

            rows.append({
                "asset_key": cfg["asset_key"],
                "leveraged": cfg["leveraged"],
                "underlying": cfg["underlying"],
                "ma_period": cfg["ma_period"],
                "entry_buffer_pct": cfg["entry_buffer_pct"],
                "exit_buffer_pct": cfg["exit_buffer_pct"],
                "leverage_multiple": cfg["leverage_multiple"],
                # Confirmed position state
                "confirmed_position": confirmed_position,
                "pending_signal": pending_signal,
                "pending_days": pending_days,
                "confirmation_days_required": CONFIRMATION_DAYS,
                "last_signal_date": last_cross_at.isoformat() if last_cross_at else None,
                "last_signal_side": last_cross_side,
                "signal_today": signal_today,
                "last_checked_at": last_checked_at.isoformat() if last_checked_at else None,
                # SMA + live intraday
                "sma": sma,
                "live_trigger": live_trigger,
                "live_dist_pct": live_dist_pct,
                "live_underlying_price": live_u_price,
                "live_leveraged_price": live_l_price,
                "underlying_change_pct": u_snap.get("change_pct"),
                "leveraged_change_pct": l_snap.get("change_pct"),
                "never_run": state is None,
            })

        # Sort: signal_today rows first, then by confirmed_position (in before out), then asset_key
        rows.sort(key=lambda r: (0 if r["signal_today"] else 1, 0 if r["confirmed_position"] == "in" else 1, r["asset_key"]))
        return rows
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Backtest engine (same state machine as live engine, day-by-day simulation)
# ---------------------------------------------------------------------------

def run_backtest(
    asset_key: str,
    ma_period: int = 161,
    entry_buffer_pct: float = ENTRY_BUFFER_PCT,
    exit_buffer_pct: float = EXIT_BUFFER_PCT,
    cash_apy_pct: float = 4.5,
) -> dict:
    """
    Day-by-day backtest using the confirmed-crossover state machine.

    Signal: underlying SMA crossing with entry/exit buffers + CONFIRMATION_DAYS window.
    Returns: TQQQ (or leveraged ETF) actual closing prices when IN, cash APY when OUT.
    Chart data: strategy equity, buy-and-hold equity, SMA, underlying price, IN/OUT bands.
    """
    from services.polygon_client import get_dated_closes

    cfg = next((c for c in ASSET_CONFIGS if c["asset_key"] == asset_key), None)
    if cfg is None:
        raise ValueError(f"Unknown asset_key: {asset_key}")

    HISTORY_DAYS = 4500  # ~12 years back

    logger.info("Backtest: fetching history for %s / %s", cfg["underlying"], cfg["leveraged"])
    u_raw = get_dated_closes(cfg["underlying"], days=HISTORY_DAYS)
    time.sleep(0.3)
    l_raw = get_dated_closes(cfg["leveraged"], days=HISTORY_DAYS)

    if len(u_raw) < ma_period + 20:
        return {"error": f"Insufficient data for {cfg['underlying']} ({len(u_raw)} bars)"}
    if len(l_raw) < 50:
        return {"error": f"Insufficient data for {cfg['leveraged']} — ETF may not have enough history"}

    # Build DataFrames indexed by date
    u_df = pd.DataFrame(u_raw, columns=["date", "close"]).set_index("date")
    u_df.index = pd.to_datetime(u_df.index)
    l_df = pd.DataFrame(l_raw, columns=["date", "close"]).set_index("date")
    l_df.index = pd.to_datetime(l_df.index)

    # Align on common trading days
    common_idx = u_df.index.intersection(l_df.index)
    if len(common_idx) < 50:
        return {"error": "Insufficient overlapping trading days between the two tickers"}

    df = pd.DataFrame({
        "underlying": u_df.loc[common_idx, "close"],
        "leveraged": l_df.loc[common_idx, "close"],
    })

    # Vectorized SMA and deviation (pandas rolling)
    df["sma"] = df["underlying"].rolling(window=ma_period, min_periods=ma_period).mean()
    df["deviation_pct"] = (df["underlying"] - df["sma"]) / df["sma"] * 100

    # Drop warmup rows where SMA is NaN
    df = df.dropna(subset=["sma"]).copy()
    if len(df) < 20:
        return {"error": "Not enough data after SMA warmup period"}

    # ---------------------------------------------------------------------------
    # State machine simulation (loop required — state depends on prior state)
    # ---------------------------------------------------------------------------
    cash_daily_rate = (1 + cash_apy_pct / 100) ** (1 / 252) - 1

    confirmed_pos = "out"   # start conservative — in cash
    pending_sig = None
    pending_cnt = 0

    strategy_equity = 1.0
    bnh_equity = 1.0  # buy-and-hold leveraged ETF from day 1

    equity_curve = []
    bnh_curve = []
    position_flags = []   # True = IN leveraged ETF
    confirmed_positions = []
    pending_signals = []
    pending_counts = []
    signal_dates = []

    prev_leveraged = df["leveraged"].iloc[0]

    for i, (idx, row) in enumerate(df.iterrows()):
        u_price = row["underlying"]
        sma_val = row["sma"]
        l_price = row["leveraged"]

        trigger = get_raw_trigger(u_price, sma_val, entry_buffer_pct, exit_buffer_pct)

        confirmed_pos, pending_sig, pending_cnt, changed = apply_confirmation_machine(
            trigger, confirmed_pos, pending_sig, pending_cnt
        )

        if changed:
            signal_dates.append({"date": str(idx.date()), "position": confirmed_pos})

        # Daily return for strategy
        if i > 0:
            lev_ret = (l_price - prev_leveraged) / prev_leveraged
            if confirmed_pos == "in":
                strategy_equity *= (1 + lev_ret)
            else:
                strategy_equity *= (1 + cash_daily_rate)
            bnh_equity *= (1 + lev_ret)

        equity_curve.append(round(strategy_equity, 6))
        bnh_curve.append(round(bnh_equity, 6))
        position_flags.append(confirmed_pos == "in")
        confirmed_positions.append(confirmed_pos)
        pending_signals.append(pending_sig)
        pending_counts.append(pending_cnt)

        prev_leveraged = l_price

    dates_str = [str(d.date()) for d in df.index]

    # ---------------------------------------------------------------------------
    # Summary statistics (full period)
    # ---------------------------------------------------------------------------
    eq = np.array(equity_curve)
    bnh = np.array(bnh_curve)

    def _stats(equity_arr: np.ndarray, dates_arr: list[str]) -> dict:
        if len(equity_arr) == 0:
            return {}
        peak = np.maximum.accumulate(equity_arr)
        drawdowns = (peak - equity_arr) / peak
        max_dd = float(np.max(drawdowns))
        total_ret = float((equity_arr[-1] - 1) * 100)
        n_years = len(equity_arr) / 252
        cagr = float(((equity_arr[-1]) ** (1 / n_years) - 1) * 100) if n_years > 0 else None
        calmar = round(cagr / (max_dd * 100), 2) if (max_dd > 0 and cagr is not None) else None
        return {
            "total_return_pct": round(total_ret, 1),
            "cagr_pct": round(cagr, 1) if cagr is not None else None,
            "max_drawdown_pct": round(max_dd * 100, 1),
            "calmar_ratio": calmar,
            "data_start": dates_arr[0] if dates_arr else None,
            "data_end": dates_arr[-1] if dates_arr else None,
            "n_trading_days": len(equity_arr),
        }

    def _slice_stats(label: str, start_str: str, end_str: str) -> dict:
        mask = [(start_str <= d <= end_str) for d in dates_str]
        sliced = eq[mask]
        sliced_dates = [d for d, m in zip(dates_str, mask) if m]
        s = _stats(sliced, sliced_dates)
        s["period"] = label
        if len(sliced) == 0:
            s["note"] = (
                f"{cfg['leveraged']} data starts {dates_str[0]} — period predates ETF launch"
                if dates_str and dates_str[0] > start_str
                else "No data in this period"
            )
        return s

    in_days = sum(position_flags)
    out_days = len(position_flags) - in_days

    sub_periods = [
        _slice_stats("2007–2009 (Financial Crisis)", "2007-01-01", "2009-12-31"),
        _slice_stats("2018 Q4 (Rate Shock)",         "2018-10-01", "2018-12-31"),
        _slice_stats("2020 (COVID Crash + Recovery)", "2020-01-01", "2020-12-31"),
        _slice_stats("2022 (Rate Hike Bear)",         "2022-01-01", "2022-12-31"),
    ]

    # Thin the chart series to ~500 points for a manageable JSON payload
    n = len(dates_str)
    stride = max(1, n // 500)
    chart_dates    = dates_str[::stride]
    chart_strategy = [round(v, 4) for v in equity_curve[::stride]]
    chart_bnh      = [round(v, 4) for v in bnh_curve[::stride]]
    chart_sma      = [round(float(v), 2) for v in df["sma"].values[::stride]]
    chart_underlying = [round(float(v), 2) for v in df["underlying"].values[::stride]]
    chart_in_pos   = position_flags[::stride]

    return {
        "asset_key": asset_key,
        "leveraged": cfg["leveraged"],
        "underlying": cfg["underlying"],
        "ma_period": ma_period,
        "entry_buffer_pct": entry_buffer_pct,
        "exit_buffer_pct": exit_buffer_pct,
        "cash_apy_pct": cash_apy_pct,
        "confirmation_days": CONFIRMATION_DAYS,
        "data_start": dates_str[0] if dates_str else None,
        "data_end": dates_str[-1] if dates_str else None,
        "n_signals": len(signal_dates),
        "signal_dates": signal_dates,
        "days_in_pct": round(in_days / len(position_flags) * 100, 1) if position_flags else None,
        "days_out_pct": round(out_days / len(position_flags) * 100, 1) if position_flags else None,
        "full_period": _stats(eq, dates_str),
        "buy_hold": _stats(bnh, dates_str),
        "sub_periods": sub_periods,
        # Chart data (thinned for payload size)
        "chart": {
            "dates": chart_dates,
            "strategy": chart_strategy,
            "buy_hold": chart_bnh,
            "sma": chart_sma,
            "underlying": chart_underlying,
            "in_position": chart_in_pos,
        },
    }
