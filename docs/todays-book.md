# Today's Book

Daily landing view (`TodayBookTab`) backed by `GET /api/today`.
Quant decides, AI explains. No live order execution.

## Response shape

```
GET /api/today?explain=quant|claude
{
  generated_at, as_of_date,
  data_note,                    # close-of-day-T / next-open + delayed-data note
  settings,                     # account_equity, peak_equity, risk_pct,
                                # max_heat_pct, max_positions, max_position_pct,
                                # covered_call_tickers
  risk_bar,                     # account size, current heat, remaining capacity,
                                # open positions, drawdown_pct, drawdown_brake
  items,                        # ranked LIVE setups, sized
  blocked,                      # candidates that breached a hard cap, with reason
  unavailable,                  # covered calls that could not be priced
  research_only,                # SHADOW items, never sized
  scoreboard,                   # same /api/book/scoreboard payload
  sources                       # wheel_run_at, alerts window, covered-call tickers
}
```

Each item carries plain language plus precise numbers: `title`,
`explanation` (2-3 sentences), `risk_text`, `invalidation_text`,
`strike`, `expiry`, `dte`, `delta`, `bid`/`ask`/`mid`, `contracts`,
`capital_at_risk`, `risk_dollars`, `premium_net_total`, `rank_score`,
`status` (LIVE), `delay_note`, `entry_modeled_at: "next open"`.

## Sources

Cache-only, no engine run on request:

- Wheel: latest `WheelRecommendation` batch (LIVE in the registry).
- Setup Alerts: `SetupAlert` rows fired in the last 36 hours. LIVE
  rows are ranked and sized; SHADOW rows go to `research_only`.
- Directional: latest `DirectionalCandidate` batch. Directional is
  SHADOW, and its stored premium is a mid, so candidates are
  research-only and never sized.
- Covered Calls: middle tier only, for tickers in settings (shares
  already owned) plus tickers with assigned wheel positions. One chain
  fetch per ticker, capped at 5. A ticker with no chain returns an
  unavailable entry, never an invented strike.

## Sizing (portfolio simulator rules)

From `backtest_harness.SimulatorParams` defaults: risk 1% of equity
per trade, max heat 10%, max 10 concurrent positions, max 10% of
equity in one position's notional, risk halved at a 10% drawdown, new
entries paused at 15%.

- `risk_budget = equity * risk_pct`, halved at 10% drawdown, zero at 15%.
- `contracts = floor(risk_budget / max_loss_per_contract)`, capped by
  the single-position notional cap.
- Heat is the sum of max-loss dollars on open wheel positions plus the
  new items, capped at `max_heat_pct`. Anything that would breach a
  cap lands in `blocked` with the reason (`heat_cap`,
  `concurrency_cap`, `drawdown_pause`, `risk_budget_too_small`,
  `single_position_cap`); nothing is silently shrunk to fit.
- Covered calls are sized by shares owned (`shares // 100`), not by
  risk budget: no new capital goes in, so risk dollars are zero and
  the heat cap does not apply.
- Rank: premium per dollar at risk for puts/calls; premium yield on
  the share price for covered calls.

## Pricing assumptions (delayed data, spread haircut)

- A seller collects the bid, never the mid and never the last trade.
  A buyer pays the ask, never the mid.
- Estimated premium/cost applies a spread haircut of half the spread,
  against the trader (bid minus half the spread for a sale, ask plus
  half the spread for a buy).
- A spread wider than 25% of the mid makes the item untradable.
- A zero bid or zero ask means no tradable price exists. On the
  Massive Options Starter plan bid/ask can be 0.0; such items are
  unavailable and never sized. A mid is never used for sizing or roll
  math.
- Wheel recommendations store only the premium priced at the bid when
  the batch ran, with no ask, so no spread haircut can be computed
  for them; the card shows the delay note and the premium as collected
  at the bid.

## Account settings

`GET/PUT /api/today/settings` (single row, `today_settings`).
Defaults: $100,000 equity (the simulator default, or
`TRADEIQ_ACCOUNT_EQUITY` when set), risk 1%, max heat 10%, max 10
positions, max 10% per position. This is the main decision-support
account, deliberately separate from the $1,000 Challenge account.
`risk_pct` is clamped to 0.1-2%.

Drawdown is measured against `peak_equity`, the highest account
equity saved for this book. The peak only ever rises on a settings
save; the user updates account equity in settings as the account
changes. The drawdown brake is therefore a book-level brake, not the
Challenge account's drawdown.

## Claude explanations

Default is the quant template in `today_book.quant_explanation`
(2-3 sentences from computed numbers only). With
`?explain=claude`, the router calls
`ClaudeAnalyst.explain_today` after quant has ranked and sized
everything, via `ai_boundary.explain_or_fallback`. Any failure, or
any item Claude does not explain, keeps the quant text, and each item
labels its `explanation_source` (`quant` or `claude`). Claude never
sets a strike, entry, stop, rank, score, size, or recommendation.

## Tests

`backend/tests/test_today_book.py`: 16 tests pinning the pricing
rules (bid less half spread, zero bid/ask untradable, wide spread
untradable), the sizing caps (risk budget, single-position cap,
heat cap, concurrency cap, drawdown halve/pause), ranking, covered
call sizing by shares, and the risk bar.
