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
    def analyze_options(self, news_bullets: str, technical_data: str, market_context: str) -> list[dict]:
        system = (
            "You are a professional options trader and technical analyst with 20+ years of experience. "
            "You have deep expertise in RSI, MACD, Bollinger Bands, VWAP, Fibonacci retracements, "
            "moving averages, ATR, and volume analysis. "
            "Identify the top 5 options trading opportunities for the next 1-10 days. "
            "Use the technical indicators to time entries precisely — e.g. buy calls near Fibonacci "
            "support when RSI is oversold and MACD is turning bullish; buy puts near resistance when "
            "RSI is overbought and price is below VWAP. "
            "Respond ONLY with a valid JSON array — no prose, no markdown fences."
        )
        user = (
            f"{market_context}\n\n"
            f"Recent news:\n{news_bullets}\n\n"
            f"Technical data (price, RSI, MACD, Bollinger Bands, MAs, Fibonacci, ATR, VWAP, volume):\n"
            f"{technical_data}\n\n"
            "Instructions:\n"
            "- Cite specific indicator readings in your explanation (e.g. 'RSI at 32 oversold, "
            "price bouncing off Fib 61.8% support at $142, MACD bullish crossover')\n"
            "- Set strike near key Fibonacci or MA level where you expect a reaction\n"
            "- Use ATR to size the move — entry/exit should reflect realistic ATR-based targets\n"
            "- Flag if a Bollinger squeeze is present (explosive move imminent)\n"
            "- Avoid trades where price is between MAs with no clear direction\n\n"
            "Return a JSON array of exactly 5 objects:\n"
            "[\n"
            '  {"rank":1,"ticker":"AAPL","option_type":"CALL","strike":195.0,'
            '"expiry":"2025-04-11","entry_price":2.40,"exit_price":4.80,'
            '"stop_loss":1.20,"score":87,"grade":"B",'
            '"explanation":"3-4 sentences citing specific indicator readings and levels"}\n'
            "]\n\n"
            "Scoring rubric (0-100):\n"
            "- Technical setup quality (RSI, MACD, Fib, MA alignment): 35%\n"
            "- Catalyst/news strength: 25%\n"
            "- IV environment and premium value: 20%\n"
            "- Risk/reward ratio: 20%\n"
            "Grade: A=90-100, B=80-89, C=70-79, D=60-69, F=below 60."
        )
        raw = self._call(system, user)
        return self._parse(raw)

    # ------------------------------------------------------------------
    # Wheel strategy analysis
    # ------------------------------------------------------------------
    def analyze_wheel(self, news_bullets: str, screening_data: str) -> list[dict]:
        system = (
            "You are a professional options income trader specialising in the Wheel Strategy. "
            "You use technical analysis to identify the safest put-selling opportunities: "
            "stocks in uptrends (above MA50 and MA200), with elevated IV rank for premium, "
            "and put strikes placed below strong Fibonacci or moving average support. "
            "Respond ONLY with a valid JSON array — no prose, no markdown fences."
        )
        user = (
            f"Current date/time (UTC): {datetime.now(timezone.utc).isoformat()}\n\n"
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
            "and why IV makes it attractive right now.\n\n"
            "Return a JSON array of exactly 5 objects:\n"
            "[\n"
            '  {"rank":1,"ticker":"MSFT","put_strike":380.0,"put_expiry":"2025-04-18",'
            '"put_premium":4.20,"iv_rank":52,"score":91,"grade":"A",'
            '"explanation":"3-4 sentences citing trend, support level, and IV context"}\n'
            "]\n\n"
            "Scoring rubric (0-100):\n"
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
    def analyze_longterm(self, news_bullets: str, fundamental_data: str) -> list[dict]:
        system = (
            "You are a fundamental equity analyst and portfolio manager with expertise in "
            "long-term investing (12+ month horizon). You combine fundamental analysis with "
            "long-term technical trend analysis: stocks must be in structural uptrends (above MA200), "
            "ideally with a golden cross (MA50 > MA200), and showing accumulation in volume trends. "
            "Respond ONLY with a valid JSON array — no prose, no markdown fences."
        )
        user = (
            f"Current date/time (UTC): {datetime.now(timezone.utc).isoformat()}\n\n"
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
            "(MA50/200 relationship), and the key risk.\n\n"
            "Return a JSON array of exactly 5 objects:\n"
            "[\n"
            '  {"rank":1,"ticker":"NVDA","investment_type":"growth","target_price":1200.0,'
            '"time_horizon":"18-24 months","score":94,"grade":"A",'
            '"explanation":"3-4 sentences on fundamentals, trend, catalyst, and risk"}\n'
            "]\n\n"
            "Scoring rubric:\n"
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
