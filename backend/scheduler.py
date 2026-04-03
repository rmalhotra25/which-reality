import logging
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

EASTERN = pytz.timezone("America/New_York")
RUN_TIMES = [(9, 0), (9, 45), (12, 0), (15, 0), (18, 0)]


def run_all_analyses() -> None:
    from database import SessionLocal
    from services.options_engine import OptionsEngine
    from services.wheel_engine import WheelEngine
    from services.longterm_engine import LongTermEngine

    logger.info("Scheduler: starting all analysis pipelines")
    db = SessionLocal()
    try:
        OptionsEngine(db).run()
        WheelEngine(db).run()
        LongTermEngine(db).run()
    except Exception as e:
        logger.error("Scheduled run failed: %s", e, exc_info=True)
    finally:
        db.close()


def refresh_call_suggestions() -> None:
    from database import SessionLocal
    from services.wheel_engine import WheelEngine

    logger.info("Scheduler: refreshing weekly call suggestions")
    db = SessionLocal()
    try:
        WheelEngine(db).refresh_all_call_suggestions()
    except Exception as e:
        logger.error("Call suggestion refresh failed: %s", e, exc_info=True)
    finally:
        db.close()


def start_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone=EASTERN)

    for hour, minute in RUN_TIMES:
        scheduler.add_job(
            run_all_analyses,
            CronTrigger(hour=hour, minute=minute, timezone=EASTERN),
            id=f"analysis_{hour:02d}{minute:02d}",
            replace_existing=True,
            misfire_grace_time=300,
        )

    # Weekly Monday 9:05 AM Eastern — refresh covered call suggestions
    scheduler.add_job(
        refresh_call_suggestions,
        CronTrigger(day_of_week="mon", hour=9, minute=5, timezone=EASTERN),
        id="call_suggestions_weekly",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(
        "Scheduler started. Jobs scheduled at %s Eastern + Monday 09:05 call refresh.",
        ", ".join(f"{h:02d}:{m:02d}" for h, m in RUN_TIMES),
    )
    return scheduler
