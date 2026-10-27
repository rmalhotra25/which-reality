import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import anthropic
from config import settings

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"

_FINANCIAL_DOMAINS = [
    "reuters.com",
    "finance.yahoo.com",
    "sec.gov",
    "marketwatch.com",
    "wsj.com",
    "seekingalpha.com",
    "benzinga.com",
    "fool.com",
    "finviz.com",
    "cnbc.com",
    "bloomberg.com",
    "investing.com",
    "businesswire.com",
    "prnewswire.com",
]


def _clean_json(text: str) -> str:
    """Extract the outermost JSON object or array, whichever comes first."""
    text = re.sub(r"```(?:json)?|```", "", text).strip()
    obj = text.find('{')
    arr = text.find('[')
    # Pick whichever opening bracket appears first
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


# Pure date math lives in services.ai_boundary now, so the live path
# can use tradeable expiries without touching a model. Kept as an
# alias because other explain-only callers in this file use it.
from services.ai_boundary import valid_expiry_dates as _valid_expiry_dates  # noqa: E402,F401


# ------------------------------------------------------------------
# Roll net math (review C3). A roll's net is (new premium received)
# MINUS (cost to buy back the old put). The premium originally
# received is sunk money already in the account and must never be
# subtracted here. Both legs must be tradable prices: the new put's
# bid (what a seller collects) and the open put's ask (what a buyer
# pays to close). On the Massive Options Starter plan bid/ask are
# 0.0, so when either leg has no live bid/ask the net is unknown
# and must not be presented at all.
# ------------------------------------------------------------------
def compute_roll_net(new_bid: float | None, buyback_ask: float | None) -> float | None:
    """Net per share of rolling into a new put: new bid minus buyback ask.

    Positive is a credit, negative is a debit. Returns None when
    either leg is missing or not a positive tradable price.
    """
    if new_bid is None or buyback_ask is None:
        return None
    try:
        bid = float(new_bid)
        ask = float(buyback_ask)
    except (TypeError, ValueError):
        return None
    if bid <= 0 or ask <= 0:
        return None
    return round(bid - ask, 2)


def validate_roll_net(claude_net: float | None, computed_net: float | None, tol: float = 0.01) -> tuple[float | None, bool]:
    """Trust the computed roll net over Claude's estimated_net.

    Returns (trusted_net, agrees): the computed net when one exists,
    otherwise None with agrees False (no net can be trusted). When
    Claude's figure disagrees with the computed net by more than tol,
    the computed net wins and agrees is False.
    """
    if computed_net is None:
        return None, False
    if claude_net is None:
        return computed_net, False
    try:
        agrees = abs(float(claude_net) - float(computed_net)) <= tol
    except (TypeError, ValueError):
        agrees = False
    return computed_net, agrees


def fetch_open_put_buyback(ticker: str, put_strike: float, put_expiry: str) -> dict | None:
    """Fetch the open put's current buyback price from the chain.

    Returns {"ask": float | None, "mid": float | None, "source": str}
    for the exact strike and expiry, or None when the contract is
    not found on any source. ask is None when the chain carries no
    live ask (the normal state on the Starter plan, where ask is
    0.0); mid is the last-trade or fair-value price, which is not a
    tradable buyback price and must never be used as the ask.
    """
    from datetime import date as _date

    try:
        dte = (_date.fromisoformat(str(put_expiry)) - _date.today()).days
    except Exception:
        return None
    if dte < 0:
        return None
    dte_min = max(0, dte - 1)
    dte_max = dte + 1

    from services.chain_provider import ChainProvider

    provider = ChainProvider()
    rows: list[dict] = []
    source = ""
    try:
        rows, _price = provider._fetch_polygon_rows(
            ticker, "put", dte_min, dte_max, near_price=float(put_strike)
        )
        source = "polygon_live"
    except Exception as e:
        logger.debug("fetch_open_put_buyback polygon failed for %s: %s", ticker, e)
    if not rows:
        try:
            rows, _price, _src = provider._fetch_yfinance_rows(
                ticker, "put", dte_min, dte_max, live_price=None
            )
            source = "yfinance_last_trade"
        except Exception as e:
            logger.debug("fetch_open_put_buyback yfinance failed for %s: %s", ticker, e)
    for row in rows or []:
        try:
            if float(row.get("strike") or 0) != float(put_strike):
                continue
            if str(row.get("expiry")) != str(put_expiry):
                continue
        except (TypeError, ValueError):
            continue
        ask = float(row.get("ask") or 0)
        mid = float(row.get("mid") or 0)
        return {
            "ask": round(ask, 2) if ask > 0 else None,
            "mid": round(mid, 2) if mid > 0 else None,
            "source": source,
        }
    return None



