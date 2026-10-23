# Scoring Systems Inventory

Six distinct scoring systems exist in the backend that answer some form of "which stocks deserve attention." This document maps each one: what it computes, every caller inside the codebase, which major subsystems depend on it, and whether removing it would break anything.

---

## 1. quant_scorer (`services/quant_scorer.py`)

**What it computes:** Pure mathematical scores from pre-fetched technical indicator data. No API calls, no AI. Exposes three functions used by callers:

- `compute_wheel_quant_score(tech)` -- returns a 0-100 score and verdict (PASS/FAIL/INSUFFICIENT) for a put-selling candidate, using IV percentile, distance from 50-day MA, spread width, ADR%, and earnings proximity.
- `compute_entry_exit_options(ticker, tech, direction)` -- returns entry, target, stop, and max risk fields for a directional options trade.
- `compute_entry_exit_wheel(ticker, tech)` -- returns entry/exit fields for a wheel trade.

Also contains option-pricing helpers (`estimate_atm_premium`, `_round_strike`, `_round_premium`) and Black-Scholes math used by the wheel engine.

**Callers:**

| File | Function used | Purpose |
|---|---|---|
| `services/wheel_engine.py` | `compute_wheel_quant_score`, `compute_entry_exit_wheel` | Builds wheel recommendation rows |
| `services/wheel_scanner_service.py` (line 124) | `compute_wheel_quant_score` | Quality gate -- candidates below the score threshold get verdict FAIL and are excluded from the scanner output |
| `services/options_engine.py` (lines 10, 176) | `compute_entry_exit_options` | Builds directional recommendation rows |
| `services/directional_engine.py` (line 31) | `compute_entry_exit_options` | Builds directional candidate rows used by Phase 3A ranker |

**Depends on it:**
- Phase 2C wheel scanner quality gate: yes -- `_quality_gate()` in `wheel_scanner_service.py` calls `compute_wheel_quant_score` directly. If quant_scorer is removed, the quality gate falls back to the `"no_data"` / `"error"` path (verdict UNGATED), which lets all candidates through regardless of quality. That is a behavior change, not a crash.
- Phase 3A directional ranker: yes -- `compute_entry_exit_options` supplies the entry/target/stop fields that are stored on `DirectionalCandidate` rows and displayed in the Directional tab. Removing it would cause `AttributeError` at runtime in both `options_engine.py` and `directional_engine.py`.
- Phase 2B alert engine: no.
- Book scoreboard: no.

**Safe to remove without breakage:** No. Three active code paths would error.

---

## 2. trigger_service (`services/trigger_service.py`)

**What it computes:** A 0-9 trigger score per ticker combining Monte Carlo DCF undervaluation (up to +2), 50-day MA crossover with volume confirmation (up to +2), earnings calendar proximity (+1), bear-case downside (+1), base-case upside (+1), and relative strength vs SPY (+1).

Results are cached per-ticker for 4 hours.

**Callers:**

| File | Function used | Purpose |
|---|---|---|
| `routers/triggers.py` (line 13) | `analyze_trigger` | Serves `GET /api/triggers/{ticker}` -- powers the trigger score card in the Stock Triggers tab |
| `services/advanced_scanner_service.py` (line 258) | `_fetch_ma_data`, `_calculate_score` | Stage 2 scoring in the Big Mover scanner |
| `services/top_rated_scanner_service.py` (line 190) | `_fetch_ma_data`, `_calculate_score` | Stage 2 scoring in the Top Rated scanner |

**Depends on it:**
- Stock Triggers tab: yes -- the `GET /api/triggers/{ticker}` endpoint is the sole data source for the per-ticker trigger score card.
- Top Rated scanner (serves the Stock Triggers tab): yes -- without trigger scoring the top-rated scan would have no stage-2 scoring and would return empty results.
- Advanced scanner Big Mover scan (serves the Stock Triggers tab): yes -- same.
- Phase 2B alert engine: no.
- Phase 2C wheel scanner: no.
- Phase 3A directional ranker: no.
- Book scoreboard: no.

