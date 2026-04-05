import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from models.recommendation import Recommendation, TabType, GradeEnum
from services.news_scraper import NewsScraper
from services.stock_data import StockDataService, DEFAULT_UNIVERSE
from services.claude_analyst import ClaudeAnalyst

logger = logging.getLogger(__name__)

LONGTERM_UNIVERSE = DEFAULT_UNIVERSE


def _format_news(items) -> str:
    lines = []
    for it in items[:40]:
        lines.append(f"- [{it.ticker or 'MARKET'}] {it.source}: {it.headline}")
    if not lines:
        return (
            "Live news feeds are unavailable in this environment. "
            "Base recommendations on well-known fundamentals, long-term secular trends "
            "(AI, energy transition, healthcare, consumer staples), and dividend reliability. "
            f"Today's date: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}."
        )
    return "\n".join(lines)


def _format_fundamentals_and_technicals(fund_data: dict, tech_data: dict) -> str:
    """Combine fundamentals + long-term technical trend data for Claude."""
    lines = []
    tickers = set(list(fund_data.keys()) + list(tech_data.keys()))
    for ticker in tickers:
        f = fund_data.get(ticker, {})
        t = tech_data.get(ticker, {})
        if not f and not t:
            continue

        # Fundamentals
        pe = f.get("pe_ratio", "?")
        eps = f.get("eps_growth_ttm", "?")
        rev = f.get("revenue_growth_ttm", "?")
        div = f.get("div_yield", "?")
        sector = f.get("sector", "?")
        rating = f.get("analyst_rating", "?")

        # Long-term technicals — focus on MAs and relative trend
        ma = t.get("moving_averages", {})
        trend = "STRONG_UPTREND" if (ma.get("above_ma50") and ma.get("above_ma200") and ma.get("golden_cross")) \
           else "UPTREND" if (ma.get("above_ma50") and ma.get("above_ma200")) \
           else "DOWNTREND" if (not ma.get("above_ma50") and not ma.get("above_ma200")) \
           else "MIXED"
        ma_str = (
            f"MA50={ma.get('ma50','?')} MA200={ma.get('ma200','?')} "
            f"price=${t.get('price','?')} [{trend}]"
            if ma else f"price=${t.get('price','?')}"
        )

        rsi = t.get("rsi", "?")
        vol = t.get("volume_trend", {})
        vol_str = f"vol_trend={vol.get('trend','?')}" if vol else ""

        fib = t.get("fibonacci", {})
        fib_str = f"52w range: {fib.get('low','?')}-{fib.get('high','?')}" if fib else ""

        lines.append(
            f"{ticker} ({sector}): PE={pe} EPS_growth={eps} rev_growth={rev} "
            f"div_yield={div} analyst={rating} RSI={rsi} {vol_str}\n"
            f"  {ma_str}\n"
            f"  {fib_str}"
        )
    return "\n\n".join(lines) if lines else "No fundamental/technical data available."


def _grade_to_enum(grade: str) -> GradeEnum:
    mapping = {"A": GradeEnum.A, "B": GradeEnum.B, "C": GradeEnum.C, "D": GradeEnum.D, "F": GradeEnum.F}
    return mapping.get(grade.upper(), GradeEnum.C)


class LongTermEngine:
    def __init__(self, db: Session):
        self.db = db
        self.scraper = NewsScraper()
        self.stock_data = StockDataService()
        self.analyst = ClaudeAnalyst()

    def run(self) -> None:
        logger.info("LongTermEngine: starting analysis run")
        run_at = datetime.now(timezone.utc)
        try:
            news = self.scraper.fetch_all(LONGTERM_UNIVERSE[:15])
            fundamentals = self.stock_data.get_fundamentals(LONGTERM_UNIVERSE)
            technicals = self.stock_data.get_technicals_bulk(LONGTERM_UNIVERSE)
            news_str = _format_news(news)
            fund_str = _format_fundamentals_and_technicals(fundamentals, technicals)
            recs = self.analyst.analyze_longterm(news_str, fund_str)
            self._store(recs, run_at)
            logger.info("LongTermEngine: stored %d recommendations", len(recs))
        except Exception as e:
            logger.error("LongTermEngine run failed: %s", e, exc_info=True)

    def _store(self, recs: list[dict], run_at: datetime) -> None:
        for rec in recs:
            obj = Recommendation(
                tab=TabType.longterm,
                ticker=str(rec.get("ticker", "")).upper(),
                rank=int(rec.get("rank", 0)),
                score=float(rec.get("score", 50)),
                grade=_grade_to_enum(str(rec.get("grade", "C"))),
                explanation=str(rec.get("explanation", "")),
                investment_type=str(rec.get("investment_type", "growth")).lower(),
                target_price=rec.get("target_price"),
                time_horizon=rec.get("time_horizon"),
                run_at=run_at,
            )
            self.db.add(obj)
        self.db.commit()
