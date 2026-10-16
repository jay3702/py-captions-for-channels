"""Tests for gpu_slots — cross-instance GPU job slots."""

import fcntl
import multiprocessing
import os
import threading
import time

from py_captions_for_channels.gpu_slots import (
    _is_stale_ticket,
    acquire_gpu_slot,
    belongs_to_other_instance,
)


def _acquire(slot_dir, job, slots=1, **kw):
    return acquire_gpu_slot(
        job, slot_dir=str(slot_dir), slots=slots, poll_seconds=0.02, **kw
    )


def test_slot_is_exclusive_and_released(tmp_path):
    first = _acquire(tmp_path, "job-a", instance="dvr1")
    acquired = threading.Event()
    waits = []

    def second():
        slot = _acquire(tmp_path, "job-b", instance="dvr2", on_wait=waits.append)
        acquired.set()
        slot.release()

    t = threading.Thread(target=second)
    t.start()
    time.sleep(0.2)
    assert not acquired.is_set()
    # The waiter is told who holds the GPU
    assert waits and waits[0] == "dvr1: job-a"

    first.release()
    t.join(timeout=5)
    assert acquired.is_set()


def test_two_slots_allow_two_jobs(tmp_path):
    a = _acquire(tmp_path, "a", slots=2)
    b = _acquire(tmp_path, "b", slots=2)
    assert a.path != b.path
    a.release()
    b.release()


def test_waiters_served_in_arrival_order(tmp_path):
    holder = _acquire(tmp_path, "holder")
    order = []
    threads = []
    for name in ("first", "second", "third"):

        def run(name=name):
            slot = _acquire(tmp_path, name)
            order.append(name)
            time.sleep(0.05)
            slot.release()

        t = threading.Thread(target=run)
        t.start()
        threads.append(t)
        time.sleep(0.1)  # make arrival order unambiguous

    holder.release()
    for t in threads:
        t.join(timeout=5)
    assert order == ["first", "second", "third"]


def test_cancel_while_waiting_returns_none(tmp_path):
    holder = _acquire(tmp_path, "holder")
    canceled = threading.Event()
    result = []

    t = threading.Thread(
        target=lambda: result.append(
            _acquire(tmp_path, "waiter", cancel_check=canceled.is_set)
        )
    )
    t.start()
    time.sleep(0.1)
    canceled.set()
    t.join(timeout=5)
    assert result == [None]
    # The canceled waiter's ticket is gone, so it doesn't block the line
    assert not list(tmp_path.glob("wait-*"))
    holder.release()


def _hold_slot_then_die(slot_dir, ready):
    _acquire(slot_dir, "crashing-job")
    ready.set()
    time.sleep(30)  # killed by the test long before this


def test_slot_freed_when_holder_process_dies(tmp_path):
    ctx = multiprocessing.get_context("fork")
    ready = ctx.Event()
    proc = ctx.Process(target=_hold_slot_then_die, args=(tmp_path, ready))
    proc.start()
    assert ready.wait(10)
    proc.kill()
    proc.join()

    slot = _acquire(tmp_path, "next-job")
    assert slot is not None
    slot.release()


def test_ticket_of_dead_waiter_is_stale(tmp_path):
    ticket = tmp_path / "wait-0001-dvr1-123"
    ticket.write_text("")
    # Nobody holds its lock: the waiter that wrote it is gone
    assert _is_stale_ticket(ticket)

    fh = open(ticket, "w")
    fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
    try:
        assert not _is_stale_ticket(ticket)
    finally:
        fh.close()


def test_belongs_to_other_instance_reads_process_tag(monkeypatch):
    from py_captions_for_channels import gpu_slots

    monkeypatch.setattr(gpu_slots, "instance_tag", lambda: "/data/dvr1")
    # This test process carries no tag: treated as ours (legacy behavior)
    monkeypatch.delenv(gpu_slots.INSTANCE_ENV_VAR, raising=False)
    assert not belongs_to_other_instance(os.getpid())
    # Nonexistent process: nothing to protect
    assert not belongs_to_other_instance(2**22 + 12345)


def test_process_tagged_by_other_instance_is_recognized(monkeypatch):
    import subprocess
    import sys

    from py_captions_for_channels import gpu_slots

    monkeypatch.setattr(gpu_slots, "instance_tag", lambda: "/data/dvr1")
    env = dict(os.environ, **{gpu_slots.INSTANCE_ENV_VAR: "/data/dvr2"})
    other = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(10)"], env=env
    )
    env[gpu_slots.INSTANCE_ENV_VAR] = "/data/dvr1"
    ours = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(10)"], env=env
    )
    try:
        assert belongs_to_other_instance(other.pid)
        assert not belongs_to_other_instance(ours.pid)
    finally:
        other.kill()
        ours.kill()
