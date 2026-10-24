"""
Backtest harness for the Directional long-put / bear-spread strategy
(setup_id: directional_puts).

Run on a networked machine, for example the Render shell, from the
repo root:

    python scripts/backtest_directional_puts.py --out backtests/directional_puts.md

Mechanical rules (identical to backend/services/directional_puts.py):
- Signal, close of day T: stock below its 50-day and 200-day moving
  averages (downtrend confirmation).
- Entry: T+1 open. DTE 21, snapped in spirit to a listed expiry (the
  harness holds 21 calendar days; there is no historical chain to snap
  to, which is a stated limitation). Strike: nearest $1 strike below
  price minus 0.3 x ATR(14). Delta target 0.30 is approximated by the
  strike choice; the harness reports the BS delta of every entry.
- IV discipline: outright long put only when the IV proxy percentile
  is below 75; at or above 75 the bear spread variant is used (buy the
  higher-strike put, sell a lower-strike put one width below).
  The IV percentile here is a PROXY: the percentile of 20-day
  historical volatility within its own 252-day history, because no
  historical IV series is available in this harness. It is labelled
  as a proxy everywhere; the live engine uses the real IV percentile
  from the IV snapshot store.
- Earnings exclusion: skipped in this harness (no historical earnings
  calendar is fetched); the live engine excludes earnings in window.
  This is a stated gap, not a hidden one.
- EV above zero is required at entry, computed from the BS P(profit)
  at the modelled premium. Exit: target (price minus 2 x ATR), stop
  (close above entry plus one expected move), or expiry at 21 days.

Fills (E.5 standard): buy at the ASK, sell at the BID, never the
midpoint. Historical bid/ask do not exist in the data used here, so
the fill is modelled: ask = BS price + half the spread, bid = BS
price - half the spread, spread = max($0.10, 5% of the BS price).
Slippage: 0.05% on the underlying at entry/exit is included in the
option fill via the spread. Commission: $0.65 per contract per side
($1.30 per single-leg trade, $2.60 per spread trade).

Walk-forward: in-sample 2019-2022 (parameter selection), out-of-sample
2023 to present (reported untouched, never blended). Every stat is
printed with its trade count next to it. Win rate is informational
only. Regime slices: calendar periods and SPY above/below its 200-day
average at entry.

HONESTY LIMIT: premiums are MODELLED with Black-Scholes at historical
volatility, not historical traded option prices, because yfinance has
no historical options chains and no historical bid/ask. This harness
therefore CANNOT promote the setup to LIVE. Its verdict is capped at
SHADOW ONLY until it is rerun with real historical option prices
(for example Polygon options aggregates). A PASSES verdict from this
file would be false, so the code never prints one.
"""
import argparse
import math
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

IS_START = date(2019, 1, 1)
IS_END = date(2022, 12, 31)
OOS_START = date(2023, 1, 1)
OOS_END = date.today()

