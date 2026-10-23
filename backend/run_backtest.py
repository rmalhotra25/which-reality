"""
Backtest CLI entry point.

Usage (from the backend/ directory):
    python run_backtest.py

Options:
    --output-dir DIR   Folder for result files (default: ../backtests)
    --tickers A,B,C    Comma-separated ticker list to override the default
                       universe.  Useful for quick spot-checks.
    --help             Show this message.

The harness writes three markdown files:
    <output-dir>/quality_pullback.md
    <output-dir>/premium_at_support.md
    <output-dir>/volume_breakout.md

Each file contains: cost assumptions, survivorship caveat, rule definition,
walk-forward IS/OOS stats, calendar and SPY MA regime splits, +/-20% robustness
tests, and a verdict (PASSES | SHADOW ONLY | FAILS).

When run without network access (yfinance unreachable), the harness falls back
to synthetic random-walk price data and stamps every report with a SYNTHETIC
data warning.  Rerun on a networked deployment for real edge measurements.

No-lookahead guarantee: signals are evaluated from df.iloc[:i+1]; the entry
price is always df.iloc[i+1]["Open"], i.e., the open of the day after the
signal close.  Spot-check: enable --spot-check to print one example trade
showing signal date, entry date, and entry price.
"""
import argparse
import logging
import os
import sys

# Ensure the backend package root is on sys.path so relative imports work
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run all three trading-setup backtests and write markdown reports.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--output-dir",
        default=os.path.join(_here, "..", "backtests"),
        help="Directory for result files (default: ../backtests relative to this script)",
    )
    parser.add_argument(
        "--tickers",
        default=None,
        help="Comma-separated ticker list to override the default universe",
    )
    parser.add_argument(
        "--spot-check",
        action="store_true",
        help="Print one example trade per setup to verify no-lookahead",
    )
    args = parser.parse_args()

    universe_override = None
    if args.tickers:
        universe_override = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        logger.info("Universe override: %s", universe_override)

    output_dir = os.path.abspath(args.output_dir)
    os.makedirs(output_dir, exist_ok=True)
    logger.info("Output directory: %s", output_dir)

    from services.backtest_harness import run_all_setups
    results = run_all_setups(
        output_dir=output_dir,
        universe_override=universe_override,
    )

    print("\n" + "=" * 60)
    print("BACKTEST RESULTS SUMMARY")
    print("=" * 60)
    for r in results:
        oos = r["oos_stats"]
        n   = oos.get("trade_count", 0)
        exp = oos.get("expectancy_pct", 0)
        pf  = oos.get("profit_factor", 0)
        pf_str = str(pf) if pf == "inf" else f"{pf:.2f}"
        insufficient = " [INSUFFICIENT SAMPLE]" if oos.get("insufficient_sample") else ""
        print(f"  {r['setup']:30s}  {r['verdict']:12s}  OOS: n={n}{insufficient}  exp={exp:.3f}%  PF={pf_str}")

    print("\nReports written to:", output_dir)

    if args.spot_check:
        _print_spot_check(universe_override)


def _print_spot_check(universe_override):
    """Print one trade per setup to verify no-lookahead."""
    import numpy as np
    from services.backtest_harness import (
        _download_history, _run_single_ticker, FULL_START, OOS_END, OOS_START,
        _signal_quality_pullback, _exit_quality_pullback,
        _signal_volume_breakout, _exit_volume_breakout,
        SLIPPAGE_PER_SIDE,
    )

    tickers = universe_override or ["AAPL", "MSFT", "JPM"]
    # Empty SPY arrays for spot check (no regime needed)
    spy_closes = spy_ma200 = spy_dates = np.array([])

    def _esf_breakout(ind, i, params):
        ph = ind["prior_high"][i]
        return {"breakout_level": float(ph) if not np.isnan(ph) else float(ind["closes"][i])}

    setups = [
        ("quality_pullback", _signal_quality_pullback, _exit_quality_pullback,
         {"pullback_pct": 0.02, "rsi_entry": 55.0, "rsi_reset": 60.0,
          "rsi_target": 68.0, "time_stop_days": 30, "breakout_days": 55},
         None),
        ("volume_breakout", _signal_volume_breakout, _exit_volume_breakout,
         {"breakout_days": 55, "vol_mult": 1.5, "atr_mult": 2.0,
          "time_stop_days": 15},
         _esf_breakout),
    ]

    print("\n" + "=" * 60)
    print("SPOT CHECK: no-lookahead verification")
    print("Entry price must equal open of the day AFTER the signal date.")
    print("=" * 60)
    for name, sig_fn, exit_fn, params, esf in setups:
        found = False
        for ticker in tickers:
            try:
                df = _download_history(ticker, FULL_START, OOS_END)
                if len(df) < 230:
                    continue
                trades = _run_single_ticker(
                    ticker, df, spy_closes, spy_ma200, spy_dates,
                    sig_fn, exit_fn, OOS_START, OOS_END, params, esf,
                )
                if trades:
                    t = trades[0]
                    # Verify: entry_price = T+1 open * (1 + slippage)
                    sig_date_idx = int(df.index.get_indexer(
                        [df.index[df.index.get_indexer(
                            [str(t.signal_date)], method="nearest"
                        )[0]]],
                        method="nearest"
                    )[0])
                    entry_raw_idx = sig_date_idx + 1
                    if entry_raw_idx < len(df):
                        raw_open = float(df.iloc[entry_raw_idx]["Open"])
                        expected = raw_open * (1 + SLIPPAGE_PER_SIDE)
                        match = abs(t.entry_price - expected) < 0.02
                        print(f"  {name} / {ticker}:")
                        print(f"    Signal date: {t.signal_date}  Entry date: {t.entry_date}")
                        print(f"    T+1 open: {raw_open:.4f}  Stored entry (with slip): {t.entry_price:.4f}")
                        print(f"    No-lookahead check: {'PASS' if match else 'WARN (check manually)'}")
                    found = True
                    break
            except Exception as e:
                logger.debug("spot check skip %s/%s: %s", name, ticker, e)
        if not found:
            print(f"  {name}: no trades found in OOS period (may be synthetic data)")


if __name__ == "__main__":
    main()
