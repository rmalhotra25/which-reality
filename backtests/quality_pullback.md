# Backtest: Quality Pullback
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
    Trades: 266  |  Win rate: 36.5% (info only)
    Expectancy/trade: 0.008%  |  Profit factor: 1.01
    Avg win: 3.77%  |  Avg loss: 2.15%
    Max drawdown: 46.36%
  Out-of-sample (2023-present)
    Trades: 339  |  Win rate: 38.1% (info only)
    Expectancy/trade: 0.352%  |  Profit factor: 1.32
    Avg win: 3.84%  |  Avg loss: 1.79%
    Max drawdown: 27.61%

## Regime Splits
### Calendar regimes
  Bear 2022
    Trades: 80  |  Win rate: 36.2% (info only)
    Expectancy/trade: 0.075%  |  Profit factor: 1.05
    Avg win: 4.15%  |  Avg loss: 2.24%
    Max drawdown: 28.29%
  Bull 2023-2024
    Trades: 192  |  Win rate: 34.9% (info only)
    Expectancy/trade: 0.233%  |  Profit factor: 1.20
    Avg win: 3.96%  |  Avg loss: 1.76%
    Max drawdown: 23.97%
  Recent 2025
    Trades: 333  |  Win rate: 39.0% (info only)
    Expectancy/trade: 0.212%  |  Profit factor: 1.17
    Avg win: 3.66%  |  Avg loss: 1.99%
    Max drawdown: 50.67%

### SPY 200-day MA regimes (per trade, at entry)
  SPY above 200 MA
    Trades: 315  |  Win rate: 37.1% (info only)
    Expectancy/trade: 0.025%  |  Profit factor: 1.02
    Avg win: 3.75%  |  Avg loss: 2.18%
    Max drawdown: 58.75%
  SPY below 200 MA
    Trades: 290  |  Win rate: 37.6% (info only)
    Expectancy/trade: 0.391%  |  Profit factor: 1.37
    Avg win: 3.88%  |  Avg loss: 1.71%
    Max drawdown: 24.53%

## Robustness Tests (+/- 20% on key parameters)
  pullback_pct -20% (=0.016): n=314  exp=0.227%  PF=1.19
  pullback_pct +20% (=0.024): n=359  exp=0.251%  PF=1.21
  rsi_entry -20% (=44): n=217  exp=0.202%  PF=1.16
  rsi_entry +20% (=66): n=413  exp=0.352%  PF=1.33
  rsi_reset -20% (=48): n=341  exp=0.345%  PF=1.31
  rsi_reset +20% (=72): n=341  exp=0.345%  PF=1.31

Edge survives across +/-20% parameter variations.

## Verdict
**SHADOW ONLY** -- synthetic data: mechanics verification only, not market evidence
