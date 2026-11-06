# AI Picks

An ideas-only research surface, completely separate from the quant system.

## The separation, stated plainly

AI Picks is the one place in the app where Claude is allowed to suggest
tickers, strikes, entries, exits, and a thesis. That is the whole point
of the section, and it is why the section is fenced off:

- **No registry, no backtest, no LIVE.** The AI Picks service and
  router import nothing from the setup registry, the backtest harness,
  or the Book scoreboard. Ideas are never marked LIVE and never appear
  in Today's Book. A test (`test_ai_picks_modules_do_not_import_quant_enforcement`)
  enforces this by AST: no quant-enforcement imports, no LIVE status
  anywhere in the modules.
- **No sizing.** AI Picks ideas carry no contract counts, no dollars
  at risk, and no portfolio heat. They are ideas, not sized trades.
- **Labelled everywhere.** Every idea card carries an AI-GENERATED
  IDEA badge, and the view opens with the disclaimer: "These are
  AI-generated ideas only. They are not based on the app's backtested
  rules and are not recommendations."

The rule-based AI boundary (Claude explains only, never decides) still
applies to every other path in the app. AI Picks is a deliberate,
user-authorized exception, confined to this section.

## Data shapes

### POST /api/ai-picks/generate

Request: `{ "tickers": ["MSFT", "NVDA"] }` (optional; defaults to 10
liquid names: MSFT, NVDA, AAPL, AMZN, META, GOOGL, TSLA, AMD, PLTR, XOM).

Generation runs in a background thread (Claude plus Polygon context
takes tens of seconds), so POST returns immediately:

```json
{ "run_id": 1, "status": "generating", "tickers": ["MSFT"] }
```

### GET /api/ai-picks/latest

```json
{
  "run": {
    "id": 1,
    "created_at": "2026-11-05T...Z",
    "tickers": ["MSFT"],
    "status": "completed",
    "error": null,
    "disclaimer": "These are AI-generated ideas only. ...",
    "data_note": "Prices and chain data are delayed about 15 minutes. ...",
    "options_ideas": [
      {
        "ticker": "MSFT", "option_type": "call", "action": "buy",
        "strike": 550, "expiry": "2026-12-18",
        "entry_price": 5.20, "exit_price": 9.00, "stop_price": 2.50,
        "plan_text": "Buy in at $5.20, get out at $9.00. ...",
        "reasoning": "...", "key_risks": ["..."],
        "reference_price": 512.34, "price_source": "polygon",
        "ai_generated": true
      }
    ],
    "long_term_ideas": [
      {
        "ticker": "MSFT", "company_name": "Microsoft",
        "current_price": 512.34, "price_source": "polygon",
        "thesis": "...", "key_risks": ["..."], "upside_case": "...",
        "ai_generated": true
      }
    ],
    "parse_error": null,
    "context_as_of": "2026-11-05T...Z"
  },
  "generating": false
}
```

`price_source` is `polygon` when the price came from a Polygon
snapshot, `ai_claimed` when only Claude's claimed price was available,
and `unavailable` when neither had one (the price then shows as a dash).

`status` is `generating`, `completed`, `completed_with_warnings`
(Claude's JSON was partly unusable), or `failed`.

### GET /api/ai-picks/runs

The last 5 runs, same shape as `run` above.

## How generation works

1. `services/ai_picks.build_context(tickers)` builds the context from
   Polygon, best-effort throughout: a batch equity snapshot (price,
   day change, volume), 35 days of daily bars summarized to 5/20-day
   returns, 35-day high/low, and volume versus its average, up to 3
   recent headlines per ticker, the VIX, and a small delayed
   near-the-money chain summary. A failed fetch narrows the context;
   it never invents data.
2. `ClaudeAnalyst.generate_ai_picks(context)` asks Claude, as a
   professional trader, to return structured JSON only: up to 6
   options ideas and exactly 10 long-term stock ideas.
3. `parse_ai_picks_response` validates the JSON: malformed ideas are
   dropped, the long-term list is truncated to 10, and a missing or
   invalid price stays null.
4. `apply_polygon_prices` overwrites AI-claimed prices with Polygon
   snapshot prices where available, including for long-term tickers
   Claude added beyond the context list (one extra batch snapshot).
5. The run is stored in the `ai_pick_runs` table, so the page can show
   the last generation without re-calling Claude on every load. The
   frontend polls every 5 seconds while a run is generating.

## Assumptions and limitations

- **Delayed data.** Prices and chain data are about 15 minutes
  delayed. On the Massive Options Starter plan, option bid/ask quotes
  are often 0.0, so a suggested strike is an AI proposal, not a
  verified tradable price. The view says so, and a strike must be
  checked against the live chain before anyone acts on it.
- **Long-term prices.** For tickers Claude suggests beyond the context
  list, the price is fetched in one batch snapshot after generation;
  if that fetch fails, the model-claimed price is shown labelled
  `ai_claimed`, and a missing price shows as unavailable.
- **Claude may return fewer than 10 long-term ideas** if its JSON is
  partly unusable; the run is then marked `completed_with_warnings`
  and the usable ideas are shown. It never pads the list.
- **No live Claude call in the sandbox.** The sandbox has no
  Anthropic key, so live generation is unproven here. The endpoint
  flow was smoke-tested with a stubbed Claude and a stubbed Polygon
  context; live proof is a real generation after Rohit's Render
  deploy, checking that options ideas and 10 long-term ideas render
  with Polygon prices.
- **Today's Book is unchanged.** `/api/today` and the Today's Book
  view shipped in master `e79176e`; this branch only adds AI Picks
  alongside it.
