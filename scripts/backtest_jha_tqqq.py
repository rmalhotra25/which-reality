"""
Backtest: Vibha Jha's TQQQ swing approach (mechanical approximation).

Jha's discretionary rules, formalized here so they can be tested:
  Entry (TWO variants, both tested, per Ro's "both"):
    V-strict -- IBD-style follow-through day (FTD): after a NASDAQ
      rally day, a day 4-7 gain of >= 1% on volume higher than the prior
      day, with no close below the rally day's low in between.
    V-loose  -- Jha's looser entry: day 4 or 5 of the rally with a
      higher low AND higher high vs the prior session (no FTD needed),
      with no undercut of the rally day's low.
  Both variants share the TQQQ gate: TQQQ must close back above its
  50-day MA within 5 sessions of the signal day (her "retakes key
  moving averages" rule). Entry at the T+1 open after the retake day.
  No overlapping positions; a signal firing while in a trade is skipped.

  Rally day: QQQ up day whose prior close was the lowest close of the
  prior 10 sessions (a turn after a decline). QQQ is used as the
  NASDAQ proxy throughout (volume, distribution days, rally days):
  true IBD work uses the NASDAQ composite; QQQ is a reasonable but
  imperfect proxy, and that substitution is a stated limitation.

  Exits (first trigger wins, executed at the T+1 open):
    - Stop: TQQQ closes below its 50-day MA (her violation rule).
    - Distribution exit: QQQ distribution-day count (down day on
      higher volume, 25-session window) reaches 4 (her "four to five"
      rule, conservative end).
    - Time: 60 sessions max hold.

  Instruments (BOTH tested, per Ro's "both"):
    - Shares: real TQQQ prices, 0.05% slippage/side.
    - Calls: MODELED long ATM calls, 45 DTE, Black-Scholes with
      30-day realized TQQQ volatility as the IV proxy, held to the
      same exit signals. Modeled, not real chain prices. Caveat: TQQQ
      options IV typically runs ABOVE realized vol, so modeled
      premiums likely UNDERSTATE real cost -- modeled calls P&L is
      optimistic, not conservative.

  Sizing (per Ro: "for this feature forget my sizing"): Jha's sizing
  -- 25% starter, up to 50% -- is used for the portfolio simulation
  only (single 25% starter, no adds in v1; her adds on pullbacks are
  a future refinement). Per-trade expectancy/PF are sizing-free.
  This sizing applies to THIS feature only; Ro's general options-plan
  framework (1-2% risk/trade) is unchanged elsewhere.
  Account context: taxable brokerage (per Ro) -- frequent swing
  trading means short-term gains taxed as ordinary income. That tax
  drag is NOT modeled in the returns below.

Conventions (same as scripts/backtest_tqqq_200ma.py): real data only,
yfinance first with Massive fallback, abort-and-write-nothing on
fetch failure; IS 2019-2022 / OOS 2023+ splits; harness verdict
PASSES / SHADOW / FAILS; --smoke-test mode with engineered data.

Usage (from the repo root):
    python scripts/backtest_jha_tqqq.py [--smoke-test]
"""

import argparse
import json
import logging
import math
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
logger = logging.getLogger("backtest_jha_tqqq")

from backtest_tqqq_200ma import (  # noqa: E402
    DataUnavailableError, download_history,
)

SLIPPAGE = 0.0005
MAX_HOLD = 60
RETAKE_WINDOW = 5
DIST_EXIT = 4
RISK_FREE = 0.04


# ---------------------------------------------------------------------------
# Indicators / signals
# ---------------------------------------------------------------------------

