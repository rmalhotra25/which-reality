import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from database import init_db
    from scheduler import start_scheduler

    init_db()
    logger.info("Database initialised")
    scheduler = start_scheduler()
    yield
    scheduler.shutdown(wait=False)
    logger.info("Scheduler stopped")


app = FastAPI(
    title="Trading Recommendations API",
    description="AI-powered options, wheel strategy, and long-term investment recommendations",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from routers import options, wheel, longterm  # noqa: E402

app.include_router(options.router, prefix="/api/options", tags=["Options"])
app.include_router(wheel.router, prefix="/api/wheel", tags=["Wheel Strategy"])
app.include_router(longterm.router, prefix="/api/longterm", tags=["Long-Term"])


@app.get("/api/health", tags=["Health"])
def health():
    return {"status": "ok"}
