"""
Check the TQQQ call window (QQQ 200DMA touch) and print the alert.

This is an ALERT runner, not a trade executor. It prints a window state
(OPEN / INVALIDATED / EXPIRED / NO_SIGNAL) with levels, invalidation,
and the backtest record. It places no orders and writes no files.

Data policy (same as scripts/backtest_tqqq_200ma.py): real data only,
yfinance first with Massive/Polygon fallback, no synthetic fallback. If
real data cannot be fetched, the run aborts with a clear error.

Usage (from the repo root):

    python scripts/check_tqqq_200ma_alert.py [--window 5]
    python scripts/check_tqqq_200ma_alert.py --smoke-test   # no network

Timing: the signal needs the day-T CLOSE, so run this after the close
(e.g. the 17:30 ET post-close alert job, or a 17:35 ET weekday cron).
An intraday dip below the line is not an alert until the close holds.

Wiring notes for TradeIQ (current master):
  - Manual: run after the close and read the printed state.
  - Cron: weekdays 17:35 ET, e.g. via the existing scheduler, calling
    this script and routing stdout to the alert channel.
  - Engine integration (later, and non-trivial): the app now enforces
    a P1 alert contract (services/alert_contract.py) and a rule
    registry (models/rule_registry.py) -- a rule not in the registry
    cannot fire, and an alert missing entry/size/expiry/reason is
    suppressed at build time. This window alert carries none of those
    by design, so engine wiring requires reframing it as a trade
    (concrete entry, stop-derived size, expiry) plus a RuleRegistry
    row. Until then, keep it as a standalone runner.
"""

import argparse
import json
import logging
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.normpath(os.path.join(_HERE, ".."))
_BACKEND = os.path.join(_REPO_ROOT, "backend")
for _p in (_BACKEND, _HERE, _REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("check_tqqq_200ma_alert")


def _print_result(result):
    print(json.dumps(result, indent=2, default=str))
    print()
    state = result.get("state")
    if state == "OPEN":
        print(f"ALERT: {result['action_summary']}")
        print(f"  QQQ close: ${result['qqq_close']}  |  200DMA: "
              f"${result['qqq_200dma']}  |  TQQQ close: ${result['tqqq_close']}")
        print(f"  {result['invalidation_text']}")
        print(f"  Structure: {result['structure_template']}")
        print(f"  Evidence: {result['backtest_note']}")
    else:
        print(f"State: {state} -- {result.get('detail', '')}")
        if result.get("last_signal_date"):
            print(f"  Last signal: {result['last_signal_date']}")


def smoke_test():
    """Engineered series: OPEN / INVALIDATED / EXPIRED / NO_SIGNAL."""
    import pandas as pd

    from services.tqqq_200ma_alert import evaluate

    def base_series(n=270):
        closes = [100.0 + 0.1 * i for i in range(n)]
        idx = pd.date_range("2020-01-01", periods=n, freq="B")
        return closes, idx

    def to_df(closes, lows, idx):
        qqq = pd.DataFrame(
            {"Open": closes, "High": [c + 0.5 for c in closes],
             "Low": lows, "Close": closes}, index=idx)
        tqqq = pd.DataFrame(
            {"Open": [c * 0.5 for c in closes],
             "High": [c * 0.5 + 0.25 for c in closes],
             "Low": [c * 0.5 - 0.25 for c in closes],
             "Close": [c * 0.5 for c in closes]}, index=idx)
        return qqq, tqqq

    # NO_SIGNAL: steady rise, price never touches the trailing 200DMA.
    closes, idx = base_series()
    lows = [c - 0.5 for c in closes]
    q, t = to_df(closes, lows, idx)
    assert evaluate(q, t)["state"] == "NO_SIGNAL", "expected NO_SIGNAL"

    # OPEN: touch 4 sessions before the end, no close below since.
    closes, idx = base_series()
    ma = pd.Series(closes).rolling(200).mean()
    touch = 265
    closes[touch] = float(ma.iloc[touch]) + 1.0
    lows = [c - 0.5 for c in closes]
    lows[touch] = float(ma.iloc[touch]) - 1.0
    q, t = to_df(closes, lows, idx)
    r = evaluate(q, t)
    assert r["state"] == "OPEN", f"expected OPEN, got {r['state']}"

    # INVALIDATED: touch, then a close below the 200DMA two days later.
    closes, idx = base_series()
    ma = pd.Series(closes).rolling(200).mean()
    closes[touch] = float(ma.iloc[touch]) + 1.0
    lows = [c - 0.5 for c in closes]
    lows[touch] = float(ma.iloc[touch]) - 1.0
    closes[touch + 2] = float(ma.iloc[touch + 2]) - 2.0
    q, t = to_df(closes, lows, idx)
    r = evaluate(q, t)
    assert r["state"] == "INVALIDATED", f"expected INVALIDATED, got {r['state']}"

    # EXPIRED: touch 19 sessions before the end, no invalidation.
    closes, idx = base_series()
    ma = pd.Series(closes).rolling(200).mean()
    old_touch = 251
    closes[old_touch] = float(ma.iloc[old_touch]) + 1.0
    lows = [c - 0.5 for c in closes]
    lows[old_touch] = float(ma.iloc[old_touch]) - 1.0
    q, t = to_df(closes, lows, idx)
    r = evaluate(q, t)
    assert r["state"] == "EXPIRED", f"expected EXPIRED, got {r['state']}"

    print("SMOKE OK: NO_SIGNAL / OPEN / INVALIDATED / EXPIRED all correct")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--window", type=int, default=5)
    args = parser.parse_args()
    if args.smoke_test:
        smoke_test()
        return 0

    import backtest_tqqq_200ma as bt

    try:
        qqq = bt.download_history("QQQ", "2010-01-01")
        tqqq = bt.download_history("TQQQ", "2010-01-01")
    except bt.DataUnavailableError as e:
        logger.error("ABORTED, no alert produced: %s", e)
        return 1

    from services.tqqq_200ma_alert import evaluate

    result = evaluate(qqq, tqqq, window_sessions=args.window)
    if result is None:
        logger.error("ABORTED: not enough history to compute a 200DMA")
        return 1
    _print_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
