import json
from collections import Counter

with open("executions.json") as f:
    response = json.load(f)

data = response.get("executions", [])

print("Jobs with canceling/cancelled status or cancel_requested flag:")
print("-" * 80)
for e in data:
    status = e.get("status")
    cancel_requested = e.get("cancel_requested", False)

    if status in ("canceling", "cancelled") or cancel_requested:
        print(f"ID: {e['id']}")
        print(f"  Status: {status}")
        print(f"  Cancel Requested: {cancel_requested}")
        print(f"  Started: {e.get('started_at', 'N/A')}")
        print(f"  Completed: {e.get('completed_at', 'N/A')}")
        if e.get("error"):
            print(f"  Error: {e['error']}")
        print()

# Count statuses
status_counts = Counter(e["status"] for e in data)
print("\nStatus counts:")
for status, count in status_counts.items():
    print(f"  {status}: {count}")
