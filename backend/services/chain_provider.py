"""
Chain provider: Polygon primary, yfinance second, CBOE delayed third,
selected in one place.

Why a third source exists (Nov 2 2026): Polygon on the Massive
Options Starter plan returns bid/ask 0.0 (no quotes entitlement), so
every Polygon row is skipped for having no executable mid, and the
yfinance fallback returned no option expiries for TSLA, NVDA, and MSFT
on Render the same day, leaving snapshot lookups with no chain at all
and the Options Strategies section unavailable. The yfinance failure
mode on Render is unproven (the provider only records that no
expiries were returned, not why Yahoo returned none), so the fix
adds a third source rather than claiming a yfinance root cause.
CBOE delayed quotes are a public endpoint that returns real bid/ask
for listed options, with Greeks on near-money rows. It is delayed,
so the source label says so, and it never replaces a live source
when one works: it is tried only after Polygon and yfinance fail.

All consumers of options chain data call ChainProvider.fetch() or ChainProvider.fetch_price()
instead of duplicating Polygon/yfinance logic. The provider normalizes both sources into
the same row format so consumers can treat them identically.

Normalized row fields:
  strike, expiry, dte, bid, ask, mid, iv_pct, delta, delta_abs,
  theta_seller (positive = income per share per day to seller), gamma, vega,
  volume, open_interest, sale_price, price_source, last_trade

Sale pricing (wheel put sales, Oct 26 2026 fix):
  A seller collects the bid, never the mid and never the last trade.
  sale_price is the bid when bid > 0, else 0. mid is the executable
  mid, (bid + ask) / 2, only when bid > 0 and ask > 0, else the bid
  when bid > 0 and ask is 0, else 0. A last trade, fair value, or day
  close is never used as the premium: on the Massive Options Starter
  plan Polygon returns bid/ask 0.0 (no quotes entitlement), so the old
  code fell through to the last trade and called it the mid. TXN Nov 13
  $270 put, Oct 26 2026: bid $1.55, ask $3.45, mid $2.50, last trade
  $5.00 on 5 contracts. The app showed $5.00, double the real price.
  price_source is "bid" when bid > 0, else "no_executable_bid".
  Rows with no executable bid are kept with sale_price 0 so callers can
  exclude them with that reason instead of silently pricing them at a
  stale last trade.

ChainResult.source: "polygon_live" | "yfinance_live" | "yfinance_last_trade"
  | "cboe_delayed"
ChainResult.fetched_at: UTC datetime of the fetch
ChainError.sources_tried: which sources were attempted before giving up
"""

import json
import logging
import math
import re
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime

logger = logging.getLogger(__name__)

try:
    import yfinance as yf
    _YF_AVAILABLE = True
except ImportError:
    yf = None  # type: ignore[assignment]
    _YF_AVAILABLE = False


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class ChainResult:
    rows: list[dict]
    price: float
    source: str
    fetched_at: datetime


@dataclass
class ChainError:
    ticker: str
    reason: str
    sources_tried: list[str] = field(default_factory=list)


