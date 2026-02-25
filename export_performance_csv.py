#!/usr/bin/env python3
import sqlite3
import csv
from datetime import datetime, timedelta
import os

# Support both Linux container and Windows local paths
if os.path.exists("/app/data/py_captions.db"):
    db_path = "/app/data/py_captions.db"
    output_path = "/tmp/performance_4hr_intervals.csv"
else:
    db_path = r"C:\Users\jay\source\repos\py-captions-for-channels\data\py_captions.db"
    output_path = r"C:\Users\jay\source\repos\py-captions-for-channels\performance_4hr_intervals.csv"

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

# Get all successful executions with durations
cursor.execute("""
    SELECT started_at, elapsed_seconds, title
    FROM executions 
    WHERE status='completed' 
      AND success=1 
      AND elapsed_seconds IS NOT NULL 
      AND elapsed_seconds > 0
    ORDER BY started_at
""")
execs = cursor.fetchall()

if not execs:
    print("No execution data found")
    conn.close()
    exit(1)

# Parse and group by 4-hour intervals
first_time = datetime.fromisoformat(execs[0][0])
last_time = datetime.fromisoformat(execs[-1][0])

# Round first_time down to nearest 4-hour mark (0, 4, 8, 12, 16, 20)
hour = (first_time.hour // 4) * 4
interval_start = first_time.replace(hour=hour, minute=0, second=0, microsecond=0)

# Collect data by 4-hour intervals
intervals = {}
current = interval_start

while current <= last_time + timedelta(hours=4):
    interval_end = current + timedelta(hours=4)
    intervals[current] = {"end": interval_end, "durations": [], "titles": []}
    current = interval_end

# Assign each execution to its interval
for started_at, duration, title in execs:
    dt = datetime.fromisoformat(started_at)
    # Find which 4-hour interval this belongs to
    hour = (dt.hour // 4) * 4
    interval_key = dt.replace(hour=hour, minute=0, second=0, microsecond=0)

    if interval_key in intervals:
        intervals[interval_key]["durations"].append(duration)
        intervals[interval_key]["titles"].append(title)

# Write to CSV
with open(output_path, "w", newline="", encoding="utf-8") as csvfile:
    writer = csv.writer(csvfile)

    # Header
    writer.writerow(
        [
            "Interval Start",
            "Interval End",
            "Job Count",
            "Avg Duration (seconds)",
            "Avg Duration (minutes)",
            "Min Duration (seconds)",
            "Max Duration (seconds)",
            "Median Duration (seconds)",
            "Total Processing Time (minutes)",
        ]
    )

    # Data rows
    for start_time in sorted(intervals.keys()):
        data = intervals[start_time]
        durations = data["durations"]

        if durations:  # Only include intervals with data
            avg_dur = sum(durations) / len(durations)
            min_dur = min(durations)
            max_dur = max(durations)
            sorted_durs = sorted(durations)
            median_dur = sorted_durs[len(sorted_durs) // 2]
            total_dur = sum(durations)

            writer.writerow(
                [
                    start_time.strftime("%Y-%m-%d %H:%M:%S"),
                    data["end"].strftime("%Y-%m-%d %H:%M:%S"),
                    len(durations),
                    f"{avg_dur:.1f}",
                    f"{avg_dur/60:.2f}",
                    f"{min_dur:.1f}",
                    f"{max_dur:.1f}",
                    f"{median_dur:.1f}",
                    f"{total_dur/60:.1f}",
                ]
            )

conn.close()

print(f"CSV exported to: {output_path}")
print(
    f"Total intervals with data: {sum(1 for d in intervals.values() if d['durations'])}"
)
print(f"Total jobs: {len(execs)}")
print(
    f"Date range: {first_time.strftime('%Y-%m-%d %H:%M')} to {last_time.strftime('%Y-%m-%d %H:%M')}"
)
