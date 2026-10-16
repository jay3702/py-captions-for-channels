"""
GPU job slots shared across independent instances.

Several Channels DVRs can share one GPU machine by running one instance of
this service per DVR on that machine. The instances never talk to each
other; instead every caption job takes one of GPU_SLOTS slot files in
GPU_SLOT_DIR before it starts, and gives it back when it finishes. Pointing
every instance's GPU_SLOT_DIR at the same host directory makes them take
turns on the GPU. Left at its default (inside DATA_DIR) it still serializes
the jobs of a single instance — whose polling and manual-process loops would
otherwise run jobs side by side.

Slots are flock()ed files, so a slot held by a process that dies (crash,
container kill) is freed by the kernel — there is no stale-lock cleanup.
Waiters take a ticket file (also flock()ed while they wait) and only the
oldest GPU_SLOTS live tickets may take a free slot, so jobs are served in
arrival order across instances instead of whichever instance happens to
poll first after a release (which would let a busy instance starve the
others).

flock() is only reliable on a local filesystem shared by one kernel: the
slot directory must live on the GPU host itself, not on an NFS/SMB mount.
"""

import fcntl
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from .logging.structured_logger import get_logger

LOG = get_logger(__name__)

POLL_SECONDS = 2.0
# Refresh the "waiting" callback at least this often, so a long wait keeps
# job progress fresh and the watchdog doesn't mistake it for a wedged loop.
WAIT_NOTIFY_SECONDS = 15.0


# Set on every caption job's environment; its value identifies the instance
# (by data directory, which is necessarily unique per instance).
INSTANCE_ENV_VAR = "PY_CAPTIONS_INSTANCE"


def instance_tag() -> str:
    from . import config

    return os.path.abspath(config.DATA_DIR)


def belongs_to_other_instance(pid: int) -> bool:
    """True if pid is a caption job started by a different instance.

    Untagged processes (from versions before tagging, or unreadable) are
    treated as ours, keeping the old cleanup behavior for them.
    """
    try:
        with open(f"/proc/{pid}/environ", "rb") as f:
            env = f.read().split(b"\0")
    except OSError:
        return False
    prefix = f"{INSTANCE_ENV_VAR}=".encode()
    for entry in env:
        if entry.startswith(prefix):
            return entry[len(prefix) :].decode(errors="replace") != instance_tag()
    return False


class GpuSlot:
    """A held slot. Call release() when the job finishes."""

    def __init__(self, fh, path: Path):
        self._fh = fh
        self.path = path

    def release(self) -> None:
        if self._fh is None:
            return
        try:
            self._fh.seek(0)
            self._fh.truncate()
            self._fh.flush()
        except OSError:
            pass
        try:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        finally:
            self._fh.close()
            self._fh = None


def _try_lock(path: Path):
    """Open path and take an exclusive lock without blocking, or return None."""
    fh = open(path, "a+")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fh
    except BlockingIOError:
        fh.close()
        return None


def _is_stale_ticket(path: Path) -> bool:
    """A ticket whose lock nobody holds belongs to a waiter that died."""
    try:
        fh = _try_lock(path)
    except FileNotFoundError:
        return True
    if fh is None:
        return False
    fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    fh.close()
    return True


def _my_turn(slot_dir: Path, my_ticket: str, slots: int) -> bool:
    live = []
    for ticket in sorted(p.name for p in slot_dir.glob("wait-*")):
        if ticket != my_ticket and _is_stale_ticket(slot_dir / ticket):
            try:
                (slot_dir / ticket).unlink()
            except FileNotFoundError:
                pass
            continue
        live.append(ticket)
    return my_ticket in live and live.index(my_ticket) < slots


def describe_holders(slot_dir: Path, slots: int) -> str:
    """Human-readable summary of who holds the slots, for the UI."""
    holders = []
    for i in range(slots):
        try:
            info = json.loads((slot_dir / f"slot-{i}.lock").read_text() or "{}")
        except (OSError, ValueError):
            info = {}
        if info:
            holders.append(f"{info.get('instance', '?')}: {info.get('job', '?')}")
    return "; ".join(holders) or "another job"


def acquire_gpu_slot(
    job_id: str,
    cancel_check: Optional[Callable[[], bool]] = None,
    on_wait: Optional[Callable[[str], None]] = None,
    slot_dir: Optional[str] = None,
    slots: Optional[int] = None,
    instance: Optional[str] = None,
    poll_seconds: float = POLL_SECONDS,
) -> Optional[GpuSlot]:
    """Block until a GPU slot is free and take it.

    on_wait(holders) is called while waiting (on first wait, whenever the
    holders change, and at least every WAIT_NOTIFY_SECONDS). Returns None if
    cancel_check() becomes true while waiting.
    """
    from . import config

    slot_dir = Path(slot_dir or config.GPU_SLOT_DIR)
    slots = max(1, slots or config.GPU_SLOTS)
    instance = instance or config.INSTANCE_NAME
    slot_dir.mkdir(parents=True, exist_ok=True)

    safe_instance = re.sub(r"[^A-Za-z0-9_.-]", "_", instance)[:40]
    ticket_name = f"wait-{time.time_ns():020d}-{safe_instance}-{os.getpid()}"
    ticket_path = slot_dir / ticket_name
    # Lock before the ticket becomes visible under its wait-* name, so other
    # waiters can never see it unlocked and discard it as stale.
    tmp_path = slot_dir / f"tmp-{ticket_name}"
    ticket = open(tmp_path, "w")
    fcntl.flock(ticket.fileno(), fcntl.LOCK_EX)
    os.rename(tmp_path, ticket_path)
    last_notice, last_notice_at = None, 0.0
    try:
        while True:
            if _my_turn(slot_dir, ticket_name, slots):
                for i in range(slots):
                    path = slot_dir / f"slot-{i}.lock"
                    fh = _try_lock(path)
                    if fh is None:
                        continue
                    fh.seek(0)
                    fh.truncate()
                    json.dump(
                        {
                            "instance": instance,
                            "job": job_id,
                            "pid": os.getpid(),
                            "since": datetime.now(timezone.utc).isoformat(),
                        },
                        fh,
                    )
                    fh.flush()
                    if last_notice is not None:
                        LOG.info("GPU slot acquired after waiting: %s", job_id)
                    return GpuSlot(fh, path)
            if cancel_check and cancel_check():
                LOG.info("Canceled while waiting for a GPU slot: %s", job_id)
                return None
            holders = describe_holders(slot_dir, slots)
            now = time.monotonic()
            if holders != last_notice or now - last_notice_at >= WAIT_NOTIFY_SECONDS:
                if last_notice is None:
                    LOG.info("Waiting for GPU slot (in use by %s): %s", holders, job_id)
                if on_wait:
                    try:
                        on_wait(holders)
                    except Exception as e:
                        LOG.debug("GPU slot wait callback failed: %s", e)
                last_notice, last_notice_at = holders, now
            time.sleep(poll_seconds)
    finally:
        try:
            fcntl.flock(ticket.fileno(), fcntl.LOCK_UN)
        finally:
            ticket.close()
            try:
                ticket_path.unlink()
            except FileNotFoundError:
                pass
