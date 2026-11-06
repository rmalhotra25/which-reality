"""AI Picks: Claude-generated ideas only, strictly separate from quant.

This module is the one place in the app where Claude is allowed to
suggest strikes, entries, exits, and tickers. That is the entire point
of AI Picks, and it is also why the section is fenced off:

- Nothing here reads or writes the setup registry, the backtest
  harness, or the Book scoreboard. Ideas are never marked LIVE and
  never appear in Today's Book.
- Every idea is labelled AI-generated, and the view carries the
  disclaimer that these are not based on the app's backtested rules
  and are not recommendations.
- Claude's numbers are never trusted on their own. Current prices are
  overwritten from Polygon snapshots when available; when a price
  cannot be fetched it is null and labelled unavailable, never
  invented. Suggested strikes are AI proposals, not chain-verified:
  the chain snapshot is delayed and bid/ask are often 0.0 on the
  Massive Options Starter plan, so a strike must be checked against
  the live chain before anyone acts on it.

Context for Claude is built from Polygon where available: a batch
equity snapshot (price, day change, volume), 35 days of daily bars
(price action and volume versus its average), recent headlines, the
VIX, and a small delayed chain summary near the money. Every Polygon
call is best-effort; a failed fetch narrows the context, it never
invents data.
"""

import json
import logging
import math
import re

logger = logging.getLogger(__name__)

DISCLAIMER = (
    "These are AI-generated ideas only. They are not based on the "
    "app's backtested rules and are not recommendations."
)

DATA_NOTE = (
    "Prices and chain data are delayed about 15 minutes. On the "
    "Massive Options Starter plan, option bid/ask quotes are often "
    "0.0, so a suggested strike is an AI proposal, not a verified "
    "tradable price. Check the live chain before acting on any idea."
)

DEFAULT_TICKERS = ["MSFT", "NVDA", "AAPL", "AMZN", "META", "GOOGL", "TSLA", "AMD", "PLTR", "XOM"]

MAX_OPTIONS_IDEAS = 6
MAX_LONG_TERM_IDEAS = 10


def _clean_json(text: str) -> str:
    """Extract the outermost JSON object or array, whichever comes first.

    Kept local (same logic as claude_analyst._clean_json) so parsing
    AI Picks output never imports the anthropic client: a malformed
    Claude reply must be a parse error, not an import failure.
    """
    text = re.sub(r"```(?:json)?|```", "", text).strip()
    obj = text.find('{')
    arr = text.find('[')
    if obj == -1 and arr == -1:
        return text
    if obj == -1 or (arr != -1 and arr < obj):
        start, end_ch = arr, ']'
    else:
        start, end_ch = obj, '}'
    end = text.rfind(end_ch)
    if end > start:
        return text[start:end + 1]
    return text


def _num(value):
    try:
        if value is None:
            return None
        out = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(out) or math.isinf(out):
        return None
    return out


def _clean_tickers(tickers):
    out = []
    for t in tickers or []:
        t = str(t or "").strip().upper()
        if re.fullmatch(r"[A-Z]{1,6}", t) and t not in out:
            out.append(t)
    return out[:12]


def _bars_summary(bars):
    """Compact price-action summary from daily OHLCV bars (ascending)."""
    closes = [_num(b.get("c")) for b in bars or []]
    closes = [c for c in closes if c]
    vols = [_num(b.get("v")) for b in bars or []]
    vols = [v for v in vols if v]
    if len(closes) < 2:
        return {}
    last = closes[-1]
    def ret(n):
        if len(closes) > n and closes[-1 - n]:
            return round((last / closes[-1 - n] - 1) * 100, 1)
        return None
    avg_vol = sum(vols) / len(vols) if vols else None
    return {
        "price": last,
        "return_5d_pct": ret(5),
        "return_20d_pct": ret(20),
        "high_35d": round(max(closes), 2),
        "low_35d": round(min(closes), 2),
        "volume_vs_avg_pct": round((vols[-1] / avg_vol - 1) * 100, 1) if vols and avg_vol else None,
    }


