"""Tests for the split wheel / harvest scanner schedule.

The wheel put + call scanner runs at 10:30 and 14:00 Eastern; the
harvest put scanner runs five minutes later as its own job, so the two
full-universe chain sweeps do not run back to back and starve the
second one of data (Nov 10 2026: harvest got no options data for 533
of 607 tickers one minute after the wheel sweep succeeded).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scheduler import start_scheduler


def test_wheel_and_harvest_jobs_are_split_and_staggered():
    scheduler = start_scheduler()
    try:
        jobs = {job.id: job for job in scheduler.get_jobs()}
        for job_id in (
            "wheel_scanner_1030",
            "wheel_scanner_1400",
            "harvest_scanner_1035",
            "harvest_scanner_1405",
        ):
            assert job_id in jobs, f"missing scheduled job {job_id}"
        assert jobs["wheel_scanner_1030"].next_run_time.hour == 10
        assert jobs["wheel_scanner_1030"].next_run_time.minute == 30
        assert jobs["wheel_scanner_1400"].next_run_time.hour == 14
        assert jobs["wheel_scanner_1400"].next_run_time.minute == 0
        assert jobs["harvest_scanner_1035"].next_run_time.hour == 10
        assert jobs["harvest_scanner_1035"].next_run_time.minute == 35
        assert jobs["harvest_scanner_1405"].next_run_time.hour == 14
        assert jobs["harvest_scanner_1405"].next_run_time.minute == 5
    finally:
        scheduler.shutdown(wait=False)
