"""
Chain provider: Polygon primary, yfinance fallback, selected in one place.

All consumers of options chain data call ChainProvider.fetch() or ChainProvider.fetch_price()
instead of duplicating Polygon/yfinance logic. The provider normalizes both sources into
the same row format so consumers can treat them identically.

Normalized row fields:
  strike, expiry, dte, bid, ask, mid, iv_pct, delta, delta_abs,
  theta_seller (positive = income per share per day to seller), gamma, vega,
  volume, open_interest

ChainResult.source: "polygon_live" | "yfinance_live" | "yfinance_last_trade"
ChainResult.fetched_at: UTC datetime of the fetch
ChainError.sources_tried: which sources were attempted before giving up
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime

logger = logging.getLogger(__name__)


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

class ChainProvider:
    """Provides normalized options chain data with Polygon primary, yfinance fallback."""

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

        Row fields: strike, expiry, dte, bid, ask, mid, iv_pct, delta, delta_abs,
                    theta_seller, gamma, vega, volume, open_interest.
        """
        try:
            from services.polygon_client import get_options_chain_snapshot
            snapshots = get_options_chain_snapshot(
                ticker,
                dte_max=dte_max,
                contract_type=contract_type,
                near_price=near_price,
                strike_pct_range=0.25,
            )
            if not snapshots:
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
                    if snap.last_quote:
                        bid = float(snap.last_quote.bid or 0)
                        ask = float(snap.last_quote.ask or 0)
                        mp = snap.last_quote.midpoint
                        mid = float(mp) if mp else (round((bid + ask) / 2, 2) if bid > 0 else 0.0)
                    if mid <= 0 and snap.last_trade:
                        mid = float(snap.last_trade.price or 0)
                    if mid <= 0 and snap.fair_market_value:
                        mid = float(snap.fair_market_value)
                    if mid <= 0 and snap.day and snap.day.close:
                        mid = float(snap.day.close)
                    mid = round(mid, 2)
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
            return rows, underlying_price
        except Exception as e:
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
        try:
            import yfinance as yf
        except ImportError:
            return [], None, ""

        try:
            t = yf.Ticker(ticker)
            expiries = t.options
            if not expiries:
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
                return [], None, ""

            chain = t.option_chain(target_expiry)
            df = chain.calls if contract_type == "call" else chain.puts
            if df.empty:
                return [], None, ""
            df = df.copy()

            exp_date = date.fromisoformat(target_expiry)
            dte_val = (exp_date - today).days
            T = max(dte_val, 1) / 365.0

            df["_mid"] = df.apply(
                lambda r: round((float(r.get("bid") or 0) + float(r.get("ask") or 0)) / 2, 2)
                          if float(r.get("bid") or 0) > 0
                          else float(r.get("lastPrice") or 0),
                axis=1,
            )
            df["_is_live"] = df["bid"].gt(0) if "bid" in df.columns else False

            df_filtered = df[df["_mid"] > 0].copy()
            if not df_filtered.empty:
                df = df_filtered
            elif "impliedVolatility" in df.columns:
                df = df[df["impliedVolatility"].fillna(0) > 0].copy()
            if df.empty:
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

                rows.append({
                    "strike": float(row["strike"]),
                    "expiry": target_expiry,
                    "dte": dte_val,
                    "bid": bid,
                    "ask": ask,
                    "mid": mid,
                    "iv_pct": round(iv_dec * 100, 1),
                    "delta": delta,
                    "delta_abs": abs(delta),
                    "theta_seller": theta_seller,
                    "gamma": None,
                    "vega": None,
                    "volume": int(row.get("volume") or 0),
                    "open_interest": int(row.get("openInterest") or 0),
                })

            return rows, price, source
        except Exception as e:
            logger.warning("_fetch_yfinance_rows %s failed: %s", ticker, e)
            return [], None, ""

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
        Polygon primary, yfinance fallback.
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

        return ChainError(
            ticker=ticker,
            reason=f"No chain data from any source (dte={dte_min}-{dte_max}, type={contract_type})",
            sources_tried=sources_tried,
        )
