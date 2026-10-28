"""
Backtest: QQQ 200-day MA touch -> long TQQQ (stock side only).

Question under test (Oct 2026): is there an edge in buying TQQQ when QQQ
pulls back to its 200-day moving average? This script tests the STOCK-side
signal only. A winning stock signal does NOT imply winning TQQQ calls:
options add theta decay and implied-volatility effects this script does
not model. The options layer stays untested until real historical option
prices replace modeled premiums (see review item 3).

Rules (mechanical, no discretion):
  Signal (day T, from closes only, no lookahead):
    - QQQ 200-day MA is rising (MA200 today above MA200 20 sessions ago).
    - QQQ was above its 200DMA at the prior close.
    - QQQ's day-T low touches or dips below the 200DMA, and day-T close
      is back above it ("touch and hold").
    - One trade per episode: after a signal, no new signal for 20
      sessions (cooldown), so clustered touches in one pullback do not
      stack into overlapping positions.
  Entry: TQQQ at the T+1 open, 0.05% slippage per side (harness standard).
  Exits (three variants, all reported):
    V1 hold_10       -- exit at the open 10 sessions after entry.
    V2 reclaim_stop  -- exit at the first open after QQQ closes back
                        above its 50DMA (bounce taken) OR closes below
                        its 200DMA (thesis dead), max 21 sessions.
    V3 confirmed_10  -- like V1, but entry requires confirmation: the
                        T+1 close must also hold above the 200DMA, so
                        entry moves to the T+2 open; otherwise no trade.

Data sources, in order (same policy as run_real_backtests.py):
  1. yfinance (daily OHLCV, auto-adjusted for splits and dividends).
  2. Massive / Polygon aggregates API (POLYGON_API_KEY or MASSIVE_API_KEY
     env var), used only if yfinance fails.
  There is NO synthetic fallback. If real data cannot be fetched, the
  run aborts with a clear error and writes nothing.

Backtest standard (same as the registered setups):
  - Walk-forward: in-sample 2019-2022, out-of-sample 2023 to present
    (harness dates), plus full-period stats from TQQQ inception
    (Feb 2010; TQQQ did not exist before then, so no 2008 test).
  - Scoring is expectancy per trade, profit factor, average win vs
    average loss, and max drawdown; win rate is informational only.
  - Robustness: the hold-days parameter rerun at +/-20% on V1; the
    verdict uses the harness PASSES / SHADOW ONLY / FAILS rule.
  - Costs: 0.05% slippage per side; $0 stock commission (harness
    standard). No options commission here because no options are traded.

Usage (from the repo root, with network access and yfinance installed):

    python scripts/backtest_tqqq_200ma.py

Writes backtests/tqqq_200ma.md (and prints the same report). Smoke test
(mechanics only, no network, no results):

    python scripts/backtest_tqqq_200ma.py --smoke-test
"""

