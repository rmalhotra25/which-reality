"""Company Story view for the ticker lookup: one ticker, four panels.

The Story is a read-only explainer, never a trade call: no LIVE label,
no sizing, no entry, no put or call. Quant decides every number, gauge,
grade, tailwind and headwind from the rules below. Claude only explains.

Panels, in professional wording rather than the reference's phrasing:
1. Market position: peer market-cap shares plus four health gauges
   (Growth, Margins, Debt, Valuation) and an overall grade.
2. Revenue mix: revenue by segment and by geography, with growth.
3. Growth and profitability: reported revenue bars plus analyst
   estimate years, with the headline multiples.
4. Outlook: analyst price targets and Buy/Hold/Sell counts,
   the long-term lane DCF base next to the analyst mean, rule-based
   tailwinds and headwinds, and one "what would change this
   assessment" line.

Enhancements over the reference, agreed with Rohit Nov 10 2026:
- The grade always shows its reasoning in one line.
- The DCF base sits next to the analyst mean, and the target spread
  is shown as analyst disagreement.
- Every gauge labels its basis. Price is never called Cheap without
  saying cheap relative to what; a forward P/E of 66 is Expensive
  against a peer median near 40, not Cheap.
- Earnings date and data-as-of stamps are on the header and panels,
  so last year's segment mix is never mistaken for today's.
- The Story links to the lookup lanes instead of restating them, and
  the grade is checked against the long-term lane verdict: a
  disagreement is reported, not hidden.

Data sources:
- price: alert_engine OHLCV + indicators, the same as the lookup.
- earnings: Finnhub calendar via alert_engine._earnings_days.
- company facts, targets, recommendations, revenue history and
  estimates: yfinance (no key).
- peers and segment revenue: FMP free tier (stock-peers,
  revenue-product-segmentation, revenue-geographic-segmentation).
- DCF base: longterm_valuation.build_longterm with statements from
  ondemand_review.fetch_statements, the same DCF the long-term lane
  shows, so the two anchors can never disagree.

Missing data is shown as missing, never invented. A panel whose
source is unavailable reports that, with the source named.
"""

import concurrent.futures
import logging
import math
import time
from datetime import date, datetime, timedelta, timezone

logger = logging.getLogger(__name__)

_CACHE: dict = {}
_CACHE_TTL = 3600
_CACHE_MAX_ENTRIES = 200


def _cache_get(ticker: str):
    row = _CACHE.get(ticker)
    if row and time.time() - row[0] < _CACHE_TTL:
        return row[1]
    return None


def _cache_put(ticker: str, payload: dict):
    from services.cache_utils import bounded_put

    bounded_put(_CACHE, ticker, payload, now=time.time(),
                ttl_seconds=_CACHE_TTL, max_entries=_CACHE_MAX_ENTRIES)


def clear_story_cache():
    _CACHE.clear()


# ---------------------------------------------------------------------------
# Pure rules: grade, gauges, tailwinds, headwinds. No fetching here, so
# these are directly testable.
# ---------------------------------------------------------------------------

def _cagr(first: float, last: float, years: int):
    if not first or not last or years <= 0 or first <= 0 or last <= 0:
        return None
    try:
        return (last / first) ** (1.0 / years) - 1.0
    except (ValueError, ZeroDivisionError):
        return None


def _pct1(value):
    if value is None:
        return None
    return round(float(value) * 100, 1)


