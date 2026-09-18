"""
Watchdog for detecting and recovering from a wedged watcher.

The polling and manual-process loops each beat a heartbeat once per
iteration (see ``services/heartbeat_service.py``). If a subprocess spawned
by the pipeline blocks in uninterruptible sleep — the classic symptom of a
hung NFS/CIFS mount, where even SIGKILL cannot clear the process — the
executor thread running it never returns, so that loop's heartbeat goes
silent forever and its queue stops advancing even though the container
looks "up" from the outside.

This module distinguishes that from a merely long-running job (whose
heartbeat is also stale, because the beat only happens once per outer loop
iteration) by cross-checking recent per-job progress updates, then:

  * always logs a throttled CRITICAL alert (and POSTs to an optional
    webhook) once a loop is judged stuck, and
  * optionally self-restarts (hard process exit, relying on the
    ``restart: unless-stopped`` Docker policy to bring the container back)
    once the stuck condition has persisted for a while, with a cooldown and
    a daily cap so a persistently recurring cause doesn't crash-loop.

A second, independent mechanism (`EventLoopFreezeMonitor`) watches for the
asyncio event loop itself going unresponsive — an unambiguous, total
freeze — from a plain OS thread, since a task scheduled on a frozen loop
would never run to report it.
"""

import asyncio
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

LOG = logging.getLogger(__name__)

