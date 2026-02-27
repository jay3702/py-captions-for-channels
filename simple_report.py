#!/usr/bin/env python3
import sqlite3
from datetime import datetime, timedelta
from collections import defaultdict
import os

# Support both Linux container and Windows local paths
if os.path.exists("/app/data/py_captions.db"):
    db_path = "/app/data/py_captions.db"
else:
    db_path = r"C:\Users\jay\source\repos\py-captions-for-channels\data\py_captions.db"

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

print("=" * 80)
print("  PERFORMANCE METRICS REPORT")
print("=" * 80)
print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

# Total counts
cursor.execute("SELECT COUNT(*) FROM executions")
total = cursor.fetchone()[0]

cursor.execute("SELECT COUNT(*) FROM executions WHERE status='completed' AND success=1")
completed_count = cursor.fetchone()[0]

cursor.execute("SELECT COUNT(*) FROM executions WHERE success=0")
failed_count = cursor.fetchone()[0]

print(f"Total Executions:    {total:,}")
print(f"  Successful:        {completed_count:,}")
print(f"  Failed:            {failed_count:,}")
if total > 0:
    success_rate = (completed_count / total) * 100
    print(f"  Success Rate:      {success_rate:.1f}%")

# Get all successful executions with durations
cursor.execute(
    """
    SELECT started_at, elapsed_seconds, title
    FROM executions 
    WHERE status='completed' AND success=1 AND elapsed_seconds IS NOT NULL AND elapsed_seconds > 0
    ORDER BY started_at
"""
)
execs = cursor.fetchall()

if execs:
    first_time = datetime.fromisoformat(execs[0][0])
    last_time = datetime.fromisoformat(execs[-1][0])
    days = (last_time - first_time).days + 1

    print()
    print(f"Tracking Period:")
    print(f"  First: {first_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Last:  {last_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Days:  {days}")

    durations = [e[1] for e in execs]
    avg_dur = sum(durations) / len(durations)
    median_dur = sorted(durations)[len(durations) // 2]

    print()
    print("Processing Time:")
    print(f"  Average: {avg_dur/60:.1f}m ({avg_dur:.1f}s)")
    print(f"  Median:  {median_dur/60:.1f}m ({median_dur:.1f}s)")
    print(f"  Fastest: {min(durations):.1f}s")
    print(f"  Slowest: {max(durations)/60:.1f}m ({max(durations):.1f}s)")

    # Weekly trends
    weekly = defaultdict(list)
    for started_at, duration, title in execs:
        dt = datetime.fromisoformat(started_at)
        week_start = dt - timedelta(days=dt.weekday())
        week_key = week_start.strftime("%Y-W%W")
        weekly[week_key].append(duration)

    if len(weekly) > 1:
        print()
        print("=" * 80)
        print("  WEEKLY TRENDS")
        print("=" * 80)
        print(f"{'Week':<12} {'Count':>6} {'Avg Time':>12} {'Change':>12}")
        print("-" * 50)

        prev_avg = None
        for week in sorted(weekly.keys()):
            week_durs = weekly[week]
            count = len(week_durs)
            avg = sum(week_durs) / len(week_durs)

            change_str = ""
            if prev_avg:
                change_pct = ((prev_avg - avg) / prev_avg) * 100
                if change_pct > 0:
                    change_str = f"+{change_pct:.1f}%"
                else:
                    change_str = f"{change_pct:.1f}%"

            print(f"{week:<12} {count:>6} {avg/60:>10.1f}m {change_str:>12}")
            prev_avg = avg

        # Calculate overall improvement
        first_week = sorted(weekly.keys())[0]
        last_week = sorted(weekly.keys())[-1]
        first_avg = sum(weekly[first_week]) / len(weekly[first_week])
        last_avg = sum(weekly[last_week]) / len(weekly[last_week])
        improvement = ((first_avg - last_avg) / first_avg) * 100

        print()
        print(f"Overall Performance Change:")
        print(f"  First Week ({first_week}): {first_avg/60:.1f}m")
        print(f"  Last Week ({last_week}):  {last_avg/60:.1f}m")
        if improvement > 0:
            print(f"  Improvement: {improvement:.1f}% FASTER!")
        else:
            print(f"  Change: {abs(improvement):.1f}% slower")

    # Recent performance (last 7 days)
    cutoff = (datetime.now() - timedelta(days=7)).isoformat()
    recent = [(dt, dur, title) for dt, dur, title in execs if dt >= cutoff]
    if recent:
        recent_durs = [e[1] for e in recent]
        recent_avg = sum(recent_durs) / len(recent_durs)
        print()
        print("=" * 80)
        print("  RECENT PERFORMANCE (Last 7 Days)")
        print("=" * 80)
        print(f"Jobs Completed: {len(recent)}")
        print(f"Avg Duration:   {recent_avg/60:.1f}m ({recent_avg:.1f}s)")

    # Top/bottom 5
    sorted_execs = sorted(execs, key=lambda x: x[1])
    print()
    print("=" * 80)
    print("Fastest 5 Jobs:")
    for i, (dt, dur, title) in enumerate(sorted_execs[:5], 1):
        title_short = title[:60] if len(title) > 60 else title
        print(f"  {i}. {dur:>6.1f}s - {title_short}")

    print()
    print("Slowest 5 Jobs:")
    for i, (dt, dur, title) in enumerate(sorted_execs[-5:][::-1], 1):
        title_short = title[:60] if len(title) > 60 else title
        dur_m = dur / 60
        print(f"  {i}. {dur_m:>6.1f}m - {title_short}")

print()
print("=" * 80)
conn.close()
