"""
Phase 4 Step 1 -- capture real yfinance chain responses and create Polygon-shaped fixtures.

Run once from backend/ dir:
    python tests/capture_fixtures.py

Writes:
  tests/fixtures/yf_chain_{TICKER}.json  -- real yfinance option chain data
  tests/fixtures/polygon_chain_put.json  -- Polygon-shaped normalized rows (synthetic)
  tests/fixtures/polygon_chain_call.json -- Polygon-shaped normalized rows (synthetic)
"""

import json
import sys
import os
from datetime import date, timedelta

# Run from backend/ dir
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TICKERS = ["MSFT", "AAPL", "SPY"]
FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")

# Fixed anchor date used for all synthetic fixtures -- test patches date.today() to this.
ANCHOR_DATE = date(2026, 10, 23)
# DTE offsets for expiry slots: weekly (7), monthly-near (14), monthly-sweet (21)
EXPIRY_DTES = [7, 14, 21]


def capture_yfinance(ticker: str) -> dict | None:
    """Capture yfinance option chain snapshot: options list, chains, fast_info, info."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        expiries = list(t.options or [])
        if not expiries:
            print(f"  {ticker}: no expiries from yfinance")
            return None

        fi = t.fast_info
        last_price = float(getattr(fi, "last_price", None) or 0) or None
        prev_close = float(getattr(fi, "previous_close", None) or 0) or None
        price = last_price or prev_close
        if not price:
            print(f"  {ticker}: could not get price from yfinance")
            return None

        today = date.today()
        chains = {}
        for exp in expiries[:4]:  # capture first few expiries
            try:
                days = (date.fromisoformat(exp) - today).days
                if days < 0:
                    continue
                chain = t.option_chain(exp)
                calls_df = chain.calls
                puts_df = chain.puts

                def _df_records(df):
                    records = []
                    for _, row in df.iterrows():
                        r = {}
                        for col in df.columns:
                            v = row[col]
                            try:
                                if hasattr(v, "isoformat"):
                                    r[col] = v.isoformat()
                                elif v != v:  # NaN
                                    r[col] = None
                                else:
                                    r[col] = float(v) if isinstance(v, (int, float)) else str(v)
                            except Exception:
                                r[col] = None
                        records.append(r)
                    return records

                chains[exp] = {
                    "dte": days,
                    "calls": _df_records(calls_df),
                    "puts": _df_records(puts_df),
                }
                print(f"  {ticker} {exp} (dte={days}): {len(chains[exp]['calls'])} calls, {len(chains[exp]['puts'])} puts")
            except Exception as e:
                print(f"  {ticker} {exp}: yfinance error: {e}")

        if not chains:
            print(f"  {ticker}: no chains captured")
            return None

        info = {}
        try:
            raw = t.info or {}
            info = {k: raw.get(k) for k in ("regularMarketPrice", "sector", "industry")}
        except Exception:
            pass

        return {
            "ticker": ticker,
            "price": price,
            "options": expiries[:4],
            "chains": chains,
            "fast_info": {"last_price": last_price, "previous_close": prev_close},
            "info": info,
        }
    except Exception as e:
        print(f"  {ticker}: capture_yfinance failed: {e}")
        return None


def make_polygon_fixture(ticker: str, contract_type: str, price: float, dte_base: int = 21, anchor: date | None = None) -> dict:
    """
    Build a synthetic Polygon-shaped fixture.

    The fixture is the OUTPUT of _polygon_options_chain (normalized list[dict] + price),
    not the raw Polygon SDK objects. Each row: strike, expiry, dte, bid, ask, mid,
    iv_pct, delta, delta_abs, theta_seller, gamma, vega, volume, open_interest.

    Values are realistic for the given price and dte. This is purely synthetic since
    no Polygon API key is available in this environment.
    """
    import math

    today = anchor or ANCHOR_DATE
    exp_date = today + timedelta(days=dte_base)
    expiry = exp_date.isoformat()
    dte = dte_base
    T = max(dte, 1) / 365.0
    r = 0.045
    hv = 0.25  # assumed HV

    def ncdf(x):
        return 0.5 * (1 + math.erf(x / math.sqrt(2)))

    def bs_call_delta(S, K, sigma, T_, r_=0.045):
        if sigma <= 0 or T_ <= 0:
            return None
        d1 = (math.log(S / K) + (r_ + 0.5 * sigma**2) * T_) / (sigma * math.sqrt(T_))
        return ncdf(d1)

    def bs_put_delta(S, K, sigma, T_, r_=0.045):
        d = bs_call_delta(S, K, sigma, T_, r_)
        return (d - 1) if d is not None else None

    def bs_call_theta(S, K, sigma, T_, r_=0.045):
        if sigma <= 0 or T_ <= 0:
            return None
        sqrtT = math.sqrt(T_)
        d1 = (math.log(S / K) + (r_ + 0.5 * sigma**2) * T_) / (sigma * sqrtT)
        d2 = d1 - sigma * sqrtT
        phi_d1 = math.exp(-0.5 * d1**2) / math.sqrt(2 * math.pi)
        return (-S * phi_d1 * sigma / (2 * sqrtT) - r_ * K * math.exp(-r_ * T_) * ncdf(d2)) / 365

    def bs_put_theta(S, K, sigma, T_, r_=0.045):
        if sigma <= 0 or T_ <= 0:
            return None
        sqrtT = math.sqrt(T_)
        d1 = (math.log(S / K) + (r_ + 0.5 * sigma**2) * T_) / (sigma * sqrtT)
        d2 = d1 - sigma * sqrtT
        phi_d1 = math.exp(-0.5 * d1**2) / math.sqrt(2 * math.pi)
        return (-S * phi_d1 * sigma / (2 * sqrtT) + r_ * K * math.exp(-r_ * T_) * ncdf(-d2)) / 365

    # strike grid around ATM
    rounding = 0.5 if price < 50 else (5.0 if price > 500 else 1.0)
    strikes = sorted(set(
        round(price * m / rounding) * rounding
        for m in [0.70, 0.75, 0.80, 0.85, 0.90, 0.95, 1.00, 1.05, 1.10, 1.15, 1.20, 1.25, 1.30]
    ))

    rows = []
    for K in strikes:
        if K <= 0:
            continue
        if contract_type == "call":
            delta = bs_call_delta(price, K, hv, T, r)
            theta_h = bs_call_theta(price, K, hv, T, r)
        else:
            delta = bs_put_delta(price, K, hv, T, r)
            theta_h = bs_put_theta(price, K, hv, T, r)

        if delta is None:
            continue

        # BS price approximation
        sqrtT = math.sqrt(T)
        d1 = (math.log(price / K) + (r + 0.5 * hv**2) * T) / (hv * sqrtT)
        d2 = d1 - hv * sqrtT
        if contract_type == "call":
            bs_p = max(price * ncdf(d1) - K * math.exp(-r * T) * ncdf(d2), 0.01)
        else:
            bs_p = max(K * math.exp(-r * T) * ncdf(-d2) - price * ncdf(-d1), 0.01)

        bs_p = round(bs_p, 2)
        spread = round(max(bs_p * 0.05, 0.05), 2)
        bid = round(max(bs_p - spread / 2, 0.01), 2)
        ask = round(bs_p + spread / 2, 2)
        mid = round((bid + ask) / 2, 2)

        theta_seller = round(abs(theta_h), 4) if theta_h else None
        gamma = round(math.exp(-0.5 * d1**2) / (math.sqrt(2 * math.pi) * price * hv * sqrtT), 4)

        rows.append({
            "strike": K,
            "expiry": expiry,
            "dte": dte,
            "bid": bid,
            "ask": ask,
            "mid": mid,
            "iv_pct": round(hv * 100, 1),
            "delta": round(delta, 4),
            "delta_abs": round(abs(delta), 4),
            "theta_seller": theta_seller,
            "gamma": gamma,
            "vega": None,
            "volume": 500,
            "open_interest": 2000,
        })

    return {
        "rows": rows,
        "price": price,
        "ticker": ticker,
        "contract_type": contract_type,
        "anchor_date": today.isoformat(),
        "_note": "Synthetic fixture -- shape matches _polygon_options_chain output. Anchor date: " + today.isoformat(),
    }


def make_yf_fixture(ticker: str, price: float) -> dict:
    """
    Build a synthetic yfinance-shaped fixture with multiple expiries.

    Expiries: ANCHOR_DATE + 7, 14, 21 days (weekly, near-monthly, sweet-spot monthly).
    This lets get_put_tiers (14-45 DTE), get_call_tiers (1-60 DTE), and
    get_weekly_call_tiers (0-16 DTE) all find a valid expiry in the fixture.

    Format matches what yfinance returns: options list, chains dict
    (each expiry -> {dte, calls: [records], puts: [records]}), fast_info, info.
    """
    import math

    r = 0.045
    hv = 0.25

    def ncdf(x):
        return 0.5 * (1 + math.erf(x / math.sqrt(2)))

    rounding = 0.5 if price < 50 else (5.0 if price > 500 else 1.0)
    strikes = sorted(set(
        round(price * m / rounding) * rounding
        for m in [0.75, 0.80, 0.85, 0.90, 0.95, 1.00, 1.05, 1.10, 1.15, 1.20]
    ))

    def _option_row(K, ctype, expiry, dte):
        T = max(dte, 1) / 365.0
        sqrtT = math.sqrt(T)
        d1 = (math.log(price / K) + (r + 0.5 * hv**2) * T) / (hv * sqrtT)
        d2 = d1 - hv * sqrtT
        if ctype == "call":
            bs_p = max(price * ncdf(d1) - K * math.exp(-r * T) * ncdf(d2), 0.01)
        else:
            bs_p = max(K * math.exp(-r * T) * ncdf(-d2) - price * ncdf(-d1), 0.01)

        bs_p = round(bs_p, 2)
        spread = round(max(bs_p * 0.05, 0.05), 2)
        bid = round(max(bs_p - spread / 2, 0.01), 2)
        ask = round(bs_p + spread / 2, 2)
        itm = (price > K) if ctype == "call" else (price < K)
        return {
            "contractSymbol": f"{ticker}{expiry.replace('-', '')}{ctype[0].upper()}{int(K*1000):08d}",
            "lastTradeDate": (ANCHOR_DATE - timedelta(days=1)).isoformat(),
            "strike": K,
            "lastPrice": bs_p,
            "bid": bid,
            "ask": ask,
            "change": 0.0,
            "percentChange": 0.0,
            "volume": 500.0,
            "openInterest": 2000.0,
            "impliedVolatility": hv,
            "inTheMoney": itm,
            "contractSize": "REGULAR",
            "currency": "USD",
        }

    chains = {}
    expiries = []
    for dte_offset in EXPIRY_DTES:
        exp = (ANCHOR_DATE + timedelta(days=dte_offset)).isoformat()
        expiries.append(exp)
        chains[exp] = {
            "dte": dte_offset,
            "calls": [_option_row(K, "call", exp, dte_offset) for K in strikes],
            "puts": [_option_row(K, "put", exp, dte_offset) for K in strikes],
        }

    return {
        "ticker": ticker,
        "price": price,
        "anchor_date": ANCHOR_DATE.isoformat(),
        "options": expiries,
        "chains": chains,
        "fast_info": {"last_price": price, "previous_close": round(price * 0.995, 2)},
        "info": {"regularMarketPrice": price, "sector": "Technology", "industry": "Software"},
        "_note": "Synthetic fixture -- shape matches yfinance but values are BS-computed. Anchor date: " + ANCHOR_DATE.isoformat(),
    }


def main():
    os.makedirs(FIXTURES_DIR, exist_ok=True)

    # Try real yfinance first; fall back to synthetic if unavailable
    yf_prices = {"MSFT": 430.0, "AAPL": 230.0, "SPY": 580.0}

    for ticker in TICKERS:
        print(f"Capturing yfinance for {ticker}...")
        data = capture_yfinance(ticker)
        if data:
            # Real fixture: replace options/chains with anchor-date-based expiries for determinism
            # Real prices are kept; chain shapes use anchor date so tests are deterministic
            data["anchor_date"] = ANCHOR_DATE.isoformat()
            path = os.path.join(FIXTURES_DIR, f"yf_chain_{ticker}.json")
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
            print(f"  Saved {path} (real)")
            if data.get("price"):
                yf_prices[ticker] = data["price"]
        else:
            print(f"  Building synthetic yfinance fixture for {ticker}...")
            data = make_yf_fixture(ticker, yf_prices[ticker])
            path = os.path.join(FIXTURES_DIR, f"yf_chain_{ticker}.json")
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
            print(f"  Saved {path} (synthetic)")

    # Build synthetic Polygon fixtures
    print(f"\nBuilding synthetic Polygon fixtures...")
    for ticker, price in yf_prices.items():
        for contract_type, dte_base in [("put", 21), ("call", 14)]:
            data = make_polygon_fixture(ticker, contract_type, price, dte_base=dte_base)
            if ticker == "MSFT":
                path = os.path.join(FIXTURES_DIR, f"polygon_chain_{contract_type}.json")
            else:
                path = os.path.join(FIXTURES_DIR, f"polygon_chain_{ticker}_{contract_type}.json")
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
            print(f"  Saved {path} ({len(data['rows'])} rows)")

    print("\nFixture capture complete.")


if __name__ == "__main__":
    main()
