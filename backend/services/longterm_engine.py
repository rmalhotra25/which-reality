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
    return "\n".join(lines) if lines else "No recent news available."


def _format_fundamentals(data: dict) -> str:
    lines = []
    for ticker, d in data.items():
        pe = d.get("pe_ratio")
        eps = d.get("eps_growth_ttm")
        rev = d.get("revenue_growth_ttm")
        div = d.get("div_yield")
        sector = d.get("sector", "?")
        rating = d.get("analyst_rating", "?")
        lines.append(
            f"{ticker}: PE={pe}, EPS_growth={eps}, rev_growth={rev}, "
            f"div_yield={div}, sector={sector}, analyst={rating}"
        )
    return "\n".join(lines) if lines else "No fundamental data available."


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
            news_str = _format_news(news)
            fund_str = _format_fundamentals(fundamentals)
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
