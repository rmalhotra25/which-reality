import json
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session

from models.wheel import WheelRecommendation, WheelPosition, WheelStatus
from services.news_scraper import NewsScraper
from services.stock_data import StockDataService, DEFAULT_UNIVERSE
from services.claude_analyst import ClaudeAnalyst

logger = logging.getLogger(__name__)

WHEEL_UNIVERSE = DEFAULT_UNIVERSE


def _format_news(items) -> str:
    lines = []
    for it in items[:40]:
        lines.append(f"- [{it.ticker or 'MARKET'}] {it.source}: {it.headline}")
    return "\n".join(lines) if lines else "No recent news available."


def _format_screening(data: dict) -> str:
    lines = []
    for ticker, d in data.items():
        iv = d.get("atm_iv") or d.get("iv_rank_approx")
        lines.append(
            f"{ticker}: price=${d['price']}, IV≈{iv}%, "
            f"5d_chg={d['change_5d_pct']}%, vol={d['volume']:,}"
        )
    return "\n".join(lines) if lines else "No screening data available."


class WheelEngine:
    def __init__(self, db: Session):
        self.db = db
        self.scraper = NewsScraper()
        self.stock_data = StockDataService()
        self.analyst = ClaudeAnalyst()

    def run(self) -> None:
        logger.info("WheelEngine: starting analysis run")
        run_at = datetime.now(timezone.utc)
        try:
            news = self.scraper.fetch_all(WHEEL_UNIVERSE[:15])
            screening = self.stock_data.get_wheel_screening_data(WHEEL_UNIVERSE)
            news_str = _format_news(news)
            screening_str = _format_screening(screening)
            recs = self.analyst.analyze_wheel(news_str, screening_str)
            self._store(recs, run_at)
            logger.info("WheelEngine: stored %d recommendations", len(recs))
        except Exception as e:
            logger.error("WheelEngine run failed: %s", e, exc_info=True)

    def _store(self, recs: list[dict], run_at: datetime) -> None:
        for rec in recs:
            obj = WheelRecommendation(
                ticker=str(rec.get("ticker", "")).upper(),
                rank=int(rec.get("rank", 0)),
                score=float(rec.get("score", 50)),
                grade=str(rec.get("grade", "C")),
                explanation=str(rec.get("explanation", "")),
                put_strike=rec.get("put_strike"),
                put_expiry=rec.get("put_expiry"),
                put_premium=rec.get("put_premium"),
                iv_rank=rec.get("iv_rank"),
                run_at=run_at,
            )
            self.db.add(obj)
        self.db.commit()

    def generate_call_suggestion(self, position: WheelPosition) -> str | None:
        """Generate a covered call suggestion for an assigned position."""
        try:
            current_price = self.stock_data.get_current_price(position.ticker)
            if not current_price:
                return None
            news = self.scraper.fetch_all([position.ticker])
            news_str = _format_news(news)
            assigned_date = (
                position.assigned_at.strftime("%Y-%m-%d")
                if position.assigned_at
                else "unknown"
            )
            suggestion = self.analyst.generate_call_suggestion(
                ticker=position.ticker,
                cost_basis=position.cost_basis or position.put_strike,
                current_price=current_price,
                assigned_date=assigned_date,
                iv_rank=None,
                earnings_date=None,
                news_bullets=news_str,
            )
            return json.dumps(suggestion)
        except Exception as e:
            logger.error("Call suggestion error for position %d: %s", position.id, e)
            return None

    def refresh_all_call_suggestions(self) -> None:
        """Weekly job: refresh call suggestions for all assigned positions."""
        stale_cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        positions = (
            self.db.query(WheelPosition)
            .filter(WheelPosition.status == WheelStatus.assigned)
            .filter(
                (WheelPosition.call_suggestion_at == None) |  # noqa: E711
                (WheelPosition.call_suggestion_at < stale_cutoff)
            )
            .all()
        )
        for pos in positions:
            suggestion = self.generate_call_suggestion(pos)
            if suggestion:
                pos.call_suggestion = suggestion
                pos.call_suggestion_at = datetime.now(timezone.utc)
        self.db.commit()
        logger.info("Refreshed call suggestions for %d positions", len(positions))
