# Backtest: Directional Puts (long puts + bear spreads)

**Data source**: REAL underlying prices via yfinance; MODELLED option premiums
(Black-Scholes at 20-day historical volatility, fills at ask when buying
and bid when selling, spread and commission included). No historical
options chains or historical bid/ask exist in this data, so premiums are
modelled, not traded prices. This report can never promote the setup to LIVE.

> **STATUS: SHADOW ONLY** -- premiums modelled, not real historical option
> prices. Rerun with real historical option prices (for example Polygon
> options aggregates) before any LIVE promotion.

## Cost Assumptions
- Buy fill: BS price + half spread; sell fill: BS price - half spread
- Spread: max($0.10, 5% of BS price) per leg
- Commission: $0.65 per contract per side ($1.30 outright, $2.60 spread)
- Slippage: included via the spread haircut on the fill

## Gaps and Caveats
- Earnings exclusion skipped in this harness (no historical earnings
  calendar fetched); the live engine excludes earnings in window.
- IV percentile is a proxy: percentile of 20-day historical volatility
  within its own 252-day history, not a real IV percentile.
- DTE is held 21 calendar days; no historical chain exists to snap the
  expiry to a listed expiry.
- Tested on currently listed names only; survivorship bias may flatter
  long-side results and understate down-market results.

## Rule Definition
```
Universe: liquid names (20 tickers, see harness UNIVERSE)
Signal (close of day T): price below 50-day MA and below 200-day MA
Variant: HV-percentile proxy < 75 -> outright long put; >= 75 -> bear spread
Entry: T+1 open; strike nearest $1 below price - 0.3 x ATR(14); delta 0.15-0.50
EV at entry must be above zero (BS P(profit) at the modelled premium)
Exit: target at price - 2 x ATR; stop on close above entry + one expected move;
  otherwise expiry at 21 calendar days
```

- Universe: 20 tickers
- In-sample (parameter selection): 2019-01-01 to 2022-12-31
- Out-of-sample (reported untouched): 2023-01-01 to 2026-10-24

## Walk-Forward Results
  In-sample (2019-2022)
    Trades: 460  |  Win rate: 39.6% (info only)
        Expectancy/trade: $-44.49  |  Profit factor: 0.8
        Avg win: $436.38  |  Avg loss: $-359.30
        Max drawdown: $-32947.66
  Out-of-sample (2023-present)
    Trades: 279  |  Win rate: 38.4% (info only)
        Expectancy/trade: $-102.69  |  Profit factor: 0.69
        Avg win: $592.45  |  Avg loss: $-535.12
        Max drawdown: $-44918.65

## Variant Splits (out-of-sample)
  Outright long puts
    Trades: 21  |  Win rate: 38.1% (info only)
        Expectancy/trade: $127.81  |  Profit factor: 1.86
        Avg win: $724.06  |  Avg loss: $-239.11
        Max drawdown: $-1313.25
  Bear spreads
    Trades: 258  |  Win rate: 38.4% (info only)
        Expectancy/trade: $-121.45  |  Profit factor: 0.65
        Avg win: $581.81  |  Avg loss: $-559.33
        Max drawdown: $-47203.45

## Regime Splits (out-of-sample)
### Calendar regimes (all trades, in-sample and out-of-sample,
because the 2022 bear market predates the out-of-sample window)
  Bear 2022
    Trades: 400  |  Win rate: 41.0% (info only)
        Expectancy/trade: $-27.27  |  Profit factor: 0.87
        Avg win: $460.28  |  Avg loss: $-366.08
        Max drawdown: $-23864.32
  Bull 2023-2024
    Trades: 36  |  Win rate: 41.7% (info only)
        Expectancy/trade: $93.75  |  Profit factor: 1.42
        Avg win: $758.63  |  Avg loss: $-381.16
        Max drawdown: $-7824.90
  Recent 2025
    Trades: 243  |  Win rate: 37.9% (info only)
        Expectancy/trade: $-131.79  |  Profit factor: 0.62
        Avg win: $565.35  |  Avg loss: $-556.54
        Max drawdown: $-37676.45
### SPY 200-day MA regimes (per trade, at entry)
  SPY above 200 MA
    Trades: 160  |  Win rate: 40.6% (info only)
        Expectancy/trade: $-88.25  |  Profit factor: 0.71
        Avg win: $544.75  |  Avg loss: $-521.36
        Max drawdown: $-28564.13
  SPY below 200 MA
    Trades: 119  |  Win rate: 35.3% (info only)
        Expectancy/trade: $-122.10  |  Profit factor: 0.66
        Avg win: $666.26  |  Avg loss: $-552.11
        Max drawdown: $-22125.57

## Verdict
**SHADOW ONLY** -- modelled premiums: mechanics verification only, not market evidence

Out-of-sample headline: 279 trades, expectancy $-102.69 per contract, profit factor 0.69. On modelled premiums the strategy as specified loses money out of sample; the outright-put split is positive only on 21 trades, too few to trust. Do not promote.

A PASSES verdict requires OOS expectancy above $0, profit factor above 1.2,
at least 30 out-of-sample trades, AND real historical option prices. This
harness cannot supply the last condition, so its verdict is capped here.

## How to rerun

From the repo root, on a networked machine:

```
python scripts/backtest_directional_puts.py --out backtests/directional_puts.md
```

## Registry Spec (for the coordinator)

- setup_id: directional_puts
- backtest file: backtests/directional_puts.md
- status: SHADOW
