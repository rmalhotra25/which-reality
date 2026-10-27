import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _auto_run_if_empty() -> None:
    """Run all analysis engines in a background thread if the DB has no data yet."""
    import threading

    def _run():
        import time
        time.sleep(3)  # let the app finish starting before hammering the DB
        from database import SessionLocal
        from models.recommendation import Recommendation
        db = SessionLocal()
        try:
            count = db.query(Recommendation).count()
            if count > 0:
                logger.info("Auto-seed: DB already has %d recommendations — skipping", count)
                return
            logger.info("Auto-seed: database is empty — running initial analysis now")
            from services.options_engine import OptionsEngine
            from services.wheel_engine import WheelEngine
            from services.champions_engine import run as run_champions
            import services.run_status as run_status
            try:
                OptionsEngine(db).run()
            except Exception as e:
                run_status.set_error("options", str(e))
                logger.error("Auto-seed: options engine failed: %s", e, exc_info=True)
            try:
                WheelEngine(db).run()
            except Exception as e:
                run_status.set_error("wheel", str(e))
                logger.error("Auto-seed: wheel engine failed: %s", e, exc_info=True)
            try:
                run_champions(db)
            except Exception as e:
                logger.error("Auto-seed: champions engine failed: %s", e, exc_info=True)
            logger.info("Auto-seed: initial analysis complete")
        except Exception as e:
            logger.error("Auto-seed failed: %s", e, exc_info=True)
        finally:
            db.close()

    threading.Thread(target=_run, daemon=True).start()


@asynccontextmanager
async def lifespan(app: FastAPI):
    from database import init_db, SessionLocal
    from scheduler import start_scheduler
    from auth import auth_status_message

    init_db()
    logger.info("Database initialised")

    # Seed the setup registry (no-op if rows already exist)
    _db = SessionLocal()
    try:
        from services.setup_registry_service import seed_registry
        seed_registry(_db)
    except Exception as e:
        logger.warning("Setup registry seed failed: %s", e)
    finally:
        _db.close()

    # Seed the rule registry and run the startup check (P1): a LIVE
    # rule with no implementing function, or thresholds that differ from
    # its row, fails the deploy visibly instead of firing on the wrong
    # thresholds.
    _db = SessionLocal()
    try:
        from services.rule_registry import seed_rule_registry, verify_rules
        seed_rule_registry(_db)
        verify_rules(_db)
        logger.info("Rule registry seeded and startup check passed")
    except Exception as e:
        logger.critical("Rule registry startup check FAILED: %s", e)
        raise
    finally:
        _db.close()

    scheduler = start_scheduler()
    app.state.scheduler = scheduler
    logger.info("%s", auth_status_message())
    _auto_run_if_empty()
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

# Auth runs after CORS in the stack (last added runs first on request),
# so preflight OPTIONS still reaches the CORS middleware. When no
# TRADEIQ_AUTH_* vars are set this is a no-op passthrough.
from auth import AuthMiddleware  # noqa: E402

app.add_middleware(AuthMiddleware)

from routers import options, wheel  # noqa: E402
from routers import market, account, performance, watchlist, champions, covered_calls, scanner, options_flow, discovery, dcf, cef, dividend_path, twelve_step, iv_history, alerts, book, challenge, rules, lookup  # noqa: E402

app.include_router(options.router, prefix="/api/options", tags=["Options"])
app.include_router(wheel.router, prefix="/api/wheel", tags=["Wheel Strategy"])
app.include_router(covered_calls.router)
app.include_router(cef.router)
app.include_router(dividend_path.router)
app.include_router(market.router)
app.include_router(account.router)
app.include_router(performance.router)
app.include_router(watchlist.router)
app.include_router(champions.router)
app.include_router(scanner.router)
app.include_router(options_flow.router)
app.include_router(discovery.router)
app.include_router(dcf.router)
app.include_router(twelve_step.router)
app.include_router(iv_history.router)
app.include_router(alerts.router)
app.include_router(book.router)
app.include_router(challenge.router)
app.include_router(rules.router)
app.include_router(lookup.router)


@app.get("/api/health", tags=["Health"])
def health():
    return {"status": "ok"}


@app.get("/api/keepalive", tags=["Health"])
def keepalive(request: Request):
    """Public liveness probe for the external uptime pinger.

    Deliberately exempt from auth so UptimeRobot or cron-job.org can hit
    it without credentials. A hit every 5 minutes keeps the free Render
    instance awake so the in-process scheduler fires on time. Returns
    the next run time of each scheduled job so the pinger log (or Rohit)
    can see at a glance whether the morning jobs are still scheduled.
    """
    from scheduler import describe_jobs

    scheduler = getattr(request.app.state, "scheduler", None)
    return {
        "status": "ok",
        "scheduler": "running" if scheduler is not None else "not started",
        "jobs": describe_jobs(scheduler),
    }


@app.get("/api/scheduler", tags=["Health"])
def scheduler_status(request: Request):
    """Scheduled job list with next run times (America/New_York). Auth applies."""
    from scheduler import describe_jobs

    scheduler = getattr(request.app.state, "scheduler", None)
    return {
        "scheduler": "running" if scheduler is not None else "not started",
        "jobs": describe_jobs(scheduler),
    }


@app.get("/api/status", tags=["Health"])
def run_status_endpoint():
    """System status: one line per job from the persistent run receipts
    (the source of truth), plus the in-memory run_status mirror as a
    fallback. A job with no receipt is a job that did not run; a failed
    job shows state error here, never silence."""
    from database import SessionLocal
    from services.run_status import get_all

    receipts = []
    db = SessionLocal()
    try:
        from services.run_receipts import latest_per_job
        receipts = latest_per_job(db)
    except Exception as e:
        logger.warning("run receipts unavailable for /api/status: %s", e)
    finally:
        db.close()
    return {"run_status": get_all(), "receipts": receipts}


# Serve the built React frontend — must come last
_frontend_dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.isdir(_frontend_dist):
    app.mount("/assets", StaticFiles(directory=os.path.join(_frontend_dist, "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_frontend(full_path: str):
        return FileResponse(os.path.join(_frontend_dist, "index.html"))
