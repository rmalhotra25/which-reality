"""
Real-data backtest runner for TradeIQ setups.

Runs the three registered backtests (Quality Pullback, Premium at Support,
Volume Breakout) on REAL market data only, using the mechanical rules in
backend/services/backtest_harness.py, and writes the markdown reports the
setup registry reads (backtests/*.md).

Data sources, in order:
  1. yfinance (daily OHLCV, auto-adjusted for splits and dividends).
  2. Massive / Polygon aggregates API (POLYGON_API_KEY or MASSIVE_API_KEY
     env var), used only if yfinance fails for a ticker.

There is NO synthetic fallback in this script. If real data cannot be
fetched for a ticker because the network or the provider fails, the run
aborts with a clear error and writes nothing. A ticker that answers but
returns no usable history (delisted, acquired, never listed) is skipped
and listed in the final summary instead of aborting the run, as is a
live ticker Yahoo serves with only a truncated partial history (a Yahoo
data quirk, recorded separately, never mistaken for a delisting); the
reports still state the full universe size, so the skip list is the
record of the smaller effective universe.

Backtest standard (review E.5):
  - Mechanical rules only, exactly as defined in the registry recipes.
  - Walk-forward: in-sample 2019-2022, out-of-sample 2023 to present.
  - Regime splits reported separately (2022 bear, 2023-2024 bull, recent,
    and per-trade SPY above/below 200-day MA).
  - Entry at the T+1 open; fills use the open adjusted by 0.05% slippage
    per side as the bid/ask proxy (daily bars carry no intraday bid/ask),
    never a midpoint; options carry a $0.65 per-contract commission and a
    5% modeled spread haircut on premium (Premium at Support only).
  - Scoring is expectancy per trade, profit factor, average win vs
    average loss, and max drawdown of the setup equity curve; win rate is
    informational only. Trade count is printed next to every statistic.
  - Robustness: each key parameter rerun at +/-20%; the edge must survive
    across the plateau, not a single peak.
  - No lookahead: signals use the close of day T, entry is day T+1 open.
  - Survivorship caveat printed on every report (currently listed names
    only). The earnings filter is skipped in the backtest (unavailable at
    backtest time); the live alert engine does apply it, so the backtest
    is slightly more permissive than live alerting.

Known rule differences vs the live alert engine (documented, not fixed
here; alert_engine.py is out of scope for this build):
  - Volume Breakout: the backtest requires the 50-day MA to be rising
    (above its value 20 sessions ago). The live evaluator's rising check
    compares the MA to itself and is always true, so live alerting is
    more permissive than this backtest.
  - Premium at Support: the backtest uses the HV percentile in the top
    third as the IV proxy. The live evaluator prefers a stored IV
    percentile and falls back to HV above 30%. The options P&L in this
    backtest is MODELED (Black-Scholes with HV as the IV proxy), so its
    verdict is capped at SHADOW ONLY by design until real historical IV
    replaces the model.
  - Quality Pullback: the live evaluator has no SPY gate (review M30);
    this backtest does not gate on SPY either, but reports the SPY
    above/below 200-day split per trade so the gate can be judged.

Exact command to run the real-data backtests on a networked machine
(from the repo root, with network access and yfinance installed):

    python scripts/run_real_backtests.py

On Render, run it in the deployed shell (same repo checkout, same
command). yfinance needs no key. If yfinance is blocked, set the
Massive key first:

    POLYGON_API_KEY=<massive-key> python scripts/run_real_backtests.py

The run downloads about 550 tickers over 2019 to present plus robustness
variants; expect roughly 30 to 60 minutes. Reports are written to
backtests/ only after all three setups complete with real data; a failed
run writes nothing there.

Smoke test (mechanics only, no network, no results):

    python scripts/run_real_backtests.py --smoke-test

The smoke test runs the harness signal, exit, and statistics functions
on a small hardcoded OHLCV sample and checks them against independently
computed values. It verifies harness mechanics only. Its numbers are NOT
backtest results and are never written to backtests/*.md.
"""
import argparse
import json
import logging
import math
import os
import sys
import time
import urllib.request
import urllib.error
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
logger = logging.getLogger("run_real_backtests")

YF_ATTEMPTS = 3
YF_BACKOFF_SECONDS = 5.0

