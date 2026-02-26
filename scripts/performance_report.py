#!/usr/bin/env python3
"""Generate a performance metrics report from the execution database.

This script analyzes historical execution data to show performance improvements
over time, including processing speed, success rates, and resource usage.
"""

import sys
import os
from datetime import datetime, timedelta
from collections import defaultdict
import statistics

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from py_captions_for_channels.database import SessionLocal  # noqa: E402
from py_captions_for_channels.models import Execution  # noqa: E402
from sqlalchemy import func, and_  # noqa: E402


def format_duration(seconds):
    """Format duration in human-readable format."""
    if seconds is None:
        return "N/A"
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        return f"{seconds/60:.1f}m"
    else:
        return f"{seconds/3600:.1f}h"


def format_size(bytes_val):
    """Format file size in human-readable format."""
    if bytes_val is None:
        return "N/A"
    for unit in ["B", "KB", "MB", "GB"]:
        if bytes_val < 1024:
            return f"{bytes_val:.1f}{unit}"
        bytes_val /= 1024
    return f"{bytes_val:.1f}TB"


def format_throughput(bytes_val, seconds):
    """Format processing throughput."""
    if bytes_val is None or seconds is None or seconds == 0:
        return "N/A"
    mb_per_sec = (bytes_val / 1024 / 1024) / seconds
    return f"{mb_per_sec:.2f} MB/s"


def print_separator(char="=", length=80):
    """Print a separator line."""
    print(char * length)


def print_section(title):
    """Print a section header."""
    print()
    print_separator()
    print(f"  {title}")
    print_separator()