def _finite(value):
    """A finite float, or None.

    NaN and infinities are not usable numbers and must never reach
    the payload: Starlette's JSON encoder rejects them
    (allow_nan=False) and the endpoint 500s. The price feed returns
    a NaN close when Yahoo's history is degraded, so this is a live
    failure mode, not a theoretical one (Nov 10 2026).
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _to_float(value):
    return _finite(value)


def _sanitize(value):
    """Recursively replace non-finite floats with None.

    Safety net for the payload: any NaN or infinity that slips
    past the per-field guards becomes null instead of 500ing the
    endpoint. Applied to the finished payload before it is cached
    or returned.
    """
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _sanitize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize(v) for v in value]
    if isinstance(value, tuple):
        return tuple(_sanitize(v) for v in value)
    return value


def grade_gauges(growth_cagr, gross_margin, operating_margin,
                 forward_pe, peer_median_pe,
                 net_cash=None, total_debt=None,
                 debt_to_equity=None, free_cashflow=None):
    """Four health gauges plus the overall grade.

    Thresholds, frozen Nov 10 2026:
    - Growth Strong at 3-year revenue CAGR >= 20%, Moderate >= 10%.
    - Margins Strong at gross >= 70% or operating >= 25%; Moderate at
      gross >= 50% or operating >= 15%.
    - Debt is judged on net cash first, the same as the Nash Step 3
      kill (more debt than cash): net cash above zero is Low. Net
      debt is Moderate when the debt is under 2x annual free cash
      flow, High otherwise. Only when cash and debt are both missing
      does debt/equity decide (< 0.5 Low, < 1.0 Moderate, else High).
      Yahoo's debtToEquity field is not trusted on its own: it reads
      1.99 for PLTR, a company holding $10.6B of cash against $0.2B
      of debt.
    - Price Cheap at forward P/E < 0.8x the peer median; Fair up to
      1.5x; Expensive above it. The basis is always shown.
    Grade counts favorable gauges (Growth Strong, Margins Strong,
    Debt Low, Price Cheap or Fair): A = 4, B = 3, C = 2, D = 1, F = 0.
    An unknown gauge counts for neither side and is named in the
    reason.
    """
    gauges = {}

    if growth_cagr is None:
        gauges["growth"] = {"label": "Unknown", "basis": "no revenue history",
                            "value": None}
    elif growth_cagr >= 0.20:
        gauges["growth"] = {"label": "Strong",
                            "basis": f"3-year revenue CAGR {_pct1(growth_cagr)}%",
                            "value": _pct1(growth_cagr)}
    elif growth_cagr >= 0.10:
        gauges["growth"] = {"label": "Moderate",
                            "basis": f"3-year revenue CAGR {_pct1(growth_cagr)}%",
                            "value": _pct1(growth_cagr)}
    else:
        gauges["growth"] = {"label": "Weak",
                            "basis": f"3-year revenue CAGR {_pct1(growth_cagr)}%",
                            "value": _pct1(growth_cagr)}

    if gross_margin is None and operating_margin is None:
        gauges["margins"] = {"label": "Unknown", "basis": "no margin data",
                             "value": None}
    else:
        g = gross_margin if gross_margin is not None else 0.0
        o = operating_margin if operating_margin is not None else 0.0
        if g >= 0.70 or o >= 0.25:
            label = "Strong"
        elif g >= 0.50 or o >= 0.15:
            label = "Moderate"
        else:
            label = "Weak"
        parts = []
        if gross_margin is not None:
            parts.append(f"gross {_pct1(gross_margin)}%")
        if operating_margin is not None:
            parts.append(f"operating {_pct1(operating_margin)}%")
        gauges["margins"] = {"label": label, "basis": ", ".join(parts),
                             "value": _pct1(gross_margin)}

    if net_cash is not None:
        if net_cash > 0:
            gauges["debt"] = {"label": "Low",
                              "basis": f"net cash ${net_cash / 1e9:.1f}B",
                              "value": round(net_cash / 1e9, 1)}
        elif total_debt is not None and free_cashflow \
                and free_cashflow > 0 \
                and total_debt <= 2.0 * free_cashflow:
            gauges["debt"] = {"label": "Moderate",
                              "basis": f"net debt ${-net_cash / 1e9:.1f}B, "
                                       "under 2x free cash flow",
                              "value": round(net_cash / 1e9, 1)}
        else:
            gauges["debt"] = {"label": "High",
                              "basis": f"net debt ${-net_cash / 1e9:.1f}B",
                              "value": round(net_cash / 1e9, 1)}
    elif debt_to_equity is not None:
        if debt_to_equity < 0.5:
            gauges["debt"] = {"label": "Low",
                              "basis": f"debt/equity {round(float(debt_to_equity), 2)}",
                              "value": round(float(debt_to_equity), 2)}
        elif debt_to_equity < 1.0:
            gauges["debt"] = {"label": "Moderate",
                              "basis": f"debt/equity {round(float(debt_to_equity), 2)}",
                              "value": round(float(debt_to_equity), 2)}
        else:
            gauges["debt"] = {"label": "High",
                              "basis": f"debt/equity {round(float(debt_to_equity), 2)}",
                              "value": round(float(debt_to_equity), 2)}
    else:
        gauges["debt"] = {"label": "Unknown", "basis": "no debt data",
                          "value": None}

    if forward_pe is None or peer_median_pe is None:
        gauges["price"] = {"label": "Unknown",
                           "basis": "no peer P/E to compare against",
                           "value": None}
    else:
        ratio = float(forward_pe) / float(peer_median_pe) if peer_median_pe else None
        if ratio is None:
            gauges["price"] = {"label": "Unknown",
                               "basis": "no peer P/E to compare against",
                               "value": None}
        elif ratio < 0.8:
            gauges["price"] = {"label": "Cheap",
                               "basis": f"forward P/E {round(float(forward_pe), 1)} "
                                        f"vs peer median {round(float(peer_median_pe), 1)}",
                               "value": round(float(forward_pe), 1)}
        elif ratio <= 1.5:
            gauges["price"] = {"label": "Fair",
                               "basis": f"forward P/E {round(float(forward_pe), 1)} "
                                        f"vs peer median {round(float(peer_median_pe), 1)}",
                               "value": round(float(forward_pe), 1)}
        else:
            gauges["price"] = {"label": "Expensive",
                               "basis": f"forward P/E {round(float(forward_pe), 1)} "
                                        f"vs peer median {round(float(peer_median_pe), 1)}",
                               "value": round(float(forward_pe), 1)}

    favorable = 0
    favorable += 1 if gauges["growth"]["label"] == "Strong" else 0
    favorable += 1 if gauges["margins"]["label"] == "Strong" else 0
    favorable += 1 if gauges["debt"]["label"] == "Low" else 0
    favorable += 1 if gauges["price"]["label"] in ("Cheap", "Fair") else 0
    grade = {4: "A", 3: "B", 2: "C", 1: "D", 0: "F"}[favorable]

    good = [k for k, g in gauges.items()
            if g["label"] in ("Strong", "Low", "Cheap", "Fair")]
    drags = [k for k, g in gauges.items()
             if g["label"] in ("Weak", "Moderate", "High", "Expensive")]
    unknown = [k for k, g in gauges.items() if g["label"] == "Unknown"]
    names = {"growth": "Growth", "margins": "Margins",
             "debt": "Debt", "price": "Valuation"}
    reason_parts = []
    if good:
        reason_parts.append(
            ", ".join(f"{names[k]} {gauges[k]['label']}" for k in good))
    if drags:
        reason_parts.append(
            "; " + ", ".join(f"{names[k]} {gauges[k]['label']}" for k in drags)
            + " is the drag" if len(drags) == 1 else
            "; " + ", ".join(f"{names[k]} {gauges[k]['label']}" for k in drags)
            + " are the drags")
    if unknown:
        reason_parts.append(
            f" ({', '.join(names[k] for k in unknown)} unknown)")
    grade_reason = "".join(reason_parts) or "No gauge could be computed."
    return {"gauges": gauges, "grade": grade, "grade_reason": grade_reason}


def _strength(value, bands):
    """Strength dots 1-3 from a value and (low, high) bands."""
    if value is None:
        return 1
    if value >= bands[1]:
        return 3
    if value >= bands[0]:
        return 2
    return 1


def build_tailwinds_headwinds(segments, growth_cagr, gross_margin,
                              operating_margin, forward_pe):
    """Rule-based tailwinds and headwinds. Every bullet comes from a
    number, with a threshold. Segment-dependent rules are skipped when
    segment data is unavailable, never guessed.
    """
    tailwinds = []
    headwinds = []
    product = (segments or {}).get("product") or []
    region = (segments or {}).get("region") or []
    by_name = {str(s.get("name", "")).lower(): s for s in product}

    commercial = None
    for key in ("commercial",):
        commercial = by_name.get(key)
    if commercial and commercial.get("growth_pct") is not None \
            and commercial["growth_pct"] >= 50.0:
        g = commercial["growth_pct"]
        tailwinds.append({
            "title": "Commercial growth surge",
            "detail": f"Commercial sales up {round(g)}%",
            "strength": _strength(g, (50.0, 60.0)),
        })

    if (operating_margin is not None and operating_margin >= 0.40) \
            or (gross_margin is not None and gross_margin >= 0.75):
        op = _pct1(operating_margin) if operating_margin is not None else None
        gr = _pct1(gross_margin) if gross_margin is not None else None
        detail = ", ".join(
            p for p in (
                f"{op}% operating margin" if op is not None else None,
                f"{gr}% gross" if gr is not None else None,
            ) if p)
        tailwinds.append({
            "title": "High profitability",
            "detail": detail,
            "strength": 3 if (operating_margin or 0) >= 0.45 else 2,
        })

    us = None
    for s in region:
        if str(s.get("name", "")).lower() in ("united states", "us", "usa"):
            us = s
    if us and us.get("growth_pct") is not None and us["growth_pct"] >= 50.0:
        g = us["growth_pct"]
        tailwinds.append({
            "title": "Strong US demand",
            "detail": f"US revenue growing {round(g)}%",
            "strength": _strength(g, (50.0, 70.0)),
        })

    if growth_cagr is not None and growth_cagr >= 0.30:
        tailwinds.append({
            "title": "Fast growth",
            "detail": f"Sales up {_pct1(growth_cagr)}% a year",
            "strength": 2,
        })

    if forward_pe is not None and forward_pe > 50:
        headwinds.append({
            "title": "Rich valuation",
            "detail": f"Forward P/E of {round(float(forward_pe))}",
            "strength": 3 if forward_pe > 80 else 2,
        })

    government = None
    for key in ("government", "government operating"):
        government = by_name.get(key)
        if government:
            break
    if government and government.get("pct") is not None \
            and government["pct"] >= 50.0:
        p = government["pct"]
        headwinds.append({
            "title": "Government dependence",
            "detail": f"{round(p)}% of sales from governments",
            "strength": 3 if p >= 60.0 else 2,
        })

    rest = None
    for s in region:
        if "rest of world" in str(s.get("name", "")).lower() \
                or "rest-of-world" in str(s.get("name", "")).lower():
            rest = s
    if rest and rest.get("growth_pct") is not None \
            and rest["growth_pct"] < 15.0:
        g = rest["growth_pct"]
        headwinds.append({
            "title": "Weak international growth",
            "detail": f"Rest of world up only {round(g)}%",
            "strength": 2 if g < 10.0 else 1,
        })

    if region:
        top = max(region, key=lambda s: s.get("pct") or 0)
        if top.get("pct") is not None and top["pct"] >= 50.0:
            headwinds.append({
                "title": "Concentrated in one region",
                "detail": f"{top.get('name')} is {round(top['pct'])}% of sales",
                "strength": 2,
            })

    return tailwinds, headwinds


def _break_plain(title, detail):
    """Plain-language break condition for one headwind."""
    if title == "Rich valuation":
        return "the market stops paying a high multiple for growth"
    if title == "Government dependence":
        return "government contracts get cut"
    if title == "Weak international growth":
        return "international sales keep stalling"
    if title == "Concentrated in one region":
        return "its biggest region slows down"
    return detail.lower() if detail else "conditions change"


def what_would_change(headwinds):
    """One line naming what changes the assessment, from the headwinds."""
    if not headwinds:
        return ("What would change this assessment: if revenue growth "
                "slows well below its recent pace.")
    top = sorted(headwinds, key=lambda h: h.get("strength", 1),
                 reverse=True)[:2]
    parts = [_break_plain(h["title"], h.get("detail", "")) for h in top]
    if len(parts) == 1:
        return f"What would change this assessment: if {parts[0]}."
    return f"What would change this assessment: if {parts[0]} or if {parts[1]}."


def story_line(name, industry, growth_cagr, gross_margin, forward_pe):
    """One-line plain-language summary, templated from the numbers."""
    ind = (industry or "").strip()
    if ind:
        ind = ind.lower().replace(" - ", " ")
    growth = _pct1(growth_cagr)
    gross = _pct1(gross_margin)
    parts = [f"{name} is a {ind} company" if ind else f"{name}"]
    if growth is not None:
        parts.append(f"growing sales {growth}% a year")
    if gross is not None:
        parts.append(f"with {gross}% gross margins")
    line = ", ".join(parts) + "."
    if forward_pe is not None:
        line += (f" At a forward P/E of {round(float(forward_pe))}, "
                 "the price assumes the growth continues.")
    return line


# ---------------------------------------------------------------------------
# Fetchers. Each one is guarded: a failure returns None plus a note,
# never an invented value.
# ---------------------------------------------------------------------------

def _fetch_price(ticker):
    """Price from the same OHLCV + indicators the lookup uses."""
    try:
        import services.alert_engine as ae

        df = ae._fetch_ohlcv(ticker)
        if df is None:
            return None, None, "no price history found"
        ind = ae._indicators(df)
        if ind is None or ind.get("price") is None:
            return None, None, "not enough history to compute indicators"
        last = df.index[-1]
        as_of = last.date().isoformat() if hasattr(last, "date") else str(last)
        return float(ind["price"]), as_of, None
    except Exception as exc:
        logger.warning("story price failed for %s: %s", ticker, exc)
        return None, None, f"price fetch failed: {exc}"


def _fetch_yinfo(ticker):
    """yfinance info dict, or None."""
    try:
        import yfinance as yf

        return yf.Ticker(ticker).info or {}
    except Exception as exc:
        logger.warning("story yfinance info failed for %s: %s", ticker, exc)
        return None


def _fetch_revenue_history(ticker):
    """Reported annual revenue bars from yfinance financials.

    Returns [{year, revenue, growth_pct, estimated: False}], ascending.
    Years with no revenue are skipped, never filled in.
    """
    try:
        import yfinance as yf

        fin = yf.Ticker(ticker).financials
        if fin is None or "Total Revenue" not in fin.index:
            return []
        series = fin.loc["Total Revenue"]
        bars = []
        for col in sorted(series.index):
            try:
                value = float(series[col])
            except (TypeError, ValueError):
                continue
            if value != value or value <= 0:
                continue
            year = col.year if hasattr(col, "year") else int(str(col)[:4])
            bars.append({"year": year, "revenue": value,
                         "growth_pct": None, "estimated": False})
        for prev, cur in zip(bars, bars[1:]):
            if prev["revenue"]:
                cur["growth_pct"] = round(
                    (cur["revenue"] / prev["revenue"] - 1.0) * 100, 1)
        return bars
    except Exception as exc:
        logger.warning("story revenue history failed for %s: %s", ticker, exc)
        return []


def _fetch_revenue_estimates(ticker, last_reported_year):
    """Analyst revenue estimates for the current and next fiscal year.

    yfinance revenue_estimate rows '0y' (current year) and '+1y'
    (next year). Only years after the last reported year are kept.
    """
    try:
        import yfinance as yf

        est = yf.Ticker(ticker).revenue_estimate
        if est is None or est.empty:
            return []
        out = []
        this_year = date.today().year
        for row, year in (("0y", this_year), ("+1y", this_year + 1)):
            if row not in est.index:
                continue
            if last_reported_year is not None and year <= last_reported_year:
                continue
            try:
                value = float(est.loc[row, "avg"])
            except (TypeError, ValueError, KeyError):
                continue
            if value != value or value <= 0:
                continue
            growth = None
            try:
                growth = float(est.loc[row, "growth"]) * 100.0
            except (TypeError, ValueError, KeyError):
                growth = None
            out.append({"year": year, "revenue": value,
                        "growth_pct": round(growth, 1) if growth is not None else None,
                        "estimated": True})
        return out
    except Exception as exc:
        logger.warning("story revenue estimates failed for %s: %s", ticker, exc)
        return []


def _fetch_recommendations(ticker):
    """Buy/Hold/Sell counts from yfinance recommendations_summary."""
    try:
        import yfinance as yf

        rec = yf.Ticker(ticker).recommendations_summary
        if rec is None or rec.empty:
            return None
        row = rec.iloc[0]
        buy = int(row.get("strongBuy", 0) or 0) + int(row.get("buy", 0) or 0)
        hold = int(row.get("hold", 0) or 0)
        sell = int(row.get("sell", 0) or 0) + int(row.get("strongSell", 0) or 0)
        total = buy + hold + sell
        if total == 0:
            return None
        return {"buy": buy, "hold": hold, "sell": sell, "total": total}
    except Exception as exc:
        logger.warning("story recommendations failed for %s: %s", ticker, exc)
        return None


def _fetch_peer_facts(tickers):
    """market_cap and forward_pe per ticker, from the working sources.

    Caps come from Polygon ticker details first, Yahoo info second.
    P/E comes from Yahoo info first; for the largest caps still
    missing one after ranking, FMP ratios second and a
    Polygon-computed P/E third. A peer with no market cap is dropped
    by the caller; a peer with no P/E is kept but skipped by the
    median. Runs in parallel.
    """
    def _caps(sym):
        cap = None
        pe = None
        shares = None
        try:
            from services.polygon_client import get_ticker_details

            det = get_ticker_details(sym) or {}
            cap = det.get("market_cap")
            shares = det.get("shares_outstanding")
        except Exception:
            pass
        try:
            import yfinance as yf

            info = yf.Ticker(sym).info or {}
        except Exception:
            info = {}
        if cap is None:
            raw_cap = info.get("marketCap")
            if raw_cap:
                cap = _finite(raw_cap)
        raw_pe = info.get("forwardPE")
        if raw_pe:
            pe = _finite(raw_pe)
        return sym, _finite(cap), pe, shares

    out = {}
    shares_map = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        for sym, cap, pe, shares in pool.map(_caps, tickers):
            out[sym] = {"market_cap": cap, "forward_pe": pe}
            shares_map[sym] = shares
    ranked = sorted(
        (s for s in tickers if out.get(s, {}).get("market_cap")),
        key=lambda s: out[s]["market_cap"], reverse=True)[:8]
    missing = [s for s in ranked if not out[s].get("forward_pe")]

    def _pe(sym):
        try:
            from services.fmp_client import _get

            rows = _get(f"/ratios/{sym}", {"limit": 1}, timeout=8)
            if rows and isinstance(rows, list) \
                    and rows[0].get("priceEarningsRatio"):
                return sym, float(rows[0]["priceEarningsRatio"])
        except Exception:
            pass
        shares = shares_map.get(sym)
        if shares:
            value = _polygon_pe(sym, shares=shares)
            if value:
                return sym, value
        return sym, None

    if missing:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            for sym, pe in pool.map(_pe, missing):
                if pe:
                    out[sym]["forward_pe"] = pe
    return out


def _fetch_peers(ticker, name):
    """Top 8 peers by market cap in the same industry, with shares.

    Peer list: FMP stock-peers first, Polygon related companies
    second. Market caps and forward P/E come from _fetch_peer_facts.
    Shares are of the summed market cap of the eight shown,
    including the subject. Returns (rows, note): the note names the
    fallback source when one was used, or the failure when the list
    cannot be fetched.
    """
    try:
        from services.fmp_client import _get

        raw = _get("/stock-peers", {"symbol": ticker})
        symbols = []
        peer_source = "fmp"
        if raw and isinstance(raw, list):
            for row in raw:
                if isinstance(row, dict) and row.get("symbol"):
                    symbols.append(str(row["symbol"]).upper())
                elif isinstance(row, str):
                    symbols.append(row.upper())
        if not symbols:
            try:
                from services.polygon_client import get_related_companies

                symbols = get_related_companies(ticker) or []
                peer_source = "polygon"
            except Exception:
                symbols = []
        symbols = [s for s in dict.fromkeys(symbols) if s != ticker][:12]
        if not symbols:
            return None, "peer list unavailable from FMP and Polygon"
        facts = _fetch_peer_facts([ticker] + symbols)
        rows = []
        for sym in [ticker] + symbols:
            cap = facts.get(sym, {}).get("market_cap")
            if cap:
                rows.append({"ticker": sym, "market_cap": cap,
                             "forward_pe": facts.get(sym, {}).get("forward_pe"),
                             "is_subject": sym == ticker,
                             "name": name if sym == ticker else sym})
        rows.sort(key=lambda r: r["market_cap"], reverse=True)
        rows = rows[:8]
        total = sum(r["market_cap"] for r in rows)
        if not total:
            return None, "no peer market caps could be fetched"
        for r in rows:
            r["share_pct"] = round(r["market_cap"] / total * 100, 1)
            del r["market_cap"]
        note = None
        if peer_source == "polygon":
            note = ("Peers from Polygon related companies "
                    "(FMP stock-peers unavailable).")
        return rows, note
    except Exception as exc:
        logger.warning("story peers failed for %s: %s", ticker, exc)
        return None, f"peer fetch failed: {exc}"


def _segments_from_rows(rows):
    """Group FMP segmentation rows by date; latest two years.

    Returns [{name, revenue, pct, growth_pct}] for the latest date,
    top 5 plus Other, with year-over-year growth per segment.
    """
    if not rows or not isinstance(rows, list):
        return None, None
    by_date = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        seg = row.get("segment")
        rev = row.get("revenue")
        d = str(row.get("date") or "")[:10]
        if not seg or rev is None or not d:
            continue
        try:
            rev = float(rev)
        except (TypeError, ValueError):
            continue
        by_date.setdefault(d, {})[str(seg)] = rev
    if not by_date:
        return None, None
    dates = sorted(by_date)
    latest = by_date[dates[-1]]
    prior = by_date[dates[-2]] if len(dates) >= 2 else {}
    total = sum(latest.values())
    if not total:
        return None, None
    items = []
    for seg, rev in sorted(latest.items(), key=lambda kv: kv[1], reverse=True):
        growth = None
        if seg in prior and prior[seg]:
            growth = round((rev / prior[seg] - 1.0) * 100, 1)
        items.append({"name": seg, "revenue": rev,
                      "pct": round(rev / total * 100, 1), "growth_pct": growth})
    if len(items) > 5:
        top, rest = items[:5], items[5:]
        other_rev = sum(i["revenue"] for i in rest)
        items = top + [{"name": "Other", "revenue": other_rev,
                        "pct": round(other_rev / total * 100, 1),
                        "growth_pct": None}]
    return items, dates[-1][:4]


def _fetch_segments(ticker):
    """Revenue by product and by region from FMP (free tier).

    Returns ({"product": [...], "region": [...], "as_of": "FY2025",
    "source": "fmp"}, None) or (None, note).
    """
    try:
        from services.fmp_client import _get

        prod = _get("/revenue-product-segmentation",
                    {"symbol": ticker, "period": "annual", "limit": 10})
        geo = _get("/revenue-geographic-segmentation",
                   {"symbol": ticker, "period": "annual", "limit": 10})
        if not prod and not geo:
            return None, "segment data unavailable from FMP"
        product, prod_year = _segments_from_rows(prod)
        region, geo_year = _segments_from_rows(geo)
        if not product and not region:
            return None, "segment data came back empty from FMP"
        year = prod_year or geo_year
        return {"product": product or [], "region": region or [],
                "as_of": f"FY{year}" if year else None,
                "source": "fmp"}, None
    except Exception as exc:
        logger.warning("story segments failed for %s: %s", ticker, exc)
        return None, f"segment fetch failed: {exc}"


def _fetch_dcf(ticker, price):
    """DCF base/bear/bull from the long-term lane, or None.

    Same builder and statements source as the long-term lane, so the
    Story anchor and the lane can never disagree.
    """
    try:
        from services.longterm_valuation import build_longterm
        from services.ondemand_review import fetch_statements
        from services.ticker_lookup import _fundamentals_for

        statements, _note = fetch_statements(ticker, price)
        if statements is None:
            return None, "no reported statements, so no DCF"
        lane = build_longterm(ticker, price,
                              _fundamentals_for(ticker, None),
                              statements=statements)
        dcf = (lane or {}).get("dcf") or {}
        fair = dcf.get("fair_value") or dcf.get("fair") or {}
        if isinstance(fair, dict):
            base = fair.get("base")
        else:
            base = None
        if base is None:
            return None, "DCF is blocked in the long-term lane"
        return {"base": base,
                "bear": fair.get("bear"),
                "bull": fair.get("bull"),
                "verdict": lane.get("verdict")}, None
    except Exception as exc:
        logger.warning("story DCF failed for %s: %s", ticker, exc)
        return None, f"DCF could not be computed: {exc}"


def _fetch_earnings_date(ticker):
    """Next earnings date from the Finnhub 120-day calendar, or None.

    The 30-day window the alert engine uses is correct for its
    earnings gate, but a name that reported this month has its next
    print a quarter out, and the Story should show that date rather
    than reading unknown.
    """
    try:
        from services.finnhub_client import get_earnings_within

        days = get_earnings_within(ticker, days=120)
        if days is None:
            return None
        return (date.today() + timedelta(days=days)).isoformat()
    except Exception as exc:
        logger.warning("story earnings date failed for %s: %s", ticker, exc)
        return None


def _fetch_polygon_fundamentals(ticker):
    """Margins, cash and debt, free cash flow, name from Polygon.

    The fallback when Yahoo company data (yfinance info) is empty
    on the server. Financials are the latest annual SEC filing:
    margins are gross profit and operating income over revenue.
    Debt is long-term debt only, so net cash from here understates
    debt slightly; the gauge still judges net cash first, as
    designed. Returns a dict, possibly empty.
    """
    out = {}
    try:
        from services.polygon_client import get_financials, get_ticker_details

        fin = get_financials(ticker) or {}
        rev = fin.get("revenue")
        if rev and rev > 0:
            gp = fin.get("gross_profit")
            oi = fin.get("operating_income")
            if gp is not None and _finite(gp) is not None:
                out["gross_margin"] = _finite(gp) / _finite(rev)
            if oi is not None and _finite(oi) is not None:
                out["operating_margin"] = _finite(oi) / _finite(rev)
        cash = _finite(fin.get("cash"))
        debt = _finite(fin.get("total_debt"))
        if cash is not None and debt is not None:
            out["net_cash"] = cash - debt
            out["total_debt"] = debt
        fcf = _finite(fin.get("free_cash_flow"))
        if fcf is not None:
            out["free_cashflow"] = fcf
        det = get_ticker_details(ticker) or {}
        if det.get("name"):
            out["name"] = det["name"]
        if det.get("market_cap"):
            out["market_cap"] = det["market_cap"]
        if det.get("shares_outstanding"):
            out["shares_outstanding"] = det["shares_outstanding"]
        if det.get("sic_description"):
            out["sic_description"] = det["sic_description"]
    except Exception as exc:
        logger.warning("story Polygon fundamentals failed for %s: %s", ticker, exc)
    return out


def _fetch_fmp_profile(ticker):
    """Company name, sector, industry from FMP, or None."""
    try:
        from services.fmp_client import _get

        rows = _get("/profile", {"symbol": ticker})
        if rows and isinstance(rows, list) and isinstance(rows[0], dict):
            r = rows[0]
            return {"name": r.get("companyName"),
                    "sector": r.get("sector"),
                    "industry": r.get("industry")}
    except Exception as exc:
        logger.warning("story FMP profile failed for %s: %s", ticker, exc)
    return None


def _fetch_fmp_targets(ticker):
    """Analyst target mean/low/high from FMP consensus, or None.

    FMP consensus publishes no Buy/Hold/Sell counts, so counts stay
    unavailable and the panel shows targets only.
    """
    try:
        from services.fmp_client import _get

        rows = _get("/price-target-consensus", {"symbol": ticker})
        if rows and isinstance(rows, list) and isinstance(rows[0], dict):
            r = rows[0]
            mean = r.get("targetConsensus") or r.get("targetMedian")
            low = r.get("targetLow")
            high = r.get("targetHigh")
            if mean is not None and low is not None and high is not None:
                return {"low": round(float(low), 2),
                        "mean": round(float(mean), 2),
                        "high": round(float(high), 2)}
    except Exception as exc:
        logger.warning("story FMP targets failed for %s: %s", ticker, exc)
    return None


def _fetch_benzinga_targets(ticker):
    """Mean/low/high of recent analyst price targets, or None.

    Last resort for the Outlook panel when both Yahoo targets and
    FMP consensus are missing. This is the mean of the most recent
    analyst actions, not a consensus, and the panel labels it so.
    Needs at least 3 priced actions.
    """
    try:
        from services.polygon_client import get_analyst_ratings

        pts = []
        for item in get_analyst_ratings(ticker, limit=10) or []:
            pt = item.get("pt")
            if pt:
                try:
                    pts.append(float(pt))
                except (TypeError, ValueError):
                    continue
        if len(pts) < 3:
            return None
        return {"low": round(min(pts), 2),
                "mean": round(sum(pts) / len(pts), 2),
                "high": round(max(pts), 2),
                "count": len(pts)}
    except Exception as exc:
        logger.warning("story Benzinga targets failed for %s: %s", ticker, exc)
        return None


def _fetch_fmp_pe(ticker):
    """Forward P/E from FMP ratios, or None."""
    try:
        from services.fmp_client import _get

        rows = _get(f"/ratios/{ticker}", {"limit": 1}, timeout=8)
        if rows and isinstance(rows, list) and rows[0].get("priceEarningsRatio"):
            return float(rows[0]["priceEarningsRatio"])
    except Exception as exc:
        logger.warning("story FMP P/E failed for %s: %s", ticker, exc)
    return None


def _polygon_pe(ticker, shares=None):
    """Forward P/E computed from Polygon: prev close / EPS.

    EPS is latest annual net income over shares outstanding.
    Returns None when any piece is missing or EPS is not positive.
    """
    try:
        from services.polygon_client import (get_financials,
                                             get_ticker_details,
                                             get_ticker_snapshot)

        if not shares:
            det = get_ticker_details(ticker) or {}
            shares = det.get("shares_outstanding")
        if not shares:
            return None
        fin = get_financials(ticker) or {}
        ni = fin.get("net_income")
        if ni is None or ni <= 0:
            return None
        snap = get_ticker_snapshot(ticker) or {}
        price = snap.get("prev_close") or snap.get("price")
        if not price:
            return None
        eps = float(ni) / float(shares)
        if eps <= 0:
            return None
        return _finite(round(float(price) / eps, 2))
    except Exception as exc:
        logger.warning("story Polygon P/E failed for %s: %s", ticker, exc)
        return None


def _fetch_week52(ticker, price):
    """52-week low/high and where the price sits in the range.

    Yahoo 1-year history first (the same source the price bars
    use), Polygon daily closes second. Returns None when neither
    works.
    """
    try:
        import yfinance as yf

        hist = yf.Ticker(ticker).history(period="1y")
        if hist is not None and not hist.empty \
                and "High" in hist and "Low" in hist:
            low = float(hist["Low"].min())
            high = float(hist["High"].max())
            if low and high and high > low:
                pos = None
                if price is not None and price == price:
                    pos = round((price - low) / (high - low) * 100, 1)
                return {"low": round(low, 2), "high": round(high, 2),
                        "position_pct": pos}
    except Exception as exc:
        logger.warning("story week52 Yahoo failed for %s: %s", ticker, exc)
    try:
        from services.polygon_client import get_dated_closes

        rows = get_dated_closes(ticker, days=250) or []
        closes = [float(r[1]) for r in rows if len(r) > 1]
        if closes:
            low = min(closes)
            high = max(closes)
            if low and high and high > low:
                pos = None
                if price is not None and price == price:
                    pos = round((price - low) / (high - low) * 100, 1)
                return {"low": round(low, 2), "high": round(high, 2),
                        "position_pct": pos}
    except Exception as exc:
        logger.warning("story week52 Polygon failed for %s: %s", ticker, exc)
    return None


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def build_story(ticker):
    """Build the Story payload for one ticker."""
    ticker = (ticker or "").upper().strip()
    cached = _cache_get(ticker)
    if cached is not None:
        return cached
    notes = []

    price, price_as_of, price_error = _fetch_price(ticker)
    if price is None:
        payload = {"status": "unavailable", "ticker": ticker,
                   "reason": price_error or "no price available"}
        _cache_put(ticker, payload)
        return payload
    if price != price:
        # NaN: the price feed returned no usable close. Keep the
        # Story (the grade does not need the price) with the
        # price-dependent fields null, instead of 500ing on NaN.
        price = None
        price_as_of = None

    info = _fetch_yinfo(ticker) or {}
    # Fallback sources, used only for fields Yahoo company data did
    # not supply. The Story keeps its letter grade in every case;
    # the fallbacks exist so the gauges are judged on real numbers
    # instead of reading Unknown. Provenance is reported in notes.
    poly = None
    profile = None
    fallback_sources = {}

    def _poly():
        nonlocal poly
        if poly is None:
            poly = _fetch_polygon_fundamentals(ticker)
        return poly or {}

    def _profile():
        nonlocal profile
        if profile is None:
            profile = _fetch_fmp_profile(ticker)
        return profile or {}

    def _used(source, field):
        fallback_sources.setdefault(source, [])
        if field not in fallback_sources[source]:
            fallback_sources[source].append(field)

    name = info.get("longName") or info.get("shortName")
    if not name:
        name = _profile().get("name")
        if name:
            _used("FMP", "company name")
    if not name:
        name = _poly().get("name")
        if name:
            _used("Polygon SEC filings", "company name")
    name = name or ticker
    sector = info.get("sector")
    if not sector:
        sector = _profile().get("sector")
        if sector:
            _used("FMP", "sector")
    industry = info.get("industry")
    if not industry:
        industry = _profile().get("industry")
        if industry:
            _used("FMP", "industry")
    if not industry:
        industry = _poly().get("sic_description")
        if industry:
            _used("Polygon SEC filings", "industry")
    forward_pe = _to_float(info.get("forwardPE"))
    gross_margin = _to_float(info.get("grossMargins"))
    operating_margin = _to_float(info.get("operatingMargins"))
    if gross_margin is None and operating_margin is None:
        p = _poly()
        gross_margin = p.get("gross_margin")
        operating_margin = p.get("operating_margin")
        if gross_margin is not None or operating_margin is not None:
            _used("Polygon SEC filings", "margins")
    debt_to_equity = _to_float(info.get("debtToEquity"))
    net_cash = None
    total_debt = None
    free_cashflow = _to_float(info.get("freeCashflow"))
    total_cash = _to_float(info.get("totalCash"))
    info_debt = _to_float(info.get("totalDebt"))
    if total_cash is not None and info_debt is not None:
        net_cash = total_cash - info_debt
        total_debt = info_debt
    if net_cash is None:
        p = _poly()
        if p.get("net_cash") is not None:
            net_cash = p["net_cash"]
            total_debt = p.get("total_debt")
            _used("Polygon SEC filings", "debt")
        if free_cashflow is None and p.get("free_cashflow") is not None:
            free_cashflow = p["free_cashflow"]
    eps_ttm = info.get("trailingEps")
    try:
        eps_ttm = round(float(eps_ttm), 2) if eps_ttm is not None else None
    except (TypeError, ValueError):
        eps_ttm = None
    week52 = None
    try:
        low = info.get("fiftyTwoWeekLow")
        high = info.get("fiftyTwoWeekHigh")
        if low and high and high > low:
            week52 = {"low": round(float(low), 2), "high": round(float(high), 2),
                      "position_pct": round((price - float(low)) / (float(high) - float(low)) * 100, 1)}
    except (TypeError, ValueError):
        week52 = None
    if week52 is None:
        week52 = _fetch_week52(ticker, price)

    history = _fetch_revenue_history(ticker)
    last_reported_year = history[-1]["year"] if history else None
    estimates = _fetch_revenue_estimates(ticker, last_reported_year)
    bars = history + estimates
    growth_cagr = None
    multiple_text = None
    if len(history) >= 2:
        years = history[-1]["year"] - history[0]["year"]
        growth_cagr = _cagr(history[0]["revenue"], history[-1]["revenue"], years)
        if growth_cagr is not None:
            multiple = history[-1]["revenue"] / history[0]["revenue"]
            multiple_text = (f"{round(multiple, 1)}x revenue in "
                             f"{years} year{'s' if years != 1 else ''}")

    peers, peers_note = _fetch_peers(ticker, name)
    if peers_note:
        notes.append(peers_note)
    peer_median_pe = None
    if peers:
        pes = [p.get("forward_pe") for p in peers
               if p.get("forward_pe")]
        if pes:
            pes.sort()
            peer_median_pe = pes[len(pes) // 2] if len(pes) % 2 == 1 else (
                pes[len(pes) // 2 - 1] + pes[len(pes) // 2]) / 2.0

    if forward_pe is None:
        forward_pe = _fetch_fmp_pe(ticker)
        if forward_pe is not None:
            _used("FMP", "valuation")
    if forward_pe is None:
        value = _polygon_pe(ticker,
                            shares=_poly().get("shares_outstanding"))
        if value:
            forward_pe = value
            _used("Polygon SEC filings", "valuation")

    graded = grade_gauges(growth_cagr, gross_margin, operating_margin,
                          forward_pe, peer_median_pe,
                          net_cash=net_cash, total_debt=total_debt,
                          debt_to_equity=debt_to_equity,
                          free_cashflow=free_cashflow)

    segments, segments_note = _fetch_segments(ticker)
    if segments_note:
        notes.append(segments_note)

    tailwinds, headwinds = build_tailwinds_headwinds(
        segments, growth_cagr, gross_margin, operating_margin, forward_pe)

    targets = None
    try:
        mean = info.get("targetMeanPrice")
        low = info.get("targetLowPrice")
        high = info.get("targetHighPrice")
        if mean is not None and low is not None and high is not None:
            mean = float(mean)
            targets = {"low": round(float(low), 2), "mean": round(mean, 2),
                       "high": round(float(high), 2),
                       "now": round(price, 2) if price is not None else None,
                       "mean_vs_now_pct": round((mean - price) / price * 100, 1)
                       if price else None,
                       "analysts": _fetch_recommendations(ticker),
                       "source": "yahoo"}
    except (TypeError, ValueError):
        targets = None
    if targets is None:
        fmp = _fetch_fmp_targets(ticker)
        if fmp:
            mean = fmp["mean"]
            targets = {"low": fmp["low"], "mean": mean, "high": fmp["high"],
                       "now": round(price, 2) if price is not None else None,
                       "mean_vs_now_pct": round((mean - price) / price * 100, 1)
                       if price else None,
                       "analysts": None, "source": "fmp"}
            _used("FMP", "targets")
    if targets is None:
        benz = _fetch_benzinga_targets(ticker)
        if benz:
            mean = benz["mean"]
            targets = {"low": benz["low"], "mean": mean, "high": benz["high"],
                       "now": round(price, 2) if price is not None else None,
                       "mean_vs_now_pct": round((mean - price) / price * 100, 1)
                       if price else None,
                       "analysts": None, "source": "benzinga",
                       "count": benz.get("count")}
            _used("Polygon Benzinga actions", "targets")
    if targets is None:
        notes.append("analyst price targets unavailable")

    dcf, dcf_note = _fetch_dcf(ticker, price)
    if dcf_note:
        notes.append(dcf_note)
    dcf_payload = None
    if dcf:
        dcf_payload = {"base": dcf.get("base"), "bear": dcf.get("bear"),
                       "bull": dcf.get("bull"), "verdict": dcf.get("verdict")}
    if targets is not None and dcf_payload:
        targets["dcf_base"] = dcf_payload["base"]
        targets["dcf_bear"] = dcf_payload["bear"]
        targets["dcf_bull"] = dcf_payload["bull"]

    earnings_date = _fetch_earnings_date(ticker)

    consistency_note = None
    longterm_verdict = dcf_payload["verdict"] if dcf_payload else None
    if longterm_verdict in ("weak",) and graded["grade"] in ("A", "B"):
        consistency_note = (
            f"The Story grade is {graded['grade']} but the long-term lane "
            "says weak. The two disagree; the DCF above is the lane's number, "
            "so check the long-term card before acting on the grade.")
    elif longterm_verdict in ("strong",) and graded["grade"] in ("D", "F"):
        consistency_note = (
            f"The Story grade is {graded['grade']} but the long-term lane "
            "says strong. The two disagree; the DCF above is the lane's number, "
            "so check the long-term card before acting on the grade.")

    if fallback_sources:
        parts = [f"{', '.join(fields)} from {source}"
                 for source, fields in fallback_sources.items()]
        notes.append("Fallback sources used: " + "; ".join(parts) + ".")

    payload = {
        "status": "ok",
        "ticker": ticker,
        "name": name,
        "price": round(price, 2) if price is not None else None,
        "price_as_of": price_as_of,
        "sector": sector,
        "industry": industry,
        "grade": graded["grade"],
        "grade_reason": graded["grade_reason"],
        "story_line": story_line(name, industry, growth_cagr,
                                 gross_margin, forward_pe),
        "earnings_date": earnings_date,
        "earnings_unknown": earnings_date is None,
        "week52": week52,
        "peers": peers,
        "gauges": graded["gauges"],
        "segments": segments,
        "growth": {"bars": bars, "multiple_text": multiple_text,
                   "gross_margin_pct": _pct1(gross_margin),
                   "eps_ttm": eps_ttm},
        "targets": targets,
        "dcf": dcf_payload,
        "tailwinds": tailwinds,
        "headwinds": headwinds,
        "what_would_change": what_would_change(headwinds),
        "longterm_verdict": longterm_verdict,
        "consistency_note": consistency_note,
        "notes": notes,
    }
    payload = _sanitize(payload)
    _cache_put(ticker, payload)
    return payload
