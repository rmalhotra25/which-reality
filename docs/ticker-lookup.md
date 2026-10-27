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

## Verdict: three binary answers first

The tab leads with the verdict, computed only from the quant results
above, in `ticker_lookup.build_verdict`. No Claude decision, no
threshold loosened, no new buy signal.

- Stock: BUY THE STOCK only when at least one LIVE setup passes
  (Quality Pullback or Volume Breakout), the earnings date is known
  and more than 5 days away, and the SPY gate passes. Premium at
  Support is SHADOW, so it never makes a BUY on its own. Otherwise
  DON'T BUY THE STOCK, with the top plain-language reason first,
  in this order: earnings unknown, earnings within 5 days, SPY
  below its 200-day average, SPY trend unknown, a live setup held
  back, or no live setup fired. At most 3 short reasons, one line
  for what would change the verdict (derived from the failing setup
  conditions, e.g. a pullback to the 50-day average), and the
  invalidation price from the passing setup when BUY. A Don't Buy
  is a good outcome too, it saved a bad trade, and the tab says so.
- Sell a put: only shown as a real option when the stock is a BUY.
  SELL THE PUT uses the listed chain, nearest 21 DTE, the put
  closest to 0.30 delta, bid-priced only, with the same gates as
  the wheel helper (bid must exist, spread at most 15% when known,
  open interest at least 100 when known). It shows strike, expiry,
  premium per contract, breakeven (strike minus premium),
  assignment price (the strike), and max loss per contract
  (strike minus premium, times 100). If no put qualifies, DON'T
  SELL A PUT with the named reason. When the stock is Don't Buy,
  the put section is NOT AVAILABLE, with no put numbers.
- Buy a call: only when the stock is a BUY. BUY THE CALL uses the
  directional engine rule: listed expiry nearest 21 DTE, strike
  snapped to the nearest listed strike above the price. Premium is
  the ask when there is one, else the mid, labelled, never a last
  trade as executable. It shows strike, expiry, premium per
  contract, breakeven (strike plus premium), max loss (the premium
  paid), and the stock invalidation price. If no call qualifies,
  DON'T BUY THE CALL with the named reason. When the stock is
  Don't Buy, the call section is NOT AVAILABLE, with no numbers.

## Conviction: what the verdict is based on

The verdict carries a conviction summary with three plain-language
lists: what supported it, what was against it, and what was missing.
No factor is invented, and no missing data is counted as support.

- Stock ticker setups: the LIVE setups, Quality Pullback and Volume
  Breakout, plus trend (price vs rising 50-day and 200-day
  averages), the display-only quality composite, volume (strong
  when at least 1.5 times the 20-day average), and the SPY gate.
- News and company releases: the live provider fetches recent
  articles from Polygon ticker news (`services.polygon_client.get_news`,
  now returning title, published date, publisher, and url, not just
  a title). Only a fresh article, published within 3 days, from a
  press-release wire (GlobeNewswire, Business Wire, PR Newswire,
  Accesswire) counts as a company release that supports the verdict.
  Fresh general news is shown with its headline, date, and
  publisher, but never counted as support. An article with no date,
  a fetch failure, or no articles at all is recorded as news
  unavailable and counts for nothing.
- Anticipated vs actual results: anticipated is the next earnings
  date and days away from the Finnhub earnings calendar. Actual is
  not available, see the gaps below. A name that reports within 5
  days is never a BUY, by the same earnings gate that blocks every
  setup, and the verdict says so plainly.

## Data sources the verdict uses, and the gaps

Used, with a named source: yfinance OHLCV for price, trend, and
indicators; Finnhub earnings calendar for the next earnings date;
the IV store for IV rank; Finnhub candles for the SPY gate; the
listed option chain (Polygon primary, yfinance fallback) for the
put and the call; Polygon ticker news for news and releases.

Gaps, fail-closed, not guessed:

- Consensus earnings estimate: no reliable feed in the repo. The
  Finnhub earnings calendar response may carry an estimate, but the
  app does not read it and it is unverified, so the verdict records
  the estimate as missing. Feed needed: a verified consensus
  estimate feed (Finnhub earnings calendar estimate field, or a
  dedicated estimates provider) before anticipated results can be
  scored against actuals.
- Reported beat or miss: no reliable feed in the repo. Post-Earnings
  Drift was retired for exactly this reason, no reliable
  earnings-beat or guidance feed exists. Feed needed: a verified
  reported-EPS and revenue vs consensus feed before actual results
  can be scored.
- News freshness and company-release identity: Polygon ticker news
  is the only dated, sourced feed, and it is wired in now, but its
  availability on the Massive Starter plan is unverified live, and
  it does not label articles as press releases, so the verdict
  infers that from the publisher name. The other news sources in
  the repo were not used: `news_scraper` (Yahoo Finance search and
  Stocktwits chatter, undocumented endpoints, no company-release
  filter) and Claude web search (a summary, not a deterministic
  feed, and Claude must never decide the verdict).
- IV rank: from the IV store only, and unavailable for names with
  no stored IV, which is listed as missing in the conviction
  summary.

## Layout

The verdict card is first, with the put and call beside it, then a
plain-language conviction card (supports, against, missing, news,
earnings). The price, trend, quality, earnings, IV, and SPY stats
follow. The full Rule Registry Check and the full listed chain are
below, in details blocks closed by default, so a normal user never
has to read 9 FAIL rows first, and anyone who wants the audit trail
can open them.

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
invalid ticker handling. Verdict tests live in
`~/workspace/.tiq-test/test_ticker_lookup_verdict.py`: BUY when a LIVE
setup passes, DON'T BUY when none pass, on earnings unknown, on SPY
below its 200-day average, and on earnings within 5 days; put shown
only on BUY with bid pricing and breakeven math; call shown only on
BUY; put and call not available on DON'T BUY; no listed chain, no bid,
and spread too wide give named DON'T SELL reasons; fresh company
release supports, fresh general news does not, stale and undated news
count for nothing; estimate and actual are recorded as missing, never
guessed; SHADOW Premium at Support alone never makes a BUY; and the
verdict is identical for the same stub inputs.
