from datetime import datetime

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