class ClaudeAnalyst:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    def _call(self, system: str, user: str, max_tokens: int = 4096) -> str:
        msg = self.client.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return msg.content[0].text

    def _parse(self, text: str) -> Any:
        return json.loads(_clean_json(text))

    def _fetch_stock_news(self, ticker: str, company_name: str = "") -> str:
        """Use Anthropic web search to fetch real-time news for a ticker. Returns bullet points or empty string."""
        ctx = f" ({company_name})" if company_name else ""
        tools = [{
            "type": "web_search_20260209",
            "name": "web_search",
            "allowed_domains": _FINANCIAL_DOMAINS,
            "max_uses": 3,
        }]
        messages = [{
            "role": "user",
            "content": (
                f"Search for the most recent financial news and analyst commentary about {ticker}{ctx} stock. "
                f"Include: recent earnings, guidance, analyst upgrades/downgrades, product news, macro tailwinds/headwinds. "
                f"Return ONLY a concise bulleted list (3-6 bullets) of the most market-moving items. No preamble."
            ),
        }]

        for _ in range(6):
            resp = self.client.messages.create(
                model=MODEL,
                max_tokens=1024,
                system="You are a financial news researcher. Search for and summarize key recent developments concisely.",
                tools=tools,
                messages=messages,
            )

            if resp.stop_reason != "tool_use":
                for block in resp.content:
                    if block.type == "text":
                        return block.text.strip()
                return ""

            # Serialize current assistant message
            messages.append({
                "role": "assistant",
                "content": [b.model_dump() for b in resp.content],
            })

            # Map tool_use_id → search result content from web_search_tool_result blocks
            result_map: dict[str, Any] = {}
            for block in resp.content:
                d = block.model_dump()
                if d.get("type") == "web_search_tool_result":
                    result_map[d.get("tool_use_id", "")] = d.get("content", [])

            tool_results = []
            for block in resp.content:
                d = block.model_dump()
                if d.get("type") == "tool_use":
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": d["id"],
                        "content": result_map.get(d["id"], "No results found"),
                    })

            if tool_results:
                messages.append({"role": "user", "content": tool_results})

        return ""



    # ------------------------------------------------------------------
    # Long-term growth & income analysis
    # ------------------------------------------------------------------
    def analyze_longterm(self, news_bullets: str, fundamental_data: str,
                         quant_scores: dict | None = None) -> list[dict]:
        system = (
            "You are a fundamental equity analyst and portfolio manager with expertise in "
            "long-term investing (12+ month horizon). You combine fundamental analysis with "
            "long-term technical trend analysis: stocks must be in structural uptrends (above MA200), "
            "ideally with a golden cross (MA50 > MA200), and showing accumulation in volume trends. "
            "Respond ONLY with a valid JSON array — no prose, no markdown fences."
        )
        quant_ctx = ""
        if quant_scores:
            lines = []
            for ticker, qs in quant_scores.items():
                comp = qs.get("composite", 50)
                ee = qs.get("entry_exit", {})
                lines.append(
                    f"  {ticker}: quant_score={comp}/100 | "
                    f"buy_zone=${ee.get('buy_zone_low','?')}-${ee.get('buy_zone_high','?')} "
                    f"stop=${ee.get('invalidation_stop','?')}"
                )
            quant_ctx = "\nPre-computed quantitative scores:\n" + "\n".join(lines) + "\n"

        user = (
            f"Current date/time (UTC): {datetime.now(timezone.utc).isoformat()}\n"
            f"{quant_ctx}\n"
            f"Recent news and sentiment:\n{news_bullets}\n\n"
            f"Fundamental + technical data:\n{fundamental_data}\n\n"
            "Selection criteria:\n"
            "- Growth picks: strong revenue/EPS growth, above MA200, ideally golden cross, "
            "RSI not above 75 (avoid buying at peak)\n"
            "- Income picks: dividend yield >2%, above MA200 for capital preservation, "
            "low RSI volatility, stable volume trend\n"
            "- Avoid stocks in death cross or below MA200 (structural downtrend)\n"
            "- Note the 52-week range position to assess entry quality\n\n"
            "In your explanation, cite: the fundamental thesis, the technical trend status "
            "(MA50/200 relationship), and the key risk.\n"
            "Your 'qual_score' is your qualitative judgment (0-100) incorporating fundamental "
            "quality, competitive moat, and macro tailwinds beyond the math.\n"
            "Also provide buy_zone_low, buy_zone_high (ideal entry price range), and "
            "invalidation_stop (price below which the thesis is broken).\n\n"
            "Return a JSON array of exactly 5 objects:\n"
            "[\n"
            '  {"rank":1,"ticker":"NVDA","investment_type":"growth","target_price":1200.0,'
            '"time_horizon":"18-24 months","buy_zone_low":850.0,"buy_zone_high":920.0,'
            '"invalidation_stop":780.0,"qual_score":91,"score":94,"grade":"A",'
            '"explanation":"3-4 sentences on fundamentals, trend, catalyst, and risk"}\n'
            "]\n\n"
            "Scoring rubric for qual_score and score (0-100):\n"
            "Growth: earnings growth 30% + technical trend 25% + market position 25% + valuation 20%.\n"
            "Income: dividend yield+safety 35% + technical trend 25% + balance sheet 25% + sector 15%.\n"
            "Grade: A=90-100, B=80-89, C=70-79, D=60-69, F=below 60."
        )
        raw = self._call(system, user)
        return self._parse(raw)


    # ------------------------------------------------------------------
    # On-demand single-stock analysis (Stock Lookup tab)
    # ------------------------------------------------------------------
    def analyze_stock(
        self,
        ticker: str,
        current_price: float,
        technicals: dict,
        fundamentals: dict,
        news_bullets: str,
    ) -> dict:
        system = (
            "You are a senior equity analyst combining technical analysis, fundamental research, "
            "and market sentiment to produce actionable stock ratings. "
            "Respond ONLY with a valid JSON object — no prose, no markdown fences."
        )

        # Enrich news context with real-time web search
        company_name = (fundamentals or {}).get("company_name", "")
        try:
            web_news = self._fetch_stock_news(ticker, company_name)
            if web_news:
                news_bullets = (
                    f"[Live web search — real-time news]\n{web_news}\n\n"
                    f"[Background news provided]\n{news_bullets}"
                )
                logger.info("Web search enrichment succeeded for %s", ticker)
        except Exception as exc:
            logger.warning("Web search failed for %s: %s", ticker, exc)

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        ma = technicals.get("moving_averages", {})
        fib = technicals.get("fibonacci", {})
        bb = technicals.get("bollinger", {})
        macd = technicals.get("macd", {})

        tech_str = (
            f"Price: ${current_price} | RSI={technicals.get('rsi','?')} | "
            f"ATR={technicals.get('atr','?')} | VWAP={technicals.get('vwap','?')}\n"
            f"MA20={ma.get('ma20','?')} MA50={ma.get('ma50','?')} MA200={ma.get('ma200','?')}\n"
            f"Bollinger: upper={bb.get('upper','?')} mid={bb.get('middle','?')} lower={bb.get('lower','?')} "
            f"%B={bb.get('pct_b','?')}\n"
            f"MACD={macd.get('macd','?')} signal={macd.get('signal','?')} "
            f"hist={macd.get('histogram','?')} [{macd.get('crossover','?')}]\n"
            f"Fib levels (from recent swing): "
            f"23.6%={fib.get('fib_236','?')} 38.2%={fib.get('fib_382','?')} "
            f"50%={fib.get('fib_500','?')} 61.8%={fib.get('fib_618','?')}\n"
            f"5d change: {technicals.get('change_5d_pct','?')}% | "
            f"Vol vs avg: {technicals.get('volume_trend', {}).get('ratio','?')}x"
        )

        fund_str = ""
        if fundamentals:
            fund_str = (
                f"\nFundamentals: PE={fundamentals.get('pe_ratio','?')} | "
                f"EPS growth={fundamentals.get('eps_growth_ttm','?')} | "
                f"Revenue growth={fundamentals.get('revenue_growth_ttm','?')} | "
                f"Div yield={fundamentals.get('div_yield','?')} | "
                f"Sector={fundamentals.get('sector','?')}"
            )

        user = (
            f"Today: {today_str}\n"
            f"Analyze {ticker} and produce a structured buy/sell/hold rating with price predictions.\n\n"
            f"Technical indicators:\n{tech_str}\n"
            f"{fund_str}\n\n"
            f"Recent news and sentiment:\n{news_bullets}\n\n"
            "Produce a comprehensive analysis covering:\n"
            "- Overall rating: BUY, SELL, or HOLD\n"
            "- Conviction: HIGH, MEDIUM, or LOW\n"
            "- Short-term outlook (1-4 weeks): direction, price target, key catalyst\n"
            "- Long-term outlook (3-12 months): direction, price target, thesis\n"
            "- Key support levels (2-3 price levels where buyers likely step in)\n"
            "- Key resistance levels (2-3 price levels where sellers likely emerge)\n"
            "- Main upside catalysts (2-3 bullet points)\n"
            "- Main risks (2-3 bullet points)\n"
            "- Technical summary: cite RSI, MACD status, MA alignment, Bollinger position\n"
            "- Score 0-100 for overall confidence\n\n"
            "Return JSON:\n"
            '{"ticker":"AAPL","rating":"BUY","conviction":"HIGH","score":84,"grade":"B",'
            '"current_price":192.50,'
            '"short_term":{"direction":"bullish","price_target":205.0,'
            '"timeframe":"2-3 weeks","catalyst":"RSI bounce from oversold, MACD crossover imminent"},'
            '"long_term":{"direction":"bullish","price_target":240.0,'
            '"timeframe":"6-9 months","thesis":"AI integration across product line drives margin expansion"},'
            '"support_levels":[188.0,182.5,175.0],'
            '"resistance_levels":[198.0,205.0,215.0],'
            '"upside_catalysts":["iPhone supercycle","Services revenue acceleration","India expansion"],'
            '"risks":["China demand slowdown","Valuation premium at risk if rates rise","Regulatory headwinds"],'
            '"technical_summary":"RSI at 38 approaching oversold; price below MA50 but above MA200 — '
            'dip within uptrend. MACD histogram turning less negative. BB %B at 0.15 near lower band.",'
            '"explanation":"2-3 sentence overall thesis combining technical and fundamental view"}'
        )
        raw = self._call(system, user, max_tokens=2048)
        return self._parse(raw)

    # ------------------------------------------------------------------
    # On-demand Wheel Strategy custom analysis (user enters any ticker)
    # ------------------------------------------------------------------
    def analyze_wheel_custom(
        self,
        ticker: str,
        current_price: float,
        put_tiers: dict,
        fundamentals: dict,
        technicals: dict,
        news_bullets: str,
    ) -> dict:
        # Enrich news with real-time web search before put-selling analysis
        company_name = (fundamentals or {}).get("company_name", "")
        try:
            web_news = self._fetch_stock_news(ticker, company_name)
            if web_news:
                news_bullets = (
                    f"[Live web search — real-time news]\n{web_news}\n\n"
                    f"[Background news provided]\n{news_bullets}"
                )
                logger.info("Web search enrichment succeeded for wheel analysis: %s", ticker)
        except Exception as exc:
            logger.warning("Web search failed for wheel analysis %s: %s", ticker, exc)

        system = (
            "You are a friendly options income coach. Your job is to help everyday investors "
            "understand the Wheel Strategy in plain, simple English — no jargon, no confusing "
            "finance terms. Write as if explaining to a smart friend who has never traded options. "
            "Respond ONLY with a valid JSON object — no prose, no markdown fences."
        )

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        ma = technicals.get("moving_averages", {})
        bb = technicals.get("bollinger", {})
        rsi = technicals.get("rsi", "?")
        atr = technicals.get("atr", "?")

        def _fmt_tier(t: dict | None, label: str) -> str:
            if not t:
                return f"  {label}: No suitable option found\n"
            return (
                f"  {label}:\n"
                f"    Strike=${t['strike']} | Expiry={t['expiry']} ({t['dte']} days)\n"
                f"    Bid=${t['bid']} / Ask=${t['ask']} | Mid=${t['mid_premium']} "
                f"(collect ${t['premium_per_contract']} per contract = 100 shares)\n"
                f"    IV={t['iv_pct']}% | Delta={t['delta_abs']} "
                f"(~{t['assignment_chance_pct']}% assignment chance)\n"
                f"    Daily time-decay income per contract=${t['daily_income_per_contract']}\n"
                f"    Breakeven=${t['breakeven']} (protected until stock drops {t['drop_to_breakeven_pct']}%)\n"
                f"    Annualized return on capital={t['annualized_return_pct']}%\n"
                f"    Volume={t['volume']} Open Interest={t['open_interest']}\n"
            )

        data_src = put_tiers.get("data_source", "last_trade")
        src_note = (
            "live bid/ask prices from open market"
            if data_src == "live"
            else "last-trade prices (markets closed — most recent actual transactions)"
        )
        tiers_str = (
            f"REAL OPTIONS DATA ({src_note}):\n"
            f"Current price: ${current_price} | ATM IV: {put_tiers.get('atm_iv_pct','?')}%\n\n"
            + _fmt_tier(put_tiers.get("likely"),   "TIER 1 — HIGH PREMIUM, HIGHER ASSIGNMENT RISK (~45% delta)")
            + _fmt_tier(put_tiers.get("moderate"), "TIER 2 — BALANCED PREMIUM AND RISK (~30% delta)")
            + _fmt_tier(put_tiers.get("unlikely"), "TIER 3 — CONSERVATIVE, LOWER PREMIUM (~16% delta)")
        )

        tech_str = (
            f"RSI={rsi} | MA50={ma.get('ma50','?')} MA200={ma.get('ma200','?')} "
            f"| Price {'above' if current_price > (ma.get('ma200') or 0) else 'below'} 200-day average\n"
            f"Bollinger %B={bb.get('pct_b','?')} | ATR={atr} (typical daily move)"
        )

        fund_str = (
            f"PE ratio={fundamentals.get('pe_ratio','?')} | "
            f"Revenue growth={fundamentals.get('revenue_growth_ttm','?')} | "
            f"Dividend yield={fundamentals.get('div_yield','?')} | "
            f"Sector={fundamentals.get('sector','?')}"
        ) if fundamentals else "Fundamental data unavailable"

        user = (
            f"Today: {today_str}\n"
            f"Analyze {ticker} (price=${current_price}) for the Wheel Strategy.\n\n"
            f"Technical picture:\n{tech_str}\n\n"
            f"Fundamentals: {fund_str}\n\n"
            f"Recent news:\n{news_bullets}\n\n"
            f"{tiers_str}\n"
            "Write everything in plain English. Avoid words like 'delta', 'theta', 'IV', 'volatility'. "
            "Instead use phrases like:\n"
            "- 'assignment chance' → 'chance you end up buying the shares'\n"
            "- 'IV is high' → 'options are pricier than usual right now — great time to sell'\n"
            "- 'theta decay' → 'earns money just from time passing'\n"
            "- 'breakeven' → 'you only lose money if the stock drops below $X'\n\n"
            "Return JSON with these exact fields:\n"
            '{"ticker":"AAPL","current_price":192.50,'
            '"wheel_rating":"GOOD",'
            '"wheel_score":82,'
            '"grade":"B",'
            '"company_assessment":"2-3 sentences: Is this a good company to own if assigned? '
            'Mention stability, business quality, and whether you are comfortable owning shares.",'
            '"technicals_plain":"1-2 sentences in plain English about the chart setup. '
            'No indicator names — just what it means (e.g. The stock is in a healthy uptrend)",'
            '"iv_environment_plain":"1 sentence: are options cheap, fair, or expensive right now? '
            'What does that mean for the seller? (e.g. Options are pricier than usual — '
            'great time to collect premium)",'
            '"tiers":['
            '{"tier_name":"Higher premium, more likely to buy shares",'
            '"strike":190.0,"expiry":"2026-05-01","dte":9,'
            '"premium_plain":"You collect $420 upfront for agreeing to buy 100 shares",'
            '"assignment_plain":"Roughly a 45-in-100 chance you end up buying the shares at $190",'
            '"time_decay_plain":"Earns about $18 per day automatically just from time passing",'
            '"protection_plain":"You only start losing money if the stock drops below $186",'
            '"return_plain":"If this keeps expiring worthless, it is like earning 28% per year on your cash",'
            '"best_for":"Investors who actually want to own the shares and want maximum premium"},'
            '{"tier_name":"Balanced — decent premium with a reasonable safety cushion",...},'
            '{"tier_name":"Conservative — smaller premium but much safer",...}'
            '],'
            '"overall_verdict":"2-3 sentences recommending which tier makes most sense right now and why."}'
        )
        raw = self._call(system, user, max_tokens=3000)
        return self._parse(raw)

    # ------------------------------------------------------------------
    # Phase 3A: directional candidate explainer (top 3 only)
    # ------------------------------------------------------------------
    def explain_directional_candidates(self, candidates: list[dict]) -> list[dict]:
        """
        Write a plain-language explanation for each already-ranked candidate.
        Claude does NOT select or re-rank. It receives computed fields and writes
        2-3 sentences per candidate: why it is a setup to watch, what the risk is,
        and what invalidates the thesis.

        Returns a list of dicts, one per candidate, in the same order as input.
        Each dict has {"ticker": ..., "explanation": ...}.
        If the call fails, the caller marks ai_available=False.
        """
        if not candidates:
            return []

        system = (
            "You are an options trading coach explaining already-selected setups in plain language. "
            "The code has already ranked these candidates using a transparent expectancy formula. "
            "Your only job is to write a clear, honest 2-3 sentence summary per candidate: "
            "why this setup scored well, what the key risk is, and what price action would invalidate it. "
            "Use plain language. No jargon. No re-ranking. Respond ONLY with a valid JSON array."
        )

        candidates_text = json.dumps(candidates, indent=2)
        user = (
            f"Write plain-language explanations for these {len(candidates)} directional option candidates. "
            f"Each has already been scored by code (EV = P(profit) x payoff at target "
            f"- (1 - P(profit)) x max loss, ranked by EV per $ risked; R/R is payoff at "
            f"target / |payoff at stop|, one figure everywhere). "
            f"Return a JSON array with one object per candidate, in the same order:\n"
            f'[{{"ticker":"AAPL","explanation":"2-3 sentence plain explanation."}}, ...]\n\n'
            f"Candidates:\n{candidates_text}"
        )

        try:
            raw = self._call(system, user, max_tokens=1200)
            result = self._parse(raw)
            if isinstance(result, list):
                return result
            return []
        except Exception as e:
            logger.warning("explain_directional_candidates failed: %s", e)
            return []

    # ------------------------------------------------------------------
    # AI boundary: explain-only methods for the live path.
    # Quant decides, Claude explains. Each method below receives
    # candidates that code has already ranked and priced, and returns
    # text only: {"ticker": ..., "explanation": ...} (or thesis fields
    # for discovery). They never return a strike, entry, stop, rank,
    # score, or recommendation, and the callers drop any such field
    # if one ever appears. A failure here returns [] and the caller
    # uses a quant-derived fallback, so the decision still fires.
    # ------------------------------------------------------------------
    def _explain_list(self, system: str, user: str, max_tokens: int = 1500) -> list[dict]:
        try:
            raw = self._call(system, user, max_tokens=max_tokens)
            result = self._parse(raw)
            if isinstance(result, list):
                return [r for r in result if isinstance(r, dict)]
            return []
        except Exception as e:
            logger.warning("Claude explanation failed: %s", e)
            return []

    def explain_options(self, picks: list[dict]) -> list[dict]:
        """Explain quant-decided options picks. Text only, no numbers set."""
        if not picks:
            return []
        system = (
            "You are an options trading coach explaining setups that code has "
            "already selected, ranked, and priced. Your only job is to write a "
            "clear 2-3 sentence explanation per pick: why the quant setup scored "
            "well, what the key risk is, and what price action invalidates it. "
            "Cite only the numbers given to you. Do not suggest a different "
            "strike, entry, exit, stop, rank, or score. Do not re-rank or drop "
            "any pick. Respond ONLY with a valid JSON array."
        )
        user = (
            "Write plain-language explanations for these quant-decided options picks, "
            "in the same order:\n"
            '[{"ticker":"AAPL","explanation":"2-3 sentence plain explanation."}, ...]\n\n'
            f"Picks:\n{json.dumps(picks, indent=2)}"
        )
        return self._explain_list(system, user)

    def explain_wheel(self, picks: list[dict]) -> list[dict]:
        """Explain quant-decided wheel picks. Text only, no numbers set."""
        if not picks:
            return []
        system = (
            "You are an options income coach explaining wheel put sales that code "
            "has already selected, ranked, and priced from the listed chain. "
            "Your only job is to write a clear 2-3 sentence explanation per pick: "
            "the trend, the support level under the put, and why the premium is "
            "attractive right now, plus the assignment risk in plain words. "
            "Cite only the numbers given to you. Do not suggest a different "
            "strike, expiry, premium, rank, or score. Do not re-rank or drop "
            "any pick. Respond ONLY with a valid JSON array."
        )
        user = (
            "Write plain-language explanations for these quant-decided wheel picks, "
            "in the same order:\n"
            '[{"ticker":"MSFT","explanation":"2-3 sentence plain explanation."}, ...]\n\n'
            f"Picks:\n{json.dumps(picks, indent=2)}"
        )
        return self._explain_list(system, user)

    def explain_discovery(self, picks: list[dict], category: str) -> list[dict]:
        """Write theses for quant-decided discovery picks. Text only.

        The picks arrive in quant rank order and stay in that order.
        No selection, no DCF parameters, no recommendation. Each item
        returns thesis, bull_case, bear_case, key_metric, catalyst,
        and risk, all text.
        """
        if not picks:
            return []
        system = (
            "You are an elite hedge fund analyst writing theses for long-term "
            "stock picks that code has already ranked with a multi-factor model. "
            "Your only job is to write, per pick, a 2-3 sentence thesis, a bull "
            "case, a bear case, the single most compelling metric, a near-term "
            "catalyst, and the main risk, all referencing the specific numbers "
            "given to you. Do not select, re-rank, drop, or add any pick. Do not "
            "set DCF parameters, a recommendation, a price target, or a score. "
            "Respond ONLY with a valid JSON array."
        )
        user = (
            f"Write theses for these quant-decided {category} picks, in the same order:\n"
            '[{"ticker":"XXXX","thesis":"...","bull_case":"...","bear_case":"...",'
            '"key_metric":"...","catalyst":"...","risk":"..."}]\n\n'
            f"Picks:\n{json.dumps(picks, indent=2)}"
        )
        return self._explain_list(system, user, max_tokens=8000)

    def explain_dcf_commentary(self, profile: dict) -> dict:
        """Write DCF commentary only: reasoning and confidence, no numbers.

        Scenario parameters are set by the mechanical rules in
        dcf_service, never here. Returns {"reasoning": ..., "confidence": ...}
        or {} on failure, and the caller never lets a failure change the
        DCF prices.
        """
        try:
            system = (
                "You are a buy-side equity analyst commenting on a DCF model whose "
                "scenario parameters were set by mechanical rules from historical "
                "growth and margins. Your only job is to write 2-3 sentences of "
                "commentary: what the key assumptions rest on, and where the model "
                "is most uncertain. Do not set or suggest scenario parameters, "
                "growth rates, margins, discount rates, or price targets. "
                "Respond ONLY with a valid JSON object."
            )
            user = (
                "Write DCF commentary for this company, using only the facts given:\n"
                f"{json.dumps(profile, indent=2)}\n\n"
                'Return JSON: {"reasoning":"...","confidence":"high"|"medium"|"low"}'
            )
            raw = self._call(system, user, max_tokens=600)
            result = self._parse(raw)
            if isinstance(result, dict):
                return {
                    "reasoning": str(result.get("reasoning", "") or ""),
                    "confidence": str(result.get("confidence", "") or ""),
                }
            return {}
        except Exception as e:
            logger.warning("Claude DCF commentary failed: %s", e)
            return {}

    # ------------------------------------------------------------------
    # Watchlist multi-strategy scoring
    # ------------------------------------------------------------------
    def score_watchlist_ticker(self, ticker: str, info: dict) -> dict:
        from datetime import datetime, timezone, timedelta

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Fetch real-time web news to enrich scoring context
        _web_news_str = ""
        try:
            _web_news = self._fetch_stock_news(ticker)
            if _web_news:
                _web_news_str = f"\nReal-time web search news:\n{_web_news}\n"
                logger.info("Web search enrichment succeeded for watchlist: %s", ticker)
        except Exception as exc:
            logger.warning("Web search failed for watchlist %s: %s", ticker, exc)

        # Earnings proximity check
        earnings_date = info.get("earnings_date")
        earnings_warning = None
        if earnings_date:
            try:
                ed = datetime.strptime(str(earnings_date)[:10], "%Y-%m-%d").date()
                days_away = (ed - datetime.now(timezone.utc).date()).days
                if 0 <= days_away <= 14:
                    earnings_warning = (
                        f"⚠ Earnings in {days_away} days ({earnings_date}). "
                        "High risk for wheel or options — avoid opening new positions."
                    )
                elif days_away < 0:
                    earnings_date = None  # past earnings, not relevant
            except Exception:
                pass

        price = info.get("price") or info.get("current_price", "?")
        sector = info.get("sector", "?")
        pe = info.get("pe_ratio", "?")
        div = info.get("div_yield", "?")
        iv_rank = info.get("iv_rank", "?")
        rsi = info.get("rsi", "?")
        ma50 = info.get("ma50", "?")
        ma200 = info.get("ma200", "?")

        system = (
            "You are a senior portfolio manager at Goldman Sachs. "
            "Evaluate a stock for three strategies and return ONLY valid JSON."
        )
        user = (
            f"Today: {today_str}\n"
            f"Stock: {ticker} | Price: ${price} | Sector: {sector}\n"
            f"PE: {pe} | Dividend Yield: {div} | IV Rank: {iv_rank}\n"
            f"RSI: {rsi} | MA50: {ma50} | MA200: {ma200}\n"
            f"Earnings date: {earnings_date or 'unknown'}\n"
            f"{_web_news_str}\n"
            "Score this stock for three strategies on a 0-100 scale with a letter grade (A/B/C/D/F):\n"
            "1. WHEEL STRATEGY: Is it a good stock to sell cash-secured puts on?\n"
            "   Score rubric: IV rank 25% + stock quality/stability 30% + premium yield 25% + technical support 20%\n"
            "2. OPTIONS TRADING: Is there a compelling short-term options trade (call or put)?\n"
            "   Score rubric: catalyst strength 30% + technical momentum 30% + IV environment 20% + risk/reward 20%\n"
            "3. LONG-TERM INVESTING: Is it worth buying and holding for 1-3 years?\n"
            "   Score rubric: earnings growth 35% + market position 25% + valuation 20% + dividend/income 20%\n\n"
            "Return JSON only:\n"
            '{"wheel_score":75,"wheel_grade":"B","wheel_note":"1 sentence why",'
            '"options_score":60,"options_grade":"C","options_note":"1 sentence why",'
            '"longterm_score":82,"longterm_grade":"B","longterm_note":"1 sentence why",'
            '"best_strategy":"wheel",'
            '"summary":"2-3 sentence plain-English verdict on this stock right now."}'
        )
        raw = self._call(system, user, max_tokens=600)
        result = self._parse(raw)
        result["earnings_date"] = str(earnings_date) if earnings_date else None
        result["earnings_warning"] = earnings_warning
        return result

    # ------------------------------------------------------------------
    # Roll suggestion for put_active wheel positions
    # ------------------------------------------------------------------
    def suggest_roll(
        self,
        ticker: str,
        current_price: float,
        put_strike: float,
        put_expiry: str,
        premium_received: float | None,
        put_tiers: dict,
        buyback_ask: float | None = None,
    ) -> dict:
        """Roll suggestion with correct roll net math (review C3).

        Net per share = new put bid - open put ask. The premium
        originally received is sunk and never enters the net. When
        buyback_ask is not passed in, it is fetched from the chain
        for the exact open strike and expiry. When the buyback ask
        cannot be fetched (no live ask on this plan), no net is
        presented at all and the result says the roll cannot be
        priced. Claude's estimated_net is validated against the
        computed net in code; the computed net always wins.
        """
        pct_from_strike = round((current_price - put_strike) / put_strike * 100, 1)
        premium_str = f"${premium_received:.2f}/share (${premium_received*100:.0f}/contract)" if premium_received else "unknown"

        # Buyback cost: caller-supplied ask wins, else the tiers dict,
        # else a live chain fetch for the exact open contract.
        buyback = None
        buyback_source = None
        if buyback_ask is not None and float(buyback_ask) > 0:
            buyback = round(float(buyback_ask), 2)
            buyback_source = "caller"
        else:
            for key in ("buyback_ask", "open_put_ask", "current_put_ask"):
                val = (put_tiers or {}).get(key)
                if val is not None and float(val) > 0:
                    buyback = round(float(val), 2)
                    buyback_source = "put_tiers"
                    break
        if buyback is None:
            try:
                fetched = fetch_open_put_buyback(ticker, put_strike, put_expiry)
            except Exception as e:
                logger.debug("buyback fetch failed for %s: %s", ticker, e)
                fetched = None
            if fetched and fetched.get("ask"):
                buyback = fetched["ask"]
                buyback_source = fetched.get("source", "chain")
        buyback_known = buyback is not None and buyback > 0

        # Computed net per tier, keyed by tier name. A tier has a net
        # only when its bid is a positive tradable price and the
        # buyback ask is known.
        computed_nets: dict[str, float | None] = {}
        for name in ("likely", "moderate", "unlikely"):
            t = (put_tiers or {}).get(name)
            if not t:
                computed_nets[name] = None
                continue
            bid = t.get("bid")
            computed_nets[name] = compute_roll_net(bid, buyback) if buyback_known else None

        def _fmt_tier(t: dict | None, label: str) -> str:
            if not t:
                return f"  {label}: not available\n"
            if buyback_known:
                buyback_str = f"Buy back the open ${put_strike} put expiring {put_expiry}: ask ${buyback:.2f}/share (${buyback*100:.0f}/contract).\n"
            else:
                buyback_str = (
                    "Buy back the open put: buyback ask is UNKNOWN, so this roll "
                    "cannot be priced. Do not state a net credit or debit.\n"
                )
            tier_name = label.split(" ")[0].lower() if label else ""
            net = None
            if "Higher" in label:
                net = computed_nets.get("likely")
            elif "Balanced" in label:
                net = computed_nets.get("moderate")
            elif "Conservative" in label:
                net = computed_nets.get("unlikely")
            bid = t.get("bid")
            bid_str = f"${bid:.2f}" if bid else "unknown (no live bid)"
            if net is not None:
                if net > 0:
                    net_str = f" | ROLL NET: ${net:.2f}/share credit (${net*100:.0f}/contract)"
                elif net < 0:
                    net_str = f" | ROLL NET: ${abs(net):.2f}/share debit (${abs(net)*100:.0f}/contract)"
                else:
                    net_str = " | ROLL NET: $0.00 (even)"
            else:
                net_str = " | ROLL NET: cannot be priced (buyback ask or new bid unknown)"
            return (
                f"  {label}: Strike=${t['strike']} Expiry={t['expiry']} ({t['dte']} DTE)\n"
                f"    {buyback_str}"
                f"    Sell the new put: bid {bid_str} | mid=${t['mid_premium']} (mid is last trade, not what you collect){net_str}\n"
                f"    Assignment chance ~{t['assignment_chance_pct']}% | Breakeven=${t['breakeven']}\n"
            )

        tiers_str = (
            f"Available puts to roll into (current price ${current_price}):\n"
            + _fmt_tier(put_tiers.get("likely"),   "Higher premium (~45% assignment chance)")
            + _fmt_tier(put_tiers.get("moderate"), "Balanced (~30% assignment chance)")
            + _fmt_tier(put_tiers.get("unlikely"), "Conservative (~16% assignment chance)")
        )

        system = (
            "You are a friendly options income coach helping an everyday investor manage a Wheel Strategy position. "
            "Explain everything in plain English — no jargon. "
            "Respond ONLY with a valid JSON object — no prose, no markdown."
        )
        roll_rule = (
            "A roll's net is: (new put bid) MINUS (buyback ask of the open put). "
            "The premium I originally collected is already in my account, it is sunk money, "
            "and it is NOT part of the net. A roll is a credit only when the new bid is "
            "greater than the buyback ask. If the buyback ask is unknown, say the roll "
            "cannot be priced and do not give a net figure at all.\n"
            f"Buyback ask for my open put: ${buyback:.2f}/share" if buyback_known else
            "Buyback ask for my open put: UNKNOWN. The roll cannot be priced. "
            "Do not invent a buyback price and do not give a net credit or debit figure."
        )
        user = (
            f"My open position: I sold a ${put_strike} put on {ticker} expiring {put_expiry}. "
            f"I collected {premium_str} in premium when I opened it. That money is already in my account.\n"
            f"Today {ticker} is trading at ${current_price} — that's {pct_from_strike}% above my strike.\n\n"
            f"{roll_rule}\n\n"
            f"{tiers_str}\n"
            "Should I roll this put? If yes, tell me exactly what to do in plain English.\n"
            "A roll means: buy back my current put (to close it), then sell a new put at a lower strike "
            "and/or later expiry to collect more premium and give myself more breathing room.\n\n"
            "Return JSON with these fields:\n"
            '{"should_roll": true,'
            '"urgency": "low|medium|high",'
            '"action_plain": "One clear sentence: exactly what to do (e.g. Roll your $190 put down to $185, '
            'push the expiry to May 16)",'
            '"new_strike": 185.0,'
            '"new_expiry": "2026-05-16",'
            '"estimated_net": 0.45,'
            '"net_description": "Plain English: e.g. You collect an extra $45 per contract by rolling",'
            '"rationale": "2-3 sentences in plain English explaining why this roll makes sense right now — '
            'what risk it reduces and what it costs you.",'
            '"if_no_action": "1 sentence: what happens if you do nothing"}'
        )
        raw = self._call(system, user, max_tokens=600)
        result = self._parse(raw)

        # Validate Claude's estimated_net against the computed net in
        # code. The computed net always wins. When no net can be
        # computed, Claude's figure is dropped, never shown.
        computed_for_choice = None
        choice_key = None
        try:
            new_strike = float(result.get("new_strike")) if result.get("new_strike") is not None else None
            new_expiry = str(result.get("new_expiry")) if result.get("new_expiry") else None
        except (TypeError, ValueError):
            new_strike = None
            new_expiry = None
        for name in ("likely", "moderate", "unlikely"):
            t = (put_tiers or {}).get(name)
            if not t:
                continue
            try:
                if new_strike is not None and float(t.get("strike")) == new_strike and (
                    new_expiry is None or str(t.get("expiry")) == new_expiry
                ):
                    choice_key = name
                    computed_for_choice = computed_nets.get(name)
                    break
            except (TypeError, ValueError):
                continue
        if computed_for_choice is None and choice_key is None:
            # Claude picked no matching tier: use the moderate tier net
            # when there is exactly one priced tier, else no net.
            priced = {k: v for k, v in computed_nets.items() if v is not None}
            if len(priced) == 1:
                choice_key, computed_for_choice = next(iter(priced.items()))
        trusted_net, agrees = validate_roll_net(result.get("estimated_net"), computed_for_choice)
        result["roll_net"] = trusted_net
        result["roll_net_known"] = trusted_net is not None
        result["roll_net_validated"] = agrees
        result["buyback_ask"] = buyback
        result["buyback_source"] = buyback_source
        result["computed_roll_nets"] = computed_nets
        if trusted_net is not None:
            result["estimated_net"] = trusted_net
            if trusted_net > 0:
                result["net_description"] = (
                    f"You collect an extra ${trusted_net*100:.0f} per contract by rolling "
                    f"(new bid minus buyback ask)."
                )
            elif trusted_net < 0:
                result["net_description"] = (
                    f"You pay ${abs(trusted_net)*100:.0f} per contract to roll "
                    f"(a debit: the buyback costs more than the new premium)."
                )
            else:
                result["net_description"] = "The roll is even: the new premium covers the buyback exactly."
        else:
            result["estimated_net"] = None
            result["net_description"] = (
                "Buyback price unknown, so this roll cannot be priced. "
                "Check the live ask on the open put before rolling."
            )
        return result

    # ------------------------------------------------------------------
    # Covered calls — weekly income from 100 shares already owned
    # ------------------------------------------------------------------
    def suggest_covered_calls(
        self,
        ticker: str,
        current_price: float,
        call_tiers: dict,
        cost_basis: float | None = None,
    ) -> dict:
        system = (
            "You are a friendly options income coach helping an everyday investor generate "
            "weekly income from 100 shares they already own. Explain everything in plain, "
            "simple English — no jargon, no confusing finance terms. "
            "Respond ONLY with a valid JSON object — no prose, no markdown fences."
        )

        def _fmt_tier(t: dict | None, label: str) -> str:
            if not t:
                return f"  {label}: No suitable option found\n"
            below = " [THIN MARKET — premium below 0.3%/week]" if t.get("below_threshold") else ""
            profit_str = ""
            if cost_basis and t["strike"] > cost_basis:
                total = round((t["strike"] - cost_basis + t["mid_premium"]) * 100, 2)
                profit_str = f" | Total profit if called away: ${total}/contract"
            return (
                f"  {label}:{below}\n"
                f"    Strike=${t['strike']} | Expiry={t['expiry']} ({t['dte']} days)\n"
                f"    Bid=${t['bid']} / Ask=${t['ask']} | Mid=${t['mid_premium']} "
                f"(collect ${t['premium_per_contract']} for 100 shares){profit_str}\n"
                f"    Call-away chance ~{t['call_away_chance_pct']}% | "
                f"Premium = {t['pct_of_stock_weekly']}% of stock price this week\n"
                f"    Stock must stay below ${t['strike']} for you to keep shares "
                f"({t['upside_to_strike_pct']}% upside room)\n"
                f"    Volume={t['volume']} | Open Interest={t['open_interest']}\n"
            )

        data_src = call_tiers.get("data_source", "last_trade")
        src_note = "live bid/ask" if data_src == "live" else "last-trade prices (markets closed)"
        cost_str = (
            f"${cost_basis:.2f}/share (${cost_basis * 100:.0f} total cost basis for 100 shares)"
            if cost_basis else "not provided"
        )
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        tiers_str = (
            f"WEEKLY CALL OPTIONS ({src_note}):\n"
            f"Current price: ${current_price} | ATM IV: {call_tiers.get('atm_iv_pct', '?')}%\n"
            f"Cost basis: {cost_str}\n\n"
            + _fmt_tier(call_tiers.get("aggressive"),   "TIER 1 — AGGRESSIVE (~70% call-away chance, highest premium)")
            + _fmt_tier(call_tiers.get("balanced"),     "TIER 2 — BALANCED (~45% call-away chance, good premium)")
            + _fmt_tier(call_tiers.get("conservative"), "TIER 3 — CONSERVATIVE (~20% call-away chance, lower premium)")
        )

        user = (
            f"Today: {today_str}\n"
            f"I own 100 shares of {ticker} at ${current_price} and want to sell a weekly covered "
            f"call to generate income. Give me plain-English explanations of my three options.\n\n"
            f"{tiers_str}\n"
            "For each tier explain in simple terms:\n"
            "- Exactly how much I collect upfront (dollars for 100 shares)\n"
            "- How likely my shares get called away, and what that means\n"
            "- What happens if the stock rallies past my strike\n"
            "- Who this option is best for\n\n"
            'Return JSON with exactly this structure:\n'
            '{"iv_environment": "1 sentence: are premiums rich or thin this week and what that means for me",'
            '"tiers": ['
            '{"tier": "aggressive",'
            '"strike": 95.0,'
            '"expiry": "2026-05-09",'
            '"dte": 7,'
            '"premium_per_contract": 180.0,'
            '"call_away_chance_pct": 70,'
            '"premium_plain": "You collect $180 upfront for agreeing to sell your 100 shares at $95",'
            '"callaway_plain": "About a 70-in-100 chance your shares get called away at $95 by Friday",'
            '"if_called_plain": "If called away: you sell at $95 and keep the $180 premium",'
            '"if_not_called_plain": "If the stock stays below $95: you keep your shares and the $180 is yours",'
            '"best_for": "Investors who want maximum income now and are OK selling at $95",'
            '"thin_market_note": null},'
            '{"tier": "balanced", ...},'
            '{"tier": "conservative", ...}]}'
        )
        raw = self._call(system, user, max_tokens=2500)
        return self._parse(raw)

    def suggest_weekly_covered_call(
        self,
        ticker: str,
        current_price: float,
        call_tiers: dict,
        iv_rank: float | None = None,
        cost_basis: float | None = None,
    ) -> dict:
        """Weekly-specific covered call recommendation with news-enriched context.
        Returns a focused play for the current week rather than generic 3-tier guidance.
        """
        system = (
            "You are a friendly options income coach. Your job is to help an everyday investor "
            "decide the single best covered call to sell THIS WEEK on 100 shares they already own. "
            "Be direct and specific: tell them exactly what to do, why, and what to expect by Friday. "
            "Explain everything in plain English — no jargon. "
            "Respond ONLY with a valid JSON object — no prose, no markdown fences."
        )

        # Fetch live news to inform the weekly recommendation
        news_bullets = ""
        try:
            news_bullets = self._fetch_stock_news(ticker)
        except Exception:
            pass

        def _fmt_tier(t: dict | None, label: str) -> str:
            if not t:
                return f"  {label}: No suitable option found\n"
            below = " [LOW PREMIUM — thin market]" if t.get("below_threshold") else ""
            return (
                f"  {label}:{below}\n"
                f"    Strike=${t['strike']} | Expiry={t['expiry']} ({t['dte']} days) | "
                f"Bid=${t['bid']} / Ask=${t['ask']} | Mid=${t['mid_premium']} "
                f"(${t['premium_per_contract']}/contract)\n"
                f"    Call-away chance ~{t['call_away_chance_pct']}% | "
                f"Weekly yield: {t['pct_of_stock_weekly']}% of stock price\n"
                f"    Volume={t['volume']} | Open Interest={t['open_interest']}\n"
            )

        data_src = call_tiers.get("data_source", "last_trade")
        src_note = "live bid/ask" if data_src in ("live", "polygon_live") else "last-trade prices (markets closed)"
        cost_str = f"${cost_basis:.2f}/share" if cost_basis else "not provided"
        iv_rank_val = iv_rank.get("iv_rank") if isinstance(iv_rank, dict) else iv_rank
        iv_str = f"{iv_rank_val:.0f}/100" if iv_rank_val is not None else "unknown"
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        expiry = call_tiers.get("expiry", "this Friday")
        dte = call_tiers.get("dte", 7)

        tiers_str = (
            f"THIS WEEK'S CALL OPTIONS ({src_note}):\n"
            f"Expiry: {expiry} ({dte} days) | Current price: ${current_price} | "
            f"ATM IV: {call_tiers.get('atm_iv_pct', '?')}% | IV Rank: {iv_str}\n"
            f"Cost basis: {cost_str}\n\n"
            + _fmt_tier(call_tiers.get("aggressive"),   "AGGRESSIVE (~70% call-away, highest premium)")
            + _fmt_tier(call_tiers.get("balanced"),     "BALANCED (~45% call-away, good premium)")
            + _fmt_tier(call_tiers.get("conservative"), "CONSERVATIVE (~20% call-away, keep shares)")
        )

        valid_expiries = _valid_expiry_dates(2)
        expiry_list = ", ".join(valid_expiries)

        user = (
            f"Today: {today_str}\n"
            f"Valid expiry dates (use one of these exactly): {expiry_list}\n\n"
            f"I own 100 shares of {ticker} at ${current_price}. "
            f"Help me decide the single best covered call to sell THIS WEEK.\n\n"
            f"{tiers_str}\n"
            f"Recent news about {ticker}:\n{news_bullets or 'No recent news available.'}\n\n"
            "Based on the news, IV environment, and available strikes, pick the BEST single call to sell "
            "this week and explain it in simple terms. Consider:\n"
            "- Is there any news that might move the stock before expiry?\n"
            "- Is premium high enough to be worth the risk of losing shares?\n"
            "- Which strike gives the best risk/reward for this specific week?\n\n"
            "Return JSON with exactly this structure:\n"
            "{\n"
            '  "recommended_tier": "balanced",\n'
            '  "strike": 195.0,\n'
            '  "expiry": "2026-09-19",\n'
            '  "dte": 5,\n'
            '  "premium_per_contract": 185.0,\n'
            '  "call_away_chance_pct": 45,\n'
            '  "weekly_yield_pct": 0.95,\n'
            '  "recommendation": "Sell the $195 call expiring Friday. Here is what I recommend and why — 2-3 plain-English sentences",\n'
            '  "news_impact": "Brief note on whether this week\'s news makes you more or less aggressive",\n'
            '  "if_called": "Plain English: what happens if the stock closes above your strike Friday",\n'
            '  "if_not_called": "Plain English: what happens if the stock stays below your strike",\n'
            '  "risk_flag": null\n'
            "}\n"
            'Set "risk_flag" to a 1-sentence warning ONLY if there is a specific near-term risk '
            "(earnings, Fed meeting, major product announcement this week). Otherwise null."
        )
        raw = self._call(system, user, max_tokens=1500)
        result = self._parse(raw)
        # Attach the full tiers in case the frontend needs them
        result["tiers"] = {k: call_tiers.get(k) for k in ("aggressive", "balanced", "conservative")}
        result["iv_environment"] = f"ATM IV: {call_tiers.get('atm_iv_pct', '?')}% | IV Rank: {iv_str}"
        return result

    # ------------------------------------------------------------------
    # Champions — one batched call to pick best stock per strategy
    # ------------------------------------------------------------------
    def pick_champions(self, survivors: list[dict]) -> dict:
        from datetime import datetime, timezone
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        lines = []
        for s in survivors:
            pe_str = f"PE={s['pe']:.0f}" if s.get("pe") else "PE=n/a"
            div_str = f"div={s['div_yield_pct']}%" if s.get("div_yield_pct") else "div=none"
            iv_str = f"IV_rank≈{s['iv_rank']}" if s.get("iv_rank") else "IV_rank=unknown"
            lines.append(
                f"{s['ticker']}: ${s['price']} | RSI={s['rsi']} | {iv_str} | "
                f"vol={s['avg_vol_m']}M/day | {pe_str} | {div_str} | "
                f"sector={s.get('sector','?')} | analyst={s.get('analyst','?')}"
            )

        stocks_block = "\n".join(lines)

        system = (
            "You are a senior Goldman Sachs portfolio manager. "
            "Pick the single best stock for each of three strategies. "
            "Return ONLY valid JSON — no prose, no markdown."
        )
        user = (
            f"Today: {today_str}\n"
            f"These {len(survivors)} stocks passed a quantitative pre-screen "
            "(price >$5, volume >500k/day, RSI 25-75, no earnings within 14 days).\n\n"
            f"{stocks_block}\n\n"
            "Pick the single BEST stock for each strategy:\n"
            "1. WHEEL STRATEGY — best for selling cash-secured puts right now\n"
            "   (favor: high IV rank, stable/quality company, strong price support, good premium yield)\n"
            "2. OPTIONS TRADING — best for a directional call or put play right now\n"
            "   (favor: clear momentum, strong catalyst, favorable risk/reward)\n"
            "3. LONG-TERM INVESTING — best buy and hold for the next 1-3 years\n"
            "   (favor: earnings growth, dominant market position, reasonable valuation)\n\n"
            "Return JSON only — no extra keys:\n"
            '{"wheel":{"ticker":"AAPL","score":88,"grade":"A",'
            '"reason":"2 sentences plain English — why this is the best wheel stock right now."},'
            '"options":{"ticker":"NVDA","score":82,"grade":"B",'
            '"reason":"2 sentences plain English — why this is the best options play right now."},'
            '"longterm":{"ticker":"MSFT","score":91,"grade":"A",'
            '"reason":"2 sentences plain English — why this is the best long-term hold right now."}}'
        )
        raw = self._call(system, user, max_tokens=500)
        return self._parse(raw)

    # ------------------------------------------------------------------
    # Day Trade Scanner — rank top movers into high-confidence plays
    # ------------------------------------------------------------------
    def scan_day_trades(self, candidates: list[dict], spy_change: float | None = None) -> list[dict]:
        import concurrent.futures as _cf
        from datetime import datetime, timezone
        if not candidates:
            # No movers, no plays. An empty list is a valid result.
            return []
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        spy_ctx = f"SPY is {'+' if (spy_change or 0) >= 0 else ''}{spy_change}% today." if spy_change is not None else ""

        # Near-term expiry dates for options suggestions
        near_expiries = _valid_expiry_dates(3)
        expiry_list = ", ".join(near_expiries)

        # Parallel web search for all candidates — surfaces the real catalyst behind each move
        web_news_map: dict[str, str] = {}
        if candidates:
            with _cf.ThreadPoolExecutor(max_workers=min(len(candidates), 4)) as pool:
                futs = [(c["ticker"], pool.submit(self._fetch_stock_news, c["ticker"])) for c in candidates]
                for ticker, fut in futs:
                    try:
                        news = fut.result(timeout=20)
                        if news:
                            web_news_map[ticker] = news
                    except Exception:
                        pass

        lines = []
        for c in candidates:
            # Merge live web news with cached headlines; web news comes first
            cached_news = " | ".join(c.get("news", [])[:2])
            web_ctx = web_news_map.get(c["ticker"], "")
            if web_ctx:
                first_line = next((l.strip().lstrip("•– -") for l in web_ctx.split("\n") if l.strip()), "")
                news_str = f"[LIVE] {first_line}" + (f" | {cached_news}" if cached_news else "") if first_line else (cached_news or "No recent news")
            else:
                news_str = cached_news or "No recent news"
            arrow = "▲" if c["change_pct"] >= 0 else "▼"

            ta_parts = []
            if c.get("rsi") is not None:
                rsi_label = "overbought" if c["rsi"] > 70 else ("oversold" if c["rsi"] < 30 else "neutral")
                ta_parts.append(f"RSI={c['rsi']}({rsi_label})")
            if c.get("atr") is not None:
                ta_parts.append(f"ATR={c['atr']}")
            if c.get("ma20") is not None:
                rel = "above" if c["price"] > c["ma20"] else "below"
                ta_parts.append(f"20MA={c['ma20']}({rel})")
            if c.get("vs_spy") is not None:
                ta_parts.append(f"vsS&P={'+' if c['vs_spy'] >= 0 else ''}{c['vs_spy']}%")
            if c.get("days_to_cover") is not None:
                ta_parts.append(f"DTC={c['days_to_cover']}d")
            if c.get("short_volume_ratio_pct") is not None:
                ta_parts.append(f"ShortVol={c['short_volume_ratio_pct']}%")

            ta_str = " | " + ", ".join(ta_parts) if ta_parts else ""
            lines.append(
                f"{c['ticker']}: ${c['price']} ({arrow}{abs(c['change_pct'])}% today) | "
                f"Vol: {c['volume_m']}M ({c['vol_ratio']}x avg) | "
                f"O:{c['open']} H:{c['high']} L:{c['low']} VWAP:{c['vwap']}"
                f"{ta_str} | News: {news_str}"
            )

        stocks_block = "\n".join(lines)

        system = (
            "You are an elite day trader and options analyst at a prop trading firm. "
            "Analyze the provided movers and identify the best trade setups. "
            "Return only plays that genuinely qualify, up to 5. Fewer is fine, "
            "and an empty list is a valid result when no setup qualifies: "
            "return {\"plays\": []} in that case. Never invent a play to fill a quota. "
            "For each play, suggest a specific options entry: strike, expiry, estimated entry premium, "
            "target premium, and stock break-even. Use ATM or slightly OTM strikes for momentum plays. "
            "Use RSI to avoid chasing overbought entries; use ATR for stop sizing. "
            "Be specific with entry zones, targets, and stops. "
            "Return ONLY valid JSON — no prose, no markdown."
        )
        user = (
            f"Today: {today_str}. {spy_ctx}\n"
            f"Near-term option expiries available: {expiry_list}\n\n"
            f"Top movers (yfinance daily data, RSI-14 + ATR-14 enriched):\n\n"
            f"{stocks_block}\n\n"
            "Select only the setups that genuinely qualify, up to 5. Fewer is fine, zero is fine. Prioritize:\n"
            "1. Momentum continuation: vol_ratio ≥ 2x + clear direction + catalyst\n"
            "2. VWAP reclaim/hold: price above VWAP with volume\n"
            "3. Oversold bounce: RSI < 35 + down on volume, reversal near low\n"
            "4. Breakout: stock breaking prior high with vol surge\n"
            "5. Short squeeze: high DTC + stock ripping — shorts trapped\n\n"
            "Use ATR for stop sizing (1–1.5× ATR below entry for longs). "
            "RSI > 75 = avoid chasing, prefer pullback entry.\n\n"
            "For option_play: use CALL for long, PUT for short. "
            "Pick the nearest ATM or 1-strike OTM. "
            "For intraday, use the nearest expiry. For swing (2-3d), use the second expiry. "
            "entry_premium = your rough estimate only. It is NOT a market price: it will be replaced "
            "by a real chain snapshot, or the play will be dropped if no snapshot is available. "
            "target_premium = estimated value if stock hits target. "
            "stop_premium = 50% of entry (e.g. entry $2.00, stop $1.00). "
            "That stop is a hardcoded convention, not a computed market level, and it is labeled as such. "
            "breakeven_stock = strike + entry_premium for calls, strike - entry_premium for puts.\n\n"
            "Return JSON only:\n"
            '{"plays": ['
            '{"ticker": "NVDA",'
            '"direction": "long",'
            '"setup": "Momentum breakout",'
            '"confidence": "high",'
            '"entry_zone": "$88.50–$89.00",'
            '"target": "$93.00",'
            '"stop_loss": "$86.50",'
            '"timeframe": "intraday",'
            '"risk_reward": "2.5:1",'
            '"catalyst": "One sentence: what is driving this move",'
            '"reasoning": "2-3 sentences: why this setup and what to watch",'
            '"option_play": {'
            '"option_type": "CALL",'
            '"strike": 89.0,'
            f'"expiry": "{near_expiries[0]}",'
            '"entry_premium": 1.50,'
            '"target_premium": 3.20,'
            '"stop_premium": 0.75,'
            '"breakeven_stock": 90.50'
            '}}'
            "]}'"
        )
        raw = self._call(system, user, max_tokens=2500)
        result = self._parse(raw)
        plays = result.get("plays", []) if isinstance(result, dict) else []
        # An empty list is a valid result: no forced minimum, no invented plays.
        return plays if isinstance(plays, list) else []

    def interpret_options_flow(
        self, alerts: list[dict], sentiment_ratio: int, overall: str
    ) -> list[dict]:
        """Interpret unusual options flow and add narrative context to each alert."""
        from datetime import datetime, timezone
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        lines = []
        for a in alerts:
            notional_k = round(a.get("notional", 0) / 1_000)
            pct_otm = a.get("pct_otm", 0)
            itm_otm = f"{abs(pct_otm)}% {'OTM' if pct_otm >= 0 else 'ITM'}"
            opt_type = (a.get("option_type") or "call").upper()
            vol_oi = a.get("vol_oi_ratio", 0)
            oi = a.get("open_interest", 0)
            ratio_str = "NEW (no prior OI)" if a.get("is_new_contract") else f"{vol_oi}x"
            earnings = a.get("earnings_context")
            earnings_str = f" | {earnings}" if earnings else ""
            change_pct = a.get("change_pct")
            move_str = f" | Today {'+' if (change_pct or 0) >= 0 else ''}{change_pct}%" if change_pct is not None else ""
            news_items = a.get("news") or []
            news_str = f" | News: {' // '.join(news_items[:2])}" if news_items else ""
            # Premium richness context
            prem_parts = []
            if a.get("breakeven"):
                prem_parts.append(f"BE=${a['breakeven']}")
            if a.get("pct_move_needed") is not None:
                prem_parts.append(f"needs {a['pct_move_needed']}% move")
            if a.get("iv_pct"):
                prem_parts.append(f"IV={a['iv_pct']}%")
            if a.get("hv_pct"):
                prem_parts.append(f"HV={a['hv_pct']}%")
            if a.get("premium_rating"):
                prem_parts.append(f"premium={a['premium_rating']}")
            richness_str = f" | {', '.join(prem_parts)}" if prem_parts else ""
            lines.append(
                f"{a.get('ticker','?')} ${a.get('strike','?')} {opt_type} "
                f"exp {a.get('expiry','?')} ({a.get('dte','?')}d) | "
                f"Vol:{a.get('volume',0):,} OI:{oi:,} Ratio:{ratio_str} | "
                f"${notional_k}K notional | {itm_otm} | Stock=${a.get('price','?')}"
                f"{richness_str}{earnings_str}{move_str}{news_str}"
            )
        flow_block = "\n".join(lines)

        system = (
            "You are an expert options flow analyst at a prop trading desk. "
            "Interpret unusual options activity — high vol/OI ratios mean fresh positioning. "
            "'NEW (no prior OI)' means a brand-new contract with zero prior open interest — very significant. "
            "Large OTM prints are directional bets. Near-ATM prints could be hedges or income plays. "
            "CRITICAL: If earnings context is provided (e.g. 'Earnings 2d ago'), factor that in — "
            "post-earnings flow is repositioning, NOT an earnings play. Pre-earnings flow is often a straddle or directional bet. "
            "When premium=RICH (IV >> HV), the option buyer is paying a large premium — they need a big move to profit. "
            "When premium=CHEAP, IV is below historical volatility — relatively inexpensive. "
            "Use break-even and % move needed to assess whether the flow is realistic or a long shot. "
            "Be direct and concise. A day trader needs actionable takeaways, not theory. "
            "Return ONLY valid JSON — no prose, no markdown."
        )
        user = (
            f"Today: {today_str}\n"
            f"Flow summary: {sentiment_ratio}% call volume vs puts = overall {overall} bias\n\n"
            f"Unusual contracts (sorted by notional premium, biggest bets first):\n\n"
            f"{flow_block}\n\n"
            "For EACH alert, return all original fields plus these new fields:\n"
            "- interpretation: what this flow likely means given any earnings context\n"
            "- implied_target: specific price target implied by the bet (e.g. '$115+ by May 15')\n"
            "- confidence: high / medium / low\n"
            "- action_note: one sentence for a day trader watching this stock\n"
            "- recommendation: 'BUY' or 'AVOID' plus one specific condition\n"
            "- verdict: exactly one of 'PROCEED' | 'CAUTION' | 'AVOID'\n"
            "  PROCEED = strong signal, good risk/reward, worth following\n"
            "  CAUTION = interesting flow but meaningful red flags (0-1 DTE, earnings imminent,\n"
            "            RICH premium, large move needed, possible hedge)\n"
            "  AVOID = too risky (0-DTE into earnings, IV crushed after earnings, very large move\n"
            "          needed, low notional that smells like retail noise)\n"
            "- verdict_reason: one short phrase (≤8 words) explaining the verdict\n"
            "  Examples: 'High Vol/OI with price confirmation'\n"
            "            'Earnings in 2d — IV crush risk'\n"
            "            '0-DTE needs 3% move — long shot'\n"
            "            'Possible hedge, not directional'\n\n"
            "Return JSON only:\n"
            '{"alerts": [{'
            '"ticker": "NVDA", "option_type": "call", "strike": 900.0, '
            '"expiry": "2026-05-10", "dte": 5, "volume": 15420, "open_interest": 1200, '
            '"vol_oi_ratio": 12.8, "is_new_contract": false, "mid_premium": 2.50, '
            '"notional": 3855000, "pct_otm": 2.9, "price": 875.0, "sentiment": "bullish", '
            '"earnings_context": null, "breakeven": 902.50, "pct_move_needed": 3.1, '
            '"iv_pct": 55.0, "hv_pct": 42.0, "iv_hv_ratio": 1.31, "premium_rating": "FAIR", '
            '"interpretation": "Aggressive sweep — fresh bullish positioning ahead of a catalyst", '
            '"implied_target": "$900+ by May 10", '
            '"confidence": "high", '
            '"action_note": "Watch for break above $880 with volume — flow confirms upside bias", '
            '"recommendation": "BUY if stock breaks $880 with volume confirmation. AVOID if market opens flat.", '
            '"verdict": "PROCEED", '
            '"verdict_reason": "High Vol/OI with price confirmation"'
            "}]}"
        )
        raw = self._call(system, user, max_tokens=3500)
        try:
            result = self._parse(raw)
            interpreted = result.get("alerts", [])
            if interpreted:
                return interpreted
            logger.warning("interpret_options_flow: Claude returned empty alerts list")
        except Exception as e:
            logger.warning("interpret_options_flow: parse failed (%s), returning raw alerts", e)
        return alerts
