# Determinism audit: TradeIQ system and notifications

Date: 2026-10-27
Base commit: b8e12a0 (master after the Income tab merge)
Branch: review-determinism-phase1
Scope: whole app. 8 tabs in `frontend/src/App.jsx` (Today, Buy and Hold, Wheel,
Directional, Income, Book, Challenge, Setup Alerts), all 14 scheduled jobs in
`backend/scheduler.py`, every notification path, and every place the app or the
AI asks the user to decide, interpret, or guess.

Goal, in Rohit's words: take the majority of the thinking away from the user
and the AI, and make the system definitive.

Method: read the registry, the alert engine, the Challenge service, the
Directional and Wheel engines and scanners, the Discovery and Champions
engines, the Options engine, the scanner and flow engines, the market context,
the dividend path service, the scheduler, the Telegram notifier, and all 8
tabs. Verified by grep and by reading the code, not by running the live app.
Live proof still needs Rohit's Render deploy.

## 0. What is already deterministic (do not break this)

These parts already work the way Rohit wants, and the redesign should copy
their pattern instead of replacing them.

- Setup registry, `backend/services/setup_registry_service.py`. Nine setups
  with a written recipe each. LIVE requires a real-data backtest file stamped
  `PASSES`; anything else is forced to SHADOW. `get_status` fails closed to
  SHADOW for an unregistered setup. This is the best determinism in the app.
- Challenge write path, `backend/services/challenge_service.py:add_trade`.
  Per-trade cap, open-risk cap, max single position, pause rule, and cash are
  all enforced at the write path, and every rejection names the violated
  rule. Nothing is silently accepted.
- Challenge alert dedupe, same file. Event alerts dedupe permanently per
  source (`eligible_setup:<id>`), condition alerts dedupe per day. A second
  run creates nothing and sends nothing.
- Directional ranker, `backend/services/directional_ranker.py`. Rank is EV
  per dollar risked, expiry-consistent, with spread cost, and the limitation
  is stated in the code: P(profit) comes from the contract IV, so EV
  restates the market price and is not a forecast or an edge. Negative
  payoff at target suppresses the candidate.
- Market context, `backend/services/market_context.py`. VIX and regime
  thresholds are written numbers (VIX 15/25/35, SPY vs 50/200-day MA).
  Missing VIX or incomplete data can never GREEN-light a trade. Unknown
  blocks.
- Alert engine SPY gate, `backend/services/alert_engine.py`. Quality
  Pullback and Volume Breakout require SPY above its 200-day MA, and
  unknown blocks exactly like below. A gate-blocked candidate is recorded
  as suppressed with a reason instead of silently dropped.
- Wheel scanner pricing, `backend/services/wheel_scanner_service.py`. Put
  sales are priced at the bid, never a last trade. Spread over 15 percent
  excludes, only when the spread is known. No executable bid excludes with
  reason `incomplete_tier_data`. EV per contract is computed the same way
  in both modes.
- Dividend path scoring, `backend/services/dividend_path_service.py`.
  Fixed point weights (yield safety 30, growth, streak, coverage), fixed
  yield bands, base and bear projections from the same model. The Income
  slider re-projects through the backend model, it does not invent a second
  model in the frontend.
- 12-step verdict, `frontend/src/tabs/TwelveStepTab.jsx:decideVerdict`.
  Pure function: BUY needs 9 passes, margin of safety at least 20 percent,
  and a strong moat; WATCH needs 7 passes and at most 2 fails; otherwise
  AVOID. No live price means the verdict is BLOCKED, never guessed.
- Book scoreboard, `backend/routers/book.py`. Stats are hidden below 5
  settled outcomes and labelled preliminary below 30. A 4-of-5 win rate is
  never presented as confident.
- Day-trade snap, `backend/services/scanner_engine.py:apply_snaps`. A play
  whose option cannot be snapped to the real chain is dropped outright.
  Claude's invented entry premium can never be shown as a market price.
  Target and stop are labelled as Claude estimates and a hardcoded 50
  percent convention, not market levels.

## 1. Audit: scheduled jobs

14 jobs in `backend/scheduler.py:start_scheduler`. All Mon-Fri, all skip
NYSE holidays inside the job. Times are Eastern.

