# Backtest: Volume-Confirmed Breakout
Generated: 2026-10-24
**Data source**: REAL (fetched 2026-10-24)

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
- Out-of-sample (reported untouched): 2023-01-01 to 2026-10-24

## Options Model Note
Options layer is out of scope for this phase.  Stock-level edge only.

## Walk-Forward Results
  In-sample (2019-2022)
    Trades: 658  |  Win rate: 44.1% (info only)
    Expectancy/trade: 0.537%  |  Profit factor: 1.45
    Avg win: 3.93%  |  Avg loss: 2.13%
    Max drawdown: 32.72%
  Out-of-sample (2023-present)
    Trades: 838  |  Win rate: 46.8% (info only)
    Expectancy/trade: 0.985%  |  Profit factor: 1.84
    Avg win: 4.60%  |  Avg loss: 2.19%
    Max drawdown: 41.28%

## Regime Splits
### Calendar regimes
  Bear 2022
    Trades: 96  |  Win rate: 32.3% (info only)
    Expectancy/trade: -0.374%  |  Profit factor: 0.73
    Avg win: 3.13%  |  Avg loss: 2.04%
    Max drawdown: 47.78%
  Bull 2023-2024
    Trades: 487  |  Win rate: 46.8% (info only)
    Expectancy/trade: 0.881%  |  Profit factor: 1.82
    Avg win: 4.19%  |  Avg loss: 2.03%
    Max drawdown: 32.83%
  Recent 2025
    Trades: 913  |  Win rate: 46.3% (info only)
    Expectancy/trade: 0.861%  |  Profit factor: 1.71
    Avg win: 4.47%  |  Avg loss: 2.25%
    Max drawdown: 33.19%

### SPY 200-day MA regimes (per trade, at entry)
  SPY above 200 MA
    Trades: 1406  |  Win rate: 46.3% (info only)
    Expectancy/trade: 0.852%  |  Profit factor: 1.74
    Avg win: 4.32%  |  Avg loss: 2.14%
    Max drawdown: 43.46%
  SPY below 200 MA
    Trades: 90  |  Win rate: 34.4% (info only)
    Expectancy/trade: -0.218%  |  Profit factor: 0.87
    Avg win: 4.13%  |  Avg loss: 2.50%
    Max drawdown: 50.93%

## Robustness Tests (+/- 20% on key parameters)
  breakout_days -20% (=44): n=351  exp=1.137%  PF=1.73
  breakout_days +20% (=66): n=345  exp=1.123%  PF=1.72
  vol_mult -20% (=1.2): n=534  exp=1.090%  PF=1.75
  vol_mult +20% (=1.8): n=233  exp=1.201%  PF=1.75

Edge survives across +/-20% parameter variations.

## Verdict
**PASSES**