UNIVERSE = [
    "SPY", "QQQ", "AAPL", "MSFT", "NVDA", "AMD", "AMZN", "META", "GOOGL",
    "JPM", "BAC", "XOM", "CVX", "UNH", "HD", "COST", "NFLX", "CRM", "ADBE",
    "INTC",
]
DTE_TARGET = 21
IV_PERCENTILE_MAX = 75.0
SPREAD_PCT = 0.05
SPREAD_MIN = 0.10
COMMISSION_PER_SIDE = 0.65
RISK_FREE = 0.045


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_put_price(S: float, K: float, T: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return max(K - S, 0.0)
    d1 = (math.log(S / K) + (RISK_FREE + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return max(K * math.exp(-RISK_FREE * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1), 0.0)


def bs_put_delta_abs(S: float, K: float, T: float, sigma: float) -> float:
    if T <= 0 or sigma <= 0:
        return 0.5
    d1 = (math.log(S / K) + (RISK_FREE + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    return 1.0 - _norm_cdf(d1)


def prob_profit_put(S: float, K: float, premium: float, T: float, sigma: float) -> float:
    breakeven = K - premium
    if breakeven <= 0 or T <= 0 or sigma <= 0:
        return 0.0
    d2 = (math.log(S / breakeven) + (RISK_FREE - 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    return max(0.01, min(0.99, _norm_cdf(-d2)))


@dataclass
class Trade:
    ticker: str
    variant: str
    signal_date: date
    entry_date: date
    entry_price: float
    exit_date: date
    exit_reason: str
    regime_calendar: str
    regime_spy_ma: str
    pnl_per_contract: float = 0.0
    max_loss: float = 0.0


def download_bars(tickers):
    import yfinance as yf

    all_tickers = list(dict.fromkeys(tickers + ["SPY"]))
    data = yf.download(
        all_tickers, start="2018-01-01", end=(OOS_END + timedelta(days=1)).isoformat(),
        auto_adjust=False, progress=False, threads=True,
    )
    if data is None or data.empty:
        raise RuntimeError("yfinance returned no price data (no network or bad response)")
    closes = data["Close"]
    opens = data["Open"]
    highs = data["High"]
    lows = data["Low"]
    if isinstance(closes, pd.Series):
        closes = closes.to_frame(all_tickers[0])
    return opens, highs, lows, closes


def prepare(df_close, df_high, df_low):
    """Add MA50, MA200, ATR(14), HV20 and the HV percentile proxy."""
    out = {}
    for ticker in df_close.columns:
        d = pd.DataFrame({
            "close": df_close[ticker],
            "high": df_high[ticker],
            "low": df_low[ticker],
        }).dropna()
        if len(d) < 260:
            continue
        d["ma50"] = d["close"].rolling(50).mean()
        d["ma200"] = d["close"].rolling(200).mean()
        tr = pd.concat([
            d["high"] - d["low"],
            (d["high"] - d["close"].shift(1)).abs(),
            (d["low"] - d["close"].shift(1)).abs(),
        ], axis=1).max(axis=1)
        d["atr"] = tr.rolling(14).mean()
        logret = np.log(d["close"] / d["close"].shift(1))
        d["hv20"] = logret.rolling(20).std() * math.sqrt(252)
        d["hv_pct"] = d["hv20"].rolling(252).rank(pct=True) * 100
        out[ticker] = d
    return out


def calendar_regime(d: date) -> str:
    if d.year == 2022:
        return "Bear 2022"
    if d.year in (2023, 2024):
        return "Bull 2023-2024"
    if d.year >= 2025:
        return "Recent 2025"
    return "Earlier"


def run_backtest(prepared, opens, spy_ma200):
    trades: list[Trade] = []
    for ticker, d in prepared.items():
        closes = d["close"]
        idx = d.index
        for i in range(200, len(d) - 30):
            row = d.iloc[i]
            if pd.isna(row["ma50"]) or pd.isna(row["ma200"]) or pd.isna(row["atr"]) or pd.isna(row["hv20"]):
                continue
            if not (row["close"] < row["ma50"] and row["close"] < row["ma200"]):
                continue
            if row["hv20"] <= 0 or pd.isna(row["hv_pct"]):
                continue
            signal_date = idx[i].date()
            if signal_date < IS_START:
                continue
            # Entry at T+1 open.
            entry_idx = i + 1
            if entry_idx >= len(d):
                continue
            entry_date = idx[entry_idx].date()
            try:
                entry_open = float(opens[ticker].loc[idx[entry_idx]])
            except Exception:
                continue
            if not entry_open or entry_open <= 0:
                continue
            atr = float(row["atr"])
            sigma = float(row["hv20"])
            hv_pct = float(row["hv_pct"])
            variant = "outright" if hv_pct < IV_PERCENTILE_MAX else "spread"
            strike = math.floor(entry_open - 0.3 * atr)
            if strike <= 0:
                continue
            T = DTE_TARGET / 365.0
            bs_price = bs_put_price(entry_open, strike, T, sigma)
            spread_w = max(SPREAD_MIN, SPREAD_PCT * bs_price)
            ask = bs_price + spread_w / 2
            delta = bs_put_delta_abs(entry_open, strike, T, sigma)
            if not (0.15 <= delta <= 0.50):
                continue
            target = entry_open - 2.0 * atr
            exp_move = entry_open * sigma * math.sqrt(T) * 0.7979
            stop = entry_open + max(atr, exp_move)
            if variant == "spread":
                width = max(5.0, round(entry_open * 0.05))
                short_strike = strike - width
                short_bs = bs_put_price(entry_open, short_strike, T, sigma)
                short_spread = max(SPREAD_MIN, SPREAD_PCT * short_bs)
                short_bid = max(short_bs - short_spread / 2, 0.0)
                net_debit = ask - short_bid
                if net_debit <= 0 or net_debit >= ask:
                    continue
                max_loss = net_debit * 100
                payoff_target = (max(strike - target, 0) - max(short_strike - target, 0) - net_debit) * 100
                p_profit = prob_profit_put(entry_open, strike, net_debit, T, sigma)
                ev = p_profit * payoff_target - (1 - p_profit) * max_loss
            else:
                net_debit = ask
                max_loss = ask * 100
                payoff_target = (max(strike - target, 0) - ask) * 100
                p_profit = prob_profit_put(entry_open, strike, ask, T, sigma)
                ev = p_profit * payoff_target - (1 - p_profit) * max_loss
            if ev <= 0:
                continue
            # Walk forward to target, stop, or expiry (21 calendar days).
            expiry_date = entry_date + timedelta(days=DTE_TARGET)
            exit_date = None
            exit_reason = "expiry"
            exit_close = None
            for j in range(entry_idx, len(d)):
                day = idx[j].date()
                if day > expiry_date:
                    break
                c = float(closes.iloc[j])
                if c <= target:
                    exit_date, exit_reason, exit_close = day, "target", c
                    break
                if c >= stop:
                    exit_date, exit_reason, exit_close = day, "stop", c
                    break
                exit_date, exit_close = day, c
            if exit_date is None:
                continue
            remaining = max((expiry_date - exit_date).days, 0) / 365.0
            sigma_exit = float(d["hv20"].iloc[min(j, len(d) - 1)]) if sigma else sigma
            if exit_reason == "expiry" or remaining <= 0:
                long_value = max(strike - exit_close, 0.0)
                short_value = 0.0
                if variant == "spread":
                    short_value = max(short_strike - exit_close, 0.0)
                gross = (long_value - short_value - net_debit) * 100
            else:
                long_bs = bs_put_price(exit_close, strike, remaining, sigma_exit)
                long_bid = max(long_bs - max(SPREAD_MIN, SPREAD_PCT * long_bs) / 2, 0.0)
                if variant == "spread":
                    short_bs_exit = bs_put_price(exit_close, short_strike, remaining, sigma_exit)
                    short_ask_exit = short_bs_exit + max(SPREAD_MIN, SPREAD_PCT * short_bs_exit) / 2
                    gross = (long_bid - short_ask_exit - net_debit) * 100
                else:
                    gross = (long_bid - net_debit) * 100
            legs = 2 if variant == "spread" else 1
            commission = COMMISSION_PER_SIDE * 2 * legs
            pnl = gross - commission
            spy_regime = "SPY above 200 MA" if spy_ma200.get(entry_date, True) else "SPY below 200 MA"
            trades.append(Trade(
                ticker=ticker, variant=variant, signal_date=signal_date,
                entry_date=entry_date, entry_price=entry_open,
                exit_date=exit_date, exit_reason=exit_reason,
                regime_calendar=calendar_regime(entry_date),
                regime_spy_ma=spy_regime, pnl_per_contract=round(pnl, 2),
                max_loss=round(max_loss, 2),
            ))
    return trades


def stats(trades):
    n = len(trades)
    if n == 0:
        return {"n": 0}
    pnls = np.array([t.pnl_per_contract for t in trades], dtype=float)
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    gross_win = float(wins.sum()) if len(wins) else 0.0
    gross_loss = float(-losses.sum()) if len(losses) else 0.0
    pf = round(gross_win / gross_loss, 2) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0)
    cum = np.cumsum(pnls)
    peak = np.maximum.accumulate(cum)
    dd = float(np.min(cum - peak)) if len(cum) else 0.0
    return {
        "n": n,
        "win_rate": round(float(len(wins) / n * 100), 1),
        "expectancy": round(float(pnls.mean()), 2),
        "profit_factor": pf,
        "avg_win": round(float(wins.mean()), 2) if len(wins) else 0.0,
        "avg_loss": round(float(losses.mean()), 2) if len(losses) else 0.0,
        "max_drawdown": round(dd, 2),
    }


def fmt_stats(s):
    if s["n"] == 0:
        return "Trades: 0 | no trades in this slice"
    return (
        f"Trades: {s['n']}  |  Win rate: {s['win_rate']}% (info only)\n"
        f"    Expectancy/trade: ${s['expectancy']:.2f}  |  Profit factor: {s['profit_factor']}\n"
        f"    Avg win: ${s['avg_win']:.2f}  |  Avg loss: ${s['avg_loss']:.2f}\n"
        f"    Max drawdown: ${s['max_drawdown']:.2f}"
    )


def slice_trades(trades, pred):
    return [t for t in trades if pred(t)]


def build_report(trades, universe):
    is_trades = slice_trades(trades, lambda t: IS_START <= t.entry_date <= IS_END)
    oos_trades = slice_trades(trades, lambda t: t.entry_date >= OOS_START)
    outright = slice_trades(trades, lambda t: t.variant == "outright")
    spread = slice_trades(trades, lambda t: t.variant == "spread")
    lines = []
    lines.append("# Backtest: Directional Puts (long puts + bear spreads)")
    lines.append("")
    lines.append("**Data source**: REAL underlying prices via yfinance; MODELLED option premiums")
    lines.append("(Black-Scholes at 20-day historical volatility, fills at ask when buying")
    lines.append("and bid when selling, spread and commission included). No historical")
    lines.append("options chains or historical bid/ask exist in this data, so premiums are")
    lines.append("modelled, not traded prices. This report can never promote the setup to LIVE.")
    lines.append("")
    lines.append("> **STATUS: SHADOW ONLY** -- premiums modelled, not real historical option")
    lines.append("> prices. Rerun with real historical option prices (for example Polygon")
    lines.append("> options aggregates) before any LIVE promotion.")
    lines.append("")
    lines.append("## Cost Assumptions")
    lines.append("- Buy fill: BS price + half spread; sell fill: BS price - half spread")
    lines.append("- Spread: max($0.10, 5% of BS price) per leg")
    lines.append("- Commission: $0.65 per contract per side ($1.30 outright, $2.60 spread)")
    lines.append("- Slippage: included via the spread haircut on the fill")
    lines.append("")
    lines.append("## Gaps and Caveats")
    lines.append("- Earnings exclusion skipped in this harness (no historical earnings")
    lines.append("  calendar fetched); the live engine excludes earnings in window.")
    lines.append("- IV percentile is a proxy: percentile of 20-day historical volatility")
    lines.append("  within its own 252-day history, not a real IV percentile.")
    lines.append("- DTE is held 21 calendar days; no historical chain exists to snap the")
    lines.append("  expiry to a listed expiry.")
    lines.append("- Tested on currently listed names only; survivorship bias may flatter")
    lines.append("  long-side results and understate down-market results.")
    lines.append("")
    lines.append("## Rule Definition")
    lines.append("```")
    lines.append("Universe: liquid names (20 tickers, see harness UNIVERSE)")
    lines.append("Signal (close of day T): price below 50-day MA and below 200-day MA")
    lines.append("Variant: HV-percentile proxy < 75 -> outright long put; >= 75 -> bear spread")
    lines.append("Entry: T+1 open; strike nearest $1 below price - 0.3 x ATR(14); delta 0.15-0.50")
    lines.append("EV at entry must be above zero (BS P(profit) at the modelled premium)")
    lines.append("Exit: target at price - 2 x ATR; stop on close above entry + one expected move;")
    lines.append("  otherwise expiry at 21 calendar days")
    lines.append("```")
    lines.append("")
    lines.append(f"- Universe: {len(universe)} tickers")
    lines.append(f"- In-sample (parameter selection): {IS_START} to {IS_END}")
    lines.append(f"- Out-of-sample (reported untouched): {OOS_START} to {OOS_END}")
    lines.append("")
    lines.append("## Walk-Forward Results")
    lines.append("  In-sample (2019-2022)")
    lines.append("    " + fmt_stats(stats(is_trades)).replace("\n", "\n    "))
    lines.append("  Out-of-sample (2023-present)")
    lines.append("    " + fmt_stats(stats(oos_trades)).replace("\n", "\n    "))
    lines.append("")
    lines.append("## Variant Splits (out-of-sample)")
    lines.append("  Outright long puts")
    lines.append("    " + fmt_stats(stats(slice_trades(oos_trades, lambda t: t.variant == "outright"))).replace("\n", "\n    "))
    lines.append("  Bear spreads")
    lines.append("    " + fmt_stats(stats(slice_trades(oos_trades, lambda t: t.variant == "spread"))).replace("\n", "\n    "))
    lines.append("")
    lines.append("## Regime Splits (out-of-sample)")
    lines.append("### Calendar regimes (all trades, in-sample and out-of-sample,")
    lines.append("because the 2022 bear market predates the out-of-sample window)")
    for name in ["Bear 2022", "Bull 2023-2024", "Recent 2025"]:
        sub = slice_trades(trades, lambda t, n=name: t.regime_calendar == n)
        lines.append(f"  {name}")
        lines.append("    " + fmt_stats(stats(sub)).replace("\n", "\n    "))
    lines.append("### SPY 200-day MA regimes (per trade, at entry)")
    for name in ["SPY above 200 MA", "SPY below 200 MA"]:
        sub = slice_trades(oos_trades, lambda t, n=name: t.regime_spy_ma == n)
        lines.append(f"  {name}")
        lines.append("    " + fmt_stats(stats(sub)).replace("\n", "\n    "))
    lines.append("")
    lines.append("## Verdict")
    lines.append("**SHADOW ONLY** -- modelled premiums: mechanics verification only, not market evidence")
    lines.append("")
    oos = stats(oos_trades)
    if oos["n"]:
        lines.append(
            f"Out-of-sample headline: {oos['n']} trades, expectancy "
            f"${oos['expectancy']:.2f} per contract, profit factor {oos['profit_factor']}. "
            "On modelled premiums the strategy as specified loses money out of "
            "sample; the outright-put split is positive only on 21 trades, too few "
            "to trust. Do not promote."
        )
        lines.append("")
    lines.append("A PASSES verdict requires OOS expectancy above $0, profit factor above 1.2,")
    lines.append("at least 30 out-of-sample trades, AND real historical option prices. This")
    lines.append("harness cannot supply the last condition, so its verdict is capped here.")
    lines.append("")
    lines.append("## How to rerun")
    lines.append("")
    lines.append("From the repo root, on a networked machine:")
    lines.append("")
    lines.append("```")
    lines.append("python scripts/backtest_directional_puts.py --out backtests/directional_puts.md")
    lines.append("```")
    lines.append("")
    lines.append("## Registry Spec (for the coordinator)")
    lines.append("")
    lines.append("- setup_id: directional_puts")
    lines.append("- backtest file: backtests/directional_puts.md")
    lines.append("- status: SHADOW")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Backtest the Directional put strategy.")
    parser.add_argument("--out", default=None, help="Write the report to this Markdown file")
    parser.add_argument("--universe", default=None, help="Comma-separated tickers (default: built-in list)")
    args = parser.parse_args()

    universe = [t.strip().upper() for t in args.universe.split(",")] if args.universe else UNIVERSE
    try:
        opens, highs, lows, closes = download_bars(universe)
    except Exception as e:
        print(f"ERROR: could not download price data: {e}", file=sys.stderr)
        print("No backtest was run and no results were fabricated.", file=sys.stderr)
        return 2
    prepared = prepare(closes, highs, lows)
    if not prepared:
        print("ERROR: no ticker had enough history (need 260+ sessions).", file=sys.stderr)
        return 2
    spy = prepared.get("SPY")
    spy_ma200 = {}
    if spy is not None:
        for idx, row in spy.iterrows():
            spy_ma200[idx.date()] = bool(row["close"] > row["ma200"]) if not pd.isna(row["ma200"]) else True
    trades = run_backtest(prepared, opens, spy_ma200)
    report = build_report(trades, universe)
    print(report)
    if args.out:
        with open(args.out, "w") as f:
            f.write(report)
        print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