def _chain_summary(snapshots):
    """Up to 6 near-the-money contracts from a delayed chain snapshot.

    Snapshot objects vary by source, so every field is read with
    getattr and anything unreadable is skipped, never guessed.
    """
    rows = []
    for s in snapshots or []:
        details = getattr(s, "details", None) or {}
        get = (lambda k: details.get(k)) if isinstance(details, dict) else (lambda k: getattr(details, k, None))
        strike = _num(get("strike_price"))
        expiry = get("expiration_date")
        ctype = (get("contract_type") or "")
        if strike is None or not expiry:
            continue
        day = getattr(s, "day", None)
        greeks = getattr(s, "greeks", None) or {}
        gget = (lambda k: greeks.get(k)) if isinstance(greeks, dict) else (lambda k: getattr(greeks, k, None))
        last_quote = getattr(s, "last_quote", None)
        bid = _num(getattr(last_quote, "bid", None)) if last_quote is not None else None
        ask = _num(getattr(last_quote, "ask", None)) if last_quote is not None else None
        rows.append({
            "strike": strike,
            "expiry": str(expiry)[:10],
            "type": str(ctype).lower(),
            "bid": bid,
            "ask": ask,
            "delta": _num(gget("delta")),
            "iv": _num(getattr(s, "implied_volatility", None)),
            "open_interest": _num(getattr(s, "open_interest", None)),
        })
    rows.sort(key=lambda r: abs(r["strike"] - (rows[0]["strike"] if rows else 0)))
    return rows[:6]


def build_context(tickers, fetchers=None):
    """Build the Polygon context Claude sees, best-effort throughout.

    fetchers lets tests inject fakes; in production the Polygon client
    functions are used. A failed fetch leaves that ticker's context
    thin, never fabricated.
    """
    from services import polygon_client as pc

    f = fetchers or {}
    get_snaps = f.get("snapshots_batch", pc.get_snapshots_batch)
    get_bars = f.get("ohlcv_bars", pc.get_ohlcv_bars)
    get_news = f.get("news", pc.get_news)
    get_vix = f.get("vix", pc.get_vix)
    get_chain = f.get("chain_snapshot", pc.get_options_chain_snapshot)

    tickers = _clean_tickers(tickers) or list(DEFAULT_TICKERS)
    try:
        snaps = get_snaps(tickers) or {}
    except Exception as exc:
        logger.warning("ai picks snapshots failed: %s", exc)
        snaps = {}
    try:
        vix = get_vix()
    except Exception:
        vix = None

    context_tickers = []
    for t in tickers:
        snap = snaps.get(t) or {}
        try:
            bars = get_bars(t, days=35) or []
        except Exception:
            bars = []
        try:
            news = get_news(t, limit=3) or []
        except Exception:
            news = []
        summary = _bars_summary(bars)
        price = _num(snap.get("price")) or summary.get("price")
        chain = []
        if price:
            try:
                chain = _chain_summary(get_chain(t, dte_max=45, near_price=price) or [])
            except Exception:
                chain = []
        context_tickers.append({
            "ticker": t,
            "price": price,
            "change_pct": _num(snap.get("change_pct")),
            "prev_close": _num(snap.get("prev_close")),
            "volume": _num(snap.get("volume")),
            "price_action_35d": summary,
            "chain_near_money": chain,
            "news": [
                {"title": n.get("title"), "published_at": n.get("published_at"), "publisher": n.get("publisher")}
                for n in news if n.get("title")
            ],
        })
    return {
        "tickers": context_tickers,
        "vix": _num(vix),
        "data_note": DATA_NOTE,
    }


def build_prompt(context):
    """Focused prompt: act as a professional trader, return JSON only."""
    system = (
        "You are a professional trader reviewing charts and market data. "
        "You write clear, plain-language trade ideas. You never claim a "
        "backtest, a rule, or a guarantee. You use only the prices and "
        "data given to you; when a price is missing you say so instead of "
        "inventing one. Respond ONLY with a valid JSON object, no prose, "
        "no markdown fences."
    )
    user = (
        "Using the market context below (delayed prices, 35 days of price "
        "action, recent headlines, VIX, and a delayed near-the-money "
        "options chain summary), produce two lists.\n\n"
        "1. options_ideas: up to 6 specific call or put setups (buy or "
        "sell) on the tickers in the context. For each: ticker, "
        "option_type (call or put), action (buy or sell), strike, expiry "
        "(YYYY-MM-DD within 45 days), entry_price (the price to buy in "
        "at, per share), exit_price (the price to get out at, per "
        "share), stop_price, plan_text (a 2-3 sentence day-trader style "
        "plan: buy in at this price, get out at this price, what "
        "invalidates it), reasoning (2-3 sentences from price action, "
        "volume, volatility, and news), key_risks (short list).\n\n"
        "2. long_term_ideas: exactly 10 stocks that appear undervalued "
        "with meaningful upside potential for a multi-year hold. Prefer "
        "the tickers in the context, but you may add others you judge "
        "undervalued. For each: ticker, company_name, thesis (2-3 plain "
        "sentences on why it might be undervalued and where upside could "
        "come from), key_risks (short list), upside_case (one sentence).\n\n"
        "Return ONLY this JSON shape:\n"
        '{"options_ideas": [{"ticker": "MSFT", "option_type": "call", '
        '"action": "buy", "strike": 0, "expiry": "YYYY-MM-DD", '
        '"entry_price": 0, "exit_price": 0, "stop_price": 0, '
        '"plan_text": "...", "reasoning": "...", '
        '"key_risks": ["..."]}], '
        '"long_term_ideas": [{"ticker": "MSFT", "company_name": "...", '
        '"thesis": "...", "key_risks": ["..."], "upside_case": "..."}]}\n\n'
        f"Market context:\n{json.dumps(context, indent=2)}"
    )
    return system, user