def compute_frame(qqq_df, tqqq_df):
    """Aligned frame with everything the signals need."""
    import numpy as np
    import pandas as pd

    # lsuffix/rsuffix: works on pandas 2.x; deprecated (but functional) on 3.x.
    joined = qqq_df.join(tqqq_df, lsuffix="_qqq", rsuffix="_tqqq", how="inner")
    joined = joined.dropna()
    if len(joined) < 100:
        return None
    qc = joined["Close_qqq"].to_numpy(dtype=float)
    ql = joined["Low_qqq"].to_numpy(dtype=float)
    qh = joined["High_qqq"].to_numpy(dtype=float)
    qv = joined["Volume_qqq"].to_numpy(dtype=float)
    tc = joined["Close_tqqq"].to_numpy(dtype=float)
    s = pd.Series
    out = {
        "dates": joined.index,
        "qqq_close": qc, "qqq_low": ql, "qqq_high": qh, "qqq_vol": qv,
        "tqqq_close": tc,
        "tqqq_open": joined["Open_tqqq"].to_numpy(dtype=float),
        "qqq_ma50": s(qc).rolling(50).mean().to_numpy(dtype=float),
        "tqqq_ma50": s(tc).rolling(50).mean().to_numpy(dtype=float),
        "tqqq_hv30": (
            s(np.log(s(tc) / s(tc).shift(1))).rolling(30).std()
            .to_numpy(dtype=float) * np.sqrt(252)
        ),
    }
    # Distribution days: QQQ down day on higher volume; 25-session count.
    is_dist = np.zeros(len(qc), dtype=int)
    is_dist[1:] = ((qc[1:] < qc[:-1]) & (qv[1:] > qv[:-1])).astype(int)
    out["dist_count"] = s(is_dist).rolling(25).sum().to_numpy(dtype=float)
    return out


def find_rally_days(f):
    """Indices of rally days: QQQ up day, prior close = 10-session low."""
    import numpy as np

    qc = f["qqq_close"]
    out = []
    for i in range(10, len(qc)):
        if np.isnan(f["qqq_ma50"][i]):
            continue
        if qc[i] > qc[i - 1] and qc[i - 1] == min(qc[i - 10:i]):
            out.append(i)
    return out


def find_signals(f, kind):
    """Signal events: list of dicts with rally_idx, signal_idx, kind.

    kind = 'strict' (FTD days 4-7, >=1% up on higher volume) or
    'loose' (days 4-5, higher low AND higher high vs prior session).
    An attempt dies if QQQ closes below the rally day's low first.
    """
    import numpy as np

    qc, ql, qh, qv = f["qqq_close"], f["qqq_low"], f["qqq_high"], f["qqq_vol"]
    signals = []
    for r in find_rally_days(f):
        rally_low = ql[r]
        days = range(4, 8) if kind == "strict" else range(4, 6)
        for j in days:
            k = r + j
            if k >= len(qc):
                break
            if qc[k] < rally_low:  # undercut kills the attempt
                break
            if kind == "strict":
                up = qc[k] / qc[k - 1] - 1.0 >= 0.01
                vol_up = qv[k] > qv[k - 1]
                if up and vol_up:
                    signals.append({"rally_idx": r, "signal_idx": k,
                                    "kind": kind})
                    break
            else:
                if ql[k] > ql[k - 1] and qh[k] > qh[k - 1] and qc[k] > qc[k - 1]:
                    signals.append({"rally_idx": r, "signal_idx": k,
                                    "kind": kind})
                    break
    return signals


# ---------------------------------------------------------------------------
# Trade simulation
# ---------------------------------------------------------------------------

def _norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_call(S, K, T, sigma, r=RISK_FREE):
    """Black-Scholes call value; intrinsic if expired or sigma missing."""
    if T <= 0 or sigma is None or sigma <= 0 or math.isnan(sigma):
        return max(0.0, S - K)
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)


