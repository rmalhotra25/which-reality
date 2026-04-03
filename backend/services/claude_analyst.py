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
    def analyze_options(self, news_bullets: str, price_data: str, market_context: str) -> list[dict]:
        system = (
            "You are a professional options trader and technical analyst with 20+ years of experience. "
            "Identify the top 5 options trading opportunities for the next 1-5 days based on the "
            "news, price data, and market context provided. "
            "Respond ONLY with a valid JSON array — no prose, no markdown fences."
        )
        user = (
            f"Current date/time (UTC): {datetime.now(timezone.utc).isoformat()}\n"
            f"Market context: {market_context}\n\n"
            f"Recent news (last 24h):\n{news_bullets}\n\n"
            f"Price and volatility data:\n{price_data}\n\n"
            "Return a JSON array of exactly 5 objects with this schema:\n"
            "[\n"
            '  {"rank":1,"ticker":"AAPL","option_type":"CALL","strike":195.0,'
            '"expiry":"2025-04-11","entry_price":2.40,"exit_price":4.80,'
            '"stop_loss":1.20,"score":87,"grade":"B",'
            '"explanation":"2-3 sentence rationale citing specific news/data"}\n'
            "]\n\n"
            "Scoring rubric (0-100): catalyst strength 30% + technical setup 30% + "
            "IV/premium value 20% + risk/reward ratio 20%.\n"
            "Grade mapping: A=90-100, B=80-89, C=70-79, D=60-69, F=below 60.\n"
            "Favour liquid underlyings with weekly options. Set exit_price at 2× entry, "
            "stop_loss at 0.5× entry."
        )
        raw = self._call(system, user)
        return self._parse(raw)

    # ------------------------------------------------------------------
    # Wheel strategy analysis
    # ------------------------------------------------------------------
    def analyze_wheel(self, news_bullets: str, screening_data: str) -> list[dict]:
        system = (
            "You are a professional options income trader specialising in the Wheel Strategy "
            "(selling cash-secured puts, then covered calls after assignment). "
            "Identify the top 5 stocks ideal for put-selling this week. "
            "Respond ONLY with a valid JSON array — no prose, no markdown fences."
        )
        user = (
            f"Current date/time (UTC): {datetime.now(timezone.utc).isoformat()}\n\n"
            f"Recent market news:\n{news_bullets}\n\n"
            f"Stock screening data:\n{screening_data}\n\n"
            "Return a JSON array of exactly 5 objects with this schema:\n"
            "[\n"
            '  {"rank":1,"ticker":"MSFT","put_strike":380.0,"put_expiry":"2025-04-18",'
            '"put_premium":4.20,"iv_rank":52,"score":91,"grade":"A",'
            '"explanation":"2-3 sentences: why this stock is ideal for put-selling now"}\n'
            "]\n\n"
            "Scoring rubric (0-100): IV rank 25% + stock quality/stability 30% + "
            "premium yield % 25% + technical support level 20%.\n"
            "Grade: A=90-100, B=80-89, C=70-79, D=60-69, F=below 60.\n"
            "Choose puts 5-10% OTM expiring in the nearest weekly Friday. "
            "Only recommend stocks with avg daily volume > 500K and price $15-$600."
        )
        raw = self._call(system, user)
        return self._parse(raw)

    # ------------------------------------------------------------------
    # Long-term growth & income analysis
    # ------------------------------------------------------------------
    def analyze_longterm(self, news_bullets: str, fundamental_data: str) -> list[dict]:
        system = (
            "You are a fundamental equity analyst and portfolio manager with expertise in "
            "long-term investing (12+ month horizon). Identify the top 5 stocks or ETFs for "
            "long-term hold, classifying each as 'growth' or 'income'. "
            "Respond ONLY with a valid JSON array — no prose, no markdown fences."
        )
        user = (
            f"Current date/time (UTC): {datetime.now(timezone.utc).isoformat()}\n\n"
            f"Recent news and sentiment summary:\n{news_bullets}\n\n"
            f"Fundamental data:\n{fundamental_data}\n\n"
            "Return a JSON array of exactly 5 objects with this schema:\n"
            "[\n"
            '  {"rank":1,"ticker":"NVDA","investment_type":"growth","target_price":1200.0,'
            '"time_horizon":"18-24 months","score":94,"grade":"A",'
            '"explanation":"3-4 sentences citing fundamentals, catalysts, and risks"}\n'
            "]\n\n"
            "Scoring rubric — Growth: earnings growth 35% + market position 25% + "
            "news sentiment 20% + valuation 20%.\n"
            "Income: dividend yield+safety 40% + balance sheet 30% + sector stability 20% + growth 10%.\n"
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
    ) -> dict:
        system = (
            "You are a professional options income trader. Generate an optimal weekly covered "
            "call recommendation for an assigned stock position. "
            "Respond ONLY with a valid JSON object — no prose, no markdown fences."
        )
        user = (
            f"I was assigned 100 shares of {ticker} at ${cost_basis:.2f}/share on {assigned_date}.\n"
            f"Current price: ${current_price:.2f}\n"
            f"IV rank: {iv_rank if iv_rank else 'unknown'}\n"
            f"Earnings date: {earnings_date if earnings_date else 'none known — avoid selling through earnings'}\n\n"
            f"Recent news for {ticker}:\n{news_bullets}\n\n"
            "Suggest the optimal covered call to sell this week. "
            "Do NOT suggest a strike below cost basis. "
            "Prefer strikes 3-8% OTM expiring the nearest Friday.\n\n"
            "Return JSON:\n"
            '{"call_strike":195.0,"call_expiry":"2025-04-18",'
            '"estimated_premium":1.85,"rationale":"explanation"}'
        )
        raw = self._call(system, user, max_tokens=1024)
        return self._parse(raw)