def _str_list(value):
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()][:5]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _text(value, limit=1200):
    if value is None:
        return ""
    return str(value).strip()[:limit]


def parse_ai_picks_response(text):
    """Validate Claude's JSON into the AI Picks shape.

    Drops malformed ideas instead of repairing them, truncates the
    long-term list to 10, and never invents a price: a missing or
    invalid price stays null for apply_polygon_prices to fill or
    leave unavailable.
    """
    try:
        data = json.loads(_clean_json(text))
    except Exception as exc:
        logger.warning("ai picks: Claude response was not valid JSON: %s", exc)
        return {"options_ideas": [], "long_term_ideas": [], "parse_error": "Claude returned invalid JSON."}
    if not isinstance(data, dict):
        return {"options_ideas": [], "long_term_ideas": [], "parse_error": "Claude returned invalid JSON."}

    options = []
    for raw in (data.get("options_ideas") or [])[:MAX_OPTIONS_IDEAS]:
        if not isinstance(raw, dict):
            continue
        ticker = str(raw.get("ticker") or "").strip().upper()
        otype = str(raw.get("option_type") or "").strip().lower()
        action = str(raw.get("action") or "").strip().lower()
        strike = _num(raw.get("strike"))
        if not re.fullmatch(r"[A-Z]{1,6}", ticker):
            continue
        if otype not in ("call", "put") or action not in ("buy", "sell"):
            continue
        if strike is None or strike <= 0:
            continue
        options.append({
            "ticker": ticker,
            "option_type": otype,
            "action": action,
            "strike": strike,
            "expiry": _text(raw.get("expiry"), 12) or None,
            "entry_price": _num(raw.get("entry_price")),
            "exit_price": _num(raw.get("exit_price")),
            "stop_price": _num(raw.get("stop_price")),
            "plan_text": _text(raw.get("plan_text")),
            "reasoning": _text(raw.get("reasoning")),
            "key_risks": _str_list(raw.get("key_risks")),
            "ai_generated": True,
        })

    long_term = []
    for raw in (data.get("long_term_ideas") or [])[:MAX_LONG_TERM_IDEAS]:
        if not isinstance(raw, dict):
            continue
        ticker = str(raw.get("ticker") or "").strip().upper()
        if not re.fullmatch(r"[A-Z]{1,6}", ticker):
            continue
        long_term.append({
            "ticker": ticker,
            "company_name": _text(raw.get("company_name"), 120) or ticker,
            "current_price": _num(raw.get("current_price")),
            "price_source": "ai_claimed",
            "thesis": _text(raw.get("thesis")),
            "key_risks": _str_list(raw.get("key_risks")),
            "upside_case": _text(raw.get("upside_case"), 400),
            "ai_generated": True,
        })

    return {"options_ideas": options, "long_term_ideas": long_term, "parse_error": None}


def apply_polygon_prices(payload, prices):
    """Overwrite AI-claimed prices with Polygon prices where available.

    prices is {ticker: price}. A Polygon price replaces the claimed
    one and is labelled polygon; a missing Polygon price leaves the
    claimed price labelled ai_claimed, and a missing claimed price
    stays null and labelled unavailable.
    """
    out = json.loads(json.dumps(payload))
    for idea in out.get("options_ideas", []):
        p = _num((prices or {}).get(idea["ticker"]))
        idea["reference_price"] = p
        idea["price_source"] = "polygon" if p else "unavailable"
    for idea in out.get("long_term_ideas", []):
        p = _num((prices or {}).get(idea["ticker"]))
        if p:
            idea["current_price"] = p
            idea["price_source"] = "polygon"
        elif idea.get("current_price") is None:
            idea["price_source"] = "unavailable"
    return out


def serialize_run(run):
    """Public shape for one stored run. No LIVE field, no setup key."""
    try:
        payload = json.loads(run.payload or "{}")
    except Exception:
        payload = {}
    return {
        "id": run.id,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "tickers": json.loads(run.tickers or "[]"),
        "status": run.status,
        "error": run.error,
        "disclaimer": DISCLAIMER,
        "data_note": DATA_NOTE,
        "options_ideas": payload.get("options_ideas", []),
        "long_term_ideas": payload.get("long_term_ideas", []),
        "parse_error": payload.get("parse_error"),
        "context_as_of": payload.get("context_as_of"),
    }