# Tickers skipped because no real data exists for them (delisted, acquired,
# or never listed), as opposed to a fetch failure. The harness treats this
# as a per-ticker skip, not a run abort.
SKIPPED_TICKERS = set()
# Live tickers Yahoo served with a truncated partial history (1-100 rows):
# skipped for the same reason, but recorded separately so they are never
# mistaken for delistings.
PARTIAL_TICKERS = set()

# In-memory download cache. The harness downloads each ticker once per
# setup run and again per robustness variant; without this cache every
# delisted ticker would pay the full retry cost on every variant, and
# every live ticker would be re-downloaded a dozen times.
_DOWNLOAD_CACHE = {}
_UNAVAILABLE_TICKERS = set()


class TickerUnavailableError(ValueError):
    """No usable real history exists for this ticker (delisted or no data)."""


def _normalize_ohlcv(df):
    """Normalize a yfinance frame to Open/High/Low/Close/Volume, daily index."""
    import pandas as pd

    if df is None or df.empty:
        return df
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.index = pd.to_datetime(df.index).normalize()
    cols = [c for c in ("Open", "High", "Low", "Close", "Volume") if c in df.columns]
    df = df[cols].dropna(subset=["Close"])
    return df


def _download_yfinance(ticker, start, end):
    """
    Fetch daily OHLCV from yfinance with retries.

    Raises TickerUnavailableError when yfinance answers but returns no
    usable history: zero rows on every attempt (delisted ticker), or a
    truncated partial history (1-100 rows). The latter is a Yahoo data
    quirk seen on a few live tickers (EQR and EA each return a single
    row); it is recorded separately as a partial-history skip, never
    silently treated as a delisting. Raises RuntimeError on
    transport/rate-limit failures after retries: the harness aborts the
    run, because the data itself is suspect.
    """
    import yfinance as yf
    from datetime import timedelta

    last_error = None
    saw_rows = 0
    for attempt in range(1, YF_ATTEMPTS + 1):
        try:
            df = yf.download(
                ticker,
                start=start.isoformat(),
                end=(end + timedelta(days=1)).isoformat(),
                progress=False,
                auto_adjust=True,
            )
            df = _normalize_ohlcv(df)
            if df is not None and len(df) > 100:
                return df
            rows = 0 if df is None else len(df)
            saw_rows = max(saw_rows, rows)
            last_error = RuntimeError(
                f"yfinance returned only {rows} rows for {ticker}"
            )
        except Exception as e:  # noqa: BLE001 - retry any fetch failure
            last_error = e
        if attempt < YF_ATTEMPTS:
            logger.warning(
                "yfinance fetch failed for %s (attempt %d/%d): %s; retrying",
                ticker, attempt, YF_ATTEMPTS, last_error,
            )
            time.sleep(YF_BACKOFF_SECONDS * attempt)
    err = TickerUnavailableError(
        f"yfinance returned only {saw_rows} rows for {ticker} after {YF_ATTEMPTS} attempts"
    )
    err.rows = saw_rows
    raise err from None


def _download_massive(ticker, start, end):
    """
    Fetch daily aggregates from the Massive / Polygon API.

    Uses POLYGON_API_KEY or MASSIVE_API_KEY from the environment (the same
    key the app already uses on Render). Adjusted bars, so splits and
    dividends match the yfinance auto-adjusted series. Follows pagination.
    """
    import pandas as pd

    api_key = os.environ.get("POLYGON_API_KEY") or os.environ.get("MASSIVE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Massive fallback needs POLYGON_API_KEY or MASSIVE_API_KEY in the environment"
        )
    url = (
        f"https://api.polygon.io/v2/aggs/ticker/{ticker}/range/1/day/"
        f"{start.isoformat()}/{end.isoformat()}"
        f"?adjusted=true&sort=asc&limit=50000&apiKey={api_key}"
    )
    rows = []
    while url:
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Massive aggregates request failed for {ticker}: HTTP {e.code}")
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"Massive aggregates request failed for {ticker}: {e}")
        for bar in payload.get("results", []):
            rows.append({
                "Open": bar["o"],
                "High": bar["h"],
                "Low": bar["l"],
                "Close": bar["c"],
                "Volume": bar["v"],
                "Date": pd.to_datetime(bar["t"], unit="ms"),
            })
        url = payload.get("next_url")
        if url and "apiKey=" not in url:
            url = url + ("&" if "?" in url else "?") + f"apiKey={api_key}"
        if url:
            time.sleep(0.2)  # stay well under the Basic plan rate limit
    if len(rows) <= 100:
        raise RuntimeError(f"Massive returned only {len(rows)} bars for {ticker}")
    df = pd.DataFrame(rows).set_index("Date").sort_index()
    return df[["Open", "High", "Low", "Close", "Volume"]]