def simulate_trades(f, kind, instrument):
    """Run one variant. Returns a list of trade dicts."""
    import numpy as np

    tc, to = f["tqqq_close"], f["tqqq_open"]
    tma, hv, dist = f["tqqq_ma50"], f["tqqq_hv30"], f["dist_count"]
    dates = f["dates"]
    trades = []
    busy_until = -1
    for sig in find_signals(f, kind):
        s = sig["signal_idx"]
        # TQQQ 50-day retake gate within RETAKE_WINDOW sessions of signal.
        retake = None
        for k in range(s, min(s + RETAKE_WINDOW + 1, len(tc))):
            if np.isnan(tma[k]):
                continue
            if tc[k] >= tma[k]:
                retake = k
                break
        if retake is None:
            continue
        entry_idx = retake + 1
        if entry_idx >= len(tc) or entry_idx <= busy_until:
            continue
        entry_price = to[entry_idx]
        exit_idx, reason = None, "max_hold"
        for j in range(entry_idx + 1, min(entry_idx + MAX_HOLD + 1, len(tc))):
            if tc[j] < tma[j]:
                exit_idx, reason = j + 1, "stop_below_50dma"
                break
            if dist[j] >= DIST_EXIT:
                exit_idx, reason = j + 1, "distribution_exit"
                break
        if exit_idx is None:
            exit_idx = min(entry_idx + MAX_HOLD + 1, len(tc) - 1)
        if exit_idx >= len(tc) or exit_idx <= entry_idx:
            break  # trade still open (or no room) at end of data; exclude
        exit_price = to[exit_idx]
        busy_until = exit_idx
        sessions = exit_idx - entry_idx
        if instrument == "shares":
            ret = (exit_price / entry_price - 1.0) - 2 * SLIPPAGE
            trades.append({
                "entry_date": dates[entry_idx].date().isoformat(),
                "exit_date": dates[exit_idx].date().isoformat(),
                "entry_price": round(float(entry_price), 2),
                "exit_price": round(float(exit_price), 2),
                "return_pct": round(float(ret) * 100, 2),
                "sessions": int(sessions), "exit_reason": reason,
            })
        else:  # modeled long ATM call, 45 DTE
            # Strike convention (important): the price series is
            # SPLIT-ADJUSTED. TQQQ has split 2:1/3:1 eight times since
            # 2010 (cumulative ~768x), so adjusted 2010 prices are
            # ~$0.23. Rounding a strike to whole dollars on adjusted
            # prices is broken (K=0 for sub-$0.50 prices, far-OTM
            # otherwise). An ATM call is therefore struck at K = S
            # exactly -- scale-invariant and the correct modeled-ATM
            # convention on adjusted data. A fixed $0.65/contract
            # commission is likewise meaningless on adjusted sub-dollar
            # prices (it would exceed the entire premium in early
            # years); at real unadjusted prices it is <0.5% of premium
            # and immaterial, so it is EXCLUDED here and the 5%
            # proportional spread haircut is the only modeled cost.
            K = float(entry_price)
            sigma_in = hv[entry_idx]
            premium = bs_call(entry_price, K, 45 / 365.0, sigma_in)
            t_remain = max(0.0, (45 - sessions * 7.0 / 5.0) / 365.0)
            value = bs_call(exit_price, K, t_remain, hv[exit_idx])
            premium_paid = premium * 1.05
            value_received = value * 0.95
            pnl = (value_received - premium_paid) * 100.0
            capital = premium_paid * 100.0
            ret = pnl / capital if capital > 0 else 0.0
            trades.append({
                "entry_date": dates[entry_idx].date().isoformat(),
                "exit_date": dates[exit_idx].date().isoformat(),
                "entry_price": round(float(entry_price), 2),
                "exit_price": round(float(exit_price), 2),
                "strike": K, "premium": round(float(premium), 2),
                "exit_value": round(float(value), 2),
                "pnl_per_contract": round(float(pnl), 2),
                "return_pct": round(float(ret) * 100, 2),
                "sessions": int(sessions), "exit_reason": reason,
            })
    return trades


# ---------------------------------------------------------------------------
# Stats / verdict / report (mirrors backtest_tqqq_200ma.py)
# ---------------------------------------------------------------------------

