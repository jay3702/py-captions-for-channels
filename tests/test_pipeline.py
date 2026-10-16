from datetime import datetime
from unittest.mock import patch

from py_captions_for_channels.pipeline import Pipeline, PipelineResult
from py_captions_for_channels.parser import ProcessingEvent


def test_pipeline_dry_run():
    """Test that dry-run mode doesn't execute commands."""
    pipeline = Pipeline("/usr/local/bin/whisper {path}", dry_run=True)

    event = ProcessingEvent(
        timestamp=datetime.now(),
        path="/tmp/test.mpg",
        title="Test Show",
        source="mock",
    )

    result = pipeline.run(event)

    assert result.success is True
    assert result.returncode == 0
    assert "/usr/local/bin/whisper /tmp/test.mpg" in result.command


def test_pipeline_formats_command():
    """Test that pipeline correctly formats the command template."""
    pipeline = Pipeline("echo {path}", dry_run=True)

    event = ProcessingEvent(
        timestamp=datetime.now(),
        path="/recordings/show.ts",
        title="My Show",
        source="webhook",
    )

    result = pipeline.run(event)

    assert result.command == "echo /recordings/show.ts"


def test_pipeline_executes_command():
    """Test that pipeline actually executes commands when not in dry-run."""
    # Use a simple command that will succeed
    pipeline = Pipeline("echo test", dry_run=False)

    event = ProcessingEvent(
        timestamp=datetime.now(),
        path="/tmp/dummy.mpg",
        title="Test",
        source="mock",
    )

    result = pipeline.run(event)

    assert result.success is True
    assert result.returncode == 0
    assert "test" in result.stdout


def test_pipeline_handles_command_failure():
    """Test that pipeline handles failed commands gracefully."""
    # Use a command that will fail
    pipeline = Pipeline("exit 1", dry_run=False)

    event = ProcessingEvent(
        timestamp=datetime.now(),
        path="/tmp/dummy.mpg",
        title="Test",
        source="mock",
    )

    result = pipeline.run(event)

    assert result.success is False
    assert result.returncode == 1


def test_pipeline_result_attributes():
    """Test that PipelineResult contains all expected attributes."""
    result = PipelineResult(
        success=True,
        returncode=0,
        stdout="output",
        stderr="errors",
        command="echo test",
    )

    assert result.success is True
    assert result.returncode == 0
    assert result.stdout == "output"
    assert result.stderr == "errors"
    assert result.command == "echo test"


def test_pipeline_crash_recovery_on_sigsegv():
    """Test that SIGSEGV (exit 139) is recovered when output file is valid."""
    # exit 139 simulates SIGSEGV
    pipeline = Pipeline("exit 139", dry_run=False)

    event = ProcessingEvent(
        timestamp=datetime.now(),
        path="/tmp/dummy.mpg",
        title="Test SIGSEGV Recovery",
        source="mock",
    )

    # Mock _validate_crash_recovery to return True (output is valid)
    with patch.object(pipeline, "_validate_crash_recovery", return_value=True):
        result = pipeline.run(event)

    assert result.success is True
    assert result.returncode == 0


def test_pipeline_crash_no_recovery_when_output_invalid():
    """Test that SIGSEGV (exit 139) stays failed when output is NOT valid."""
    pipeline = Pipeline("exit 139", dry_run=False)

    event = ProcessingEvent(
        timestamp=datetime.now(),
        path="/tmp/dummy.mpg",
        title="Test SIGSEGV No Recovery",
        source="mock",
    )

    # Mock _validate_crash_recovery to return False (output missing/invalid)
    with patch.object(pipeline, "_validate_crash_recovery", return_value=False):
        result = pipeline.run(event)

    assert result.success is False
    assert result.returncode == 139


def test_pipeline_no_recovery_for_normal_exit_codes():
    """Test that non-signal exit codes (e.g. 1) are NOT recovered."""
    pipeline = Pipeline("exit 1", dry_run=False)

    event = ProcessingEvent(
        timestamp=datetime.now(),
        path="/tmp/dummy.mpg",
        title="Test Normal Failure",
        source="mock",
    )

    # Even if _validate_crash_recovery would return True, it shouldn't
    # be called for exit code 1 (not a signal-based exit)
    with patch.object(pipeline, "_validate_crash_recovery", return_value=True) as mock:
        result = pipeline.run(event)

    assert result.success is False
    assert result.returncode == 1
    mock.assert_not_called()


def _event(name):
    return ProcessingEvent(
        timestamp=datetime.now(), path=f"/tmp/{name}.mpg", title=name, source="mock"
    )


def test_concurrent_runs_take_turns_on_gpu_slot(tmp_path, monkeypatch):
    """The polling and manual loops both call run(); jobs must not overlap."""
    import threading

    from py_captions_for_channels import config

    monkeypatch.setattr(config, "GPU_SLOT_DIR", str(tmp_path / "slots"))
    log = tmp_path / "order.log"
    pipeline = Pipeline(
        f"echo start >> {log}; sleep 0.5; echo end >> {log}", dry_run=False
    )

    threads = [
        threading.Thread(target=pipeline.run, args=(_event(f"show{n}"),))
        for n in range(2)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert log.read_text().split() == ["start", "end", "start", "end"]


def test_cancel_while_waiting_for_gpu(tmp_path, monkeypatch):
    from py_captions_for_channels import config
    from py_captions_for_channels.gpu_slots import acquire_gpu_slot

    monkeypatch.setattr(config, "GPU_SLOT_DIR", str(tmp_path / "slots"))
    holder = acquire_gpu_slot("other instance's job")
    try:
        result = Pipeline("echo should-not-run", dry_run=False).run(
            _event("waiting"), cancel_check=lambda: True
        )
    finally:
        holder.release()

    assert result.success is False
    assert result.returncode == -2  # reported as "Canceled" by the watcher
    assert "should-not-run" not in result.stdout
