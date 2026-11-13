"""Insider trading activity for the ticker lookup Answer block.

Primary source is SEC EDGAR directly: Form 4 filings are public
record, free, and need no API key. The app fetches a company's
recent Form 4 filings and parses the open-market transactions
(code P purchases and code S sales) out of the filing XML. A
Form 4 is due within two business days of the trade, so this is
one of the timeliest public signals available.

Fallback is yfinance insider_transactions / insider_purchases.
That data comes from Yahoo's quoteSummary, which already returns
empty on Render (Yahoo throttles Render's IPs), so the fallback
is weak by design and the payload always names its source.

Only open-market transactions count toward the signal. Grants
(code A), option exercises (code M), gifts (code G) and
dispositions to the issuer (code D) are not insiders spending
their own money, so they are excluded from the summary. 10b5-1
plan sales are included in the totals but flagged: a pre-arranged
sale is weaker evidence than a discretionary one, and the
recommendation rules treat heavy net selling as a SELL trigger
only when it is not all pre-arranged.

The summary is a pure function of the parsed transactions, so
it is directly testable. Fetching is guarded: a failure returns
a note, never an invented value.
"""

import json
import logging
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, timedelta

logger = logging.getLogger(__name__)

_CACHE: dict = {}
_CACHE_TTL = 3600
_CACHE_MAX_ENTRIES = 100

_WINDOW_DAYS = 90
_TICKER_CIK_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{doc}"
_USER_AGENT = "TradeIQ/1.0 (https://optionstrade-1raj.onrender.com)"

# Open-market transaction codes only. P = open-market purchase,
# S = open-market sale. Everything else (A grant, M option
# exercise, G gift, D disposition to issuer, F tax withholding,
# J other) is not an insider spending or receiving their own
# money on the open market.
_OPEN_MARKET_CODES = {"P", "S"}

# Heavy discretionary selling, the SELL trigger: at least $25M of
# open-market sales NOT under a 10b5-1 plan in the window.
# 10b5-1 sales are pre-arranged and routine (every large-cap
# executive sells under one), so they must not trigger a sell on
# their own: AAPL, PLTR and ANET all clear $5M+ of 10b5-1 selling
# in 90 days with zero discretionary sales. The $25M bar catches
# a genuinely large discretionary liquidation, such as a director
# selling $350M, and ignores routine executive selling. A
# market-cap-relative bar would be better, but EDGAR alone does
# not give market cap.
_HEAVY_SELL_DISC_VALUE = 25_000_000

# Net discretionary flow that counts as a signal: more than $1M
# net bought or sold, excluding 10b5-1 plan sales.
_SIGNAL_BUY_VALUE = 1_000_000


def _cache_get(ticker: str):
    row = _CACHE.get(ticker)
    if row and time.time() - row[0] < _CACHE_TTL:
        return row[1]
    return None


def _cache_put(ticker: str, payload: dict):
    from services.cache_utils import bounded_put

    bounded_put(_CACHE, ticker, payload, now=time.time(),
                ttl_seconds=_CACHE_TTL, max_entries=_CACHE_MAX_ENTRIES)


def clear_insider_cache():
    _CACHE.clear()


def _http_get(url: str, timeout: int = 15):
    """GET a URL with the SEC-required User-Agent. Returns bytes."""
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


_TICKER_CIK: dict | None = None


def _ticker_to_cik(ticker: str):
    """CIK (10-digit int) for a ticker, from SEC's company list."""
    global _TICKER_CIK
    if _TICKER_CIK is None:
        try:
            raw = json.loads(_http_get(_TICKER_CIK_URL, timeout=15))
            mapping = {}
            for row in raw.values():
                sym = str(row.get("ticker", "")).upper()
                cik = row.get("cik_str")
                if sym and cik:
                    mapping[sym] = int(cik)
            _TICKER_CIK = mapping
        except Exception as exc:
            logger.warning("insider ticker->CIK fetch failed: %s", exc)
            return None
    return (_TICKER_CIK or {}).get(ticker.upper())


