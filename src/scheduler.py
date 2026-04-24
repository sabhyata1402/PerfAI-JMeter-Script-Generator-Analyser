"""
scheduler.py
Schedules recurring JMeter test runs using APScheduler.
Public functions:
    schedule_test(job_id, cron_expr, run_fn, *args, **kwargs) -> str
    list_jobs()                                                -> list[dict]
    remove_job(job_id)                                         -> bool
    start_scheduler()                                          -> None
    shutdown_scheduler()                                       -> None
"""

import threading
from typing import Callable

_scheduler = None
_lock = threading.Lock()


def _get_scheduler():
    global _scheduler
    if _scheduler is None:
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
        except ImportError:
            raise ImportError(
                "apscheduler is required for scheduled runs. "
                "Install it with: pip install apscheduler>=3.10.0"
            )
        with _lock:
            if _scheduler is None:
                _scheduler = BackgroundScheduler(daemon=True)
                _scheduler.start()
    return _scheduler


def schedule_test(
    job_id: str,
    cron_expr: str,
    run_fn: Callable,
    *args,
    **kwargs,
) -> str:
    """
    Schedule a recurring test run using a cron expression.

    Args:
        job_id:    Unique identifier for this schedule (e.g. "nightly-load-test")
        cron_expr: Cron string in 5-field format: "minute hour day month day_of_week"
                   Examples:
                     "0 2 * * *"   → every night at 02:00
                     "0 */6 * * *" → every 6 hours
                     "30 9 * * 1"  → every Monday at 09:30
        run_fn:    Callable to invoke (e.g. run_local or run_on_aws)
        *args:     Positional arguments passed to run_fn
        **kwargs:  Keyword arguments passed to run_fn

    Returns:
        job_id string.
    """
    from apscheduler.triggers.cron import CronTrigger

    scheduler = _get_scheduler()

    # Remove existing job with same ID to allow reschedule
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    parts = cron_expr.strip().split()
    if len(parts) != 5:
        raise ValueError(
            f"cron_expr must have exactly 5 fields (got {len(parts)}): '{cron_expr}'"
        )

    minute, hour, day, month, day_of_week = parts
    trigger = CronTrigger(
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=day_of_week,
    )

    scheduler.add_job(
        func=run_fn,
        trigger=trigger,
        args=args,
        kwargs=kwargs,
        id=job_id,
        replace_existing=True,
        misfire_grace_time=300,
    )

    return job_id


def list_jobs() -> list[dict]:
    """
    Return a list of currently scheduled jobs.

    Returns:
        List of dicts with keys: id, next_run, cron
    """
    scheduler = _get_scheduler()
    result = []
    for job in scheduler.get_jobs():
        result.append(
            {
                "id": job.id,
                "next_run": str(job.next_run_time) if job.next_run_time else "paused",
                "trigger": str(job.trigger),
            }
        )
    return result


def remove_job(job_id: str) -> bool:
    """
    Remove a scheduled job by ID.

    Returns:
        True if removed, False if not found.
    """
    scheduler = _get_scheduler()
    job = scheduler.get_job(job_id)
    if job:
        scheduler.remove_job(job_id)
        return True
    return False


def start_scheduler() -> None:
    """Ensure the background scheduler is running."""
    _get_scheduler()


def shutdown_scheduler() -> None:
    """Gracefully shut down the scheduler (call on app exit)."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        _scheduler = None
