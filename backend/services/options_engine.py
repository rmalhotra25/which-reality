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


def _format_technicals(data: dict) -> str:
    """Format full technical indicator suite for Claude."""
    lines = []
    for ticker, d in data.items():
        if not d:
            continue
        price = d.get("price", "?")
        chg = d.get("change_5d_pct", "?")
        rsi = d.get("rsi", "?")
        iv = d.get("atm_iv") or d.get("iv_rank_approx", "?")

        macd = d.get("macd", {})
        macd_str = (
            f"MACD={macd.get('macd','?')} signal={macd.get('signal','?')} "
            f"hist={macd.get('histogram','?')} [{macd.get('crossover','?')}]"
            if macd else "MACD=n/a"
        )

        bb = d.get("bollinger", {})
        bb_str = (
            f"BB upper={bb.get('upper','?')} lower={bb.get('lower','?')} "
            f"%B={bb.get('pct_b','?')} squeeze={'YES' if bb.get('squeeze') else 'no'}"
            if bb else "BB=n/a"
        )

        ma = d.get("moving_averages", {})
        ma_str = (
            f"MA20={ma.get('ma20','?')} MA50={ma.get('ma50','?')} MA200={ma.get('ma200','?')} "
            f"[above_50={'Y' if ma.get('above_ma50') else 'N'} "
            f"above_200={'Y' if ma.get('above_ma200') else 'N'} "
            f"{'GOLDEN_CROSS' if ma.get('golden_cross') else 'DEATH_CROSS' if ma.get('death_cross') else 'no_cross'}]"
            if ma else "MA=n/a"
        )

        fib = d.get("fibonacci", {})
        fib_str = (
            f"Fib: high={fib.get('high','?')} 61.8%={fib.get('fib_618','?')} "
            f"50%={fib.get('fib_500','?')} 38.2%={fib.get('fib_382','?')} low={fib.get('low','?')}"
            if fib else "Fib=n/a"
        )

        atr = d.get("atr", "?")
        vwap = d.get("vwap", "?")
        vol = d.get("volume_trend", {})
        vol_str = f"vol_trend={vol.get('trend','?')}({vol.get('ratio','?')}x)" if vol else ""

        lines.append(
            f"{ticker}: ${price} 5d={chg}% RSI={rsi} IV≈{iv}% ATR={atr} VWAP={vwap}\n"
            f"  {macd_str}\n"
            f"  {bb_str}\n"
            f"  {ma_str}\n"
            f"  {fib_str} {vol_str}"
        )
    return "\n\n".join(lines) if lines else "No technical data available."


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
            technicals = self.stock_data.get_technicals_bulk(OPTIONS_UNIVERSE)
            options_data = self.stock_data.get_options_data(list(technicals.keys())[:20])
            for t in options_data:
                if t in technicals:
                    technicals[t].update(options_data[t])

            news_str = _format_news(news)
            tech_str = _format_technicals(technicals)
            market_context = f"Date: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"

            recs = self.analyst.analyze_options(news_str, tech_str, market_context)
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