def generate_report():
    """Generate and print the performance report."""
    db = SessionLocal()
    try:
        # Query all completed executions
        completed = (
            db.query(Execution)
            .filter(
                and_(
                    Execution.status == "completed",
                    Execution.success == True,  # noqa: E712
                    Execution.elapsed_seconds.isnot(None),
                    Execution.elapsed_seconds > 0,
                )
            )
            .order_by(Execution.started_at)
            .all()
        )

        if not completed:
            print("No completed executions found in database.")
            return

        # Calculate time ranges
        first_exec = completed[0]
        last_exec = completed[-1]
        total_days = (last_exec.started_at - first_exec.started_at).days + 1

        print_section("PERFORMANCE METRICS REPORT")
        print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(
            f"Database: {os.getenv('DATABASE_URL', 'sqlite:///./data/py_captions.db')}"
        )
        print()
        print("Tracking Period:")
        first_dt = first_exec.started_at.strftime("%Y-%m-%d %H:%M:%S")
        print(f"  First Execution: {first_dt}")
        last_dt = last_exec.started_at.strftime("%Y-%m-%d %H:%M:%S")
        print(f"  Last Execution:  {last_dt}")
        print(f"  Duration:        {total_days} days")

        # Overall statistics
        print_section("OVERALL STATISTICS")

        total_executions = db.query(func.count(Execution.id)).scalar()
        total_success = (
            db.query(func.count(Execution.id))
            .filter(Execution.success == True)  # noqa: E712
            .scalar()
        )
        total_failed = (
            db.query(func.count(Execution.id))
            .filter(Execution.success == False)  # noqa: E712
            .scalar()
        )

        success_rate = (
            (total_success / total_executions * 100) if total_executions > 0 else 0
        )

        print(f"Total Executions:    {total_executions:,}")
        print(f"  Successful:        {total_success:,} ({success_rate:.1f}%)")
        print(f"  Failed:            {total_failed:,}")
        print()

        # Processing time statistics
        durations = [e.elapsed_seconds for e in completed]
        print("Processing Time:")
        print(f"  Average:           {format_duration(statistics.mean(durations))}")
        print(f"  Median:            {format_duration(statistics.median(durations))}")
        print(f"  Fastest:           {format_duration(min(durations))}")
        print(f"  Slowest:           {format_duration(max(durations))}")
        std_dev = (
            format_duration(statistics.stdev(durations))
            if len(durations) > 1
            else "N/A"
        )
        print(f"  Std Dev:           {std_dev}")

        # File size statistics
        input_sizes = [e.input_size_bytes for e in completed if e.input_size_bytes]
        if input_sizes:
            print()
            print("Input File Sizes:")
            print(f"  Average:           {format_size(statistics.mean(input_sizes))}")
            print(f"  Median:            {format_size(statistics.median(input_sizes))}")
            print(f"  Smallest:          {format_size(min(input_sizes))}")
            print(f"  Largest:           {format_size(max(input_sizes))}")

        # Throughput
        throughputs = []
        for e in completed:
            if e.input_size_bytes and e.elapsed_seconds and e.elapsed_seconds > 0:
                mb_per_sec = (e.input_size_bytes / 1024 / 1024) / e.elapsed_seconds
                throughputs.append(mb_per_sec)

        if throughputs:
            print()
            print("Processing Throughput:")
            print(f"  Average:           {statistics.mean(throughputs):.2f} MB/s")
            print(f"  Median:            {statistics.median(throughputs):.2f} MB/s")
            print(f"  Best:              {max(throughputs):.2f} MB/s")
            print(f"  Worst:             {min(throughputs):.2f} MB/s")

        # Time-based trend analysis (weekly buckets)
        print_section("PERFORMANCE TRENDS (Weekly)")

        # Group by week
        weekly_stats = defaultdict(list)
        for exec in completed:
            week_start = exec.started_at - timedelta(days=exec.started_at.weekday())
            week_key = week_start.strftime("%Y-W%W")
            weekly_stats[week_key].append(exec)

        if len(weekly_stats) > 1:
            print(
                f"{'Week':<12} {'Count':>6} {'Avg Time':>12} {'Avg Throughput':>16} {'Success':>8}"
            )
            print("-" * 65)

            for week_key in sorted(weekly_stats.keys()):
                execs = weekly_stats[week_key]
                count = len(execs)
                avg_duration = statistics.mean([e.elapsed_seconds for e in execs])

                # Calculate average throughput for this week
                week_throughputs = []
                for e in execs:
                    if (
                        e.input_size_bytes
                        and e.elapsed_seconds
                        and e.elapsed_seconds > 0
                    ):
                        mb_per_sec = (
                            e.input_size_bytes / 1024 / 1024
                        ) / e.elapsed_seconds
                        week_throughputs.append(mb_per_sec)

                avg_throughput = (
                    statistics.mean(week_throughputs) if week_throughputs else 0
                )

                # Count successes for this week (all in 'completed' should be successful)
                success_count = sum(1 for e in execs if e.success)
                success_rate = (success_count / count * 100) if count > 0 else 0

                print(
                    f"{week_key:<12} {count:>6} {format_duration(avg_duration):>12} "
                    f"{avg_throughput:>13.2f} MB/s {success_rate:>7.1f}%"
                )

            # Calculate improvement
            first_week = sorted(weekly_stats.keys())[0]
            last_week = sorted(weekly_stats.keys())[-1]

            first_avg = statistics.mean(
                [e.elapsed_seconds for e in weekly_stats[first_week]]
            )
            last_avg = statistics.mean(
                [e.elapsed_seconds for e in weekly_stats[last_week]]
            )

            improvement_pct = (
                ((first_avg - last_avg) / first_avg * 100) if first_avg > 0 else 0
            )

            print()
            print(f"Performance Improvement:")
            print(f"  First Week ({first_week}):  {format_duration(first_avg)}")
            print(f"  Last Week ({last_week}):   {format_duration(last_avg)}")
            if improvement_pct > 0:
                print(f"  Improvement:        {improvement_pct:.1f}% faster ⬆️")
            elif improvement_pct < 0:
                print(f"  Change:             {abs(improvement_pct):.1f}% slower ⬇️")
            else:
                print(f"  Change:             No significant change")

        # Recent performance (last 24 hours)
        print_section("RECENT PERFORMANCE (Last 24 Hours)")

        recent_cutoff = datetime.now() - timedelta(hours=24)
        recent_execs = [e for e in completed if e.started_at >= recent_cutoff]

        if recent_execs:
            recent_durations = [e.elapsed_seconds for e in recent_execs]
            recent_throughputs = []
            for e in recent_execs:
                if e.input_size_bytes and e.elapsed_seconds and e.elapsed_seconds > 0:
                    mb_per_sec = (e.input_size_bytes / 1024 / 1024) / e.elapsed_seconds
                    recent_throughputs.append(mb_per_sec)

            print(f"Jobs Completed:      {len(recent_execs)}")
            print(
                f"Average Duration:    {format_duration(statistics.mean(recent_durations))}"
            )
            if recent_throughputs:
                print(
                    f"Average Throughput:  {statistics.mean(recent_throughputs):.2f} MB/s"
                )
        else:
            print("No executions in the last 24 hours.")

        # Top 5 fastest and slowest jobs
        print_section("TOP PERFORMERS")

        sorted_by_speed = sorted(completed, key=lambda e: e.elapsed_seconds)
        print("Fastest Jobs:")
        for i, exec in enumerate(sorted_by_speed[:5], 1):
            throughput_str = format_throughput(
                exec.input_size_bytes, exec.elapsed_seconds
            )
            print(
                f"  {i}. {format_duration(exec.elapsed_seconds):>10} - {throughput_str:>14} - {exec.title[:50]}"
            )

        print()
        print("Slowest Jobs:")
        for i, exec in enumerate(sorted_by_speed[-5:][::-1], 1):
            throughput_str = format_throughput(
                exec.input_size_bytes, exec.elapsed_seconds
            )
            print(
                f"  {i}. {format_duration(exec.elapsed_seconds):>10} - {throughput_str:>14} - {exec.title[:50]}"
            )

        print_separator()

    finally:
        db.close()


if __name__ == "__main__":
    generate_report()
