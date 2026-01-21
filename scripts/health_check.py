"""
Health check for caption processing outputs.

- Parses application log incrementally (tracks last offset in a state file)
- Collects completed pipeline paths from new log entries
- For each folder referenced, compares expected outputs (.mpg, .srt)
- Reports missing outputs and unprocessed candidates

Usage:
    python scripts/health_check.py --log-file /path/to/app.log \
        --state-file /path/to/health_state.json

Defaults:
    --log-file    ./app.log
    --state-file  ./health_state.json
"""

import argparse
import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple

LOG = logging.getLogger("health_check")

# Regex to extract timestamps and successful pipeline completions
# Match lines with optional [Job ID] prefix before timestamp
TIMESTAMP_RE = re.compile(r"^(?:\[.+?\] )?(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
COMPLETED_RE = re.compile(r"Caption pipeline completed for (?P<path>.+)")


def load_state(state_path: Path) -> int:
    """Load last processed byte offset from state file."""
    if not state_path.exists():
        return 0
    try:
        data = json.loads(state_path.read_text())
        return int(data.get("log_offset", 0))
    except Exception:
        return 0


def save_state(state_path: Path, offset: int) -> None:
    """Persist last processed byte offset and timestamp."""
    payload = {"log_offset": offset, "last_run": datetime.utcnow().isoformat()}
    state_path.write_text(json.dumps(payload, indent=2))


def parse_log(
    log_path: Path, start_offset: int, cutoff_dt: datetime | None
) -> Tuple[Set[Path], int]:
    """Parse log from given offset, returning completed paths and new offset.

    If cutoff_dt is provided, only include entries at or after that timestamp,
    and ignore the state offset (start at beginning).
    """

    completed: Set[Path] = set()
    if not log_path.exists():
        LOG.warning("Log file not found: %s", log_path)
        return completed, start_offset

    # If doing lookback, read from start
    start_pos = 0 if cutoff_dt else start_offset

    with log_path.open("r", encoding="utf-8", errors="ignore") as fh:
        fh.seek(start_pos)
        for line in fh:
            if cutoff_dt:
                ts_match = TIMESTAMP_RE.match(line)
                if not ts_match:
                    continue
                try:
                    ts = datetime.strptime(ts_match.group("ts"), "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    continue
                if ts < cutoff_dt:
                    continue

            match = COMPLETED_RE.search(line)
            if match:
                completed.add(Path(match.group("path")).resolve())

        new_offset = fh.tell()
    return completed, new_offset


def expected_outputs(path: Path) -> Tuple[Path, Path]:
    """Return expected mpg and srt paths for a recording."""
    mpg_path = path.with_suffix(".mpg") if path.suffix else path
    srt_path = mpg_path.with_suffix(".srt")
    return mpg_path, srt_path


def scan_folders(paths: Iterable[Path]) -> Dict[Path, Dict[str, List[str]]]:
    """For each folder, compare processed paths with filesystem."""
    folders: Dict[Path, Dict[str, List[str]]] = defaultdict(
        lambda: {
            "processed_ok": [],
            "missing_outputs": [],
            "unprocessed_candidates": [],
        }
    )

    processed_map: Dict[Path, Set[Path]] = defaultdict(set)
    for p in paths:
        processed_map[p.parent].add(p)

    for folder, proc_paths in processed_map.items():
        if not folder.exists():
            continue

        # Evaluate processed paths
        for p in proc_paths:
            mpg_path, srt_path = expected_outputs(p)
            missing = []
            if not mpg_path.exists():
                missing.append(str(mpg_path.name))
            if not srt_path.exists():
                missing.append(str(srt_path.name))
            if missing:
                folders[folder]["missing_outputs"].append(
                    f"{p.name} -> missing {', '.join(missing)}"
                )
            else:
                folders[folder]["processed_ok"].append(p.name)

        # Identify unprocessed candidates in the same folder
        for mpg in folder.glob("*.mpg"):
            # Skip .orig.mpg files (renamed originals after transcoding)
            if mpg.suffix == ".mpg" and mpg.stem.endswith(".orig"):
                continue
            if mpg in proc_paths:
                continue
            srt = mpg.with_suffix(".srt")
            if not srt.exists():
                folders[folder]["unprocessed_candidates"].append(mpg.name)

    return folders


def summarize(folders: Dict[Path, Dict[str, List[str]]]) -> None:
    """Print a human-readable summary."""
    for folder, data in sorted(folders.items()):
        ok = len(data["processed_ok"])
        missing = data["missing_outputs"]
        unproc = data["unprocessed_candidates"]
        print(f"Folder: {folder}")
        print(f"  Processed OK: {ok}")
        if missing:
            print(f"  Missing outputs ({len(missing)}):")
            for item in missing:
                print(f"    - {item}")
        if unproc:
            print(f"  Unprocessed candidates ({len(unproc)}):")
            for item in unproc:
                print(f"    - {item}")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Health check for captions pipeline")
    parser.add_argument(
        "--log-file", default="/app/logs/app.log", help="Path to application log file"
    )
    parser.add_argument(
        "--state-file",
        default="/app/data/health_state.json",
        help="Path to store last processed log offset",
    )
    parser.add_argument(
        "--lookback-days",
        type=float,
        default=None,
        help="If set, ignore state and analyze log entries from the last N days",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    log_path = Path(args.log_file).resolve()
    state_path = Path(args.state_file).resolve()

    start_offset = load_state(state_path)

    cutoff_dt = None
    if args.lookback_days is not None:
        cutoff_dt = datetime.utcnow() - timedelta(days=args.lookback_days)
        LOG.info(
            "Starting health check with lookback of %.2f days (cutoff %s)",
            args.lookback_days,
            cutoff_dt,
        )
    else:
        LOG.info("Starting health check from offset %d", start_offset)

    completed_paths, new_offset = parse_log(log_path, start_offset, cutoff_dt)
    LOG.info("Found %d completed recordings", len(completed_paths))

    folder_summary = scan_folders(completed_paths)
    summarize(folder_summary)

    save_state(state_path, new_offset)
    LOG.info("Health check complete. Saved offset %d", new_offset)


if __name__ == "__main__":
    main()
