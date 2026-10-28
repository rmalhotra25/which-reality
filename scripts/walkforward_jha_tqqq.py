"""
Walk-forward check: Vibha Jha TQQQ swing approach, frozen rules.

Design note (read this before interpreting results): the Jha
formalization in scripts/backtest_jha_tqqq.py has NO tunable
parameters -- the 50-day retake gate, 4-distribution exit, 60-day cap,
and 1% FTD threshold are fixed rules, not fitted values. A classic
walk-forward re-tunes parameters per window; there is nothing to
re-tune here. So this script does the honest equivalent for frozen
rules: it segments the already-generated trades (which use no
lookahead -- all indicators are trailing, all actions at T+1 open)
into 2-year entry windows and asks whether the frozen rule set wins
consistently across regimes, instead of once on a single IS/OOS split.

Windows: 2010-2014 (pre-window baseline), then 2-year buckets
2015-2016 through 2025-2026 (the last bucket is partial, through the
latest close in the data). A setup that is real should be positive in
most buckets with n >= 5, not carried by one bucket or one trade.

Robustness footnotes included per variant:
  - expectancy with the single best trade removed;
  - count of buckets with n >= 5 that are positive.

Conventions (same as scripts/backtest_jha_tqqq.py): real data only,
yfinance first with Massive fallback, abort-and-write-nothing on
fetch failure; --smoke-test mode with a synthetic trade list.

Usage (from the repo root):
    python scripts/walkforward_jha_tqqq.py [--smoke-test]
"""

import argparse
import logging
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.normpath(os.path.join(_HERE, ".."))
for _p in (_HERE, _REPO_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("walkforward_jha_tqqq")

from backtest_jha_tqqq import (  # noqa: E402
    DataUnavailableError, compute_frame, download_history, simulate_trades,
    stats_for,
)

WINDOWS = [(2010, 2014), (2015, 2016), (2017, 2018), (2019, 2020),
           (2021, 2022), (2023, 2024), (2025, 2026)]


def bucket_trades(trades):
    """Group trades by entry year into WINDOWS. Returns {label: [trades]}."""
    out = {}
    for y0, y1 in WINDOWS:
        label = f"{y0}-{y1}"
        out[label] = [t for t in trades if y0 <= int(t["entry_date"][:4]) <= y1]
    return out


def analyze_variant(f, kind, instrument):
    trades = simulate_trades(f, kind, instrument)
    buckets = bucket_trades(trades)
    bucket_stats = {label: stats_for(ts) for label, ts in buckets.items()}
    full = stats_for(trades)
    best_removed = None
    if trades:
        best = max(trades, key=lambda t: t["return_pct"])
        best_removed = stats_for([t for t in trades if t is not best])
    solid = [label for label, st in bucket_stats.items()
             if st["n"] >= 5 and st["expectancy_pct"] > 0]
    return {
        "kind": kind, "instrument": instrument, "trades": trades,
        "buckets": bucket_stats, "full": full,
        "best_removed_expectancy": (
            best_removed["expectancy_pct"] if best_removed else 0.0),
        "positive_buckets": solid,
        "n_buckets_with_data": sum(
            1 for st in bucket_stats.values() if st["n"] >= 5),
    }


def render_report(results, start, end):
    lines = [
        "# Walk-forward: Jha TQQQ swing approach (frozen rules)",
        "",
        f"Data: QQQ (NASDAQ proxy) + TQQQ, {start} to {end}. Real prices only.",
        "Rules frozen from scripts/backtest_jha_tqqq.py -- no per-window",
        "tuning. Trades segmented by entry year into 2-year windows",
        "(2010-2014 baseline, then 2015-2016 ... 2025-2026 partial).",
        "Read the buckets, not just the full row: a real setup wins in",
        "most buckets, not one.",
        "",
    ]
    for res in results:
        lines += [
            f"## {res['kind']} / {res['instrument']}",
            "",
            "| window | n | win% | expectancy | PF | max DD |",
            "|---|---|---|---|---|---|",
        ]
        for label, st in res["buckets"].items():
            lines.append(
                f"| {label} | {st['n']} | {st['win_rate']}% | "
                f"{st['expectancy_pct']}% | {st['profit_factor']} | "
                f"{st['max_drawdown_pct']}% |"
            )
        f = res["full"]
        lines += [
            f"| FULL | {f['n']} | {f['win_rate']}% | {f['expectancy_pct']}% | "
            f"{f['profit_factor']} | {f['max_drawdown_pct']}% |",
            "",
            f"Positive buckets (n >= 5): {len(res['positive_buckets'])} of "
            f"{res['n_buckets_with_data']} -- {res['positive_buckets']}",
            f"Expectancy with best trade removed: "
            f"{res['best_removed_expectancy']}%",
            "",
        ]
    return "\n".join(lines)


def smoke_test():
    """Bucketing math on a synthetic trade list."""
    trades = [
        {"entry_date": "2015-03-02", "return_pct": 2.0},
        {"entry_date": "2016-06-01", "return_pct": -1.0},
        {"entry_date": "2021-04-05", "return_pct": 3.0},
        {"entry_date": "2023-01-03", "return_pct": -2.0},
    ]
    buckets = bucket_trades(trades)
    assert len(buckets["2015-2016"]) == 2, buckets["2015-2016"]
    assert len(buckets["2021-2022"]) == 1
    assert len(buckets["2023-2024"]) == 1
    assert len(buckets["2017-2018"]) == 0
    st = stats_for(buckets["2015-2016"])
    assert st["n"] == 2 and st["expectancy_pct"] == 0.5, st
    print("SMOKE OK: bucketing correct (2015-2016 n=2, expectancy 0.5%)")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args()
    if args.smoke_test:
        smoke_test()
        return 0

    try:
        qqq = download_history("QQQ", "2010-01-01")
        tqqq = download_history("TQQQ", "2010-01-01")
    except DataUnavailableError as e:
        logger.error("ABORTED, wrote nothing: %s", e)
        return 1

    f = compute_frame(qqq, tqqq)
    if f is None:
        logger.error("ABORTED: not enough history")
        return 1

    results = []
    for kind in ("strict", "loose"):
        for instrument in ("shares", "calls"):
            res = analyze_variant(f, kind, instrument)
            results.append(res)
            logger.info(
                "%s/%s: positive buckets %d/%d, best-removed expectancy %s%%",
                kind, instrument, len(res["positive_buckets"]),
                res["n_buckets_with_data"], res["best_removed_expectancy"])

    out_dir = os.path.join(_REPO_ROOT, "backtests")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "jha_tqqq_walkforward.md")
    with open(out_path, "w") as fh:
        fh.write(render_report(results, f["dates"][0].date().isoformat(),
                               f["dates"][-1].date().isoformat()))
    logger.info("Wrote %s", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