| Job | Time | What it does | Deterministic? | Gap |
|---|---|---|---|---|
| discovery_scan_daily | 06:00 | Buy-and-hold discovery, full universe, Claude picks top 10 | No. Claude selects the picks and writes DCF params from its own knowledge. Same inputs, different picks possible. | No written rule for what makes a pick. Fallback picks are just the top 10 by quant score, so Claude failing silently changes the list. |
| alert_outcome_daily | 08:00 | Settle open setup alerts on target/stop/time-stop | Mostly. Target/stop are on the alert row. | Some targets are invented prices (see W3). Settlement basis changed over time, old rows carry no settlement record. |
| champion_outcome_daily | 08:15 | Settle Champion picks at fixed horizon | Mostly. Horizon is fixed per strategy (30/21/90 days). | Settled on the underlying stock move because no contract was recorded at pick time. A pick can "win" while the option would have lost. |
| analysis_0900, _0945, _1200, _1500, _1800 | 09:00, 09:45, 12:00, 15:00, 18:00 | OptionsEngine + WheelEngine, each a Claude call | No. | Five Claude re-rankings a day, no dedupe, no rule for when a new recommendation replaces an old one. Recommendations accumulate; the user must decide which run to trust. |
| champions_daily | 09:10 | Champions scan, one batched Claude call, 3 picks | No. | Claude picks. SHADOW only, graded only, which is correct, but the picks themselves are not reproducible. |
| wheel_scanner_1030, _1400 | 10:30, 14:00 | Wheel put + call scanner, 607 tickers, EV ranked | Yes, for classic mode. | Only classic mode is scanned. Harvest mode is never populated by the scheduler; it only fills when the user manually refreshes in the tab. |
| call_suggestions_weekly | Tue 09:05 | Refresh covered-call suggestions | Unknown. | Weekly, Tuesday only, no written rule in the scheduler for which positions qualify. |
| challenge_snapshot_daily | 17:15 | Snapshot, stage graduation, Challenge alert generation | Yes, the math. | Runs 15 minutes BEFORE the alert engine (17:30), so Challenge alerts can only see yesterday's LIVE setups. A setup that fires today cannot alert until tomorrow. See fix F2 below. |
| alert_engine_daily | 17:30 | Evaluate all 9 setups, write alerts and suppressed rows | Yes, with exceptions in W1, W2, W4, W5. | No dedupe, no Telegram. See W1 and W6. |

Not scheduled at all, only on demand:

- DirectionalEngine (`backend/services/directional_engine.py:run`). Only
  runs from POST /api/options/directional/refresh, i.e. when a human clicks
  it. The Directional tab goes stale silently; there is no "last run" age
  shown as a block, and no job to refresh it.
- Day-trade scan (`backend/services/scanner_engine.py:run_scan`) and
  options-flow scan (`backend/services/options_flow_engine.py:run_flow_scan`)
  and momentum scan (`backend/services/momentum_scanner_service.py`).
  On demand from the Today tab. Flow scan shuffles its universe with
  `random.shuffle` and races futures against a 90 second timeout, so the
  top 20 depends on which tickers finish first. Same inputs, different
  output. Momentum does the same shuffle.
- Dividend path and CEF scans. On demand with a 202 scan-running response
  and a Postgres cache (fixed Oct 27). No scheduled refresh, so the Income
  tab can show a stale portfolio until someone opens it and triggers a scan.
- `run_status` (`backend/services/run_status.py`) is in-memory only. It is
  wiped on every restart or redeploy, so /api/status reads "idle" after a
  deploy even if jobs ran an hour earlier. Champions, discovery, dividend,
  CEF, and Challenge snapshot never report into it at all, so their
  failures are invisible in the app.

## 2. Audit: notifications

There is exactly one outbound notification path: Telegram, and only for
Challenge alerts.

- `backend/services/telegram_notifier.py:notify_new_alerts`. One batched
  message, at most 10 lines, each line is `- [severity] TICKER: title`.
  The title says a setup "fits your risk budget". It does NOT carry the
  action, the size, the entry, the stop, the target, or the expiry. The
  user must open the app to learn what to do. A notification that requires
  a second lookup is not definitive. See fix F1 below.
- Telegram is best-effort and silent on failure. A failed send logs a
  warning and returns False. Nothing retries, nothing tells the user a
  notification was lost. If Telegram is unconfigured, generation still
  creates the in-app alerts, which is correct, but there is no visible
  "notifications are off" state in the Challenge tab beyond a config flag.
