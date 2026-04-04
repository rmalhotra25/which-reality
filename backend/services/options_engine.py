import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from models.recommendation import Recommendation, TabType, GradeEnum
from services.news_scraper import NewsScraper
from services.stock_data import StockDataService, DEFAULT_UNIVERSE
from services.claude_analyst import ClaudeAnalyst

logger = logging.getLogger(__name__)

OPTIONS_UNIVERSE = DEFAULT_UNIVERSE[:30]


def _format_news(items) -> str:
    lines = []
    for it in items[:40]:
        lines.append(f"- [{it.ticker or 'MARKET'}] {it.source}: {it.headline}")
    if not lines:
        return (
            "Live news feeds are unavailable in this environment. "
            "Base recommendations on current market conditions, recent macro trends "
            "(tariff news, Fed policy, earnings season), and technical price action. "
            f"Today's date: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}."
        )
    return "\n".join(lines)


def _format_price_data(data: dict) -> str:
    lines = []
    for ticker, d in data.items():
        iv = d.get("atm_iv") or d.get("iv_rank_approx")
        lines.append(
            f"{ticker}: price=${d['price']}, 5d_chg={d['change_5d_pct']}%, "
            f"IV≈{iv}%, vol={d['volume']:,}"
        )
    return "\n".join(lines) if lines else "No price data available."


def _grade_to_enum(grade: str) -> GradeEnum:
    mapping = {"A": GradeEnum.A, "B": GradeEnum.B, "C": GradeEnum.C, "D": GradeEnum.D, "F": GradeEnum.F}
    return mapping.get(grade.upper(), GradeEnum.C)


class OptionsEngine:
    def __init__(self, db: Session):
        self.db = db
        self.scraper = NewsScraper()
        self.stock_data = StockDataService()
        self.analyst = ClaudeAnalyst()

    def run(self) -> None:
        logger.info("OptionsEngine: starting analysis run")
        run_at = datetime.now(timezone.utc)
        try:
            news = self.scraper.fetch_all(OPTIONS_UNIVERSE[:15])
            price_data = self.stock_data.get_price_data(OPTIONS_UNIVERSE)
            options_data = self.stock_data.get_options_data(OPTIONS_UNIVERSE[:20])
            combined = {}
            for t in OPTIONS_UNIVERSE:
                if t in price_data:
                    combined[t] = {**price_data[t], **(options_data.get(t, {}))}

            market_context = "Normal trading session. Check VIX for volatility context."
            news_str = _format_news(news)
            price_str = _format_price_data(combined)

            recs = self.analyst.analyze_options(news_str, price_str, market_context)
            self._store(recs, run_at)
            logger.info("OptionsEngine: stored %d recommendations", len(recs))
        except Exception as e:
            logger.error("OptionsEngine run failed: %s", e, exc_info=True)

    def _store(self, recs: list[dict], run_at: datetime) -> None:
        for rec in recs:
            obj = Recommendation(
                tab=TabType.options,
                ticker=str(rec.get("ticker", "")).upper(),
                rank=int(rec.get("rank", 0)),
                score=float(rec.get("score", 50)),
                grade=_grade_to_enum(str(rec.get("grade", "C"))),
                explanation=str(rec.get("explanation", "")),
                option_type=str(rec.get("option_type", "CALL")).upper(),
                strike=rec.get("strike"),
                expiry=rec.get("expiry"),
                entry_price=rec.get("entry_price"),
                exit_price=rec.get("exit_price"),
                stop_loss=rec.get("stop_loss"),
                run_at=run_at,
            )
            self.db.add(obj)
        self.db.commit()