**Safe to remove without breakage:** No. The Stock Triggers tab and both scanner scans depend on it.

---

## 3. discovery_engine (`services/discovery_engine.py`)

**What it computes:** A multi-factor percentile-normalized score across a ~300-ticker universe, looking for two patterns:
- Next Compounders: high-growth, high-margin, accelerating revenue, price momentum.
- Sleeper Picks: profitable, wide moat, low valuation, high ROIC, overlooked.

Results are cached in memory for 24 hours. The scan runs in a background thread triggered by `GET /api/discovery` or `POST /api/discovery/refresh`.

Also exposes `_wacc_from_beta`, `_reverse_dcf`, and `_run_dcf` as DCF utilities reused by other services.

**Callers:**

| File | Function used | Purpose |
|---|---|---|
| `routers/discovery.py` | `get_state`, `trigger_scan` | Serves the discovery API endpoints |
| `services/dcf_service.py` (line 20) | `_wacc_from_beta`, `_reverse_dcf`, `_run_dcf` | DCF math used by the DCF router (individual ticker DCF in 12 Step) |
| `services/top_rated_scanner_service.py` (line 192) | `_wacc_from_beta`, `_run_dcf` | DCF component of the top-rated scanner's stage-2 trigger score |
| `frontend/src/api.js` (line 105) via `BuyHoldTab.jsx` | `GET /api/discovery` | Buy and Hold tab shows discovery results as a candidate list for 12 Step deep-dives |

**Depends on it:**
- Buy and Hold tab discovery section: yes -- `BuyHoldTab.jsx` polls `GET /api/discovery` and displays compounders/sleepers lists. If the discovery endpoint is removed, that section shows its "No discovery results yet" fallback, which is graceful.
- DCF service (12 Step tab): yes on the DCF math helpers. Removing the whole module would break `dcf_service.py` imports.
- Top Rated scanner: yes on DCF helpers.
- Phase 2B alert engine: no.
- Phase 2C wheel scanner: no.
- Phase 3A directional ranker: no.
- Book scoreboard: no.

**Safe to remove without breakage:** No. DCF math reuse in two places would cause import errors. The scan feature itself could be extracted without those helpers if needed.

---

## 4. advanced_scanner_service (`services/advanced_scanner_service.py`)

**What it computes:** Two scans:
- Dividend Income Scanner: filters the Dividend Achievers universe (~270 tickers) on yield, payout ratio, revenue growth, market cap, and gross margin; ranks survivors by trigger score. Results cached to `/tmp/cache_dividend_scan.json` for 24 hours.
- Big Mover Scanner: filters S&P 500 + Nasdaq 100 (~500 tickers) on Polygon volume then Finnhub fundamentals; ranks survivors by `(Monte Carlo % x base case upside)`. Results cached to `/tmp/cache_mover_scan.json` for 24 hours.

**Callers:**

| File | Function used | Purpose |
|---|---|---|
| `routers/advanced_scanner.py` (lines 10, 19, 30, 43) | `get_scan_status`, `_load_cache`, `launch_scan_background` | Serves the Dividend Income and Big Movers endpoints in the Stock Triggers tab |
| `scheduler.py` (line 171) | `run_dividend_scan`, `run_mover_scan` | Scheduled background refresh |

**Frontend:** The Stock Triggers tab (`StockTriggersTab.jsx`) calls `GET /api/advanced-scanner/movers` and `GET /api/advanced-scanner/status/movers`.

**Depends on it:**
- Stock Triggers tab Big Movers section: yes.
- Scheduler: yes, but removing it only means the scheduled jobs fail silently.
- Phase 2B alert engine: no.
- Phase 2C wheel scanner: no.
- Phase 3A directional ranker: no.
- Book scoreboard: no.

**Safe to remove without breakage:** No. The Stock Triggers tab Big Movers section would return 404s. The Dividend Income scanner section would also fail.

---

## 5. top_rated_scanner_service (`services/top_rated_scanner_service.py`)