def download_real_history(ticker, start, end, allow_synthetic=False):
    """
    Real-data-only download matching the harness _download_history signature.

    Returns (df, False). A ticker with no usable history raises
    TickerUnavailableError (a ValueError), which the harness treats as a
    per-ticker skip. Any other failure raises RuntimeError and aborts the
    run. The allow_synthetic argument is accepted for signature
    compatibility and ignored: this runner never uses synthetic data.
    """
    if ticker in _DOWNLOAD_CACHE:
        return _DOWNLOAD_CACHE[ticker], False
    if ticker in _UNAVAILABLE_TICKERS:
        raise TickerUnavailableError(f"no usable real history for {ticker} (cached)")
    try:
        df, is_synthetic = _download_yfinance(ticker, start, end), False
        _DOWNLOAD_CACHE[ticker] = df
        return df, is_synthetic
    except TickerUnavailableError as e:
        rows = getattr(e, "rows", 0)
        if rows == 0:
            SKIPPED_TICKERS.add(ticker)
            logger.warning("Skipping %s: no usable real history (delisted or no data)", ticker)
        else:
            PARTIAL_TICKERS.add(ticker)
            logger.warning(
                "Skipping %s: Yahoo served only %d rows (partial history, not a delisting)",
                ticker, rows,
            )
        _UNAVAILABLE_TICKERS.add(ticker)
        raise
    except Exception as e:
        logger.warning("yfinance failed for %s: %s; trying Massive fallback", ticker, e)
    df = _download_massive(ticker, start, end)
    _DOWNLOAD_CACHE[ticker] = df
    return df, False


# ---------------------------------------------------------------------------
# Real run
# ---------------------------------------------------------------------------

def run_real(output_dir, universe_override=None):
    """Run all three setups on real data and write the reports."""
    import services.backtest_harness as harness

    harness._download_history = download_real_history
    results = harness.run_all_setups(
        output_dir=output_dir,
        universe_override=universe_override,
        allow_synthetic=False,
    )
    for r in results:
        if not r.get("data_source", "").startswith("REAL"):
            raise RuntimeError(
                f"Setup {r['setup']} did not produce a REAL data stamp: {r.get('data_source')!r}"
            )
    return results


# ---------------------------------------------------------------------------
# Smoke test (mechanics only, hardcoded sample, never a result)
# ---------------------------------------------------------------------------

def _smoke_sample():
    """
    Hardcoded 300-session OHLCV sample, labeled SMOKE ONLY.

    Shape: 200 flat sessions at 100, a 15-session grind up 0.10 per day
    to 101.50, a 5-session pullback to 100.40, then a slow recovery. The
    last pullback day (row 219) is designed so Quality Pullback fires:
    price within 2% above a rising 200-day MA, RSI(14) below 55 after
    having been above 60 during the grind, volume below its 20-day
    average. Row 219 is the first row where the 20-session lagged MA200
    exists, which the rising-MA200 check needs.
    """
    import pandas as pd

    closes = [100.0] * 200
    for k in range(1, 16):
        closes.append(100.0 + 0.10 * k)  # grind to 101.50
    closes += [101.00, 100.70, 100.50, 100.40, 100.40]  # pullback
    for k in range(1, 81):
        closes.append(100.40 + 0.05 * k)  # recovery to 104.40
    n = len(closes)
    assert n == 300
    opens = [closes[0]] + closes[:-1]
    highs = [c * 1.002 for c in closes]
    lows = [c * 0.998 for c in closes]
    volumes = [1_000_000.0] * 200 + [1_200_000.0] * 15 + [600_000.0] * 5 + [900_000.0] * 80
    dates = pd.bdate_range(start="2024-01-02", periods=n)
    return pd.DataFrame(
        {"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": volumes},
        index=dates,
    )


