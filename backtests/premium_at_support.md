# Backtest: Premium at Support (Wheel)
Generated: 2026-10-26
**Data source**: REAL (fetched 2026-10-26)

## Cost Assumptions
- Slippage: 0.05% per side (applied to T+1 open)
- Commission: $0.65 per options contract; $0 for stock
- Modeled spread haircut (Setup 2 only): 5% of premium

## Survivorship Caveat
Tested on currently listed names only; survivorship bias may flatter long-side results.

## Rule Definition
```
Universe: S&P 500 + Dividend Achievers
Signal (close of day T):
  price within 2% of 50-day MA (above or below)
  200-day MA rising
  HV percentile in top third of trailing year
  [IV percentile substitution: HV used as IV proxy; stated in every reference]
Entry: T+1 open (stock signal); modeled put entered same day
Modeled trade: sell 30-delta put, 37 DTE, Black-Scholes with HV;
  5% spread haircut; close at 50% profit or 21 DTE;
  assignment modeled if ITM at expiry
Stock exit: stop on close below 200 MA; time stop 30 days
Options P&L: MODELED everywhere it appears
```

## Universe and Periods
- Universe: S&P 500 + Dividend Achievers (543 tickers)
- In-sample (parameter selection): 2019-01-01 to 2022-12-31
- Out-of-sample (reported untouched): 2023-01-01 to 2026-10-26

## Options Model Note
All options P&L figures are **MODELED** using Black-Scholes with historical volatility as the IV proxy.  Real IV was not available for historical dates.  The HV-as-IV substitution is stated here and in every table that shows options P&L.  Stock-signal quality (did support hold) is reported separately.

## Stock Signal Quality Note
Stock signal quality: support held (trade profitable) on 30.6% of trades (n=8034).  This is the stock-side edge only, independent of the options model.

## Walk-Forward Results
Per-trade stats below compound each trade at 100% of the account in date order. That max drawdown is not a portfolio drawdown; the portfolio drawdown is in the Portfolio Simulator section.
  In-sample (2019-2022)
    Trades: 3699  |  Win rate: 28.7% (info only)
    Expectancy/trade: 0.695%  |  Profit factor: 1.48
    Avg win: 7.52%  |  Avg loss: 2.05%
    Max drawdown: 100.00%
  Out-of-sample (2023-present)
    Trades: 4335  |  Win rate: 32.2% (info only)
    Expectancy/trade: 1.277%  |  Profit factor: 2.04
    Avg win: 7.79%  |  Avg loss: 1.82%
    Max drawdown: 99.55%

## Regime Splits
### Calendar regimes
  Pre-2022
    Trades: 1984  |  Win rate: 31.8% (info only)
    Expectancy/trade: 0.912%  |  Profit factor: 1.54
    Avg win: 8.15%  |  Avg loss: 2.45%
    Max drawdown: 100.00%
  Bear 2022
    Trades: 1715  |  Win rate: 25.1% (info only)
    Expectancy/trade: 0.443%  |  Profit factor: 1.37
    Avg win: 6.59%  |  Avg loss: 1.61%
    Max drawdown: 99.92%
  Bull 2023-2024
    Trades: 1710  |  Win rate: 37.1% (info only)
    Expectancy/trade: 1.660%  |  Profit factor: 2.41
    Avg win: 7.66%  |  Avg loss: 1.88%
    Max drawdown: 96.75%
  Recent 2025
    Trades: 2625  |  Win rate: 29.1% (info only)
    Expectancy/trade: 1.028%  |  Profit factor: 1.81
    Avg win: 7.90%  |  Avg loss: 1.79%
    Max drawdown: 99.55%

### SPY 200-day MA regimes (per trade, at entry)
  SPY above 200 MA
    Trades: 5517  |  Win rate: 31.9% (info only)
    Expectancy/trade: 0.972%  |  Profit factor: 1.68
    Avg win: 7.53%  |  Avg loss: 2.11%
    Max drawdown: 100.00%
  SPY below 200 MA
    Trades: 2517  |  Win rate: 27.6% (info only)
    Expectancy/trade: 1.091%  |  Profit factor: 1.97
    Avg win: 8.04%  |  Avg loss: 1.56%
    Max drawdown: 99.98%

## Robustness Tests (+/- 20% on key parameters)
  support_pct -20% (=0.016): n=236  exp=1.385%  PF=1.94
  support_pct +20% (=0.024): n=276  exp=1.203%  PF=1.89
  hv_pct_thresh -20% (=0.5333): n=356  exp=1.551%  PF=2.19
  hv_pct_thresh +20% (=0.8): n=158  exp=1.171%  PF=1.74

Edge survives across +/-20% parameter variations.

## Verdict
**SHADOW ONLY**

## Portfolio Simulator and Random-Entry Baseline (2026-10-26)
Simulator settings: 1% of current equity risked per trade, sized by distance to the stop where known, otherwise by the 10% per-position notional cap; max 10 concurrent positions; total open risk capped at 10% of equity; risk halves at a 10% equity drawdown and new entries pause at a 15% drawdown, resuming below 10%. Starting equity $100,000. Open positions are marked at cost, so the equity curve moves on realized exits only and intra-trade drawdown is not captured.

### Portfolio simulator, out-of-sample trades
  Setup through simulator
    Trades taken: 1452  |  Skipped: 2883 (max positions 2861, heat 0, paused 0, cash 22)
    Expectancy/trade: 0.185%  |  Profit factor: 1.20
    Start equity: $100,000.00  |  Final equity: $120,610.74  |  Total return: 20.61%
    CAGR: 5.06%  |  Portfolio max drawdown: 13.40% ($16,821.66)
    Calmar ratio: 0.38  |  Recovery factor: 1.23
    Avg trade duration: 7.8 days  |  Max concurrent positions: 10

### Random-entry baseline, out-of-sample
Random entries, same universe and holding periods as the setup, same T+1 open entry and costs, averaged across 5 seeds (seed base 42), run through the same portfolio simulator.
  Baseline per-trade (mean across seeds)
    Trades: 4335  |  Win rate: 51.1% (info only)
    Expectancy/trade: 0.536%  |  Profit factor: 1.28
    Avg win: 4.78%  |  Avg loss: 3.91%
    Max drawdown: 99.97%
  Baseline through simulator
    Trades taken: 1245.4  |  Skipped: 3089.6 (max positions 1274.6, heat 0.0, paused 713.0, cash 1102.0)
    Expectancy/trade: 0.129%  |  Profit factor: 1.08
    Start equity: $100,000.00  |  Final equity: $121,702.59  |  Total return: 21.70%
    CAGR: 4.75%  |  Portfolio max drawdown: 17.24% ($23,279.89)
    Calmar ratio: 0.40  |  Recovery factor: 1.09
    Avg trade duration: 8.8 days  |  Max concurrent positions: 10.0

Setup beats its random-entry baseline: yes (setup simulator expectancy 0.185% vs baseline 0.129%; setup profit factor 1.2 vs baseline 1.084). The registry verdict above is unchanged by this comparison; the baseline is reported so the edge can be judged against doing nothing.

### Prior run, preserved
Per-trade numbers from the 2026-10-24 report run, preserved when this report regenerated. The max drawdown below is the old ticker-ordered sequential figure, known broken, and is kept for history only; the portfolio drawdown in the simulator section above replaces it.
  Out-of-sample (2023-present)
    Trades: 4335  |  Win rate: 32.2% (info only)
    Expectancy/trade: 1.270%  |  Profit factor: 2.02
    Avg win: 7.79%  |  Avg loss: 1.83%
    Max drawdown: 63.89%
