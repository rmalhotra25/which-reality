# TradeIQ

A personal trading decision-support app. It runs backtested screeners on your watchlist and portfolio, surfaces options setups across wheel, directional, and covered-call strategies, tracks income from dividends and premiums, and grades every source of recommendations on a live scoreboard so you know what is actually working.

---

## What the app does

**Buy and Hold** -- runs your watchlist against the 12 Step Process: a quality screen checking revenue growth, margins, ROIC, debt, and valuation. Discovery candidates from a multi-factor scan are fed into Claude for a deeper qualitative analysis. The 12 Step tab lets you run a fresh analysis on any individual ticker.

**Wheel Strategy** -- scans the dividend-achievers universe for put-selling candidates near support with elevated implied volatility. Displays put tiers at 0.45 / 0.30 / 0.16 delta with breakeven, annualized return, and income per day. Tracks open wheel positions through assignment, covered-call writing, and exit.

**Directional** -- ranks options candidates by a composite score combining momentum, volatility rank, and setup quality. Presents call and weekly-call tier tables with entry levels and risk parameters. Integrates the momentum convergence scanner (unusual options flow + insider buying + pre-earnings drift).

**Setup Alerts** -- fires real-time alerts based on six backtested setups: Quality Pullback, Premium at Support (Wheel), Volume-Confirmed Breakout, Oversold Bounce, Trend Pullback Reversal, and Post-Earnings Drift. Each setup has a registry entry with its recipe and status (LIVE, SHADOW, or RETIRED). A setup can only reach LIVE status when a real-data backtest on file carries a PASSES verdict. Alerts link to an outcome journal so you can track whether the trade worked.

**Leveraged Signals** -- moving-average regime signals for leveraged ETF pairs (e.g. UPRO/TMF, TQQQ/SQQQ). Monitors the signal state and last crossover date.

**Income** -- dividend calendar across held names and watchlist tickers. Tracks REITs, aristocrats, ETFs, and custom income positions. Projects ex-dates and payout amounts for the next 90 days.

**Book** -- the master scoreboard. Aggregates settled outcomes across all four recommendation sources (Setup Alerts, Directional, Champions AI picks, Wheel positions) into per-source tiles. Shows open positions, watchlist, and income calendar. A tile shows "not enough settled outcomes yet" until at least five trades are settled, so stats are not printed from too few data points.

Five utility screens are also available: Stock Triggers (DCF/MA/earnings watchlist trigger scores), Momentum (convergence scanner), 12 Step (deep-dive on a single ticker), Covered Calls (covered-call tiers on held positions), and Today (market pulse summary).

---

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11, FastAPI, SQLAlchemy 2.x |
| Frontend | React 18, Vite |
| Database | SQLite (local dev), PostgreSQL via Neon or Render (production) |
| Hosting | Render (free tier, single web service) |
| Data | yfinance (prices, chains), Finnhub (fundamentals, earnings), Polygon.io (options chains, flow), Financial Modeling Prep (12 Step screener), Anthropic API (AI analysis) |

---

## Local setup

### 1. Clone and install dependencies

```bash
git clone https://github.com/rmalhotra25/which-reality.git
cd which-reality

# Backend
cd backend
pip install -r requirements.txt

# Frontend (separate terminal)
cd ../frontend
npm install
```

### 2. Set environment variables

Copy `.env.example` to `.env` in the project root and fill in the keys:

```
ANTHROPIC_API_KEY    required — AI analysis (Claude)
FINNHUB_API_KEY      required — fundamentals and earnings calendar (free at finnhub.io)
POLYGON_API_KEY      required — options chains and flow (free tier at polygon.io)
FMP_API_KEY          optional — 12 Step screener (250 calls/day free at financialmodelingprep.com)
DATABASE_URL         optional — PostgreSQL URL; omit to use SQLite locally
DB_PATH              SQLite file path, default ../data/trading.db
BACKEND_PORT         default 8000
```

The app starts without any API keys; screens that need a key will show an error for that specific feature only.

### 3. Run the app

```bash
# Backend (from the backend/ directory)
uvicorn main:app --reload --port 8000

# Frontend (from the frontend/ directory)
npm run dev
```

The frontend dev server proxies API calls to `localhost:8000`. Open `http://localhost:5173`.

---

## Backtest harness

The three backtested setups (Quality Pullback, Premium at Support, Volume-Confirmed Breakout) are validated by a walk-forward harness in `backend/services/backtest_harness.py`. Results are written to `backtests/`.

Run from the `backend/` directory:

```bash
python run_backtest.py
```

Options:
- `--output-dir DIR` -- write results to a different folder
- `--tickers A,B,C` -- run on a subset of tickers for a quick spot-check
- `--allow-synthetic` -- allow synthetic random-walk fallback when yfinance is unreachable; caps verdict at SHADOW ONLY (mechanics verification only, not market evidence)
- `--spot-check` -- print one example trade per setup to verify no-lookahead

**Important:** a setup can only be promoted to LIVE in the registry when the backtest file on disk is stamped `Data source: REAL` and carries a `PASSES` verdict. The registry service enforces this automatically and will raise an error on any attempt to set LIVE without those conditions met. The `--allow-synthetic` flag must never be used as a substitute for real-data results when promoting a setup.
