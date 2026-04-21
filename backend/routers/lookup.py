import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from services.stock_data import StockDataService
from services.news_scraper import NewsScraper
from services.claude_analyst import ClaudeAnalyst

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/lookup", tags=["lookup"])


class LookupRequest(BaseModel):
    ticker: str


@router.post("/analyze")
def analyze_stock(req: LookupRequest, db: Session = Depends(get_db)):
    ticker = req.ticker.strip().upper()
    if not ticker or len(ticker) > 10:
        raise HTTPException(status_code=400, detail="Invalid ticker symbol")

    stock_data = StockDataService()
    scraper = NewsScraper()
    analyst = ClaudeAnalyst()

    try:
        technicals_map = stock_data.get_price_and_technicals([ticker])
        tech = technicals_map.get(ticker) or {}
    except Exception as e:
        logger.warning("Technicals fetch failed for %s: %s", ticker, e)
        tech = {}

    current_price = tech.get("price")
    if not current_price:
        try:
            current_price = stock_data.get_current_price(ticker)
        except Exception:
            current_price = None

    if not current_price:
        raise HTTPException(
            status_code=404,
            detail=f"Could not fetch price data for {ticker}. Check the symbol and try again."
        )

    try:
        fund_map = stock_data.get_fundamentals([ticker])
        fundamentals = fund_map.get(ticker) or {}
    except Exception as e:
        logger.warning("Fundamentals fetch failed for %s: %s", ticker, e)
        fundamentals = {}

    try:
        news_items = scraper.fetch_all([ticker])
        news_bullets = "\n".join(
            f"- [{it.ticker or 'MARKET'}] {it.source}: {it.headline}"
            for it in news_items[:30]
        ) or "No recent news available."
    except Exception as e:
        logger.warning("News fetch failed for %s: %s", ticker, e)
        news_bullets = "News unavailable — base analysis on technicals and fundamentals."

    try:
        result = analyst.analyze_stock(
            ticker=ticker,
            current_price=current_price,
            technicals=tech,
            fundamentals=fundamentals,
            news_bullets=news_bullets,
        )
        result["ticker"] = ticker
        result["current_price"] = current_price
        return result
    except Exception as e:
        logger.error("Claude analysis failed for %s: %s", ticker, e)
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")
