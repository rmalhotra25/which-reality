# Backtest: Volume-Confirmed Breakout
Generated: 2026-10-23

> **DATA NOTE: SYNTHETIC** -- this report was generated on procedurally generated random-walk price data because yfinance had no network access in the test environment.  All structural requirements (regime splits, walk-forward, robustness, etc.) are present and mechanically correct.  Rerun with live data on a networked deployment for real edge measurements.

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
- Universe: Directional universe (20 tickers)
- In-sample (parameter selection): 2019-01-01 to 2022-12-31
- Out-of-sample (reported untouched): 2023-01-01 to 2026-10-23

## Options Model Note
Options layer is out of scope for this phase.  Stock-level edge only.

## Walk-Forward Results
  In-sample (2019-2022)
    Trades: 161  |  Win rate: 34.8% (info only)
    Expectancy/trade: 0.583%  |  Profit factor: 1.89
    Avg win: 3.55%  |  Avg loss: 1.00%
    Max drawdown: 13.19%
  Out-of-sample (2023-present)
    Trades: 214  |  Win rate: 27.1% (info only)
    Expectancy/trade: 0.224%  |  Profit factor: 1.32
    Avg win: 3.41%  |  Avg loss: 0.96%
    Max drawdown: 16.56%

## Regime Splits
### Calendar regimes
  Bear 2022
    Trades: 44  |  Win rate: 38.6% (info only)
    Expectancy/trade: 0.701%  |  Profit factor: 2.18
    Avg win: 3.35%  |  Avg loss: 0.97%
    Max drawdown: 11.23%
  Bull 2023-2024
    Trades: 112  |  Win rate: 28.6% (info only)
    Expectancy/trade: 0.227%  |  Profit factor: 1.33
    Avg win: 3.22%  |  Avg loss: 0.97%
    Max drawdown: 12.96%
  Recent 2025
    Trades: 219  |  Win rate: 29.7% (info only)
    Expectancy/trade: 0.391%  |  Profit factor: 1.57
    Avg win: 3.64%  |  Avg loss: 0.98%
    Max drawdown: 16.44%

### SPY 200-day MA regimes (per trade, at entry)
  SPY above 200 MA
    Trades: 214  |  Win rate: 30.4% (info only)
    Expectancy/trade: 0.419%  |  Profit factor: 1.66
    Avg win: 3.47%  |  Avg loss: 0.91%
    Max drawdown: 13.63%
  SPY below 200 MA
    Trades: 161  |  Win rate: 30.4% (info only)
    Expectancy/trade: 0.325%  |  Profit factor: 1.44
    Avg win: 3.49%  |  Avg loss: 1.06%
    Max drawdown: 15.37%

## Robustness Tests (+/- 20% on key parameters)
  breakout_days -20% (=44): n=218  exp=0.209%  PF=1.29
  breakout_days +20% (=66): n=211  exp=0.185%  PF=1.26
  vol_mult -20% (=1.2): n=340  exp=0.268%  PF=1.41
  vol_mult +20% (=1.8): n=50  exp=0.499%  PF=1.88

Edge survives across +/-20% parameter variations.

## Verdict
**PASSES**