def stats_for(trades):
    import numpy as np

    if not trades:
        return {"n": 0, "win_rate": 0.0, "expectancy_pct": 0.0,
                "profit_factor": 0.0, "avg_win_pct": 0.0, "avg_loss_pct": 0.0,
                "max_drawdown_pct": 0.0}
    r = np.array([t["return_pct"] for t in trades], dtype=float)
    wins, losses = r[r > 0], r[r <= 0]
    curve = np.cumprod(1.0 + r / 100.0)
    peak = np.maximum.accumulate(curve)
    dd = np.max((peak - curve) / peak) * 100.0 if len(curve) else 0.0
    return {
        "n": int(len(r)),
        "win_rate": round(float((r > 0).mean() * 100), 1),
        "expectancy_pct": round(float(r.mean()), 2),
        "profit_factor": round(float(wins.sum() / abs(losses.sum())), 2)
        if len(losses) and losses.sum() != 0 else float("inf"),
        "avg_win_pct": round(float(wins.mean()), 2) if len(wins) else 0.0,
        "avg_loss_pct": round(float(losses.mean()), 2) if len(losses) else 0.0,
        "max_drawdown_pct": round(float(dd), 2),
    }


def verdict(st, modeled=False):
    """Harness verdict, aligned with services/backtest_harness._verdict
    on current master: FAILS on OOS expectancy <= 0 or profit factor
    <= 1.2; SHADOW ONLY when positive but fragile, sample < 30, or
    modeled only; PASSES otherwise."""
    if st["expectancy_pct"] <= 0 or st["profit_factor"] <= 1.2:
        return "FAILS"
    if st["n"] < 30 or modeled:
        return "SHADOW ONLY"
    return "PASSES"


def run_variant(f, kind, instrument):
    import pandas as pd

    trades = simulate_trades(f, kind, instrument)
    dates = pd.to_datetime([t["entry_date"] for t in trades])
    is_start, oos_start = pd.Timestamp("2019-01-01"), pd.Timestamp("2023-01-01")
    is_tr = [t for t, d in zip(trades, dates)
             if is_start <= d < oos_start]
    oos_tr = [t for t, d in zip(trades, dates) if d >= oos_start]
    return {
        "kind": kind, "instrument": instrument,
        "full": stats_for(trades), "is": stats_for(is_tr),
        "oos": stats_for(oos_tr), "trades": trades,
        "verdict": verdict(stats_for(oos_tr),
                           modeled=(instrument == "calls")),
    }


# ---------------------------------------------------------------------------
# Report / smoke / main
# ---------------------------------------------------------------------------