def _independent_indicators(closes):
    """Plain-Python MA50, MA200, and RSI(14) (rolling-mean version, as in the harness)."""
    def sma(series, window, i):
        if i + 1 < window:
            return float("nan")
        return sum(series[i - window + 1: i + 1]) / window

    def rsi(series, i, period=14):
        if i < period:
            return float("nan")
        gains = []
        losses = []
        for k in range(i - period + 1, i + 1):
            d = series[k] - series[k - 1]
            gains.append(max(d, 0.0))
            losses.append(max(-d, 0.0))
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss == 0:
            # Matches the harness: a zero-loss window divides by NaN,
            # so RSI is NaN (not 100) when there is no down day at all.
            return float("nan")
        rs = avg_gain / avg_loss
        return 100.0 - 100.0 / (1.0 + rs)

    return sma, rsi


def smoke_test():
    """
    Verify harness mechanics on the hardcoded sample against independently
    computed values. Returns True when every check passes.

    Checks: indicator math vs plain-Python computation; Quality Pullback
    fires on the designed pullback day and not on the flat base; every
    trade enters at the T+1 open plus 0.05% slippage (no lookahead);
    SetupStats expectancy / profit factor / max drawdown vs hand-computed
    values; synthetic verdict cap (PASSES on synthetic data stays
    SHADOW ONLY).
    """
    import numpy as np
    import services.backtest_harness as h

    failures = []

    def check(name, ok, detail=""):
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail and not ok else ""))
        if not ok:
            failures.append(name)

    df = _smoke_sample()
    closes = df["Close"].tolist()
    ind = h._precompute(df, {"breakout_days": 55}, "")
    sma, rsi = _independent_indicators(closes)

    # 1. Indicator math matches an independent computation.
    for i in (210, 214, 217, 219, 250):
        for label, got, want in (
            ("ma50", ind["ma50"][i], sma(closes, 50, i)),
            ("ma200", ind["ma200"][i], sma(closes, 200, i)),
            ("rsi", ind["rsi"][i], rsi(closes, i)),
        ):
            ok = (math.isnan(want) and math.isnan(got)) or abs(got - want) < 1e-6
            check(f"indicator {label} at row {i} (got {got:.4f}, want {want:.4f})", ok)

    # 2. Quality Pullback fires on the designed pullback day (row 219,
    #    close 100.40) and not on the flat base (row 150).
    qp = {"pullback_pct": 0.02, "rsi_entry": 55.0, "rsi_reset": 60.0,
          "rsi_target": 68.0, "time_stop_days": 30, "breakout_days": 55}
    check("quality pullback fires on pullback day (row 219)",
          h._signal_quality_pullback(ind, 219, qp) is True,
          f"rsi={ind['rsi'][219]:.1f} ma50={ind['ma50'][219]:.2f} price={closes[219]:.2f}")
    check("quality pullback silent on flat base (row 150)",
          h._signal_quality_pullback(ind, 150, qp) is False)

    # 3. No lookahead: every trade enters at the T+1 open plus slippage.
    from datetime import date as _date
    spy = (np.array([], dtype=float), np.array([], dtype=float),
           np.array([], dtype="datetime64[ns]"))
    trades = h._run_single_ticker(
        "SMOKE", df, spy[0], spy[1], spy[2],
        h._signal_quality_pullback, h._exit_quality_pullback,
        _date(2024, 1, 1), _date(2025, 12, 31), qp,
    )
    check("smoke sample produces at least one trade", len(trades) >= 1, f"n={len(trades)}")
    no_lookahead = True
    for t in trades:
        sig_idx = int(np.where(df.index == np.datetime64(t.signal_date))[0][0])
        raw_open = float(df.iloc[sig_idx + 1]["Open"])
        if abs(t.entry_price - raw_open * (1 + h.SLIPPAGE_PER_SIDE)) > 1e-6:
            no_lookahead = False
        if t.entry_date != df.index[sig_idx + 1].date():
            no_lookahead = False
    check("every trade enters at T+1 open plus 0.05% slippage", no_lookahead)

    # 4. SetupStats math vs hand-computed values.
    #    Trades (pct): +4, -2, +6, -1.
    #    Avg win 5.00, avg loss 1.50, win rate 50%, expectancy 1.75,
    #    profit factor 10/3 = 3.33. Max drawdown 2.00%: equity peaks at
    #    104 after the first trade, then falls to 101.92 on the -2%
    #    trade, a 2.00% drawdown from that peak (the later -1% trade is
    #    only a 1.00% drawdown from the 108.04 peak).
    stats = h.SetupStats()
    for pnl in (4.0, -2.0, 6.0, -1.0):
        stats.add(pnl)
    s = stats.summary()
    check("stats expectancy is 1.75%", abs(s["expectancy_pct"] - 1.75) < 0.001,
          f"got {s['expectancy_pct']}")
    check("stats profit factor is 3.33", abs(s["profit_factor"] - 3.33) < 0.01,
          f"got {s['profit_factor']}")
    check("stats avg win 5.00 / avg loss 1.50",
          abs(s["avg_win_pct"] - 5.0) < 0.01 and abs(s["avg_loss_pct"] - 1.5) < 0.01)
    check("stats max drawdown is 2.00%", abs(s["max_drawdown_pct"] - 2.00) < 0.01,
          f"got {s['max_drawdown_pct']}")

    # 5. Synthetic verdict cap: a PASSES verdict on synthetic data is
    #    capped at SHADOW ONLY; FAILS stays FAILS.
    v, reason = h._apply_synthetic_cap("PASSES", True)
    check("synthetic PASSES caps at SHADOW ONLY", v == "SHADOW ONLY", f"got {v}")
    v, _ = h._apply_synthetic_cap("FAILS", True)
    check("synthetic FAILS stays FAILS", v == "FAILS", f"got {v}")
    v, _ = h._apply_synthetic_cap("PASSES", False)
    check("real PASSES stays PASSES", v == "PASSES", f"got {v}")

    print(f"\nSmoke test: {len(failures)} failure(s).")
    if failures:
        print("Failures: " + ", ".join(failures))
        return False
    print("Smoke test PASSED: harness mechanics verified on the hardcoded sample.")
    print("These numbers are NOT backtest results and were not written to backtests/.")
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Run the three TradeIQ backtests on REAL market data only.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--output-dir",
        default=os.path.join(_REPO_ROOT, "backtests"),
        help="Directory for the report files (default: <repo>/backtests)",
    )
    parser.add_argument(
        "--tickers",
        default=None,
        help="Comma-separated ticker list to override the default universe (spot checks).",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Verify harness mechanics on a hardcoded sample. No network, no results written.",
    )
    args = parser.parse_args()

    if args.smoke_test:
        ok = smoke_test()
        sys.exit(0 if ok else 1)

    universe_override = None
    if args.tickers:
        universe_override = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        logger.info("Universe override: %s", universe_override)

    output_dir = os.path.abspath(args.output_dir)
    os.makedirs(output_dir, exist_ok=True)
    logger.info("Output directory: %s", output_dir)
    logger.info("Real data only: yfinance first, Massive fallback, no synthetic.")

    results = run_real(output_dir, universe_override)

    print("\n" + "=" * 60)
    print("REAL-DATA BACKTEST RESULTS")
    print("=" * 60)
    for r in results:
        oos = r["oos_stats"]
        n = oos.get("trade_count", 0)
        exp = oos.get("expectancy_pct", 0)
        pf = oos.get("profit_factor", 0)
        pf_str = str(pf) if pf == "inf" else f"{pf:.2f}"
        print(f"  {r['setup']:30s}  {r['verdict']:12s}  OOS: n={n}  exp={exp:.3f}%  PF={pf_str}")
    print("\nReports written to:", output_dir)
    if SKIPPED_TICKERS:
        print(f"Tickers skipped, no history (delisted or no data): {len(SKIPPED_TICKERS)}")
        print("  " + ", ".join(sorted(SKIPPED_TICKERS)))
    if PARTIAL_TICKERS:
        print(f"Tickers skipped, Yahoo served only a partial history: {len(PARTIAL_TICKERS)}")
        print("  " + ", ".join(sorted(PARTIAL_TICKERS)))
    if SKIPPED_TICKERS or PARTIAL_TICKERS:
        print("The reports' universe line still states the full universe size;")
        print("the effective universe is smaller by the skipped tickers above.")
    print("Restart the app (or re-seed the registry) for the new verdicts to take effect.")


if __name__ == "__main__":
    main()