def _safe_int(x) -> int:
    """int() that survives None and NaN. yfinance chain frames carry NaN
    volume/openInterest on illiquid strikes, NaN is truthy, and
    int(NaN) raises ValueError, which used to kill the whole fallback."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0
    return 0 if math.isnan(v) else int(v)


def resolve_sale_price(bid: float, ask: float) -> tuple[float, float, str]:
    """
    Sale price for an option a seller is writing, from a quote.

    Returns (sale_price, mid, price_source):
      - bid > 0: sale_price is the bid, what the seller actually collects.
        mid is (bid + ask) / 2 when ask > 0 too, else the bid.
        price_source is "bid".
      - bid <= 0: sale_price 0, mid 0, price_source "no_executable_bid".
        There is no executable price, and the caller must exclude the
        contract, never fall back to a last trade, fair value, or day
        close as if it were executable.

    Pure function, no API calls. Used by both chain sources below and
    by the wheel tiers in stock_data.py so every wheel premium is
    priced the same way.
    """
    bid = float(bid or 0)
    ask = float(ask or 0)
    if bid <= 0:
        return 0.0, 0.0, "no_executable_bid"
    mid = round((bid + ask) / 2, 2) if ask > 0 else round(bid, 2)
    return round(bid, 2), mid, "bid"


# ---------------------------------------------------------------------------
# Black-Scholes helpers (duplicated from stock_data to keep this module
# self-contained; stock_data's copies remain authoritative for the tiers)
# ---------------------------------------------------------------------------

def _ncdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _bs_call_delta(S, K, sigma, T, r=0.045):
    if sigma <= 0 or T <= 0 or S <= 0 or K <= 0:
        return None
    try:
        d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
        return _ncdf(d1)
    except Exception:
        return None


def _bs_put_delta(S, K, sigma, T, r=0.045):
    d = _bs_call_delta(S, K, sigma, T, r)
    return (d - 1) if d is not None else None


def _bs_call_theta_daily(S, K, sigma, T, r=0.045):
    if sigma <= 0 or T <= 0 or S <= 0 or K <= 0:
        return None
    try:
        sqrtT = math.sqrt(T)
        d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * sqrtT)
        d2 = d1 - sigma * sqrtT
        phi = math.exp(-0.5 * d1**2) / math.sqrt(2 * math.pi)
        return (-S * phi * sigma / (2 * sqrtT) - r * K * math.exp(-r * T) * _ncdf(d2)) / 365
    except Exception:
        return None


def _bs_put_theta_daily(S, K, sigma, T, r=0.045):
    if sigma <= 0 or T <= 0 or S <= 0 or K <= 0:
        return None
    try:
        sqrtT = math.sqrt(T)
        d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * sqrtT)
        d2 = d1 - sigma * sqrtT
        phi = math.exp(-0.5 * d1**2) / math.sqrt(2 * math.pi)
        return (-S * phi * sigma / (2 * sqrtT) + r * K * math.exp(-r * T) * _ncdf(-d2)) / 365
    except Exception:
        return None


def _historical_volatility(ticker: str) -> float | None:
    """30-day HV using Polygon daily closes (primary) or yfinance (fallback)."""
    try:
        from services.polygon_client import get_close_prices
        closes = get_close_prices(ticker, days=35)
        if len(closes) >= 20:
            import numpy as np
            returns = np.diff(np.log(closes))
            return float(np.std(returns) * math.sqrt(252))
    except Exception:
        pass
    try:
        import yfinance as yf
        df = yf.download(ticker, period="2mo", progress=False, auto_adjust=True)
        if not df.empty and len(df) >= 20:
            import numpy as np
            closes = df["Close"].values
            returns = np.diff(np.log(closes))
            return float(np.std(returns) * math.sqrt(252))
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# ChainProvider
# ---------------------------------------------------------------------------

# CBOE delayed-quotes payload cache: one lookup fetches puts and calls
# separately, and both would otherwise download the same full chain
# file twice. 120 seconds is short against a delayed feed and long
# enough to cover one lookup. Keyed by ticker only, never by price.
_CBOE_CACHE: dict = {}
_CBOE_CACHE_TTL_SECONDS = 120.0
_CBOE_SYMBOL_RE = re.compile(r"^([A-Z]+)(\d{6})([CP])(\d{8})$")


def _parse_cboe_symbol(symbol: str):
    """Parse a CBOE option symbol into (expiry_iso, contract_type, strike).

    Symbol form: ROOT + YYMMDD + C/P + strike x 1000, zero padded to
    8 digits, for example TSLA261120C00405000 is a Nov 20 2026 call
    struck at $405.00. Returns None when the symbol does not parse,
    so an unparseable row is skipped, never guessed.
    """
    try:
        match = _CBOE_SYMBOL_RE.match(str(symbol or "").strip().upper())
        if not match:
            return None
        yy, mm, dd = int(match.group(2)[0:2]), int(match.group(2)[2:4]), int(match.group(2)[4:6])
        expiry = date(2000 + yy, mm, dd).isoformat()
        contract_type = "call" if match.group(3) == "C" else "put"
        strike = int(match.group(4)) / 1000.0
        return expiry, contract_type, strike
    except (ValueError, IndexError):
        return None


class ChainProvider:
    """Provides normalized options chain data with Polygon primary, yfinance second, CBOE delayed third."""

    # Human-readable notes on what the most recent fetch from each source
    # produced, so a total failure can say why instead of going silent.
    last_polygon_note: str = ""
    last_yfinance_note: str = ""
    last_cboe_note: str = ""

    # ------------------------------------------------------------------
    # Price pre-fetch
    # ------------------------------------------------------------------

    def fetch_price(self, ticker: str) -> float | None:
        """
        Live price: Finnhub quote -> yfinance fast_info.
        Sanity-checks last_price vs previous_close (rejects 2x+ swings as stale data).
        """
        # Finnhub primary
        try:
            from services.finnhub_client import get_quote
            q = get_quote(ticker)
            p = float(q.get("c") or q.get("pc") or 0) or None
            if p:
                return p
        except Exception:
            pass

        # yfinance fast_info fallback
        try:
            import yfinance as yf
            fi = yf.Ticker(ticker).fast_info
            raw_last = float(fi.last_price or 0) or None
            prev_close = float(fi.previous_close or 0) or None
            if raw_last and prev_close and not (0.5 <= raw_last / prev_close <= 2.0):
                logger.warning(
                    "fetch_price %s: last_price=%s vs prev_close=%s -- using prev_close",
                    ticker, raw_last, prev_close,
                )
                return prev_close
            return raw_last or prev_close
        except Exception:
            pass

        return None

    # ------------------------------------------------------------------
    # Polygon chain
    # ------------------------------------------------------------------

    def _fetch_polygon_rows(
        self,
        ticker: str,
        contract_type: str,
        dte_min: int,
        dte_max: int,
        near_price: float | None = None,
    ) -> tuple[list[dict], float | None]:
        """
        Fetch normalized chain rows from Polygon for the given DTE window.
        Returns (rows, underlying_price). Returns ([], None) on any failure.

        Row fields: strike, expiry, dte, bid, ask, mid, sale_price,
                    price_source, last_trade, iv_pct, delta, delta_abs,
                    theta_seller, gamma, vega, volume, open_interest.
        mid is the executable mid only, never a last trade, fair value,
        or day close (see resolve_sale_price). Rows with no executable
        bid are skipped, so the caller falls through to yfinance.
        """
        try:
            from services.polygon_client import (
                get_last_snapshot_outcome,
                get_options_chain_snapshot,
            )
            snapshots = get_options_chain_snapshot(
                ticker,
                dte_max=dte_max,
                contract_type=contract_type,
                near_price=near_price,
                strike_pct_range=0.25,
                dte_min=dte_min,
            )
            if not snapshots:
                outcome = get_last_snapshot_outcome() or {}
                if outcome.get("ticker") == ticker and outcome.get("error"):
                    self.last_polygon_note = f"polygon error: {outcome['error']}"
                else:
                    self.last_polygon_note = "polygon returned 0 contracts"
                return [], None

            today = date.today()
            underlying_price = near_price or None
            rows = []
            skipped_dte = skipped_mid = skipped_delta = skipped_exc = 0

            for snap in snapshots:
                if not snap.details:
                    continue
                if not underlying_price and snap.underlying_asset and snap.underlying_asset.price:
                    underlying_price = float(snap.underlying_asset.price)
                try:
                    exp = str(snap.details.expiration_date)
                    dte = (date.fromisoformat(exp) - today).days
                    if dte < dte_min or dte > dte_max:
                        skipped_dte += 1
                        continue
                    strike = float(snap.details.strike_price or 0)
                    if strike <= 0:
                        continue

                    bid = ask = mid = 0.0
                    last_trade = 0.0
                    if snap.last_quote:
                        bid = float(snap.last_quote.bid or 0)
                        ask = float(snap.last_quote.ask or 0)
                    # Sale price is the bid, mid is the executable mid only.
                    # A last trade, fair value, or day close is never used
                    # as the premium: on this data plan bid/ask are 0.0, so
                    # the old fallback priced every contract at its last
                    # trade (TXN Nov 13 $270 put: $5.00 last trade vs
                    # $1.55 bid, $2.50 mid). Rows with no executable bid
                    # are skipped here, so callers fall through to
                    # yfinance, which does return real bid/ask.
                    sale_price, mid, price_source = resolve_sale_price(bid, ask)
                    if snap.last_trade:
                        last_trade = float(snap.last_trade.price or 0)
                    if mid <= 0:
                        skipped_mid += 1
                        continue

                    iv_pct = round(float(snap.implied_volatility or 0) * 100, 1)

                    delta = gamma = theta_holder = vega = None
                    if snap.greeks:
                        delta = float(snap.greeks.delta) if snap.greeks.delta is not None else None
                        gamma = float(snap.greeks.gamma) if snap.greeks.gamma is not None else None
                        theta_holder = float(snap.greeks.theta) if snap.greeks.theta is not None else None
                        vega = float(snap.greeks.vega) if snap.greeks.vega is not None else None

                    if delta is None and iv_pct > 0 and underlying_price:
                        T = max(dte, 1) / 365
                        iv_dec = iv_pct / 100
                        if contract_type == "call":
                            delta = _bs_call_delta(underlying_price, strike, iv_dec, T)
                            theta_holder = -(_bs_call_theta_daily(underlying_price, strike, iv_dec, T) or 0)
                        else:
                            delta = _bs_put_delta(underlying_price, strike, iv_dec, T)
                            theta_holder = -(_bs_put_theta_daily(underlying_price, strike, iv_dec, T) or 0)

                    if delta is None:
                        skipped_delta += 1
                        continue

                    theta_seller = round(abs(theta_holder), 4) if theta_holder is not None else None

                    rows.append({
                        "strike": strike,
                        "expiry": exp,
                        "dte": dte,
                        "bid": round(bid, 2),
                        "ask": round(ask, 2),
                        "mid": round(mid, 2),
                        "sale_price": sale_price,
                        "price_source": price_source,
                        "last_trade": round(last_trade, 2),
                        "iv_pct": iv_pct,
                        "delta": delta,
                        "delta_abs": abs(delta),
                        "theta_seller": theta_seller,
                        "gamma": gamma,
                        "vega": vega,
                        "volume": int(snap.day.volume or 0) if snap.day else 0,
                        "open_interest": int(snap.open_interest or 0),
                    })
                except Exception:
                    skipped_exc += 1
                    continue

            logger.debug(
                "_fetch_polygon_rows %s: kept=%d skipped(dte=%d mid=%d delta=%d exc=%d)",
                ticker, len(rows), skipped_dte, skipped_mid, skipped_delta, skipped_exc,
            )
            if rows:
                self.last_polygon_note = (
                    f"polygon ok ({len(rows)} usable rows from {len(snapshots)} contracts)"
                )
            else:
                self.last_polygon_note = (
                    f"polygon returned {len(snapshots)} contracts but 0 usable rows "
                    f"(skipped: dte={skipped_dte}, mid={skipped_mid}, "
                    f"delta={skipped_delta}, exc={skipped_exc})"
                )
            return rows, underlying_price
        except Exception as e:
            self.last_polygon_note = f"polygon failed: {type(e).__name__}: {e}"
            logger.warning("_fetch_polygon_rows %s failed: %s", ticker, e)
            return [], None

    # ------------------------------------------------------------------
    # yfinance chain
    # ------------------------------------------------------------------

    def _fetch_yfinance_rows(
        self,
        ticker: str,
        contract_type: str,
        dte_min: int,
        dte_max: int,
        live_price: float | None = None,
    ) -> tuple[list[dict], float | None, str]:
        """
        Fetch normalized chain rows from yfinance for the nearest expiry in [dte_min, dte_max].
        Returns (rows, price, source) where source is "yfinance_live" or "yfinance_last_trade".
        Returns ([], None, "") on failure.
        """
        if not _YF_AVAILABLE or yf is None:
            self.last_yfinance_note = "yfinance is not available in this environment"
            return [], None, ""

        try:
            t = yf.Ticker(ticker)
            expiries = t.options
            if not expiries:
                self.last_yfinance_note = f"yfinance returned no option expiries for {ticker}"
                return [], None, ""

            today = date.today()
            target_expiry = None
            # Pick nearest expiry in [dte_min, dte_max]
            for exp in expiries:
                days = (date.fromisoformat(exp) - today).days
                if dte_min <= days <= dte_max:
                    target_expiry = exp
                    break
            # Fallback: any future expiry up to 60 days
            if not target_expiry:
                for exp in expiries:
                    days = (date.fromisoformat(exp) - today).days
                    if 1 <= days <= 60:
                        target_expiry = exp
                        break
            # Last resort
            if not target_expiry:
                for exp in expiries:
                    if (date.fromisoformat(exp) - today).days >= 1:
                        target_expiry = exp
                        break
            if not target_expiry:
                return [], None, ""

            # Price
            price = live_price
            if not price:
                try:
                    price = getattr(t.fast_info, "last_price", None)
                except Exception:
                    pass
            if not price:
                self.last_yfinance_note = f"yfinance could not fetch a price for {ticker}"
                return [], None, ""

            chain = t.option_chain(target_expiry)
            df = chain.calls if contract_type == "call" else chain.puts
            if df.empty:
                self.last_yfinance_note = "yfinance returned an empty chain for the target expiry"
                return [], None, ""
            df = df.copy()

            exp_date = date.fromisoformat(target_expiry)
            dte_val = (exp_date - today).days
            T = max(dte_val, 1) / 365.0

            # Executable mid only: (bid + ask) / 2 when both are real,
            # the bid when only a bid exists, else 0. A last trade is
            # never used as the premium (TXN Nov 13 $270 put: last $5.00
            # vs bid $1.55, mid $2.50). Rows with no executable bid are
            # kept when they carry a last trade or IV, so callers can
            # exclude them as "no_executable_bid" instead of the contract
            # vanishing silently.
            df["_mid"] = df.apply(
                lambda r: round((float(r.get("bid") or 0) + float(r.get("ask") or 0)) / 2, 2)
                          if float(r.get("bid") or 0) > 0 and float(r.get("ask") or 0) > 0
                          else round(float(r.get("bid") or 0), 2)
                          if float(r.get("bid") or 0) > 0
                          else 0.0,
                axis=1,
            )
            df["_is_live"] = df["bid"].gt(0) if "bid" in df.columns else False

            df_filtered = df[(df["_mid"] > 0) | (df["lastPrice"].fillna(0) > 0)].copy()
            if not df_filtered.empty:
                df = df_filtered
            elif "impliedVolatility" in df.columns:
                df = df[df["impliedVolatility"].fillna(0) > 0].copy()
            if df.empty:
                self.last_yfinance_note = "yfinance chain was empty after price filters"
                return [], None, ""

            # IV correction: use HV or default when chain IV is near zero
            if "impliedVolatility" in df.columns:
                mean_iv = float(df["impliedVolatility"].fillna(0).mean())
            else:
                mean_iv = 0.0
            if mean_iv < 0.01:
                hv = _historical_volatility(ticker)
                df["impliedVolatility"] = hv if hv else 0.30

            source = "yfinance_live" if df["_is_live"].any() else "yfinance_last_trade"

            rows = []
            for _, row in df.iterrows():
                iv_dec = float(row.get("impliedVolatility") or 0)
                if contract_type == "call":
                    delta = _bs_call_delta(price, float(row["strike"]), iv_dec, T)
                    theta_h = _bs_call_theta_daily(price, float(row["strike"]), iv_dec, T)
                else:
                    delta = _bs_put_delta(price, float(row["strike"]), iv_dec, T)
                    theta_h = _bs_put_theta_daily(price, float(row["strike"]), iv_dec, T)

                if delta is None:
                    continue

                theta_seller = round(abs(theta_h), 4) if theta_h is not None else None
                bid = round(float(row.get("bid") or 0), 2)
                ask = round(float(row.get("ask") or 0), 2)
                mid = round(float(row["_mid"]), 2)
                sale_price, _, price_source = resolve_sale_price(bid, ask)

                rows.append({
                    "strike": float(row["strike"]),
                    "expiry": target_expiry,
                    "dte": dte_val,
                    "bid": bid,
                    "ask": ask,
                    "mid": mid,
                    "sale_price": sale_price,
                    "price_source": price_source,
                    "last_trade": round(float(row.get("lastPrice") or 0), 2),
                    "iv_pct": round(iv_dec * 100, 1),
                    "delta": delta,
                    "delta_abs": abs(delta),
                    "theta_seller": theta_seller,
                    "gamma": None,
                    "vega": None,
                    "volume": _safe_int(row.get("volume")),
                    "open_interest": _safe_int(row.get("openInterest")),
                })

            self.last_yfinance_note = f"yfinance ok ({len(rows)} rows)"
            return rows, price, source
        except Exception as e:
            self.last_yfinance_note = f"yfinance failed: {type(e).__name__}: {e}"
            logger.warning("_fetch_yfinance_rows %s failed: %s", ticker, e)
            return [], None, ""

    # ------------------------------------------------------------------
    # CBOE delayed chain (third fallback)
    # ------------------------------------------------------------------

    def _fetch_cboe_payload(self, ticker: str):
        """Download the CBOE delayed-quotes options list for one ticker.

        Returns the list of option dicts, or None on any failure. The
        payload is cached for 120 seconds so a lookup's separate put
        and call fetches share one download. This method is the only
        HTTP step in the CBOE path, so tests patch it, not the parser.
        """
        key = str(ticker or "").strip().upper()
        cached = _CBOE_CACHE.get(key)
        if cached and (time.monotonic() - cached[0]) < _CBOE_CACHE_TTL_SECONDS:
            return cached[1]
        url = f"https://cdn.cboe.com/api/global/delayed_quotes/options/{key}.json"
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            options = (payload or {}).get("data", {}).get("options") or []
            _CBOE_CACHE[key] = (time.monotonic(), options)
            return options
        except Exception as e:
            self.last_cboe_note = f"cboe failed: {type(e).__name__}: {e}"
            logger.warning("_fetch_cboe_payload %s failed: %s", ticker, e)
            return None

    def _fetch_cboe_rows(
        self,
        ticker: str,
        contract_type: str,
        dte_min: int,
        dte_max: int,
        live_price: float | None = None,
    ) -> tuple[list[dict], float | None, str]:
        """
        Fetch normalized chain rows from CBOE delayed quotes for the
        given DTE window. Returns (rows, price, source) where source
        is "cboe_delayed". Returns ([], None, "") on failure.

        Pricing follows the same rule as the other sources: bought
        legs at ask else mid, sold legs at bid, never a last trade.
        Rows with neither a bid nor an ask are skipped, because
        neither side of the trade has an executable price. CBOE
        Greeks are used as supplied on near-money rows; when CBOE
        reports IV 0, gamma, vega, and theta are set to None rather
        than shown as 0.0, and delta falls back to Black-Scholes
        only when IV is positive, exactly as the Polygon path does.
        """
        options = self._fetch_cboe_payload(ticker)
        if options is None:
            return [], None, ""
        if not options:
            self.last_cboe_note = f"cboe returned no options for {ticker}"
            return [], None, ""

        today = date.today()
        rows = []
        skipped_symbol = skipped_dte = 0
        for opt in options:
            parsed = _parse_cboe_symbol(opt.get("option"))
            if parsed is None:
                skipped_symbol += 1
                continue
            expiry, opt_type, strike = parsed
            if opt_type != contract_type:
                continue
            try:
                dte_val = (date.fromisoformat(expiry) - today).days
            except ValueError:
                skipped_symbol += 1
                continue
            if dte_val < dte_min or dte_val > dte_max:
                skipped_dte += 1
                continue
            bid = round(float(opt.get("bid") or 0), 2)
            ask = round(float(opt.get("ask") or 0), 2)
            if bid <= 0 and ask <= 0:
                continue
            sale_price, mid, price_source = resolve_sale_price(bid, ask)
            if bid <= 0 and ask > 0:
                mid = round(ask, 2)
            iv_dec = float(opt.get("iv") or 0)
            iv_pct = round(iv_dec * 100, 1)
            delta = opt.get("delta")
            delta = float(delta) if delta is not None else None
            if (delta is None or delta == 0.0) and iv_dec > 0 and live_price:
                T = max(dte_val, 1) / 365.0
                if contract_type == "call":
                    delta = _bs_call_delta(live_price, strike, iv_dec, T)
                    theta_h = _bs_call_theta_daily(live_price, strike, iv_dec, T)
                else:
                    delta = _bs_put_delta(live_price, strike, iv_dec, T)
                    theta_h = _bs_put_theta_daily(live_price, strike, iv_dec, T)
            else:
                theta_h = opt.get("theta")
                theta_h = float(theta_h) if theta_h is not None else None
            if delta is None:
                continue
            if iv_dec <= 0:
                gamma = vega = theta_seller = None
            else:
                gamma = opt.get("gamma")
                gamma = float(gamma) if gamma is not None else None
                vega = opt.get("vega")
                vega = float(vega) if vega is not None else None
                theta_seller = round(abs(theta_h), 4) if theta_h is not None else None
            rows.append({
                "strike": strike,
                "expiry": expiry,
                "dte": dte_val,
                "bid": bid,
                "ask": ask,
                "mid": mid,
                "sale_price": sale_price,
                "price_source": price_source,
                "last_trade": round(float(opt.get("last_trade_price") or 0), 2),
                "iv_pct": iv_pct,
                "delta": delta,
                "delta_abs": abs(delta),
                "theta_seller": theta_seller,
                "gamma": gamma,
                "vega": vega,
                "volume": _safe_int(opt.get("volume")),
                "open_interest": _safe_int(opt.get("open_interest")),
            })

        if not rows:
            self.last_cboe_note = (
                f"cboe returned {len(options)} options but 0 usable rows "
                f"for {ticker} {contract_type} (skipped: symbol={skipped_symbol}, "
                f"dte={skipped_dte})"
            )
            return [], None, ""
        self.last_cboe_note = f"cboe ok ({len(rows)} rows)"
        return rows, live_price, "cboe_delayed"

    # ------------------------------------------------------------------
    # Public fetch
    # ------------------------------------------------------------------

    def fetch(
        self,
        ticker: str,
        contract_type: str,
        dte_min: int,
        dte_max: int,
        near_price: float | None = None,
    ) -> "ChainResult | ChainError":
        """
        Polygon primary, yfinance second, CBOE delayed third.
        Returns ChainResult on success, ChainError on total failure.
        Never returns an empty-rows ChainResult as a success.
        """
        sources_tried: list[str] = []
        live_price = near_price or self.fetch_price(ticker)

        # --- Polygon ---
        rows, poly_price = self._fetch_polygon_rows(
            ticker, contract_type, dte_min, dte_max, near_price=live_price
        )
        sources_tried.append("polygon")
        if rows:
            return ChainResult(
                rows=rows,
                price=poly_price or live_price or 0.0,
                source="polygon_live",
                fetched_at=datetime.utcnow(),
            )

        # --- yfinance fallback ---
        yf_rows, yf_price, yf_source = self._fetch_yfinance_rows(
            ticker, contract_type, dte_min, dte_max, live_price=live_price
        )
        sources_tried.append("yfinance")
        if yf_rows:
            return ChainResult(
                rows=yf_rows,
                price=yf_price or live_price or 0.0,
                source=yf_source,
                fetched_at=datetime.utcnow(),
            )

        # --- CBOE delayed fallback ---
        # Only reached when both live sources fail, so a delayed
        # quote is never preferred over a live one. The source label
        # stays "cboe_delayed" all the way to the UI, so a strategy
        # built on it is never presented as live-priced.
        cboe_rows, cboe_price, cboe_source = self._fetch_cboe_rows(
            ticker, contract_type, dte_min, dte_max, live_price=live_price
        )
        sources_tried.append("cboe")
        if cboe_rows:
            return ChainResult(
                rows=cboe_rows,
                price=cboe_price or live_price or 0.0,
                source=cboe_source,
                fetched_at=datetime.utcnow(),
            )

        return ChainError(
            ticker=ticker,
            reason=(
                f"No chain data from any source (dte={dte_min}-{dte_max}, "
                f"type={contract_type}). {self.last_polygon_note}; "
                f"{self.last_yfinance_note}; {self.last_cboe_note}"
            ),
            sources_tried=sources_tried,
        )