import argparse
import logging
import os
import sys
from datetime import date

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.normpath(os.path.join(_HERE, ".."))
_BACKEND = os.path.join(_REPO_ROOT, "backend")
for _p in (_BACKEND, _REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("backtest_tqqq_200ma")

SLIPPAGE = 0.0005
COOLDOWN_SESSIONS = 20
HOLD_DAYS = 10
MAX_HOLD = 21
SIGNAL_INDEX = "QQQ"
TRADE_INDEX = "TQQQ"
START = "2010-01-01"

YF_ATTEMPTS = 3
YF_BACKOFF_SECONDS = 5.0


class DataUnavailableError(ValueError):
    pass


def _normalize_ohlcv(df):
    """Return a DataFrame with plain Open/High/Low/Close columns."""
    import pandas as pd

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[["Open", "High", "Low", "Close"]].dropna()
    return df


def _download_yfinance(ticker, start):
    import time

    import yfinance as yf

    last_err = None
    for attempt in range(1, YF_ATTEMPTS + 1):
        try:
            df = yf.download(
                ticker, start=start, auto_adjust=True,
                progress=False,
            )
            if df is None or df.empty:
                raise DataUnavailableError(f"yfinance returned no rows for {ticker}")
            return _normalize_ohlcv(df)
        except Exception as e:  # noqa: BLE001 - retry then abort loudly
            last_err = e
            logger.warning("yfinance %s attempt %d failed: %s", ticker, attempt, e)
            time.sleep(YF_BACKOFF_SECONDS * attempt)
    raise DataUnavailableError(f"yfinance failed for {ticker}: {last_err}")


def _download_massive(ticker, start):
    """Massive (Polygon) aggregates fallback. Raises if no key or no rows."""
    import urllib.request
    import urllib.error

    import pandas as pd

    key = os.environ.get("POLYGON_API_KEY") or os.environ.get("MASSIVE_API_KEY")
    if not key:
        raise DataUnavailableError("no Massive/Polygon key set")
    end = date.today().isoformat()
    url = (
        f"https://api.massive.com/v2/aggs/ticker/{ticker}/range/1/day/"
        f"{start}/{end}?adjusted=true&limit=50000&apiKey={key}"
    )
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            import json

            payload = json.load(r)
    except urllib.error.URLError as e:
        raise DataUnavailableError(f"Massive request failed for {ticker}: {e}")
    results = payload.get("results") or []
    if not results:
        raise DataUnavailableError(f"Massive returned no rows for {ticker}")
    df = pd.DataFrame(results)
    df["t"] = pd.to_datetime(df["t"], unit="ms").dt.tz_localize(None)
    df = df.set_index("t").rename(
        columns={"o": "Open", "h": "High", "l": "Low", "c": "Close"}
    )
    return _normalize_ohlcv(df)


def download_history(ticker, start):
    """Real data only. yfinance first, Massive fallback, else abort."""
    try:
        return _download_yfinance(ticker, start)
    except DataUnavailableError as e:
        logger.warning("yfinance unusable for %s (%s); trying Massive", ticker, e)
    return _download_massive(ticker, start)


def build_trades(qqq, tqqq, hold_days=HOLD_DAYS, variant="hold_10"):
    """Generate Trade objects for one exit variant.

    qqq / tqqq are aligned DataFrames with Open/High/Low/Close columns
    and a DatetimeIndex. Signal uses QQQ closes only; entry/exit prices
    are TQQQ opens. No lookahead: a day-T signal enters at T+1 open at
    the earliest.
    """
    import numpy as np
    import pandas as pd

    import services.backtest_harness as harness

    closes = qqq["Close"].to_numpy(dtype=float)
    lows = qqq["Low"].to_numpy(dtype=float)
    highs = qqq["High"].to_numpy(dtype=float)
    opens_t = tqqq["Open"].to_numpy(dtype=float)
    dates = qqq.index

    ma200 = pd.Series(closes).rolling(200).mean().to_numpy(dtype=float)
    ma50 = pd.Series(closes).rolling(50).mean().to_numpy(dtype=float)

    trades = []
    next_allowed = 0
    for i in range(200, len(qqq) - 2):
        if i < next_allowed:
            continue
        if np.isnan(ma200[i]) or np.isnan(ma200[i - 20]):
            continue
        rising = ma200[i] > ma200[i - 20]
        was_above = closes[i - 1] >= ma200[i - 1]
        touched = lows[i] <= ma200[i]
        held = closes[i] >= ma200[i]
        if not (rising and was_above and touched and held):
            continue

        # Entry index / price, by variant.
        if variant == "confirmed_10":
            # Confirmation: T+1 must also close above the 200DMA.
            if closes[i + 1] < ma200[i + 1]:
                continue
            entry_idx = i + 2
        else:
            entry_idx = i + 1
        if entry_idx >= len(qqq):
            break
        entry_price = opens_t[entry_idx] * (1 + SLIPPAGE)

        # Exit index / reason.
        if variant == "hold_10" or variant == "confirmed_10":
            exit_idx = min(entry_idx + hold_days, len(qqq) - 1)
            exit_reason = f"hold_{hold_days}d"
        elif variant == "reclaim_stop":
            exit_idx = min(entry_idx + MAX_HOLD, len(qqq) - 1)
            exit_reason = f"max_{MAX_HOLD}d"
            for j in range(entry_idx, min(entry_idx + MAX_HOLD, len(qqq) - 1)):
                if closes[j] > ma50[j]:
                    exit_idx = j + 1
                    exit_reason = "reclaim_50dma"
                    break
                if closes[j] < ma200[j]:
                    exit_idx = j + 1
                    exit_reason = "stop_below_200dma"
                    break
        else:
            raise ValueError(f"unknown variant {variant}")

        exit_price = opens_t[exit_idx] * (1 - SLIPPAGE)
        pnl_pct = (exit_price / entry_price - 1.0) * 100.0
        trades.append(harness.Trade(
            ticker=TRADE_INDEX,
            signal_date=dates[i].date(),
            entry_date=dates[entry_idx].date(),
            entry_price=round(float(entry_price), 4),
            exit_date=dates[exit_idx].date(),
            exit_price=round(float(exit_price), 4),
            exit_reason=exit_reason,
            regime_calendar=harness._calendar_regime(dates[entry_idx].date()),
            regime_spy_ma="",
            pnl_pct=round(float(pnl_pct), 4),
        ))
        next_allowed = entry_idx + COOLDOWN_SESSIONS
    return trades


def split_stats(trades):
    """Full / IS / OOS / bear-2022 stats via the harness scorer."""
    import services.backtest_harness as harness

    def stats_for(sub):
        return harness._compute_stats_for_trades(sub)

    return {
        "full": stats_for(trades),
        "in_sample": stats_for(
            [t for t in trades
             if harness.IS_START <= t.entry_date <= harness.IS_END]),
        "out_of_sample": stats_for(
            [t for t in trades
             if harness.OOS_START <= t.entry_date <= harness.OOS_END]),
        "bear_2022": stats_for(
            [t for t in trades if t.regime_calendar == "bear_2022"]),
    }


def buy_and_hold_baseline(tqqq, qqq):
    """Total return and max drawdown of holding each index over the window."""
    import numpy as np

    def series_stats(closes):
        closes = np.asarray(closes, dtype=float)
        total = (closes[-1] / closes[0] - 1.0) * 100.0
        peak = closes[0]
        max_dd = 0.0
        for c in closes:
            peak = max(peak, c)
            max_dd = max(max_dd, (peak - c) / peak * 100.0)
        return round(float(total), 2), round(float(max_dd), 2)

    t_ret, t_dd = series_stats(tqqq["Close"].to_numpy())
    q_ret, q_dd = series_stats(qqq["Close"].to_numpy())
    return (t_ret, t_dd), (q_ret, q_dd)


def render_report(variants, splits, verdicts, baselines, data_note):
    import services.backtest_harness as harness

    lines = []
    lines.append("# Backtest: QQQ 200DMA touch -> long TQQQ (stock side)")
    lines.append("")
    lines.append("## Rule definition")
    lines.append("  Signal (day T, closes only): QQQ 200DMA rising (above its value")
    lines.append("  20 sessions ago); QQQ above the 200DMA at the prior close; day-T")
    lines.append("  low touches/dips below the 200DMA and day-T close is back above")
    lines.append("  it. One trade per episode: 20-session cooldown after a signal.")
    lines.append("  Entry: TQQQ at the T+1 open (T+2 open for the confirmed variant).")
    lines.append("  Exits: V1 hold_10 (fixed 10 sessions); V2 reclaim_stop (first")
    lines.append("  QQQ close above 50DMA, or below 200DMA, max 21 sessions);")
    lines.append("  V3 confirmed_10 (T+1 close must also hold above 200DMA, then")
    lines.append("  fixed 10 sessions).")
    lines.append("")
    lines.append("## Universe and costs")
    lines.append("  Signal index: QQQ. Traded instrument: TQQQ (3x daily leveraged")
    lines.append("  Nasdaq-100 ETF, inception Feb 2010 -- no pre-2010 history exists,")
    lines.append("  so there is no 2008 test. Slippage 0.05% per side; $0 stock")
    lines.append("  commission (harness standard). Data source: " + data_note + ".")
    lines.append("")
    lines.append("## Caveats (read before trading this)")
    lines.append("  - STOCK SIDE ONLY. This backtest says nothing about TQQQ calls:")
    lines.append("    options add theta decay and IV effects that are not modeled here.")
    lines.append("  - Leveraged-ETF decay: TQQQ resets daily, so choppy markets drag")
    lines.append("    it even when QQQ ends flat. A winning stock signal can still")
    lines.append("    lose as an options trade if the bounce is slow or small.")
    lines.append("  - Adjusted closes (splits/dividends). Past performance is not a")
    lines.append("    promise; the 200DMA is a watched level, not a law, and touches")
    lines.append("    that fail are how corrections become bear markets.")
    lines.append("")
    (t_ret, t_dd), (q_ret, q_dd) = baselines
    lines.append("## Buy-and-hold baseline (same window, closes)")
    lines.append(f"  TQQQ: total {t_ret:+.2f}%  |  max drawdown {t_dd:.2f}%")
    lines.append(f"  QQQ:  total {q_ret:+.2f}%  |  max drawdown {q_dd:.2f}%")
    lines.append("")
    for name, sp in splits.items():
        lines.append(f"## Variant {name} -- verdict: {verdicts[name]}")
        lines.append(harness._fmt_stats("Full period", sp["full"]))
        lines.append(harness._fmt_stats("In-sample 2019-2022", sp["in_sample"]))
        lines.append(harness._fmt_stats("Out-of-sample 2023-present", sp["out_of_sample"]))
        lines.append(harness._fmt_stats("Bear 2022", sp["bear_2022"]))
        lines.append("")
    return "\n".join(lines)


def smoke_test():
    """Mechanics only: hardcoded bars engineered to fire exactly the
    touch-and-hold signal, so entry/exit math is exercised. No network,
    no results."""
    import pandas as pd

    import services.backtest_harness as harness

    # 270 sessions rising 0.1/day: the 200DMA trails below price and rises.
    closes = [100.0 + 0.1 * i for i in range(270)]
    # Day 251: intraday dip below the 200DMA (~115.10), close back above.
    closes[251] = 116.0
    lows = [c - 0.5 for c in closes]
    highs = [c + 0.5 for c in closes]
    lows[251] = 114.0
    idx = pd.date_range("2020-01-01", periods=len(closes), freq="B")
    qqq = pd.DataFrame(
        {"Open": closes, "High": highs, "Low": lows, "Close": closes},
        index=idx)
    tqqq = pd.DataFrame(
        {"Open": [c * 0.5 for c in closes],
         "High": [c * 0.5 + 0.25 for c in closes],
         "Low": [c * 0.5 - 0.25 for c in closes],
         "Close": [c * 0.5 for c in closes]}, index=idx)
    trades = build_trades(qqq, tqqq, variant="hold_10")
    assert len(trades) >= 1, "smoke series must fire at least one signal"
    stats = harness._compute_stats_for_trades(trades)
    for t in trades:
        assert t.pnl_pct == t.pnl_pct and abs(t.pnl_pct) < 1000, "sane pnl"
        assert t.exit_date >= t.entry_date, "exit after entry"
        assert t.exit_reason == "hold_10d", "expected fixed-hold exit"
    print(f"SMOKE OK: {len(trades)} trades, stats keys: {sorted(stats.keys())}")
    return True


def run(output_dir):
    import pandas as pd

    import services.backtest_harness as harness

    qqq = download_history(SIGNAL_INDEX, START)
    tqqq = download_history(TRADE_INDEX, START)
    joined = qqq.join(tqqq, lsuffix="_qqq", rsuffix="_tqqq", how="inner")
    q = pd.DataFrame({
        "Open": joined["Open_qqq"], "High": joined["High_qqq"],
        "Low": joined["Low_qqq"], "Close": joined["Close_qqq"],
    })
    t = pd.DataFrame({
        "Open": joined["Open_tqqq"], "High": joined["High_tqqq"],
        "Low": joined["Low_tqqq"], "Close": joined["Close_tqqq"],
    })
    if len(q) < 250:
        raise DataUnavailableError("not enough overlapping QQQ/TQQQ history")
    logger.info("History: %s rows, %s to %s", len(q), q.index[0].date(),
                q.index[-1].date())

    variants = {}
    splits = {}
    verdicts = {}
    for name, kwargs in [
        ("V1_hold_10", {"variant": "hold_10"}),
        ("V2_reclaim_stop", {"variant": "reclaim_stop"}),
        ("V3_confirmed_10", {"variant": "confirmed_10"}),
    ]:
        trades = build_trades(q, t, **kwargs)
        variants[name] = trades
        splits[name] = split_stats(trades)
        logger.info("%s: %d trades", name, len(trades))

    # Robustness on the primary variant: hold days +/-20% (8 / 12), OOS only.
    robustness = []
    for hold in (8, 12):
        r_trades = build_trades(q, t, hold_days=hold, variant="hold_10")
        r_oos = harness._compute_stats_for_trades(
            [x for x in r_trades
             if harness.OOS_START <= x.entry_date <= harness.OOS_END])
        robustness.append({"oos_stats": r_oos})
    oos_primary = splits["V1_hold_10"]["out_of_sample"]
    fragile = harness._is_fragile(oos_primary, robustness)
    verdicts["V1_hold_10"] = harness._verdict(oos_primary, fragile, False)
    for name in ("V2_reclaim_stop", "V3_confirmed_10"):
        verdicts[name] = harness._verdict(
            splits[name]["out_of_sample"], False, False)

    baselines = buy_and_hold_baseline(t, q)
    report = render_report(variants, splits, verdicts, baselines, "REAL")
    print(report)

    os.makedirs(output_dir, exist_ok=True)
    out_path = os.path.join(output_dir, "tqqq_200ma.md")
    with open(out_path, "w") as f:
        f.write(report + "\n")
    logger.info("Report written to %s", out_path)
    return verdicts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--output-dir", default="backtests")
    args = parser.parse_args()
    if args.smoke_test:
        smoke_test()
        return 0
    try:
        run(args.output_dir)
    except DataUnavailableError as e:
        logger.error("ABORTED, nothing written: %s", e)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