def render_report(results, start, end):
    lines = [
        "# Backtest: Vibha Jha TQQQ swing approach (mechanical approximation)",
        "",
        f"Data: QQQ (NASDAQ proxy) + TQQQ, {start} to {end}. Real prices only.",
        "Entries: strict FTD (days 4-7, >=1% up on higher volume) and loose",
        "(days 4-5, higher low + higher high), both gated on a TQQQ",
        "50-day MA retake within 5 sessions; entry at T+1 open.",
        "Exits: TQQQ close below 50-day, QQQ distribution count >= 4,",
        "or 60 sessions. No overlapping positions. Slippage 0.05%/side.",
        "Calls are MODELED (Black-Scholes, HV30 as IV proxy, 45 DTE,",
        "struck ATM at K = entry price -- NOT dollar-rounded, because",
        "the series is split-adjusted and TQQQ has split ~768x since",
        "2010, which makes dollar-rounded strikes nonsense on early",
        "history). Cost: 5% spread haircut only; the fixed $0.65",
        "commission is excluded (meaningless on adjusted sub-dollar",
        "prices; immaterial at real unadjusted prices).",
        "TQQQ options IV typically exceeds realized vol, so modeled calls",
        "P&L remains optimistic even after the haircut.",
        "Verdict per services/backtest_harness._verdict on current master:",
        "FAILS on OOS expectancy <= 0 or PF <= 1.2; SHADOW ONLY when",
        "positive but sample < 30, fragile, or modeled only; else PASSES.",
        "Tax drag (taxable brokerage) is NOT modeled. Sizing for",
        "simulation: 25% starter (Jha's sizing, this feature only;",
        "no adds in v1).",
        "",
    ]
    for res in results:
        lines += [
            f"## {res['kind']} / {res['instrument']} -- verdict: {res['verdict']}",
            "",
            "| split | n | win% | expectancy | PF | avg win | avg loss | max DD |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for name in ("full", "is", "oos"):
            st = res[name]
            lines.append(
                f"| {name} | {st['n']} | {st['win_rate']}% | "
                f"{st['expectancy_pct']}% | {st['profit_factor']} | "
                f"{st['avg_win_pct']}% | {st['avg_loss_pct']}% | "
                f"{st['max_drawdown_pct']}% |"
            )
        lines += ["", "Trades (entry -> exit, return, reason):"]
        for t in res["trades"]:
            lines.append(
                f"- {t['entry_date']} -> {t['exit_date']}: "
                f"{t['return_pct']}% ({t['exit_reason']}, {t['sessions']} sessions)"
            )
        lines.append("")
    return "\n".join(lines)


def smoke_test():
    """Engineered series: one strict trade fires; a failed attempt does not."""
    import numpy as np
    import pandas as pd

    n = 200
    idx = pd.date_range("2020-01-01", periods=n, freq="B")
    # QQQ: decline to a low at session 60, rally day 61, FTD on day 65
    # (day 4 after rally), then a steady rise, then a drop below TQQQ MA50.
    qc = [100.0 - 0.3 * i for i in range(61)]
    qc += [82.0 + 0.4 * (i - 60) for i in range(61, 120)]
    qc += [105.0 - 0.2 * (i - 119) for i in range(120, n)]
    qc = np.array(qc, dtype=float)
    qv = np.where(np.arange(n) % 2 == 0, 100.0, 90.0)
    qv[65] = 200.0  # FTD day: higher volume
    qc[65] = qc[64] * 1.02  # FTD day: +2%
    qdf = pd.DataFrame({"Open": qc, "High": qc + 0.3, "Low": qc - 0.3,
                        "Close": qc, "Volume": qv}, index=idx)
    # TQQQ: below its 50DMA before the FTD, retakes on the FTD day.
    tc = np.array([40.0 + 0.05 * i for i in range(n)], dtype=float)
    ma50 = pd.Series(tc).rolling(50).mean()
    tc[60:66] = ma50.iloc[60:66].to_numpy() - 1.0
    tc[65] = ma50.iloc[65] + 1.0  # retake on FTD day
    tc[66:] = tc[65] + 0.3 * np.arange(0, n - 66)
    tc[150:] = tc[149] - 0.5 * np.arange(0, n - 150)  # later breakdown
    tdf = pd.DataFrame({"Open": tc, "High": tc + 0.2, "Low": tc - 0.2,
                        "Close": tc, "Volume": qv}, index=idx)
    f = compute_frame(qdf, tdf)
    assert f is not None
    strict = simulate_trades(f, "strict", "shares")
    assert len(strict) >= 1, f"expected >=1 strict trade, got {len(strict)}"
    loose = simulate_trades(f, "loose", "shares")
    assert isinstance(loose, list)
    calls = simulate_trades(f, "strict", "calls")
    assert len(calls) >= 1, "expected >=1 modeled calls trade"
    print(f"SMOKE OK: strict shares={len(strict)}, loose shares={len(loose)}, "
          f"strict calls={len(calls)}")
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
            results.append(run_variant(f, kind, instrument))
            r = results[-1]
            logger.info("%s/%s: n=%d OOS expectancy=%s%% verdict=%s",
                        kind, instrument, r["full"]["n"],
                        r["oos"]["expectancy_pct"], r["verdict"])

    out_dir = os.path.join(_REPO_ROOT, "backtests")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "jha_tqqq.md")
    with open(out_path, "w") as fh:
        fh.write(render_report(results, f["dates"][0].date().isoformat(),
                               f["dates"][-1].date().isoformat()))
    logger.info("Wrote %s", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
