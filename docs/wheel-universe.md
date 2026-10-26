# Wheel scan universe

File: `data/wheel_universe.json` (607 tickers, sorted alphabetically, deduped).

## What it is

The union of three lists, nothing removed:

- The previous 314-ticker universe (Dividend Achievers plus watchlist, seeded Oct 23 2026). 89 of those names are in neither index below and stay in, including the ETFs SPY, QQQ, IWM, GLD, TLT and Dividend Achievers not in the S&P 500.
- All current S&P 500 constituents, 503 tickers.
- All current Nasdaq-100 constituents, 101 securities (100 companies, Alphabet in two classes).

293 tickers were added in this expansion, 314 to 607.

## Source and date

Fetched Oct 26 2026 from Wikipedia, which tracks the index providers:

- S&P 500: List of S&P 500 companies, 503 common stocks issued by 500 companies, as listed that day.
- Nasdaq-100: List of NASDAQ-100 companies, 101 securities issued by 100 companies, as of Oct 22 2026.

Wikipedia is a secondary source. Constituents change on index rebalances, so re-fetch from the same pages when the list looks stale, and update the counts here. Do not fall back to the repo's `data/sp500.json` and `data/nasdaq100.json` without saying so: those files are stale (462 and 99 unique tickers) and miss current constituents such as JPM, JNJ, LLY, MCD, and MMM.

## Dot tickers

The JSON file keeps the canonical Wikipedia forms `BRK.B` and `BF.B`, the only two dot tickers in the universe. The scanner normalizes them to `BRK-B` and `BF-B` when loading (`_load_universe` in `backend/services/wheel_scanner_service.py`), because yfinance returns no option expiries and no price for the dot form (verified Oct 26 2026), so those names would silently never produce candidates. A hyphen ticker that Polygon does not recognise falls back to yfinance, which does return a chain.

## Runtime impact

The universe grows about 93 percent (314 to 607), so the morning scan takes longer and makes more API calls, roughly double the per-ticker work, before the run-time pre-filters apply. The existing pre-filters still drop illiquid names at run time (spread over 15 percent excluded, open interest under 100 excluded), so most of the added names that have no liquid options chain are skipped cheaply after the chain fetch, not ranked.
