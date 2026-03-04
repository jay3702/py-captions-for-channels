"""
Daily summary logger for pipeline processing activity.

Emits a once-daily log entry summarising recordings processed,
successes, failures, recoveries, and average processing times.
"""

import asyncio
from datetime import datetime, timedelta, timezone

from .database import get_db
from .logging.structured_logger import get_logger
from .models import Execution

LOG = get_logger("daily_summary")


def _format_duration(seconds: float) -> str:
    """Format seconds into a human-readable string."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours = int(minutes // 60)
    mins = minutes % 60
    return f"{hours}h {mins}m"


def generate_daily_summary(target_date: datetime = None) -> str | None:
    """Generate a summary string for a given day's executions.

    Args:
        target_date: Date to summarise (defaults to yesterday).

    Returns:
        Formatted summary string, or None if no executions found.
    """
    if target_date is None:
        target_date = datetime.now(timezone.utc) - timedelta(days=1)

    # Build local-day boundaries in UTC
    local_dt = target_date.astimezone()
    day_start = local_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    day_start_utc = day_start.astimezone(timezone.utc)
    day_end_utc = day_end.astimezone(timezone.utc)

    db_gen = get_db()
    try:
        db = next(db_gen)
        executions = (
            db.query(Execution)
            .filter(Execution.started_at >= day_start_utc)
            .filter(Execution.started_at < day_end_utc)
            .all()
        )
    finally:
        try:
            next(db_gen)
        except StopIteration:
            pass

    if not executions:
        return None

    total = len(executions)
    successes = [e for e in executions if e.success is True]
    failures = [
        e
        for e in executions
        if e.status in ("completed", "failed") and e.success is False
    ]
    # Recoveries are successes whose error_message mentions "crash"
    # or whose original exit code was a signal — but since we mark
    # recovered jobs as success, we detect them via the log/error field.
    recovered = [
        e
        for e in successes
        if e.error_message and "recovered" in e.error_message.lower()
    ]
    pending = [
        e for e in executions if e.status in ("pending", "discovered", "running")
    ]

    # Timing stats (only for completed jobs with elapsed data)
    completed_with_time = [
        e for e in executions if e.elapsed_seconds is not None and e.elapsed_seconds > 0
    ]
    if completed_with_time:
        times = [e.elapsed_seconds for e in completed_with_time]
        avg_time = sum(times) / len(times)
        min_time = min(times)
        max_time = max(times)
        total_time = sum(times)
    else:
        avg_time = min_time = max_time = total_time = 0.0

    date_label = day_start.strftime("%Y-%m-%d")

    lines = [
        f"Daily Summary for {date_label}",
        f"  Total jobs: {total}",
        f"  Successes:  {len(successes)}",
        f"  Failures:   {len(failures)}",
    ]
    if recovered:
        lines.append(f"  Recovered:  {len(recovered)} (crash recovery)")
    if pending:
        lines.append(f"  Pending:    {len(pending)}")
    if completed_with_time:
        lines.append(
            f"  Avg time:   {_format_duration(avg_time)}  "
            f"(min {_format_duration(min_time)}, "
            f"max {_format_duration(max_time)})"
        )
        lines.append(f"  Total time: {_format_duration(total_time)}")

    # List failures by title for quick reference
    if failures:
        lines.append("  Failed recordings:")
        for e in failures:
            error = e.error_message or "unknown error"
            # Truncate long error messages
            if len(error) > 80:
                error = error[:77] + "..."
            lines.append(f"    - {e.title}: {error}")

    return "\n".join(lines)


def emit_daily_summary(target_date: datetime = None):
    """Generate and log the daily summary."""
    summary = generate_daily_summary(target_date)
    if summary:
        LOG.info("=" * 60)
        LOG.info(summary)
        LOG.info("=" * 60)
    else:
        date_label = (
            target_date.astimezone().strftime("%Y-%m-%d")
            if target_date
            else "yesterday"
        )
        LOG.info("Daily Summary for %s: no jobs processed", date_label)


def _seconds_until_target(hour: int = 0, minute: int = 5) -> float:
    """Seconds from now until the next occurrence of local HH:MM."""
    now = datetime.now().astimezone()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def daily_summary_loop(hour: int = 0, minute: int = 5):
    """Async loop that emits a daily summary once per day.

    Default schedule: 00:05 local time (shortly after midnight).
    """
    while True:
        try:
            wait = _seconds_until_target(hour, minute)
            LOG.debug(
                "Daily summary scheduled in %.0f seconds " "(at %02d:%02d local)",
                wait,
                hour,
                minute,
            )
            await asyncio.sleep(wait)

            # Summarise *yesterday* (the day that just ended)
            emit_daily_summary()
        except asyncio.CancelledError:
            LOG.debug("Daily summary loop cancelled")
            break
        except Exception as e:
            LOG.error("Error in daily summary: %s", e, exc_info=True)
            # Sleep a bit to avoid tight loop on persistent errors
            await asyncio.sleep(3600)
