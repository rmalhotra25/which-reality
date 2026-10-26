# Backtest: Volume-Confirmed Breakout
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
Universe: app directional universe (DEFAULT_UNIVERSE in stock_data.py)
Signal (close of day T):
  close above prior 55-day high (today excluded)
  volume >= 1.5x 20-day average volume
  price above rising 50-day MA
Entry: T+1 open + 0.05% slippage
Exit: stop on close below breakout level;
      target at entry + 2 * ATR(14); time stop 15 days
```

## Universe and Periods
- Universe: Directional universe (94 tickers)
- In-sample (parameter selection): 2019-01-01 to 2022-12-31
- Out-of-sample (reported untouched): 2023-01-01 to 2026-10-26

## Options Model Note
Options layer is out of scope for this phase.  Stock-level edge only.

## Walk-Forward Results
Per-trade stats below compound each trade at 100% of the account in date order. That max drawdown is not a portfolio drawdown; the portfolio drawdown is in the Portfolio Simulator section.
  In-sample (2019-2022)
    Trades: 658  |  Win rate: 44.1% (info only)
    Expectancy/trade: 0.537%  |  Profit factor: 1.45
    Avg win: 3.93%  |  Avg loss: 2.13%
    Max drawdown: 58.79%
  Out-of-sample (2023-present)
    Trades: 838  |  Win rate: 46.8% (info only)
    Expectancy/trade: 0.985%  |  Profit factor: 1.84
    Avg win: 4.60%  |  Avg loss: 2.19%
    Max drawdown: 47.40%

## Regime Splits
### Calendar regimes
  Pre-2022
    Trades: 562  |  Win rate: 46.1% (info only)
    Expectancy/trade: 0.693%  |  Profit factor: 1.60
    Avg win: 4.02%  |  Avg loss: 2.15%
    Max drawdown: 58.79%
  Bear 2022
    Trades: 96  |  Win rate: 32.3% (info only)
    Expectancy/trade: -0.374%  |  Profit factor: 0.73
    Avg win: 3.13%  |  Avg loss: 2.04%
    Max drawdown: 57.89%
  Bull 2023-2024
    Trades: 487  |  Win rate: 46.8% (info only)
    Expectancy/trade: 0.881%  |  Profit factor: 1.82
    Avg win: 4.19%  |  Avg loss: 2.03%
    Max drawdown: 36.35%
  Recent 2025
    Trades: 351  |  Win rate: 46.7% (info only)
    Expectancy/trade: 1.129%  |  Profit factor: 1.88
    Avg win: 5.16%  |  Avg loss: 2.41%
    Max drawdown: 47.40%

### SPY 200-day MA regimes (per trade, at entry)
  SPY above 200 MA
    Trades: 1406  |  Win rate: 46.3% (info only)
    Expectancy/trade: 0.852%  |  Profit factor: 1.74
    Avg win: 4.32%  |  Avg loss: 2.14%
    Max drawdown: 57.26%
  SPY below 200 MA
    Trades: 90  |  Win rate: 34.4% (info only)
    Expectancy/trade: -0.218%  |  Profit factor: 0.87
    Avg win: 4.13%  |  Avg loss: 2.50%
    Max drawdown: 54.84%

## Robustness Tests (+/- 20% on key parameters)
  breakout_days -20% (=44): n=351  exp=1.137%  PF=1.73
  breakout_days +20% (=66): n=345  exp=1.123%  PF=1.72
  vol_mult -20% (=1.2): n=534  exp=1.090%  PF=1.75
  vol_mult +20% (=1.8): n=233  exp=1.201%  PF=1.75

Edge survives across +/-20% parameter variations.

## Verdict
**PASSES**

## Portfolio Simulator and Random-Entry Baseline (2026-10-26)
Simulator settings: 1% of current equity risked per trade, sized by distance to the stop where known, otherwise by the 10% per-position notional cap; max 10 concurrent positions; total open risk capped at 10% of equity; risk halves at a 10% equity drawdown and new entries pause at a 15% drawdown, resuming below 10%. Starting equity $100,000. Open positions are marked at cost, so the equity curve moves on realized exits only and intra-trade drawdown is not captured.

### Portfolio simulator, out-of-sample trades
  Setup through simulator
    Trades taken: 738  |  Skipped: 100 (max positions 91, heat 0, paused 0, cash 9)
    Expectancy/trade: 1.007%  |  Profit factor: 1.90
    Start equity: $100,000.00  |  Final equity: $206,860.54  |  Total return: 106.86%
    CAGR: 21.08%  |  Portfolio max drawdown: 5.49% ($11,138.80)
    Calmar ratio: 3.84  |  Recovery factor: 9.59
    Avg trade duration: 8.4 days  |  Max concurrent positions: 10

### Random-entry baseline, out-of-sample
Random entries, same universe and holding periods as the setup, same T+1 open entry and costs, averaged across 5 seeds (seed base 42), run through the same portfolio simulator.
  Baseline per-trade (mean across seeds)
    Trades: 838  |  Win rate: 51.4% (info only)
    Expectancy/trade: 0.463%  |  Profit factor: 1.27
    Avg win: 4.28%  |  Avg loss: 3.58%
    Max drawdown: 87.18%
  Baseline through simulator
    Trades taken: 668.8  |  Skipped: 169.2 (max positions 13.2, heat 0.0, paused 135.4, cash 20.6)
    Expectancy/trade: 0.400%  |  Profit factor: 1.19
    Start equity: $100,000.00  |  Final equity: $133,934.28  |  Total return: 33.93%
    CAGR: 7.46%  |  Portfolio max drawdown: 15.90% ($23,181.22)
    Calmar ratio: 0.52  |  Recovery factor: 1.48
    Avg trade duration: 9.8 days  |  Max concurrent positions: 10.0

Setup beats its random-entry baseline: yes (setup simulator expectancy 1.007% vs baseline 0.400%; setup profit factor 1.9 vs baseline 1.19). The registry verdict above is unchanged by this comparison; the baseline is reported so the edge can be judged against doing nothing.

### Prior run, preserved
Per-trade numbers from the 2026-10-24 report run, preserved when this report regenerated. The max drawdown below is the old ticker-ordered sequential figure, known broken, and is kept for history only; the portfolio drawdown in the simulator section above replaces it.
  Out-of-sample (2023-present)
    Trades: 838  |  Win rate: 46.8% (info only)
    Expectancy/trade: 0.985%  |  Profit factor: 1.84
    Avg win: 4.60%  |  Avg loss: 2.19%
    Max drawdown: 41.28%