def _recent_form4_filings(cik: int, limit: int = 12):
    """Recent Form 4 filings for a CIK, newest first.

    Returns [{accession, primary_doc, filing_date}] from the
    submissions JSON. Amendments (4/A) are skipped: the original
    filing is the signal, and an amendment would double-count it.
    """
    try:
        raw = json.loads(_http_get(_SUBMISSIONS_URL.format(cik=cik),
                                   timeout=15))
    except Exception as exc:
        logger.warning("insider submissions fetch failed for CIK %s: %s",
                       cik, exc)
        return None
    recent = (raw or {}).get("filings", {}).get("recent", {}) or {}
    forms = recent.get("form", []) or []
    accessions = recent.get("accessionNumber", []) or []
    docs = recent.get("primaryDocument", []) or []
    dates = recent.get("filingDate", []) or []
    out = []
    for form, acc, doc, fdate in zip(forms, accessions, docs, dates):
        if form != "4":
            continue
        if not acc or not doc:
            continue
        out.append({"accession": acc, "primary_doc": doc,
                    "filing_date": fdate})
        if len(out) >= limit:
            break
    return out


def _parse_form4_xml(xml_text: str):
    """Open-market transactions from one Form 4 XML document.

    Returns [{date, code, shares, price, value, insider, role,
    is_10b5}]. A transaction with no price or no share count is
    skipped, never guessed. The XML namespace is stripped by
    matching on local tag names.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.warning("insider Form 4 XML parse failed: %s", exc)
        return []

    def _local(tag):
        return tag.rsplit("}", 1)[-1] if "}" in tag else tag

    def _text(elem, name):
        for child in elem:
            if _local(child.tag) == name:
                if child.text is not None and child.text.strip():
                    return child.text.strip()
                # Form 4 values are often nested in a <value> child
                # (transactionShares, transactionPricePerShare,
                # transactionDate), while codes carry direct text.
                for grand in child:
                    if _local(grand.tag) == "value" \
                            and grand.text is not None:
                        return grand.text.strip()
        return None

    def _find(elem, name):
        for child in elem:
            if _local(child.tag) == name:
                return child
        return None

    owner_name = None
    owner_role = None
    is_10b5 = False
    for elem in root.iter():
        if _local(elem.tag) == "reportingOwner":
            name_el = _find(elem, "reportingOwnerId")
            if name_el is not None:
                owner_name = _text(name_el, "rptOwnerName")
            rel = _find(elem, "reportingOwnerRelationship")
            if rel is not None:
                roles = []
                if _text(rel, "isDirector") == "1":
                    roles.append("Director")
                if _text(rel, "isOfficer") == "1":
                    roles.append("Officer")
                    title = _text(rel, "officerTitle")
                    if title:
                        roles[-1] = f"Officer ({title})"
                if _text(rel, "isTenPercentOwner") == "1":
                    roles.append("10% owner")
                owner_role = ", ".join(roles) if roles else None
            break

    out = []
    for elem in root.iter():
        if _local(elem.tag) != "nonDerivativeTransaction":
            continue
        code = None
        coding = _find(elem, "transactionCoding")
        if coding is not None:
            code = _text(coding, "transactionCode")
        if code not in _OPEN_MARKET_CODES:
            continue
        amounts = _find(elem, "transactionAmounts")
        if amounts is None:
            continue
        shares_raw = _text(amounts, "transactionShares")
        price_raw = _text(amounts, "transactionPricePerShare")
        try:
            shares = float(shares_raw) if shares_raw else None
            price = float(price_raw) if price_raw else None
        except (TypeError, ValueError):
            shares = price = None
        if shares is None or price is None or shares <= 0 or price <= 0:
            continue
        tx_date = _text(elem, "transactionDate")
        footnote = None
        for foot in root.iter():
            if _local(foot.tag) == "footnote" and foot.text:
                text = foot.text.lower()
                if "10b5-1" in text or "rule 10b5-1" in text:
                    footnote = True
                    break
        out.append({
            "date": tx_date,
            "code": code,
            "shares": shares,
            "price": round(price, 2),
            "value": round(shares * price, 2),
            "insider": owner_name,
            "role": owner_role,
            "is_10b5": bool(footnote),
        })
    return out


def _fetch_form4_xml(cik: int, accession: str, primary_doc: str):
    """Raw Form 4 XML text for one filing.

    The submissions JSON names the rendered HTML version of the
    filing (xslF345X06/wk-form4_*.xml), which is not XML at all.
    The raw XML sits at the accession root under the same file
    name, so that is tried first. The full primary-document URL
    is the fallback for filings whose primary document is already
    the raw XML.
    """
    raw_name = primary_doc.rsplit("/", 1)[-1]
    candidates = [
        _ARCHIVES_URL.format(cik=cik, accession=accession, doc=raw_name),
    ]
    if primary_doc != raw_name:
        candidates.append(
            _ARCHIVES_URL.format(cik=cik, accession=accession,
                                 doc=primary_doc))
    for url in candidates:
        try:
            raw = _http_get(url, timeout=15)
            text = raw.decode("utf-8", errors="replace")
        except Exception as exc:
            logger.warning("insider Form 4 fetch failed %s: %s", url, exc)
            continue
        if "<ownershipDocument" in text:
            return text
        logger.warning("insider Form 4 at %s is not ownership XML, "
                       "trying the next candidate", url)
    return None


def _fetch_edgar_transactions(ticker: str, window_days: int):
    """Open-market Form 4 transactions from EDGAR in the window.

    Returns (transactions, note). A failure returns ([], note)
    so the caller can fall back to yfinance.
    """
    cik = _ticker_to_cik(ticker)
    if cik is None:
        return [], "CIK lookup failed, no EDGAR filings could be found"
    filings = _recent_form4_filings(cik)
    if filings is None:
        return [], "EDGAR submissions fetch failed"
    if not filings:
        return [], "no Form 4 filings found on EDGAR"
    cutoff = date.today() - timedelta(days=window_days)
    transactions = []
    for filing in filings:
        accession = filing["accession"].replace("-", "")
        text = _fetch_form4_xml(cik, accession, filing["primary_doc"])
        if text is None:
            continue
        for tx in _parse_form4_xml(text):
            if not tx.get("date"):
                continue
            try:
                tx_date = date.fromisoformat(tx["date"][:10])
            except (TypeError, ValueError):
                continue
            if tx_date < cutoff:
                continue
            transactions.append(tx)
    transactions.sort(key=lambda t: t.get("date") or "", reverse=True)
    return transactions, None


def _fetch_yfinance_transactions(ticker: str, window_days: int):
    """Open-market insider transactions from yfinance, or ([], note).

    yfinance insider_transactions is a DataFrame with Transaction
    text like 'Purchase' or 'Sale'. The columns vary by version,
    so this reads defensively and skips rows it cannot parse.
    """
    try:
        import yfinance as yf

        frame = yf.Ticker(ticker).insider_transactions
    except Exception as exc:
        logger.warning("insider yfinance fetch failed for %s: %s",
                       ticker, exc)
        return [], "yfinance insider data unavailable"
    if frame is None or getattr(frame, "empty", True):
        return [], "yfinance returned no insider transactions"
    cutoff = date.today() - timedelta(days=window_days)
    transactions = []
    try:
        rows = frame.to_dict("records")
    except Exception:
        return [], "yfinance insider frame could not be read"
    for row in rows:
        text = str(row.get("Transaction") or "").strip().lower()
        if "purchase" in text:
            code = "P"
        elif "sale" in text:
            code = "S"
        else:
            continue
        try:
            shares = float(row.get("Shares"))
            value = float(row.get("Value"))
        except (TypeError, ValueError):
            continue
        if shares <= 0 or value <= 0:
            continue
        price = round(value / shares, 2) if shares else None
        raw_date = row.get("Date")
        tx_date = None
        try:
            tx_date = str(raw_date)[:10]
            parsed = date.fromisoformat(tx_date)
        except (TypeError, ValueError):
            continue
        if parsed < cutoff:
            continue
        transactions.append({
            "date": tx_date,
            "code": code,
            "shares": shares,
            "price": price,
            "value": round(value, 2),
            "insider": str(row.get("Insider") or "") or None,
            "role": str(row.get("Position") or "") or None,
            "is_10b5": False,
        })
    transactions.sort(key=lambda t: t.get("date") or "", reverse=True)
    return transactions, None


def summarize_insider(transactions, window_days=_WINDOW_DAYS):
    """Pure summary of open-market insider transactions.

    Returns a dict with buy/sell totals, net value, a one-word
    signal (buying / selling / mixed / quiet), and the notable
    transactions (largest buys first). A transaction dated in
    the future is ignored; a transaction with no value is skipped.

    The signal and the heavy_sell flag are judged on
    discretionary flow only: 10b5-1 plan sales are pre-arranged
    and routine, so they are reported in the totals and in
    sell_10b5_value but do not move the signal or trigger a
    sell. A company whose insiders only sell under 10b5-1 plans
    reads as quiet or mixed, not selling.
    """
    buys = [t for t in transactions if t.get("code") == "P"]
    sells = [t for t in transactions if t.get("code") == "S"]
    buy_value = sum(t.get("value") or 0 for t in buys)
    sell_value = sum(t.get("value") or 0 for t in sells)
    net_value = buy_value - sell_value
    # Discretionary flow: 10b5-1 sales removed. This is the
    # economically meaningful signal.
    sell_10b5 = sum(t.get("value") or 0 for t in sells if t.get("is_10b5"))
    disc_sell_value = sell_value - sell_10b5
    disc_net_value = buy_value - disc_sell_value
    # Heavy discretionary selling, the SELL trigger: at least
    # $25M of non-10b5-1 sales in the window.
    heavy_sell = disc_sell_value >= _HEAVY_SELL_DISC_VALUE
    if not transactions:
        signal = "quiet"
    elif disc_net_value > _SIGNAL_BUY_VALUE:
        signal = "buying"
    elif disc_net_value < -_SIGNAL_BUY_VALUE:
        signal = "selling"
    else:
        signal = "mixed"
    # Notable: the largest buys first, then the largest sells.
    notable = sorted(buys, key=lambda t: t.get("value") or 0,
                     reverse=True)[:3]
    notable += sorted(sells, key=lambda t: t.get("value") or 0,
                      reverse=True)[:2]
    return {
        "window_days": window_days,
        "buys": {"count": len(buys), "value": round(buy_value, 2)},
        "sells": {"count": len(sells), "value": round(sell_value, 2)},
        "net_value": round(net_value, 2),
        "signal": signal,
        "heavy_sell": heavy_sell,
        "sell_10b5_value": round(sell_10b5, 2),
        "disc_sell_value": round(disc_sell_value, 2),
        "notable": [
            {"date": t.get("date"), "code": t.get("code"),
             "insider": t.get("insider"), "role": t.get("role"),
             "shares": t.get("shares"), "price": t.get("price"),
             "value": t.get("value"), "is_10b5": t.get("is_10b5")}
            for t in notable
        ],
    }


def fetch_insider(ticker: str):
    """Insider activity for one ticker: EDGAR first, yfinance second.

    Returns a payload with status ok (or unavailable), the
    summary, the recent transactions, and the source named. A
    failure in both sources is reported, never invented.
    """
    ticker = (ticker or "").upper().strip()
    cached = _cache_get(ticker)
    if cached is not None:
        return cached

    transactions, note = _fetch_edgar_transactions(ticker, _WINDOW_DAYS)
    source = "edgar"
    if not transactions and note:
        yf_transactions, yf_note = _fetch_yfinance_transactions(
            ticker, _WINDOW_DAYS)
        if yf_transactions:
            transactions = yf_transactions
            source = "yfinance"
            note = None
        elif yf_note:
            note = f"EDGAR: {note}. yfinance: {yf_note}."
        else:
            note = f"EDGAR: {note}."

    if not transactions and note:
        payload = {"status": "unavailable", "ticker": ticker,
                   "source": source, "reason": note,
                   "summary": summarize_insider([])}
        _cache_put(ticker, payload)
        return payload

    summary = summarize_insider(transactions)
    payload = {
        "status": "ok",
        "ticker": ticker,
        "source": source,
        "window_days": _WINDOW_DAYS,
        "summary": summary,
        "transactions": transactions[:20],
        "note": note,
    }
    _cache_put(ticker, payload)
    return payload
