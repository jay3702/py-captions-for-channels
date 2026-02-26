#!/usr/bin/env python3
"""Check for ghost quarantine records (DB records with missing quarantine files).

Usage: docker exec py-captions-for-channels python3 scripts/check_ghost_quarantine.py [--fix]
"""

import sys
from pathlib import Path

from py_captions_for_channels.database import get_db, init_db
from py_captions_for_channels.models import QuarantineItem

fix = "--fix" in sys.argv

init_db()
db = next(get_db())
items = db.query(QuarantineItem).filter(QuarantineItem.status == "quarantined").all()

ghost_ids = []
ok_count = 0
for item in items:
    if not Path(item.quarantine_path).exists():
        ghost_ids.append(item.id)
    else:
        ok_count += 1

print(f"Total quarantined records: {len(items)}")
print(f"  Files present (OK): {ok_count}")
print(f"  Ghost records (missing file): {len(ghost_ids)}")

if fix and ghost_ids:
    for gid in ghost_ids:
        db.query(QuarantineItem).filter(QuarantineItem.id == gid).update(
            {"status": "deleted"}
        )
    db.commit()
    print(f"\nFixed: marked {len(ghost_ids)} ghost records as 'deleted'")
elif ghost_ids and not fix:
    print("\nRun with --fix to mark ghost records as 'deleted'")
