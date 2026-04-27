import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import anthropic
from config import settings

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"


def _clean_json(text: str) -> str:
    """Strip markdown fences and surrounding whitespace."""
    return re.sub(r"```(?:json)?|```", "", text).strip()


def _valid_expiry_dates(n: int = 6) -> list[str]:
    """Return the next n upcoming Friday dates that are at least 5 calendar days away.
    These are real tradeable weekly/monthly expiries."""
    today = datetime.now(timezone.utc).date()
    days_to_friday = (4 - today.weekday()) % 7  # weekday 4 = Friday
    # Ensure at least 5 calendar days gap so we're not expiring imminently
    if days_to_friday < 5:
        days_to_friday += 7
    fridays = []
    d = today + timedelta(days=days_to_friday)
    for _ in range(n):
        fridays.append(d.strftime("%Y-%m-%d"))
        d += timedelta(weeks=1)
    return fridays


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

    # ------------------------------------------------------------------
    # Options analysis
    # ------------------------------------------------------------------
    def analyze_options(self, news_bullets: str, technical_data: str, market_context: str,
                        quant_scores: dict | None = None) -> list[dict]:
        system = (
            "You are a professional options trader and technical analyst with 20+ years of experience. "
            "You have deep expertise in single-leg options, iron condors, bull put spreads, bear call "
            "spreads, and debit spreads. You select the BEST strategy structure for each setup:\n"
            "  - single_leg CALL/PUT: strong directional momentum or BB squeeze breakout\n"
            "  - iron_condor: range-bound price with high IV (sell premium both sides)\n"
            "  - bull_put_spread: mildly bullish with high IV (credit spread)\n"
            "  - bear_call_spread: mildly bearish with high IV (credit spread)\n"
            "  - bull_call_spread: moderately bullish with lower IV (debit spread)\n"
            "  - bear_put_spread: moderately bearish with lower IV (debit spread)\n"
            "Respond ONLY with a valid JSON array — no prose, no markdown fences."
        )

        quant_ctx = ""
        if quant_scores:
            lines = []
            for ticker, qs in quant_scores.items():
                comp  = qs.get("composite", 50)
                ee    = qs.get("entry_exit", {})
                strat = qs.get("recommended_strategy", "single_leg")
                ml    = qs.get("multi_leg", {})
                if strat == "single_leg":
                    lines.append(
                        f"  {ticker}: quant={comp}/100 | strategy={strat} | "
                        f"underlying entry=${ee.get('underlying_entry','?')} "
                        f"target=${ee.get('underlying_target','?')} "
                        f"stop=${ee.get('underlying_stop','?')} | "
                        f"suggested strike=${ee.get('suggested_strike','?')} "
                        f"BS-premium-est entry=${ee.get('entry_premium_est','?')} "
                        f"target=${ee.get('target_premium_est','?')} "
                        f"stop=${ee.get('stop_premium_est','?')}"
                    )
                else:
                    sc = ml.get("short_call_strike","?")
                    lc = ml.get("long_call_strike","?")
                    sp = ml.get("short_put_strike","?")
                    lp = ml.get("long_put_strike","?")
                    lines.append(
                        f"  {ticker}: quant={comp}/100 | strategy={strat} | "
                        f"strikes SC={sc} LC={lc} SP={sp} LP={lp} | "
                        f"BS-credit-est=${ml.get('net_credit','?')} "
                        f"max_profit=${ml.get('max_profit','?')} "
                        f"max_loss=${ml.get('max_loss','?')}"
                    )
            quant_ctx = (
                "\nQuantitative analysis with Black-Scholes estimated premiums "
                "(use these as realistic anchors — adjust based on your judgment):\n"
                + "\n".join(lines) + "\n"
            )

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        valid_expiries = _valid_expiry_dates(6)
        expiry_list = ", ".join(valid_expiries)
        # Use nearest and second-nearest as concrete examples in the schema
        ex_expiry1 = valid_expiries[0]
        ex_expiry2 = valid_expiries[1] if len(valid_expiries) > 1 else valid_expiries[0]

        user = (
            f"Today's date (UTC): {today_str}\n"
            f"Valid option expiry dates — YOU MUST use one of these exact dates for every expiry field: "
            f"{expiry_list}\n"
            f"IMPORTANT: Never use a date not in the list above. Never use example dates from the schema.\n\n"
            f"{market_context}\n"
            f"{quant_ctx}\n"
            f"Recent news:\n{news_bullets}\n\n"
            f"Technical data (RSI, MACD, Bollinger, MAs, Fibonacci, ATR, VWAP, volume):\n"
            f"{technical_data}\n\n"
            "Instructions:\n"
            "- Select the strategy_type that best fits the technical setup (use the suggestions above "
            "as a starting point but override if the setup calls for it)\n"
            "- For single_leg: set option_type (CALL/PUT), strike, entry_price, exit_price, stop_loss, "
            "underlying_entry, underlying_target, underlying_stop\n"
            "- For multi-leg (iron_condor, spreads): set the appropriate strikes from "
            "short_call_strike, long_call_strike, short_put_strike, long_put_strike, "
            "net_credit (positive=credit received, negative=debit paid), max_profit, max_loss, "
            "breakeven_low, breakeven_high. Also set expiry.\n"
            "- Cite specific indicator readings in your explanation\n"
            "- Your qual_score is your qualitative judgment (0-100)\n\n"
            "Return a JSON array of exactly 5 objects. For single_leg:\n"
            f'  {{"rank":1,"ticker":"AAPL","strategy_type":"single_leg","option_type":"CALL",'
            f'"strike":195.0,"expiry":"{ex_expiry1}","entry_price":2.40,"exit_price":4.80,'
            '"stop_loss":1.20,"underlying_entry":192.5,"underlying_target":198.0,'
            '"underlying_stop":189.0,"qual_score":82,"score":87,"grade":"B",'
            '"explanation":"RSI 32 oversold, bouncing off Fib 61.8%..."}}\n\n'
            "For iron_condor:\n"
            f'  {{"rank":2,"ticker":"SPY","strategy_type":"iron_condor","option_type":"N/A",'
            f'"expiry":"{ex_expiry2}","short_call_strike":512.0,"long_call_strike":515.0,'
            '"short_put_strike":490.0,"long_put_strike":487.0,"net_credit":1.85,'
            '"max_profit":185.0,"max_loss":115.0,"breakeven_low":488.15,'
            '"breakeven_high":513.85,"qual_score":79,"score":83,"grade":"B",'
            '"explanation":"RSI neutral at 52, BB %B at 0.45 range-bound, IV rank 48..."}}\n\n'
            "For spreads (bull_put_spread example):\n"
            f'  {{"rank":3,"ticker":"MSFT","strategy_type":"bull_put_spread","option_type":"N/A",'
            f'"expiry":"{ex_expiry1}","short_put_strike":380.0,"long_put_strike":375.0,'
            '"net_credit":1.20,"max_profit":120.0,"max_loss":380.0,"breakeven_low":378.80,'
            '"qual_score":85,"score":88,"grade":"B",'
            '"explanation":"Strong uptrend above MA50+200, Fib 61.8% support at 381..."}}\n\n'
            "Scoring rubric for qual_score and score (0-100):\n"
            "- Technical setup quality (RSI, MACD, Fib, MA alignment): 35%\n"
            "- Catalyst/news strength: 25%\n"
            "- IV environment and premium value: 20%\n"
            "- Risk/reward of chosen structure: 20%\n"
            "Grade: A=90-100, B=80-89, C=70-79, D=60-69, F=below 60."
        )
        raw = self._call(system, user)
        return self._parse(raw)

    # ------------------------------------------------------------------
    # Wheel strategy analysis
    # ------------------------------------------------------------------
    def analyze_wheel(self, news_bullets: str, screening_data: str,
                      quant_scores: dict | None = None) -> list[dict]:
        system = (
            "You are a professional options income trader specialising in the Wheel Strategy. "
            "You use technical analysis to identify the safest put-selling opportunities: "
            "stocks in uptrends (above MA50 and MA200), with elevated IV rank for premium, "
            "and put strikes placed below strong Fibonacci or moving average support. "
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
                    f"suggested_strike=${ee.get('suggested_put_strike','?')} "
                    f"pct_otm={ee.get('pct_otm','?')}%"
                )
            quant_ctx = "\nPre-computed quantitative scores:\n" + "\n".join(lines) + "\n"

        valid_expiries = _valid_expiry_dates(6)
        expiry_list = ", ".join(valid_expiries)
        ex_expiry1 = valid_expiries[0]

        user = (
            f"Current date/time (UTC): {datetime.now(timezone.utc).isoformat()}\n"
            f"Valid option expiry dates — YOU MUST use one of these exact dates for every expiry field: "
            f"{expiry_list}\n"
            f"IMPORTANT: Never use a date not in the list above.\n\n"
            f"{quant_ctx}\n"
            f"Recent market news:\n{news_bullets}\n\n"
            f"Technical screening data:\n{screening_data}\n\n"
            "Selection criteria — prioritise stocks where:\n"
            "1. Price is above MA50 AND MA200 (uptrend — safer to own if assigned)\n"
            "2. RSI is between 40-65 (not overbought, not in freefall)\n"
            "3. Put strike can be placed at or below a Fibonacci support level\n"
            "4. IV is elevated (better premium) but stock is fundamentally sound\n"
            "5. Volume trend is normal or high (liquid, active stock)\n"
            "6. Avoid stocks in death cross (MA50 < MA200) or with RSI below 30\n\n"
            "In your explanation, state: the trend, the support level where you'd place the put, "
            "and why IV makes it attractive right now.\n"
            "Your 'qual_score' is your qualitative judgment (0-100) incorporating stock quality, "
            "news context, and willingness-to-own assessment.\n\n"
            "Return a JSON array of exactly 5 objects:\n"
            "[\n"
            f'  {{"rank":1,"ticker":"MSFT","put_strike":380.0,"put_expiry":"{ex_expiry1}",'
            '"put_premium":4.20,"iv_rank":52,"qual_score":88,"score":91,"grade":"A",'
            '"explanation":"3-4 sentences citing trend, support level, and IV context"}}\n'
            "]\n\n"
            "Scoring rubric for qual_score and score (0-100):\n"
            "- Technical trend strength (MA, Fib support quality): 35%\n"
            "- IV rank / premium yield: 25%\n"
            "- Stock quality / willingness to own: 25%\n"
            "- RSI and momentum safety: 15%\n"
            "Grade: A=90-100, B=80-89, C=70-79, D=60-69, F=below 60."
        )
        raw = self._call(system, user)
        return self._parse(raw)

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
    # Covered call suggestion for assigned wheel position
    # ------------------------------------------------------------------
    def generate_call_suggestion(
        self,
        ticker: str,
        cost_basis: float,
        current_price: float,
        assigned_date: str,
        iv_rank: float | None,
        earnings_date: str | None,
        news_bullets: str,
        technicals: dict | None = None,
    ) -> dict:
        system = (
            "You are a professional options income trader. Generate an optimal weekly covered "
            "call recommendation using technical analysis to select the best strike. "
            "Respond ONLY with a valid JSON object — no prose, no markdown fences."
        )

        tech_str = ""
        if technicals:
            ma = technicals.get("moving_averages", {})
            fib = technicals.get("fibonacci", {})
            rsi = technicals.get("rsi", "?")
            bb = technicals.get("bollinger", {})
            tech_str = (
                f"\nTechnical context:\n"
                f"RSI={rsi} | MA50={ma.get('ma50','?')} MA200={ma.get('ma200','?')}\n"
                f"Bollinger upper={bb.get('upper','?')} middle={bb.get('middle','?')}\n"
                f"Fib resistance levels: 23.6%={fib.get('fib_236','?')} 38.2%={fib.get('fib_382','?')}\n"
                f"ATR={technicals.get('atr','?')} (daily expected move)"
            )

        valid_expiries = _valid_expiry_dates(4)
        expiry_list = ", ".join(valid_expiries)
        ex_expiry1 = valid_expiries[0]

        user = (
            f"Today's date (UTC): {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n"
            f"Valid expiry dates — use one of these exactly: {expiry_list}\n\n"
            f"I own 100 shares of {ticker} at cost basis ${cost_basis:.2f}/share "
            f"(assigned on {assigned_date}).\n"
            f"Current price: ${current_price:.2f}\n"
            f"IV rank: {iv_rank if iv_rank else 'unknown'}\n"
            f"Earnings date: {earnings_date if earnings_date else 'none known — avoid selling through earnings'}\n"
            f"{tech_str}\n\n"
            f"Recent news for {ticker}:\n{news_bullets}\n\n"
            "Select the call strike at a Fibonacci resistance level or near the Bollinger upper band "
            "where price is likely to stall. Do NOT go below cost basis. "
            "Use ATR to estimate realistic premium. Use the nearest date from the valid expiry list above.\n\n"
            "Return JSON:\n"
            f'{{"call_strike":195.0,"call_expiry":"{ex_expiry1}",'
            '"estimated_premium":1.85,"rationale":"cite the specific technical level used"}}'
        )
        raw = self._call(system, user, max_tokens=1024)
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
            'Mention stability, business quality, and whether you\'d be comfortable owning shares.",'
            '"technicals_plain":"1-2 sentences in plain English about the chart setup. '
            'No indicator names — just what it means (e.g. \'The stock is in a healthy uptrend \'",'
            '"iv_environment_plain":"1 sentence: are options cheap, fair, or expensive right now? '
            'What does that mean for the seller? (e.g. \'Options are pricier than usual — '
            'great time to collect premium\')",'
            '"tiers":['
            '{"tier_name":"Higher premium, more likely to buy shares",'
            '"strike":190.0,"expiry":"2026-05-01","dte":9,'
            '"premium_plain":"You collect $420 upfront for agreeing to buy 100 shares",'
            '"assignment_plain":"Roughly a 45-in-100 chance you end up buying the shares at $190",'
            '"time_decay_plain":"Earns about $18 per day automatically just from time passing",'
            '"protection_plain":"You only start losing money if the stock drops below $186 — '
            'that\'s a 3% drop from today\'s price",'
            '"return_plain":"If this keeps expiring worthless, it\'s like earning 28% per year on your cash",'
            '"best_for":"Investors who actually want to own the shares and want maximum premium"},'
            '{"tier_name":"Balanced — decent premium with a reasonable safety cushion",...},'
            '{"tier_name":"Conservative — smaller premium but much safer",...}'
            '],'
            '"overall_verdict":"2-3 sentences recommending which tier makes most sense right now '
            'and why, in plain English."}'
        )
        raw = self._call(system, user, max_tokens=3000)
        return self._parse(raw)

    # ------------------------------------------------------------------
    # Watchlist multi-strategy scoring
    # ------------------------------------------------------------------
    def score_watchlist_ticker(self, ticker: str, info: dict) -> dict:
        from datetime import datetime, timezone, timedelta

        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

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
            f"Earnings date: {earnings_date or 'unknown'}\n\n"
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
