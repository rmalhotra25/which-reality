"""Company-name search via Yahoo Finance.

Type a company name, get matching tickers. Yahoo search needs no
API key. A source failure returns an empty list, never an exception,
so the autocomplete degrades to no suggestions instead of an error.
"""

import logging
import time

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 300
_MAX_RESULTS = 8
_cache = {}


def clear_search_cache():
    _cache.clear()


def _search_yahoo(query):
    """Return the raw quotes list from yfinance Search, or None."""
    try:
        import yfinance as yf
        result = yf.Search(query, max_results=20)
        return result.quotes or []
    except Exception as e:
        logger.debug("yahoo search failed %s: %s", query, e)
        return None


def search_companies(query, _search=_search_yahoo):
    """Return up to 8 equity matches for a company name or ticker.

    Each match is {"ticker", "name", "exchange"}. Queries shorter
    than 2 characters return an empty list. When the source provides
    a quote type, only equities are kept; when it provides none, the
    top matches are returned as-is. Results are cached for 5 minutes
    per query so typing does not hammer the source.
    """
    q = (query or "").strip()
    if len(q) < 2:
        return []
    key = q.lower()
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < _CACHE_TTL_SECONDS:
        return hit[1]
    quotes = _search(q)
    results = []
    if quotes:
        for quote in quotes:
            quote_type = quote.get("quoteType")
            if quote_type is not None and quote_type != "EQUITY":
                continue
            symbol = (quote.get("symbol") or "").strip()
            if not symbol:
                continue
            name = (quote.get("longname") or quote.get("shortname") or symbol).strip()
            results.append({
                "ticker": symbol,
                "name": name,
                "exchange": (quote.get("exchDisp") or "").strip(),
            })
            if len(results) >= _MAX_RESULTS:
                break
    _cache[key] = (now, results)
    return results