# Loops we monitor: (heartbeat service name, execution "kind" that indicates
# that loop is actively running a job).
_WATCHED_LOOPS = [
    ("manual", "manual_process"),
    ("polling", "normal"),
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


@dataclass
class LoopAssessment:
    name: str
    heartbeat_age_seconds: Optional[float]
    stuck: bool
    reason: str


@dataclass
class WatchdogAssessment:
    loops: List[LoopAssessment] = field(default_factory=list)

    @property
    def stuck(self) -> bool:
        return any(loop.stuck for loop in self.loops)

    @property
    def max_stuck_age_seconds(self) -> float:
        ages = [
            loop.heartbeat_age_seconds
            for loop in self.loops
            if loop.stuck and loop.heartbeat_age_seconds is not None
        ]
        return max(ages) if ages else 0.0

    @property
    def stuck_loop_names(self) -> List[str]:
        return [loop.name for loop in self.loops if loop.stuck]


def assess_stuck_loops(
    heartbeats: Dict[str, dict],
    running_executions: List[dict],
    progress_by_job: Dict[str, dict],
    heartbeat_stale_seconds: float,
    progress_fresh_seconds: float,
    watched_loops: Optional[List[tuple]] = None,
) -> WatchdogAssessment:
    """Pure decision logic, kept separate from I/O so it's easy to test.

    Args:
        heartbeats: HeartbeatService.get_all_heartbeats() result.
        running_executions: Executions currently with status "running".
        progress_by_job: job_id -> progress dict (has "updated_at").
        heartbeat_stale_seconds: Age past which a heartbeat is "stale".
        progress_fresh_seconds: Progress newer than this counts as "busy".
        watched_loops: Override for testing; defaults to _WATCHED_LOOPS.
    """
    watched_loops = watched_loops if watched_loops is not None else _WATCHED_LOOPS
    now = _now()
    result = WatchdogAssessment()

    running_by_kind: Dict[str, List[dict]] = {}
    for execu in running_executions:
        running_by_kind.setdefault(execu.get("kind"), []).append(execu)

    for heartbeat_name, exec_kind in watched_loops:
        hb = heartbeats.get(heartbeat_name)
        if hb is None:
            # Loop has never beaten (not enabled, or hasn't started yet) —
            # not this check's job; startup health checks cover that case.
            continue

        age = hb.get("age_seconds")
        if age is None or age <= heartbeat_stale_seconds:
            result.loops.append(
                LoopAssessment(heartbeat_name, age, stuck=False, reason="alive")
            )
            continue

        # Heartbeat is stale. That's expected while a legitimately long job
        # runs (the beat only happens once per outer loop iteration), so
        # only call it "stuck" if there's no recent progress to show for it.
        busy = False
        for execu in running_by_kind.get(exec_kind, []):
            prog = progress_by_job.get(execu.get("id"))
            if not prog:
                continue
            updated_dt = _parse_iso(prog.get("updated_at"))
            if updated_dt is None:
                continue
            progress_age = (now - updated_dt).total_seconds()
            if progress_age <= progress_fresh_seconds:
                busy = True
                break

        if busy:
            result.loops.append(
                LoopAssessment(
                    heartbeat_name,
                    age,
                    stuck=False,
                    reason="heartbeat stale but job progress is fresh (busy)",
                )
            )
        else:
            result.loops.append(
                LoopAssessment(
                    heartbeat_name,
                    age,
                    stuck=True,
                    reason=(
                        f"heartbeat stale for {age:.0f}s with no fresh job "
                        "progress to explain it"
                    ),
                )
            )

    return result


class _WatchdogState:
    """Small persisted record of alert/restart history (survives restarts)."""

    def __init__(self, state_file: str):
        self.state_file = state_file
        self.last_alert_at: Optional[str] = None
        self.last_budget_alert_at: Optional[str] = None
        self.restarts: List[str] = []
        self._load()

    def _load(self):
        try:
            with open(self.state_file, "r") as f:
                data = json.load(f)
            self.last_alert_at = data.get("last_alert_at")
            self.last_budget_alert_at = data.get("last_budget_alert_at")
            self.restarts = data.get("restarts", [])
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            tmp_file = self.state_file + ".tmp"
            with open(tmp_file, "w") as f:
                json.dump(
                    {
                        "last_alert_at": self.last_alert_at,
                        "last_budget_alert_at": self.last_budget_alert_at,
                        "restarts": self.restarts,
                    },
                    f,
                )
            os.replace(tmp_file, self.state_file)
        except Exception as e:
            LOG.debug("Failed to persist watchdog state: %s", e)

    def recent_restarts(self, window_seconds: float) -> List[str]:
        now = _now()
        cutoff = now.timestamp() - window_seconds
        kept = []
        for ts in self.restarts:
            dt = _parse_iso(ts)
            if dt and dt.timestamp() >= cutoff:
                kept.append(ts)
        self.restarts = kept
        return kept

    def record_restart(self):
        self.restarts.append(_now().isoformat())
        self.save()


def _send_alert_webhook(url: str, message: str, level: str) -> None:
    if not url:
        return
    try:
        import requests

        requests.post(
            url,
            json={
                "text": message,
                "level": level,
                "app": "py-captions-for-channels",
                "timestamp": _now().isoformat(),
            },
            timeout=5,
        )
    except Exception as e:
        LOG.warning("Watchdog alert webhook failed: %s", e)


class ServiceWatchdog:
    """Periodically checks loop heartbeats/progress and reacts if stuck."""

    def __init__(self):
        from .config import DATA_DIR

        self.state_file = os.path.join(DATA_DIR, "watchdog_state.json")
        self.status_file = os.path.join(DATA_DIR, "watchdog_status.json")
        self._state = _WatchdogState(self.state_file)

    def _write_status(self, assessment: WatchdogAssessment) -> None:
        try:
            os.makedirs(os.path.dirname(self.status_file), exist_ok=True)
            status = {
                "checked_at": _now().isoformat(),
                "stuck": assessment.stuck,
                "loops": [
                    {
                        "name": loop.name,
                        "heartbeat_age_seconds": loop.heartbeat_age_seconds,
                        "stuck": loop.stuck,
                        "reason": loop.reason,
                    }
                    for loop in assessment.loops
                ],
                "recent_restarts": self._state.restarts,
            }
            tmp_file = self.status_file + ".tmp"
            with open(tmp_file, "w") as f:
                json.dump(status, f)
            os.replace(tmp_file, self.status_file)
        except Exception as e:
            LOG.debug("Failed to write watchdog status: %s", e)

    def _gather_inputs(self):
        from .database import get_db
        from .services.heartbeat_service import HeartbeatService
        from .execution_tracker import get_tracker
        from .progress_tracker import get_progress_tracker

        heartbeats = {}
        db_gen = get_db()
        try:
            db = next(db_gen)
            heartbeats = HeartbeatService(db).get_all_heartbeats()
        except Exception as e:
            LOG.debug("Watchdog: failed to read heartbeats: %s", e)
        finally:
            try:
                next(db_gen)
            except StopIteration:
                pass

        try:
            executions = get_tracker().get_executions(limit=200)
            running_executions = [e for e in executions if e.get("status") == "running"]
        except Exception as e:
            LOG.debug("Watchdog: failed to read executions: %s", e)
            running_executions = []

        try:
            progress_by_job = get_progress_tracker().get_all_progress()
        except Exception as e:
            LOG.debug("Watchdog: failed to read progress: %s", e)
            progress_by_job = {}

        return heartbeats, running_executions, progress_by_job

    def check_once(self) -> WatchdogAssessment:
        from .config import (
            WATCHDOG_HEARTBEAT_STALE_SECONDS,
            WATCHDOG_PROGRESS_FRESH_SECONDS,
            WATCHDOG_ALERT_REPEAT_SECONDS,
            WATCHDOG_RESTART_AFTER_SECONDS,
            WATCHDOG_AUTO_RESTART,
        )

        heartbeats, running_executions, progress_by_job = self._gather_inputs()
        assessment = assess_stuck_loops(
            heartbeats,
            running_executions,
            progress_by_job,
            WATCHDOG_HEARTBEAT_STALE_SECONDS,
            WATCHDOG_PROGRESS_FRESH_SECONDS,
        )
        self._write_status(assessment)

        if not assessment.stuck:
            return assessment

        self._maybe_alert(assessment, WATCHDOG_ALERT_REPEAT_SECONDS)

        if WATCHDOG_AUTO_RESTART and (
            assessment.max_stuck_age_seconds >= WATCHDOG_RESTART_AFTER_SECONDS
        ):
            self._attempt_restart(
                reason=(
                    f"loop(s) {assessment.stuck_loop_names} stuck for "
                    f"{assessment.max_stuck_age_seconds:.0f}s "
                    f"(>= WATCHDOG_RESTART_AFTER_SECONDS="
                    f"{WATCHDOG_RESTART_AFTER_SECONDS})"
                )
            )

        return assessment

    def _maybe_alert(self, assessment: WatchdogAssessment, repeat_seconds: float):
        last = _parse_iso(self._state.last_alert_at)
        if last and (_now() - last).total_seconds() < repeat_seconds:
            return

        message = (
            "py-captions-for-channels appears STUCK: "
            f"{assessment.stuck_loop_names}. Details: "
            + "; ".join(
                f"{loop.name}: {loop.reason}" for loop in assessment.loops if loop.stuck
            )
        )
        LOG.critical(message)

        from .config import WATCHDOG_ALERT_WEBHOOK_URL

        if WATCHDOG_ALERT_WEBHOOK_URL:
            threading.Thread(
                target=_send_alert_webhook,
                args=(WATCHDOG_ALERT_WEBHOOK_URL, message, "critical"),
                daemon=True,
                name="watchdog-alert-webhook",
            ).start()

        self._state.last_alert_at = _now().isoformat()
        self._state.save()

    def _restart_budget_available(self) -> bool:
        from .config import (
            WATCHDOG_MAX_RESTARTS_PER_DAY,
            WATCHDOG_MIN_RESTART_INTERVAL_SECONDS,
        )

        recent = self._state.recent_restarts(24 * 3600)
        if len(recent) >= WATCHDOG_MAX_RESTARTS_PER_DAY:
            return False

        if recent:
            last = _parse_iso(recent[-1])
            if (
                last
                and (_now() - last).total_seconds()
                < WATCHDOG_MIN_RESTART_INTERVAL_SECONDS
            ):
                return False

        return True

    def _attempt_restart(self, reason: str) -> None:
        """Restart the process, or alert loudly if the restart budget is spent."""
        if not self._restart_budget_available():
            last = _parse_iso(self._state.last_budget_alert_at)
            if last and (_now() - last).total_seconds() < 3600:
                return  # already screamed about this in the last hour
            message = (
                "py-captions-for-channels is stuck AND has exhausted its "
                f"auto-restart budget (reason: {reason}). Restarting again "
                "automatically would likely crash-loop without fixing the "
                "underlying cause (e.g. a hung network mount) — manual "
                "intervention is needed. Check `docker logs`, the recordings "
                "mount, and consider `docker compose restart`."
            )
            LOG.critical(message)
            from .config import WATCHDOG_ALERT_WEBHOOK_URL

            if WATCHDOG_ALERT_WEBHOOK_URL:
                threading.Thread(
                    target=_send_alert_webhook,
                    args=(WATCHDOG_ALERT_WEBHOOK_URL, message, "critical"),
                    daemon=True,
                    name="watchdog-alert-webhook",
                ).start()
            self._state.last_budget_alert_at = _now().isoformat()
            self._state.save()
            return

        message = f"Watchdog is restarting the process now — {reason}"
        LOG.critical(message)
        from .config import WATCHDOG_ALERT_WEBHOOK_URL

        # Send the webhook synchronously (best-effort, short timeout) since
        # we're about to exit and a background thread wouldn't get to run.
        if WATCHDOG_ALERT_WEBHOOK_URL:
            _send_alert_webhook(WATCHDOG_ALERT_WEBHOOK_URL, message, "critical")

        self._state.record_restart()

        for handler in logging.getLogger().handlers:
            try:
                handler.flush()
            except Exception:
                pass

        # Hard exit: graceful shutdown relies on the wedged loop noticing a
        # flag, which it never will. Docker's `restart: unless-stopped`
        # brings the container back once this process dies.
        os._exit(1)

    async def run_forever(self, check_interval_seconds: float):
        LOG.info("Watchdog started (check interval: %ds)", int(check_interval_seconds))
        while True:
            try:
                self.check_once()
            except Exception as e:
                LOG.error("Watchdog check failed: %s", e, exc_info=True)
            await asyncio.sleep(check_interval_seconds)


class EventLoopFreezeMonitor:
    """Detects a fully wedged asyncio event loop from an independent thread.

    A task scheduled *on* a frozen loop would never run to report the
    freeze, so this pings the loop from the outside via
    ``call_soon_threadsafe`` and fires if the ping goes unacknowledged.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop, freeze_seconds: float):
        self.loop = loop
        self.freeze_seconds = freeze_seconds
        self._last_ack = time.monotonic()
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    def _ack(self):
        with self._lock:
            self._last_ack = time.monotonic()

    def start(self):
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="EventLoopFreezeMonitor"
        )
        self._thread.start()

    def _run(self):
        poll_interval = min(5.0, max(1.0, self.freeze_seconds / 10))
        while True:
            time.sleep(poll_interval)
            try:
                self.loop.call_soon_threadsafe(self._ack)
            except RuntimeError:
                return  # Loop closed — process is shutting down normally

            with self._lock:
                age = time.monotonic() - self._last_ack

            if age > self.freeze_seconds:
                self._on_frozen(age)
                return  # os._exit below ends the process; nothing to loop on

    def _on_frozen(self, age: float):
        LOG.critical(
            "Event loop unresponsive for %.0fs (>= %ds) — the process is "
            "completely wedged, not just a slow job. Restarting.",
            age,
            self.freeze_seconds,
        )
        watchdog = ServiceWatchdog()
        watchdog._attempt_restart(reason=f"event loop frozen for {age:.0f}s")
        # If the restart budget was exhausted, _attempt_restart only alerts
        # and returns rather than exiting — nothing more to do here.


def start_watchdog(loop: asyncio.AbstractEventLoop) -> None:
    """Start both watchdog mechanisms. Call once from the watcher's main()."""
    from .config import WATCHDOG_ENABLED, WATCHDOG_LOOP_FREEZE_SECONDS

    if not WATCHDOG_ENABLED:
        LOG.info("Watchdog disabled (WATCHDOG_ENABLED=false)")
        return

    EventLoopFreezeMonitor(loop, WATCHDOG_LOOP_FREEZE_SECONDS).start()

    from .config import WATCHDOG_CHECK_INTERVAL_SECONDS

    watchdog = ServiceWatchdog()
    asyncio.ensure_future(watchdog.run_forever(WATCHDOG_CHECK_INTERVAL_SECONDS))


def get_watchdog_status() -> dict:
    """Read the last-written watchdog status, for display in the web UI."""
    from .config import DATA_DIR

    status_file = os.path.join(DATA_DIR, "watchdog_status.json")
    try:
        with open(status_file, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"checked_at": None, "stuck": False, "loops": [], "recent_restarts": []}