- Setup alerts have no Telegram at all. A LIVE Quality Pullback fires at
  17:30 and the user hears nothing until the next day's Challenge pass, if
  it survives the 48-hour cutoff and the risk caps. There is no
  notification for a LIVE alert, and no notification for a run that
  produced nothing. Silence is ambiguous: it can mean "ran, nothing
  qualified", "job failed", "Telegram unconfigured", or "app was down".
  The app never distinguishes these for the user.
- Morning trade ideas live in chat, not in the app. They are graded on
  Fridays, which is good, but they are a second, separate alert system
  with no shared rule registry, no dedupe against app alerts, and no
  in-app record. A ticker can appear as a morning idea and as a setup
  alert with different strikes and no link between them.
- In-app Challenge alerts that are vague by construction:
  - Position review, up or down 75 percent of planned risk
    (`challenge_service.py:_gen_position_reviews`): "Review the position:
    take profit, trail the stop, or hold with intent." Three options, no
    rule for which one. The user does all the thinking.
  - Position review, within 10 percent of target: "Decide the exit before
    it gets there." No exit rule.
  - Drawdown past half the pause line: "Consider smaller size until the
    curve turns." No size rule. "Consider" is the opposite of definitive.
  - Expiry within 3 days: "Decide the exit now, not at the close on
    expiry day." No exit rule, no roll rule.

## 3. Audit: tabs, worst decision burdens first

### Today (MarketPulseTab)
- Three separate AI systems on one screen: day-trade scan (Claude picks,
  snapped to chain), options-flow scan (Claude interprets flow, shuffled
  universe, timeout race), momentum convergence (quant score plus Claude
  web-news enrichment). Each can name a different ticker with a different
  action. There is no rule for which one wins, and no ranking across them.
- Market verdict is deterministic (see section 0), but the strategy
  guidance text says "Consider adding to income positions gradually" and
  "Watch for a real bottom before adding". No amounts, no triggers.

### Buy and Hold (BuyHoldTab)
- Discovery picks are Claude-selected top 10 with `long_term_rec` of
  Strong Buy, Buy, Hold, or Pass. A "Buy" carries no size, no entry
  price, no invalidation, and no time horizon for the user. The DCF
  behind it uses Claude-set growth and margin parameters, so the same
  ticker can get a different fair value on different days for no
  market reason.
- The 12-step deep dive is mostly deterministic, except the moat step:
  the user ticks checkboxes for brand, lock-in, network effects, and so
  on, from their own judgment. The verdict depends on those ticks, so two
  honest users get different verdicts for the same company. The DCF tab
  also calls Claude for scenario parameters, with a mechanical fallback
  that produces different numbers when Claude is unavailable.

### Wheel (WheelTab)
- Two wheel systems in one tab. Old WheelEngine: Claude recommendations
  over 94 tickers, five runs a day, strikes snapped to the chain, premium
  at bid. New wheel scanner: deterministic EV ranking over 607 tickers,
  twice a day. Both are shown. The user must decide which list to trust,
  and they disagree.
- Mode toggle: classic wheel vs premium harvesting. Assignment is fine in
  one mode and the failure case in the other. The app does not recommend
  a mode for the account, the regime, or the ticker. The user picks a
  philosophy, then the scanner re-ranks everything under it.
- WheelCard warnings say "Consider waiting until after earnings" and
  "Consider skipping or reducing size" when a trade exceeds the position
  limit. No rule for how much to reduce, and no block: an over-limit
  trade can still be accepted.
- PositionTracker guidance has an action `close_or_roll` and a roll
  suggestion with `should_roll` and `action_plain`, but the underlying
  roll rule (when to roll, to which strike and expiry, for how much
  credit) is not a single written rule the user can check.

