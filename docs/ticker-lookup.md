# Ticker Lookup (deterministic query)

One tab, "Ticker Lookup", and one endpoint, `GET /api/lookup/{ticker}`.

## What it is

A query, not a decision maker. Type a ticker, get a snapshot: price with
data timestamp and price source, trend (price vs 50-day and 200-day MAs,
each MA rising or falling), a display-only quality score with its inputs,
each setup rule as pass or fail with its values, earnings date or
`earnings_unknown`, IV rank or IV unavailable, and the listed option chain
for the nearest 21 DTE (puts and calls, bid and ask, with price source).
Unknown values are shown as unknown and fail closed, never guessed.

There was no Stock Lookup tab at this base: the P2 determinism work
deleted the dead Claude-decision Stock Lookup methods
(`analyze_stock`, `analyze_longterm`) from `claude_analyst.py`, and no
lookup tab existed in `App.jsx`. So the lookup is one new tab that reuses
the alert engine, not a second competing lookup.

## Determinism

The lookup runs the same rule registry check as the alert engine, on the
same ticker, on demand:

- Indicators from `alert_engine._fetch_ohlcv` and `_indicators`, same
  thresholds, same earnings fail-closed gate, same SPY gate.
- Every setup in `alert_engine._SETUP_EVALUATORS` is evaluated by the
  same evaluator function. A setup that fires gets its action from
  `alert_engine._build_alert`, so entry, stop, target or exit rule,
  strike, size, expiry, and invalidation match what the live run would
  show for that ticker at that data timestamp.
- No new rules, no new picks, no different data source. Rule statuses
  come from the rule registry: Quality Pullback and Volume Breakout are
  LIVE, Premium at Support is SHADOW, Oversold Bounce and Trend Pullback
  Reversal are SHADOW. Directional Options and Champions are SHADOW
  systems evaluated by their own scheduled runs, so the lookup reports
  them as not evaluated on demand. Down-market puts are SHADOW ONLY and
  Post-Earnings Drift is RETIRED; both are reported, never evaluated.
- Quality is a display-only composite from existing `quant_scorer`
  components (trend 40%, RSI 30%, volume 30%). It never gates a setup.
- The listed chain comes from `ChainProvider` (Polygon primary, yfinance
  fallback). Premium at Support still prices from `get_listed_put` at the
  bid, or suppresses with a named reason.

## What it never does

No alert fires, no journal row is created, no Telegram message is sent,
no run receipt is written, and no scheduler job runs. The service module
imports none of those writers. A passing setup is labelled as the rule
result for that ticker at that time, not as an instruction to trade.

## Claude

Quant decides, Claude explains only (`services.ai_boundary`). The
explanation is opt-in (`?explain=true`); it is written by
`ClaudeAnalyst.explain_watchlist` from quant numbers already computed.
A Claude failure leaves the quant result untouched and the quant
fallback text is used.

## Cache

The live wrapper caches a lookup result in memory for 120 seconds,
labelled `cached` with its original data timestamp. It is never served
past its TTL. `evaluate_lookup()` itself is pure and uncached, so the
same stubbed inputs always give the same result.

## Errors

Invalid or unknown tickers return a named error, not a crash:
`invalid_ticker`, `no_data`, `no_indicators`. No listed chain returns
`no_listed_chain` on the chain block and suppresses the options result
with that reason; the rest of the snapshot still returns.

## Tests

Stub tests live in `~/workspace/.tiq-test/test_ticker_lookup_deterministic.py`
(outside the repo, with the other determinism stub tests). They cover
same-input determinism, Claude failure, earnings unknown fail-closed,
no listed chain suppression, no alert row and no Telegram call, and
invalid ticker handling.
