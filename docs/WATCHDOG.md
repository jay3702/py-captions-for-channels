# Watchdog

Detects when the watcher has wedged and alerts and/or restarts the process.

## Why this exists

The polling loop and the manual-process loop each run one pipeline job at a
time via `loop.run_in_executor(...)`. If the subprocess for that job blocks
in uninterruptible sleep (D state) — the classic symptom of a hung NFS/CIFS
mount — even `SIGKILL` cannot clear it, so the executor thread never
returns. The owning loop's heartbeat then goes silent forever and that
queue stops advancing, even though the container itself still looks "up"
(the web UI keeps responding, since it runs on a separate thread).

Two independent mechanisms cover this and the rarer case of the whole
process freezing outright.

## 1. Heartbeat + progress staleness (`ServiceWatchdog`)

Every `WATCHDOG_CHECK_INTERVAL_SECONDS` (default 60s), the watchdog reads:

- the `polling` / `manual` heartbeats (`services/heartbeat_service.py`,
  beaten once per outer loop iteration),
- currently `running` executions, and
- their last progress update (`progress_tracker.py`).

A stale heartbeat alone isn't proof of a hang — it's also what a
legitimately long job looks like, since the beat only happens once per
outer loop iteration. So a loop is only judged **stuck** when its heartbeat
is stale (`WATCHDOG_HEARTBEAT_STALE_SECONDS`, default 90 min) **and** there's
no running job for that loop with progress updated in the last
`WATCHDOG_PROGRESS_FRESH_SECONDS` (default 120s).

Once stuck:

- A throttled `CRITICAL` log line fires (repeats at most every
  `WATCHDOG_ALERT_REPEAT_SECONDS`, default 15 min), plus a POST to
  `WATCHDOG_ALERT_WEBHOOK_URL` if set (`{"text", "level", "app",
  "timestamp"}` — works as-is with generic webhook receivers/automation
  tools like ntfy, Home Assistant, n8n; Discord/Slack need a small adapter).
- If the stuck condition has persisted continuously for
  `WATCHDOG_RESTART_AFTER_SECONDS` (default 3h) and `WATCHDOG_AUTO_RESTART`
  is enabled (default on), the watchdog hard-exits the process
  (`os._exit(1)`). It does **not** use the existing graceful-shutdown
  controller — that only sets a flag the wedged loop would never get a
  chance to check. Docker's `restart: unless-stopped` policy brings the
  container back.

A restart budget (`WATCHDOG_MAX_RESTARTS_PER_DAY`, default 3, and
`WATCHDOG_MIN_RESTART_INTERVAL_SECONDS`, default 30 min) prevents a
persistently recurring cause (e.g. a mount that hangs again immediately)
from crash-looping the container. Once the budget is spent, the watchdog
alerts loudly instead of restarting and asks for manual intervention.

State (last alert time, restart history) is persisted to
`DATA_DIR/watchdog_state.json` so the budget survives restarts. The latest
assessment is written to `DATA_DIR/watchdog_status.json` and surfaced at
`GET /api/status` → `watchdog`.

## 2. Event loop freeze monitor (`EventLoopFreezeMonitor`)

A plain OS thread pings the watcher's asyncio loop via
`call_soon_threadsafe` every few seconds. If the loop doesn't acknowledge
within `WATCHDOG_LOOP_FREEZE_SECONDS` (default 3 min), the loop itself is
wedged — not just one job — and this thread restarts the process
immediately (subject to the same restart budget above). This is
independent of `ServiceWatchdog` on purpose: a task scheduled *on* a frozen
loop would never run to report the freeze.

## Tuning

All thresholds are environment variables — see the `WATCHDOG_*` block in
`.env.example`. If you see false-positive alerts on legitimately slow jobs
(e.g. very large recordings on constrained CPU hardware), raise
`WATCHDOG_HEARTBEAT_STALE_SECONDS` and/or `WATCHDOG_RESTART_AFTER_SECONDS`
rather than disabling the watchdog outright.

To alert only, without ever auto-restarting, set `WATCHDOG_AUTO_RESTART=false`.

## Related fix

While building this, `pipeline.py`'s subprocess cleanup paths were found to
call an unbounded `proc.wait()` after a `SIGKILL` — which blocks forever if
the child is truly stuck in uninterruptible I/O, the same D-state scenario
above. Those now bound the wait and fall back to reaping the process from a
background daemon thread (`_reap_in_background`) instead of blocking the
pipeline's caller, so a single wedged subprocess can no longer wedge the
whole queue by itself.
