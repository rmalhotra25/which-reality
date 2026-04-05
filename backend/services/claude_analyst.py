import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

import anthropic
from config import settings

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"


def _clean_json(text: str) -> str:
    """Strip markdown fences and surrounding whitespace."""
    return re.sub(r"```(?:json)?|```", "", text).strip()


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
                comp = qs.get("composite", 50)
                ee = qs.get("entry_exit", {})
                strat = qs.get("recommended_strategy", "single_leg")
                ml = qs.get("multi_leg", {})
                lines.append(
                    f"  {ticker}: quant={comp}/100 | suggested={strat} | "
                    f"entry=${ee.get('underlying_entry','?')} "
                    f"target=${ee.get('underlying_target','?')} "
                    f"stop=${ee.get('underlying_stop','?')}"
                )
                if ml and strat != "single_leg":
                    sc = ml.get("short_call_strike","?")
                    lc = ml.get("long_call_strike","?")
                    sp = ml.get("short_put_strike","?")
                    lp = ml.get("long_put_strike","?")
                    cred = ml.get("net_credit","?")
                    lines.append(
                        f"    strikes: SC={sc} LC={lc} SP={sp} LP={lp} | "
                        f"net_credit≈${cred} | "
                        f"max_profit≈${ml.get('max_profit','?')} max_loss≈${ml.get('max_loss','?')}"
                    )
            quant_ctx = "\nQuantitative analysis (math-based baseline):\n" + "\n".join(lines) + "\n"

        user = (
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
            '  {"rank":1,"ticker":"AAPL","strategy_type":"single_leg","option_type":"CALL",'
            '"strike":195.0,"expiry":"2025-04-18","entry_price":2.40,"exit_price":4.80,'
            '"stop_loss":1.20,"underlying_entry":192.5,"underlying_target":198.0,'
            '"underlying_stop":189.0,"qual_score":82,"score":87,"grade":"B",'
            '"explanation":"RSI 32 oversold, bouncing off Fib 61.8%..."}\n\n'
            "For iron_condor:\n"
            '  {"rank":2,"ticker":"SPY","strategy_type":"iron_condor","option_type":"N/A",'
            '"expiry":"2025-04-18","short_call_strike":512.0,"long_call_strike":515.0,'
            '"short_put_strike":490.0,"long_put_strike":487.0,"net_credit":1.85,'
            '"max_profit":185.0,"max_loss":115.0,"breakeven_low":488.15,'
            '"breakeven_high":513.85,"qual_score":79,"score":83,"grade":"B",'
            '"explanation":"RSI neutral at 52, BB %B at 0.45 range-bound, IV rank 48..."}\n\n'
            "For spreads (bull_put_spread example):\n"
            '  {"rank":3,"ticker":"MSFT","strategy_type":"bull_put_spread","option_type":"N/A",'
            '"expiry":"2025-04-18","short_put_strike":380.0,"long_put_strike":375.0,'
            '"net_credit":1.20,"max_profit":120.0,"max_loss":380.0,"breakeven_low":378.80,'
            '"qual_score":85,"score":88,"grade":"B",'
            '"explanation":"Strong uptrend above MA50+200, Fib 61.8% support at 381..."}\n\n'
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

        user = (
            f"Current date/time (UTC): {datetime.now(timezone.utc).isoformat()}\n"
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
            '  {"rank":1,"ticker":"MSFT","put_strike":380.0,"put_expiry":"2025-04-18",'
            '"put_premium":4.20,"iv_rank":52,"qual_score":88,"score":91,"grade":"A",'
            '"explanation":"3-4 sentences citing trend, support level, and IV context"}\n'
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

        user = (
            f"I own 100 shares of {ticker} at cost basis ${cost_basis:.2f}/share "
            f"(assigned on {assigned_date}).\n"
            f"Current price: ${current_price:.2f}\n"
            f"IV rank: {iv_rank if iv_rank else 'unknown'}\n"
            f"Earnings date: {earnings_date if earnings_date else 'none known — avoid selling through earnings'}\n"
            f"{tech_str}\n\n"
            f"Recent news for {ticker}:\n{news_bullets}\n\n"
            "Select the call strike at a Fibonacci resistance level or near the Bollinger upper band "
            "where price is likely to stall. Do NOT go below cost basis. "
            "Use ATR to estimate realistic premium. Prefer the nearest Friday expiry.\n\n"
            "Return JSON:\n"
            '{"call_strike":195.0,"call_expiry":"2025-04-18",'
            '"estimated_premium":1.85,"rationale":"cite the specific technical level used"}'
        )
        raw = self._call(system, user, max_tokens=1024)
        return self._parse(raw)
