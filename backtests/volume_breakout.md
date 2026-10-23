# Backtest: Volume-Confirmed Breakout
Generated: 2026-10-23
**Data source**: SYNTHETIC (mechanics verification only, not market evidence)

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
    Trades: 159  |  Win rate: 34.0% (info only)
    Expectancy/trade: 0.590%  |  Profit factor: 1.90
    Avg win: 3.67%  |  Avg loss: 1.00%
    Max drawdown: 15.02%
  Out-of-sample (2023-present)
    Trades: 214  |  Win rate: 26.6% (info only)
    Expectancy/trade: 0.182%  |  Profit factor: 1.25
    Avg win: 3.38%  |  Avg loss: 0.98%
    Max drawdown: 21.91%

## Regime Splits
### Calendar regimes
  Bear 2022
    Trades: 45  |  Win rate: 35.6% (info only)
    Expectancy/trade: 0.530%  |  Profit factor: 1.69
    Avg win: 3.66%  |  Avg loss: 1.20%
    Max drawdown: 19.16%
  Bull 2023-2024
    Trades: 113  |  Win rate: 30.1% (info only)
    Expectancy/trade: 0.262%  |  Profit factor: 1.38
    Avg win: 3.15%  |  Avg loss: 0.98%
    Max drawdown: 12.34%
  Recent 2025
    Trades: 215  |  Win rate: 28.4% (info only)
    Expectancy/trade: 0.369%  |  Profit factor: 1.54
    Avg win: 3.70%  |  Avg loss: 0.95%
    Max drawdown: 14.02%

### SPY 200-day MA regimes (per trade, at entry)
  SPY above 200 MA
    Trades: 211  |  Win rate: 30.3% (info only)
    Expectancy/trade: 0.456%  |  Profit factor: 1.71
    Avg win: 3.63%  |  Avg loss: 0.93%
    Max drawdown: 14.29%
  SPY below 200 MA
    Trades: 162  |  Win rate: 29.0% (info only)
    Expectancy/trade: 0.226%  |  Profit factor: 1.30
    Avg win: 3.38%  |  Avg loss: 1.06%
    Max drawdown: 24.91%

## Robustness Tests (+/- 20% on key parameters)
  breakout_days -20% (=44): n=220  exp=0.162%  PF=1.22
  breakout_days +20% (=66): n=211  exp=0.149%  PF=1.21
  vol_mult -20% (=1.2): n=351  exp=0.246%  PF=1.37
  vol_mult +20% (=1.8): n=51  exp=0.561%  PF=1.98

Edge survives across +/-20% parameter variations.

## Verdict
**SHADOW ONLY** -- synthetic data: mechanics verification only, not market evidence