**What it computes:** Finds S&P 500 + Nasdaq 100 stocks scoring 6 out of 8+ on the trigger system. Two-stage funnel: Polygon batch snapshot filter (price >= $15, volume >= 1M) then Finnhub fundamentals filter, then full trigger scoring on approximately 80 survivors.

Results cached to `/tmp/scan_top_rated_result.json` for 24 hours.

Also exposes `_load_universe()`, which is reused by the momentum scanner.

**Callers:**

| File | Function used | Purpose |
|---|---|---|
| `routers/top_rated_scanner.py` | `_load_result_cache`, `get_scan_status`, `launch_scan_background` | Serves `GET /api/top-rated/*` endpoints |
| `services/momentum_scanner_service.py` (line 39) | `_load_universe` | Borrows the S&P 500 + Nasdaq 100 universe list |
| `scheduler.py` (line 194) | `run_top_rated_scan` | Scheduled background refresh |

**Frontend:** `StockTriggersTab.jsx` calls `GET /api/top-rated/results` and related endpoints. The Stock Triggers tab's "Top Rated" section depends on this service.

**Depends on it:**
- Stock Triggers tab Top Rated section: yes.
- Momentum scanner: yes on `_load_universe`. If removed, momentum scanner import would fail.
- Phase 2B alert engine: no.
- Phase 2C wheel scanner: no.
- Phase 3A directional ranker: no.
- Book scoreboard: no.

**Safe to remove without breakage:** No. Two callers would break.

---

## 6. momentum_scanner_service (`services/momentum_scanner_service.py`)

**What it computes:** Finds S&P 500 + Nasdaq 100 stocks with 3 or more independent signals firing in the same 21-day rolling window. Signals: unusual options flow via Polygon (0-2 pts), insider cluster buying via Finnhub (0-2 pts), pre-earnings drift vs SPY (0-2 pts). Returns top 10 by score. Results cached to `/tmp/cache_momentum_scan.json` for 6 hours.

**Callers:**

| File | Function used | Purpose |
|---|---|---|
| `routers/momentum.py` | `_cache_read`, `get_scan_status`, `launch_scan_background` | Serves `GET /api/momentum/*` -- the Momentum tab |
| `services/directional_engine.py` (line 448) | `MomentumScannerService` | Directional engine reads the current momentum scan cache to annotate candidates with convergence signals |

**Frontend:** `MomentumTab.jsx` calls `GET /api/momentum/alerts` and related endpoints. The Momentum tab is entirely backed by this service.

**Depends on it:**
- Momentum tab: yes.
- Phase 3A directional ranker: yes. `directional_engine.py` instantiates `MomentumScannerService()` to read the cache. If the service is removed, the import at line 448 would raise an `ImportError` at the point it is executed (it is a lazy import inside a method, so the error would surface at runtime when a directional scan runs, not at startup).
- Phase 2B alert engine: no.
- Phase 2C wheel scanner: no.
- Book scoreboard: no.

**Safe to remove without breakage:** No. The Momentum tab and the directional engine annotation step would both fail.

---

## Summary table

| System | Active screens | Safe to remove |
|---|---|---|
| quant_scorer | Wheel tab, Directional tab (via engines + scanner quality gate) | No -- multiple callers would error |
| trigger_service | Stock Triggers tab (per-ticker scores, top-rated scan, big movers scan) | No -- Stock Triggers tab would fail |
| discovery_engine | Buy and Hold tab (discovery candidates), 12 Step tab (DCF math), top-rated scanner (DCF math) | No -- DCF helper reuse causes import errors; scan endpoint could be removed independently |
| advanced_scanner_service | Stock Triggers tab (dividend income scan, big movers scan) | No -- those sections would 404 |
| top_rated_scanner_service | Stock Triggers tab (top-rated section), momentum scanner (universe list) | No -- two callers would break |
| momentum_scanner_service | Momentum tab, Directional tab (convergence annotation) | No -- both would fail |

None of the six systems is consumed by the Phase 2B alert engine or the Book scoreboard. All six power active screens and at least one has a dependency shared with another system. Any removal requires resolving the dependency chain first.