### Directional (OptionsTab)
- Two directional systems. OptionsEngine: Claude picks with a 60 percent
  qualitative / 40 percent quant combined score, Claude's entry, exit,
  stop, strike, and expiry preferred over the quant calculator
  (`options_engine.py:_store`: "prefer Claude's values; fall back to
  quant"). DirectionalEngine: deterministic EV ranking, manual refresh
  only, SHADOW. The tab shows both. The Claude system re-ranks five
  times a day; the deterministic system is stale unless clicked.
- The Directional tab also shows a "Fits Challenge" presentation tier
  that is not a rule: it does not create a Challenge trade and does not
  enforce the caps. A user can read "fits" as "do it".
- Directional grading is honest (0 percent win rate, negative P and L,
  on the record), but the candidates keep being shown with ranks and
  scores as if the ranking meant something. A SHADOW system with a 0
  percent win rate should be labelled as failing, not just SHADOW.

### Income (IncomeTab)
- Fixed Oct 27: crash guard, Postgres cache, slider. Remaining burden:
  the dividend portfolio is a scored list, but the slider's "where the
  money goes" is an allocation, not an order. There is no rule for when
  to buy (which day, what price, what to do if a holding cuts its
  dividend), and no alert when a holding's score drops or its yield
  moves into the trap band (9 percent plus scores 0, but the user is not
  told). CEF candidates are a scan list with no buy rule.
- The projection assumes yield stays flat and dividends grow at the
  growth rate, with no bear market and no dividend cut beyond the growth
  rate shown. That assumption is labelled, which is good, but there is no
  rule for what the user does when reality breaks the assumption.

### Book (BookTab)
- The scoreboard is the most honest surface in the app, and it is
  read-only grading. It does not feed back into any rule: a setup with a
  bad win rate keeps firing, a source with a good win rate gets no more
  weight. Grading and firing are disconnected.
- Champions are settled on the underlying stock move, not on an option
  contract, because no contract is recorded. Directional picks settled
  the same way before the fix. Any win rate built on the wrong basis is
  not a grade, it is a different trade.

### Challenge (ChallengeTab)
- The strongest deterministic surface (caps enforced at write, dedupe,
  snapshots). Remaining burdens are all manual: trade entry is a form
  the user fills in (symbol, quantity, entry, stop, target, planned max
  loss, expiry). An eligible alert carries a payload, but nothing
  pre-fills the form from the alert, so the user retypes numbers and can
  mistype them. Option marks are manual. The snapshot button is manual.
  "Not enough snapshots yet. Use Take Snapshot to start the curve."
  tells the user to do the system's job.

### Setup Alerts (AlertsTab)
- Shows LIVE and SHADOW alerts side by side, with a SHADOW pill. A
  SHADOW alert looks like a LIVE alert with a different colour. The user
  must remember that SHADOW means "do not trade this", and the tab does
  not enforce it anywhere.
- Suppressed candidates are listed with reasons, which is good, but the
  reasons include estimates ("spread_quality: estimated") and
  approximations that the user cannot verify from the card.

## 4. Worst offenders, ranked

W1. Alert engine has no dedupe or cooldown.
`alert_engine.py:run_alert_engine` inserts a new SetupAlert row for every
firing ticker on every run, with no check for an identical open alert.
Run it twice, manually or after a restart, and the same setup appears
twice. `routers/alerts.py:get_today_alerts` then shows both (36-hour
window). The Challenge dedupe exists downstream, but the Alerts tab and
the journal do not have it. Fix: dedupe key
`setup_key:ticker:signal_date:entry:invalidation`, one open alert per key,
re-fire only when the signal is new or the price re-enters after the
invalidation.

W2. Earnings unknown is fail-open.
`alert_engine.py:_eval_quality_pullback` and the other evaluators treat
`earnings_days is None` as "no earnings within 5 days". A Finnhub failure
therefore green-lights a trade that the rule would have blocked. The SPY
gate in the same file is fail-closed; earnings should match it. Same
pattern in `_eval_premium_at_support`, `_eval_volume_breakout`,
`_eval_oversold_bounce`, `_eval_trend_pullback_reversal`, and
`_eval_post_earnings_drift`. Fix: unknown earnings blocks, and the
suppressed reason says "earnings date unknown".

W3. Targets and stops are invented in the alert engine.
`alert_engine.py:_build_stock_action`: Quality Pullback target is price
times 1.08 with the comment "approximate; RSI target not expressible as
price". Oversold Bounce target is price times 1.07. Trend Pullback
invalidation is price minus half an ATR, labelled "below signal-day low
approx". The entry is "next open estimate". These look like precise
numbers and feed the Challenge sizing math, but they are placeholders.
Fix: only publish a target when the rule defines one (Volume Breakout:
entry plus 2 times ATR, which is real). Otherwise publish the real exit
rule (RSI above 68, RSI above 50) and no target price, and mark the
alert as having no price target instead of inventing one.

W4. Two setups do not implement their own recipe.
Trend Pullback Reversal: `alert_engine.py:_eval_trend_pullback_reversal`
sets `prev_rsi_est = rsi` with the comment "we don't store yesterday's
RSI in real time; note limitation", then treats RSI between 40 and 55 as
"turning up". RSI in a band is not turning up. Post-Earnings Drift:
`_eval_post_earnings_drift` fires on gap-held plus HV below 35 percent
and records `earnings_beat_guidance_raised` as
"not_checked_requires_news_feed". The registry recipe requires a beat
and raised guidance. Both setups fire on a subset of their stated rule
and are SHADOW, which limits the damage, but the gap between recipe and
code is exactly the kind of thing that gets promoted to LIVE by mistake.
Fix: either implement the missing check or rewrite the recipe to the
check that actually runs, and keep both SHADOW until a real backtest
passes.

W5. Premium at Support uses an HV proxy as IV.
`alert_engine.py:_eval_premium_at_support`: when no IV percentile is
available, HV above 30 percent counts as "IV high". The options action
is priced by Black-Scholes with HV as IV, a 30-delta strike guessed as
95 percent of price, and an expiry of today plus 37 days, which may not
be a listed expiry. `spread_quality` is "estimated". The wheel scanner
already does this correctly from the listed chain; the alert engine
should use the listed chain or suppress. Fix: no listed chain, no wheel
alert, with reason "no listed chain".

W6. Challenge snapshot runs before the alert engine.
`scheduler.py`: snapshot 17:15, alert engine 17:30. Challenge alert
generation runs inside the snapshot, so eligible-setup alerts can only
see setups fired up to yesterday, and only within a 48-hour cutoff.
A LIVE setup that fires today waits a day to alert, and a setup that
fires late in the window can age out. Fix F2 in this branch adds a
17:35 Challenge-alert pass after the engine, keeping the 17:15 snapshot
where it is.

W7. Telegram carries no instruction.
See section 2. A notification that says "fits your risk budget" and
nothing else forces the user to open the app and re-derive the trade.
Fix F1 in this branch puts the alert body (shares, entry, stop, target)
into the Telegram message.

W8. Claude decides entry, exit, strike, and rank in the live path.
`options_engine.py:_store` prefers Claude's values over the quant
calculator, with a 60/40 qual/quant combined score. `wheel_engine.py`
asks Claude to pick wheel recommendations. `discovery_engine.py`
asks Claude to pick top 10 and set DCF parameters. `dcf_service.py`
asks Claude to set bear/base/bull parameters. `champions_engine.py`
asks Claude to pick 3. The day-trade, flow, and momentum scanners all
ask Claude to interpret or pick. None of these outputs is reproducible,
none has a written threshold, and a Claude failure silently changes the
output (fallback picks, mechanical DCF, or an empty list). The
scanner_engine snap fix proves the right pattern: Claude proposes,
the chain disposes. That pattern is not applied anywhere else. Fix:
Claude writes explanations and theses only. Entry, stop, target, size,
and rank come from quant rules, and any Claude number that disagrees
with the quant rule or the listed chain is dropped, not shown.

W9. Four directional systems, two wheel systems, no winner.
OptionsEngine vs DirectionalEngine vs day-trade scanner vs momentum
scanner; WheelEngine vs wheel scanner. Each has its own universe (94
vs 607 tickers), its own refresh cadence (5 times a day vs twice a day
vs manual vs on demand), and its own scoring. The user is the
integration layer. Fix: one canonical system per decision, the others
either feed it as evidence or are removed. DirectionalEngine is the
canonical directional system (deterministic EV). The wheel scanner is
the canonical wheel system (listed chain, bid pricing). The rest become
research views, clearly labelled, and never alert.

W10. Silence is ambiguous.
No "nothing qualified" signal, no run receipt, no failure notice. A
morning with zero alerts looks identical to a morning the scheduler
died. `run_status` is in-memory and incomplete (see section 1). Fix:
persist run status in Postgres, report every job, and show one line in
the app per job: last run, result, tickers evaluated, alerts fired,
next run. Telegram gets a failure notice only, not a daily "all clear"
unless Rohit asks for it; the in-app receipt is the source of truth.

W11. Position reviews and wheel warnings tell the user to decide.
"Take profit, trail the stop, or hold", "Consider smaller size",
"Consider waiting", "Decide the exit now". Each of these needs a rule:
at 75 percent of planned risk, the rule is X; at expiry minus 3 days,
the rule is Y; over the position limit, the trade is blocked or sized
to the limit, not "considered". Fix: replace every "consider/decide/
review" alert body with one imperative and its numbers, or do not send
the alert.

W12. Stale docs and stale counts.
`docs/scoring-systems-inventory.md` describes six scoring systems and
references files that no longer exist (`routers/triggers.py`,
`services/advanced_scanner_service.py`, StockTriggersTab.jsx) and a
scheduler line that is not in the current scheduler. `routers/alerts.py`
says "all six setups" while the registry seeds nine. The README says
six setups and describes a Leveraged Signals tab that was removed. A
user or a future agent reading the docs will build on rules that do not
exist. Fix: rewrite the inventory from the code, and generate the setup
count from the registry instead of hardcoding it.

## 5. Proposed deterministic design

### 5.1 Rule registry: one place where every rule lives

Extend the existing setup registry pattern, which already works, instead
of inventing a second system. New table `rule_registry`, one row per
alert or notification rule, plus a service
`backend/services/rule_registry.py` and a read-only endpoint
GET /api/rules. Every rule row carries:

- `rule_key`: stable id, e.g. `challenge.eligible_setup`,
  `alert.quality_pullback`, `wheel.spread_too_wide`,
  `challenge.position_review_75pct`.
- `name`: plain-language name.
- `trigger`: the exact condition, as code and as text. Thresholds are
  numbers in the row, not literals buried in functions.
- `universe`: which tickers it runs over, by name (S and P 500 list,
  Dividend Achievers, DEFAULT_UNIVERSE, watchlist).
- `action`: the exact imperative the alert will carry, with placeholders
  for ticker, size, entry, stop, target, expiry.
- `size_rule`: how size is computed (1 percent risk, per-trade cap,
  open-risk cap, max single position), and the fallback when size cannot
  be computed (suppress, do not guess 1 unit).
- `invalidation`: the exact condition that kills the idea, and the price
  or event that expresses it.
- `expiry`: when the alert itself expires (signal date plus N sessions,
  option expiry, time stop).
- `cooldown`: minimum time before the same rule can fire again for the
  same ticker, and the dedupe key format.
- `status`: LIVE, SHADOW, RETIRED, enforced the same way the setup
  registry enforces LIVE (real-data backtest PASSES on file).
- `source`: the function that implements it, e.g.
  `alert_engine._eval_quality_pullback`, so the row and the code cannot
  drift apart silently. A startup check fails the deploy if a LIVE rule
  has no implementing function or its thresholds differ from the row.
- `last_fired_at`, `fired_count`: for audit, not for decisions.

Rules that are not in the registry cannot fire and cannot notify. If a
rule is not written down, it does not exist in the live path.

### 5.2 Alert contract: every alert must carry these fields, or it is suppressed

- action: one imperative verb phrase, e.g. "Buy 12 shares at $50.20".
- size: units and dollars, computed by the size rule, with the equity
  source named (challenge, env, default). No silent 1-unit fallback.
- entry: a real price (next open estimate labelled as an estimate, or a
  listed contract premium with its source: bid, ask, last trade, fair
  value).
- invalidation: price and condition, e.g. "close below $48.10, the
  200-day MA".
- target or exit rule: a real price target when the rule defines one,
  otherwise the exit rule in words ("exit when RSI(14) exceeds 68") and
  no invented target price.
- expiry: option expiry or time stop, as a date.
- reason: the exact conditions that fired, with their values
  ("RSI 52, was 63 three sessions ago; volume 0.8x average; SPY 1.2
  percent above its 200-day MA").
- rule_key and status: so the user can see which rule fired and whether
  it is LIVE or SHADOW. SHADOW alerts never appear in the same list as
  LIVE alerts without a visible SHADOW label, and never create a
  Challenge alert or a Telegram message.
- suppressed_reason: when a candidate almost fires, the reason is stored
  and shown, so "nothing fired" is checkable.

### 5.3 Notification contract

- Telegram sends the full instruction, not a pointer to it: ticker,
  action, size, entry, stop, target, expiry, invalidation, and reason.
  One message per rule fire, batched per run, at most 10 alerts, body
  truncated so the message stays under the Telegram limit.
- Dedupe is permanent for event alerts and per-day for condition alerts,
  as the Challenge service already does. The alert engine adopts the
  same dedupe keys.
- Failure is visible: if Telegram fails, the failure is recorded in the
  persistent run status and shown in the app. No silent loss.
- Silence means "ran, nothing qualified". That claim is only made when
  the run receipt exists (section 5.4). No receipt, no claim.
- Morning ideas stay in chat, but they adopt the same alert contract
  (action, size, entry, invalidation, expiry, reason) and are logged
  against the same rule keys where they overlap, so a Friday grade can
  compare the idea against the app alert for the same ticker.

### 5.4 Run receipts: make "nothing happened" checkable

- Move `run_status` from in-memory to a Postgres table `run_receipts`.
  One row per job run: job id, started at, finished at, state (ok,
  error, skipped_not_trading_day), tickers evaluated, alerts fired,
  shadow hits, suppressed count, errors (first 50), duration.
- Every scheduled job and every on-demand engine writes a receipt,
  including champions, discovery, directional, dividend, CEF, and
  Challenge snapshot. A job with no receipt is a job that did not run.
- The app shows one line per job in the Today tab or a System tab:
  last run, result, counts, next run. No separate page of logs is
  needed; one line per job is enough.

### 5.5 AI boundary

- AI writes explanations, theses, and plain-language summaries only.
- AI never sets entry, stop, target, size, rank, or a DCF parameter that
  flows into a number shown as a price or a verdict, unless the value is
  validated against the quant rule or the listed chain and dropped when
  it disagrees. The scanner_engine snap pattern is the template.
- Discovery and Champions stay SHADOW research views until their picks
  pass the same real-data backtest gate as the setups. Their output is
  labelled "research, not a rule" wherever it appears.
- DCF scenario parameters come from the mechanical model by default.
  Claude parameters, if kept, are shown alongside the mechanical ones
  with their source labelled, never silently substituted.
- The 12-step moat checkboxes are replaced by a deterministic proxy or
  removed from the verdict math: the verdict must be computable from
  fetched data alone, so the same ticker gives the same verdict for
  every user. If a moat cannot be measured from data, it becomes a note,
  not a verdict input.

### 5.6 Fail-closed everywhere

- Earnings date unknown blocks. IV unknown blocks or suppresses with a
  reason. Price unknown blocks the verdict (already done in 12-step).
  Stale data blocks (market context already does this for SPY; extend
  the same freshness check to every feed).
- A missing feed is a suppressed candidate with a reason, never a pass.
- A rule whose implementing function and registry row disagree fails
  startup in a visible way, instead of firing on the wrong thresholds.

### 5.7 One canonical system per decision

- Directional: DirectionalEngine (deterministic EV, listed chain).
  OptionsEngine becomes a research view, labelled as Claude-ranked, and
  stops writing Recommendation rows that the tab presents as trades.
  It gets a scheduled refresh, so it is no longer manual-only.
- Wheel: wheel scanner (607 tickers, EV, bid pricing). WheelEngine
  becomes a research view or is removed. One universe, one ranking.
- Today: one ranked list, with day-trade, flow, and momentum as evidence
  columns on the same candidates, not three separate lists. Flow and
  momentum lose the `random.shuffle` and the timeout race: fixed order,
  fixed timeout, partial results labelled partial.
- Mode choice (classic vs harvest) is made once by a rule, not per
  visit: default classic, harvest only when the account rule says so
  (e.g. assignment is not wanted for that ticker), and the mode is
  shown on every card so the user never has to remember which mode they
  are in.

## 6. Ranked build plan

P0, removes the most user thinking first, small and safe:

1. Telegram carries the full instruction (fix F1, in this branch).
   Also apply the same body-in-message change to any future notifier.
2. Challenge-alert pass after the alert engine (fix F2, in this branch).
   17:35 daily, dedupe makes it safe.
3. Alert-engine dedupe and cooldown (W1). One open alert per
   setup/ticker/signal. Stops duplicate cards and duplicate journal rows.
4. Earnings unknown blocks (W2). Five evaluators, one-line change each,
   plus a suppressed reason. Removes a fail-open that can put real money
   at risk.
5. Replace "consider/decide/review" alert bodies with one imperative and
   its numbers (W11), starting with position reviews and drawdown.
   No new math, just writing the rule that is already implied.

P1, needs a redesign of one surface at a time:

6. Rule registry (section 5.1) plus the alert contract (5.2), starting
   with the 9 setups and the 5 Challenge alert types. Migrate thresholds
   out of function literals into registry rows, with the startup check.
7. Persistent run receipts (5.4) and one-line-per-job system status in
   the app. This is what makes "nothing fired" trustworthy.
8. Remove invented targets and stops (W3) and implement-or-rewrite the
   two recipe gaps (W4), plus listed-chain-or-suppress for Premium at
   Support (W5).
9. Consolidate Directional to one system and Wheel to one system (W9),
   and put Directional on the scheduler instead of manual refresh.
10. Notification contract (5.3): failure visibility, "notifications off"
    state, and a single daily run receipt. Do not add a daily "all clear"
    Telegram unless Rohit asks for it.

P2, larger, do after P0 and P1 prove out:

11. AI boundary (5.5): Claude to explanations only, quant rules for
    entry/stop/size/rank, DCF mechanical by default, moat out of the
    verdict math.
12. Book feedback loop: a setup whose graded win rate is below its
    backtest, or below a written floor, is demoted to SHADOW
    automatically, and the demotion is shown with its numbers. Grading
    then changes what fires, instead of only reporting it.
13. Income buy rule: when to buy, what to do on a dividend cut or a
    score drop, and an alert when a holding enters the trap band.
    The slider already projects; the missing piece is the action rule.
14. Docs rewrite (W12): regenerate the scoring inventory from the code,
    derive setup counts from the registry, and delete references to
    removed tabs and services.

## 7. Small fixes in this branch

F1. Telegram carries the alert body.
`backend/services/telegram_notifier.py:notify_new_alerts` now appends
each alert's body on the line after its title, truncated to 220
characters with newlines stripped, so the message carries the shares,
entry, stop, and target the Challenge service already computed. The
existing title line format is unchanged, so the existing Telegram test
still passes. Total message is capped at 4000 characters.

F2. Challenge-alert pass after the alert engine.
`backend/scheduler.py`: new job `challenge_alerts_after_engine`,
Mon-Fri 17:35 Eastern, calls `run_challenge_alerts_job`, which calls
`challenge_service.generate_challenge_alerts` and logs how many were
created. The 17:15 snapshot is unchanged, so Rohit's 17:45 Challenge
check still sees the snapshot, and the 17:30 alert engine's LIVE setups
can now alert the same evening. Dedupe keys make the second pass safe:
alerts created at 17:15 are not recreated at 17:35.

Tests: new stub test `~/workspace/.tiq-test/test_determinism_phase1.py`
covers F1 (body present, title format unchanged, empty batch sends
nothing, 4000-char cap) and F2 (job registered, runs at 17:35, after
`alert_engine_daily` at 17:30, snapshot still 17:15). Existing Telegram
test and scheduler test still pass.

## 8. What this phase deliberately did not do

- No merge and no deploy. Branch only.
- No registry table, no alert-contract migration, no consolidation of
  Directional or Wheel, no AI-boundary change. Those are P1 and P2 above
  and need Rohit's go-ahead per item, because each one changes what the
  app shows or fires.
- No change to Challenge risk caps, LIVE/SHADOW statuses, or the
  backtest gate. Those are correct as they are.
- No new Telegram messages beyond the body lines in F1, and no daily
  "all clear" message. Silence still means silence until run receipts
  exist.

## Appendix: inventory counted on 2026-10-27

- Tabs in `frontend/src/App.jsx`: 8.
- Registry setups in `setup_registry_service.py:_SETUPS`: 9. The router
  docstring and the README say six; that count is stale.
- Scheduled jobs in `scheduler.py:start_scheduler`: 14.
- Notification paths: 1 (Telegram, Challenge alerts only).
- Engines that call Claude in the live path: OptionsEngine,
  WheelEngine, Discovery, Champions, DCF service, day-trade scanner,
  options-flow engine, momentum scanner, directional explainer (top 3
  summaries only, display only).
- Engines with no scheduled job: DirectionalEngine, day-trade scanner,
  options-flow scanner, momentum scanner, dividend path, CEF scan.
- Randomness in the live path: `options_flow_engine.py:random.shuffle`
  plus a 90 second future race; `momentum_scanner_service.py:
  random.shuffle` for partial runs. `dcf_service.py` uses a seeded
  RNG (seed 42) for Monte Carlo, which is reproducible.
