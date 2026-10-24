# Backtest: Quality Pullback
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
- Universe: S&P 500 + Dividend Achievers (543 tickers combined)
- In-sample (parameter selection): 2019-01-01 to 2022-12-31
- Out-of-sample (reported untouched): 2023-01-01 to 2026-10-24

## Walk-Forward Results
  In-sample (2019-2022)
    Trades: 5104  |  Win rate: 48.2% (info only)
    Expectancy/trade: 0.792%  |  Profit factor: 1.57
    Avg win: 4.53%  |  Avg loss: 2.68%
    Max drawdown: 50.02%
  Out-of-sample (2023-present)
    Trades: 6828  |  Win rate: 46.7% (info only)
    Expectancy/trade: 0.589%  |  Profit factor: 1.43
    Avg win: 4.18%  |  Avg loss: 2.55%
    Max drawdown: 88.06%

## Regime Splits
### Calendar regimes
  Bear 2022
    Trades: 1430  |  Win rate: 38.6% (info only)
    Expectancy/trade: 0.146%  |  Profit factor: 1.10
    Avg win: 3.98%  |  Avg loss: 2.27%
    Max drawdown: 78.14%
  Bull 2023-2024
    Trades: 3662  |  Win rate: 48.0% (info only)
    Expectancy/trade: 0.617%  |  Profit factor: 1.46
    Avg win: 4.08%  |  Avg loss: 2.59%
    Max drawdown: 73.96%
  Recent 2025
    Trades: 6840  |  Win rate: 48.8% (info only)
    Expectancy/trade: 0.818%  |  Profit factor: 1.59
    Avg win: 4.52%  |  Avg loss: 2.70%
    Max drawdown: 68.70%

### SPY 200-day MA regimes (per trade, at entry)
  SPY above 200 MA
    Trades: 10161  |  Win rate: 48.4% (info only)
    Expectancy/trade: 0.697%  |  Profit factor: 1.49
    Avg win: 4.35%  |  Avg loss: 2.73%
    Max drawdown: 76.79%
  SPY below 200 MA
    Trades: 1771  |  Win rate: 41.1% (info only)
    Expectancy/trade: 0.552%  |  Profit factor: 1.48
    Avg win: 4.17%  |  Avg loss: 1.97%
    Max drawdown: 49.11%

## Robustness Tests (+/- 20% on key parameters)
  pullback_pct -20% (=0.016): n=402  exp=0.676%  PF=1.57
  pullback_pct +20% (=0.024): n=458  exp=0.862%  PF=1.75
  rsi_entry -20% (=44): n=276  exp=0.970%  PF=1.90
  rsi_entry +20% (=66): n=547  exp=0.601%  PF=1.53
  rsi_reset -20% (=48): n=430  exp=0.771%  PF=1.66
  rsi_reset +20% (=72): n=430  exp=0.771%  PF=1.66

Edge survives across +/-20% parameter variations.

## Verdict
**PASSES**
