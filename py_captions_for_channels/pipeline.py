import subprocess
import logging

LOG = logging.getLogger(__name__)


class PipelineResult:
    """Result of a pipeline execution."""

    def __init__(
        self,
        success: bool,
        returncode: int,
        stdout: str = "",
        stderr: str = "",
        command: str = "",
    ):
        self.success = success
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.command = command


class Pipeline:
    """Executes the captioning workflow.

    Supports dry-run mode for testing and captures stdout/stderr
    for debugging and logging.
    """

    def __init__(self, command_template: str, dry_run: bool = False):
        """Initialize pipeline.

        Args:
            command_template: Command template with {path} placeholder
            dry_run: If True, print commands instead of executing them
        """
        self.command_template = command_template
        self.dry_run = dry_run

    def run(self, event) -> PipelineResult:
        """Execute the caption command for the given event.

        Args:
            event: ProcessingEvent with path, title, etc.

        Returns:
            PipelineResult with execution details
        """
        # Format command with event path
        cmd = self.command_template.format(path=event.path)

        if self.dry_run:
            LOG.info("[DRY-RUN] Would execute: %s", cmd)
            LOG.info("[DRY-RUN] Event: %s (path=%s)", event.title, event.path)
            return PipelineResult(
                success=True,
                returncode=0,
                stdout="",
                stderr="",
                command=cmd,
            )

        LOG.info("Running caption pipeline: %s", cmd)

        try:
            # Execute command and capture output
            proc = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=3600,  # 1 hour timeout
            )

            if proc.returncode != 0:
                LOG.error(
                    "Caption pipeline failed for %s (exit code %d)",
                    event.path,
                    proc.returncode,
                )
                if proc.stderr:
                    LOG.error("stderr: %s", proc.stderr[:500])
                return PipelineResult(
                    success=False,
                    returncode=proc.returncode,
                    stdout=proc.stdout,
                    stderr=proc.stderr,
                    command=cmd,
                )
            else:
                LOG.info("Caption pipeline completed for %s", event.path)
                # Log whisper's output for debugging
                if proc.stdout:
                    LOG.debug("stdout: %s", proc.stdout[-1000:])
                if proc.stderr:
                    LOG.info("whisper output: %s", proc.stderr[-500:])
                return PipelineResult(
                    success=True,
                    returncode=0,
                    stdout=proc.stdout,
                    stderr=proc.stderr,
                    command=cmd,
                )

        except subprocess.TimeoutExpired:
            LOG.error("Caption pipeline timed out for %s", event.path)
            return PipelineResult(
                success=False,
                returncode=-1,
                stdout="",
                stderr="Command timed out after 3600 seconds",
                command=cmd,
            )
        except Exception as e:
            LOG.error("Exception running caption pipeline: %s", e)
            return PipelineResult(
                success=False,
                returncode=-1,
                stdout="",
                stderr=str(e),
                command=cmd,
            )
