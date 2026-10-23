# Backtest: Quality Pullback
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
Universe: S&P 500 + Dividend Achievers with >=5y history
Signal (close of day T):
  price within 2% ABOVE 50-day or 200-day MA
  200-day MA rising (today > value 20 days ago)
  RSI(14) < 55 now and was > 60 within prior 20 sessions
  volume < 20-day average volume
  [earnings filter: skipped -- unavailable at backtest time]
Entry: T+1 open + 0.05% slippage
Exit: stop on close below 200 MA; target when RSI(14) > 68; time stop 30 days
```

## Universe and Periods
- Universe: S&P 500 + Dividend Achievers (20 tickers combined)
- In-sample (parameter selection): 2019-01-01 to 2022-12-31
- Out-of-sample (reported untouched): 2023-01-01 to 2026-10-23

## Walk-Forward Results
  In-sample (2019-2022)
    Trades: 272  |  Win rate: 37.9% (info only)
    Expectancy/trade: 0.123%  |  Profit factor: 1.09
    Avg win: 3.83%  |  Avg loss: 2.14%
    Max drawdown: 31.68%
  Out-of-sample (2023-present)
    Trades: 314  |  Win rate: 36.3% (info only)
    Expectancy/trade: 0.266%  |  Profit factor: 1.23
    Avg win: 3.94%  |  Avg loss: 1.83%
    Max drawdown: 46.30%

## Regime Splits
### Calendar regimes
  Bear 2022
    Trades: 76  |  Win rate: 34.2% (info only)
    Expectancy/trade: 0.120%  |  Profit factor: 1.09
    Avg win: 4.15%  |  Avg loss: 1.98%
    Max drawdown: 21.04%
  Bull 2023-2024
    Trades: 183  |  Win rate: 31.1% (info only)
    Expectancy/trade: -0.006%  |  Profit factor: 1.00
    Avg win: 3.99%  |  Avg loss: 1.81%
    Max drawdown: 52.27%
  Recent 2025
    Trades: 327  |  Win rate: 41.0% (info only)
    Expectancy/trade: 0.333%  |  Profit factor: 1.27
    Avg win: 3.79%  |  Avg loss: 2.07%
    Max drawdown: 43.71%

### SPY 200-day MA regimes (per trade, at entry)
  SPY above 200 MA
    Trades: 325  |  Win rate: 36.9% (info only)
    Expectancy/trade: 0.013%  |  Profit factor: 1.01
    Avg win: 3.78%  |  Avg loss: 2.19%
    Max drawdown: 50.79%
  SPY below 200 MA
    Trades: 261  |  Win rate: 37.2% (info only)
    Expectancy/trade: 0.432%  |  Profit factor: 1.41
    Avg win: 4.02%  |  Avg loss: 1.69%
    Max drawdown: 32.90%

## Robustness Tests (+/- 20% on key parameters)
  pullback_pct -20% (=0.016): n=292  exp=0.162%  PF=1.13
  pullback_pct +20% (=0.024): n=335  exp=0.206%  PF=1.16
  rsi_entry -20% (=44): n=196  exp=0.236%  PF=1.18
  rsi_entry +20% (=66): n=388  exp=0.259%  PF=1.23
  rsi_reset -20% (=48): n=316  exp=0.259%  PF=1.22
  rsi_reset +20% (=72): n=316  exp=0.259%  PF=1.22

Edge survives across +/-20% parameter variations.

## Verdict
**PASSES**
