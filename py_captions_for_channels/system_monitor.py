"""
Lightweight system monitor for tracking CPU, disk, network, and GPU metrics.
"""

import time
import psutil
import threading
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict
from collections import deque
import logging

logger = logging.getLogger(__name__)


@dataclass
class MetricPoint:
    """Single point-in-time system metrics."""

    timestamp: float
    cpu_percent: float
    disk_read_mbps: float
    disk_write_mbps: float
    net_recv_mbps: float
    net_sent_mbps: float
    gpu_util_percent: Optional[float] = None
    gpu_mem_used_mb: Optional[float] = None
    gpu_mem_total_mb: Optional[float] = None


@dataclass
class PipelineStage:
    """Single pipeline stage timing."""

    stage: str
    job_id: str
    filename: str
    started_at: float
    ended_at: Optional[float] = None
    gpu_engaged: bool = False

    @property
    def duration(self) -> Optional[float]:
        if self.ended_at:
            return self.ended_at - self.started_at
        return None

    @property
    def elapsed(self) -> float:
        """Current elapsed time (even if not ended)."""
        end = self.ended_at if self.ended_at else time.time()
        return end - self.started_at


class GPUProvider:
    """Base class for GPU metric providers."""

    def get_metrics(self) -> Dict[str, Optional[float]]:
        """Returns dict with util_percent, mem_used_mb, mem_total_mb."""
        return {"util_percent": None, "mem_used_mb": None, "mem_total_mb": None}

    def is_available(self) -> bool:
        return False

    def get_name(self) -> str:
        return "None"


class NvidiaNvmlProvider(GPUProvider):
    """NVIDIA GPU metrics via pynvml library."""

    def __init__(self):
        self.available = False
        try:
            import pynvml

            pynvml.nvmlInit()
            self.handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            self.available = True
            self.pynvml = pynvml
            device_name = pynvml.nvmlDeviceGetName(self.handle)
            logger.warning(f"NVIDIA NVML GPU provider initialized: {device_name}")
        except Exception as e:
            logger.warning(f"NVIDIA NVML not available: {type(e).__name__}: {e}")

    def is_available(self) -> bool:
        return self.available

    def get_name(self) -> str:
        return "NVIDIA NVML"

    def get_metrics(self) -> Dict[str, Optional[float]]:
        if not self.available:
            return super().get_metrics()

        try:
            util = self.pynvml.nvmlDeviceGetUtilizationRates(self.handle)
            mem_info = self.pynvml.nvmlDeviceGetMemoryInfo(self.handle)

            return {
                "util_percent": float(util.gpu),
                "mem_used_mb": mem_info.used / (1024 * 1024),
                "mem_total_mb": mem_info.total / (1024 * 1024),
            }
        except Exception as e:
            logger.warning(f"Failed to get NVIDIA NVML metrics: {e}")
            return super().get_metrics()


class NvidiaSmiProvider(GPUProvider):
    """NVIDIA GPU metrics via nvidia-smi command."""

    def __init__(self):
        self.available = False
        try:
            import subprocess

            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=utilization.gpu,memory.used,memory.total",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if result.returncode == 0:
                self.available = True
                logger.info("NVIDIA SMI GPU provider initialized")
        except Exception as e:
            logger.debug(f"NVIDIA SMI not available: {e}")

    def is_available(self) -> bool:
        return self.available

    def get_name(self) -> str:
        return "NVIDIA SMI"

    def get_metrics(self) -> Dict[str, Optional[float]]:
        if not self.available:
            return super().get_metrics()

        try:
            import subprocess

            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=utilization.gpu,memory.used,memory.total",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if result.returncode == 0:
                parts = result.stdout.strip().split(",")
                return {
                    "util_percent": float(parts[0].strip()),
                    "mem_used_mb": float(parts[1].strip()),
                    "mem_total_mb": float(parts[2].strip()),
                }
        except Exception as e:
            logger.warning(f"Failed to get NVIDIA SMI metrics: {e}")

        return super().get_metrics()


class SysfsDrmProvider(GPUProvider):
    """AMD/Intel GPU metrics via sysfs DRM (best effort)."""

    def __init__(self):
        self.available = False
        self.card_path = None

        try:
            import os

            # Try to find a DRM card
            for card in ["card0", "card1"]:
                path = f"/sys/class/drm/{card}/device"
                if os.path.exists(path):
                    self.card_path = path
                    self.available = True
                    logger.info(f"DRM GPU provider initialized for {card}")
                    break
        except Exception as e:
            logger.debug(f"DRM sysfs not available: {e}")

    def is_available(self) -> bool:
        return self.available

    def get_name(self) -> str:
        return "DRM sysfs"

    def get_metrics(self) -> Dict[str, Optional[float]]:
        if not self.available:
            return super().get_metrics()

        # This is best-effort; sysfs GPU metrics vary widely by vendor/driver
        # Return placeholder for now
        return super().get_metrics()


class SystemMonitor:
    """Lightweight system metrics collector with ring buffer."""

    def __init__(self, max_seconds: int = 600):
        self.max_seconds = max_seconds
        self.buffer: deque[MetricPoint] = deque(maxlen=max_seconds)
        self.lock = threading.Lock()
        self.running = False
        self.sample_thread: Optional[threading.Thread] = None

        # Initialize GPU provider
        self.gpu_provider = self._init_gpu_provider()

        # Disk/network baselines for delta calculation
        self.prev_disk = psutil.disk_io_counters()
        self.prev_net = psutil.net_io_counters()
        self.prev_time = time.time()

        # GPU engagement tracking
        self.gpu_util_history: deque[float] = deque(maxlen=10)

    def _init_gpu_provider(self) -> GPUProvider:
        """Try GPU providers in order of preference."""
        providers = [NvidiaNvmlProvider(), NvidiaSmiProvider(), SysfsDrmProvider()]

        for provider in providers:
            if provider.is_available():
                logger.warning(f"Selected GPU provider: {provider.get_name()}")
                return provider

        logger.warning("No GPU provider available - GPU monitoring disabled")
        return GPUProvider()

    def get_gpu_provider_info(self) -> Dict[str, Any]:
        """Get GPU provider status."""
        return {
            "available": self.gpu_provider.is_available(),
            "name": self.gpu_provider.get_name(),
        }

    def start(self):
        """Start the sampling thread."""
        if self.running:
            return

        self.running = True
        self.sample_thread = threading.Thread(target=self._sample_loop, daemon=True)
        self.sample_thread.start()
        logger.info("System monitor started")

    def stop(self):
        """Stop the sampling thread."""
        self.running = False
        if self.sample_thread:
            self.sample_thread.join(timeout=2)
        logger.info("System monitor stopped")

    def _sample_loop(self):
        """Main sampling loop (1 Hz)."""
        while self.running:
            try:
                self._sample_once()
            except Exception as e:
                logger.error(f"Error sampling metrics: {e}")
            time.sleep(1.0)

    def _sample_once(self):
        """Collect one metric sample."""
        now = time.time()

        # CPU
        cpu_percent = psutil.cpu_percent(interval=0)

        # Disk I/O
        disk = psutil.disk_io_counters()
        disk_delta_time = now - self.prev_time
        disk_read_mbps = 0.0
        disk_write_mbps = 0.0

        if disk and self.prev_disk and disk_delta_time > 0:
            bytes_read = disk.read_bytes - self.prev_disk.read_bytes
            bytes_written = disk.write_bytes - self.prev_disk.write_bytes
            disk_read_mbps = (bytes_read / disk_delta_time) / (1024 * 1024)
            disk_write_mbps = (bytes_written / disk_delta_time) / (1024 * 1024)

        # Network I/O
        net = psutil.net_io_counters()
        net_recv_mbps = 0.0
        net_sent_mbps = 0.0

        if net and self.prev_net and disk_delta_time > 0:
            bytes_recv = net.bytes_recv - self.prev_net.bytes_recv
            bytes_sent = net.bytes_sent - self.prev_net.bytes_sent
            net_recv_mbps = (bytes_recv * 8 / disk_delta_time) / (1024 * 1024)  # Mbps
            net_sent_mbps = (bytes_sent * 8 / disk_delta_time) / (1024 * 1024)

        # GPU
        gpu_metrics = self.gpu_provider.get_metrics()

        # Track GPU utilization history
        if gpu_metrics["util_percent"] is not None:
            self.gpu_util_history.append(gpu_metrics["util_percent"])

        # Create metric point
        point = MetricPoint(
            timestamp=now,
            cpu_percent=cpu_percent,
            disk_read_mbps=disk_read_mbps,
            disk_write_mbps=disk_write_mbps,
            net_recv_mbps=net_recv_mbps,
            net_sent_mbps=net_sent_mbps,
            gpu_util_percent=gpu_metrics["util_percent"],
            gpu_mem_used_mb=gpu_metrics["mem_used_mb"],
            gpu_mem_total_mb=gpu_metrics["mem_total_mb"],
        )

        # Add to buffer
        with self.lock:
            self.buffer.append(point)

        # Update baselines
        self.prev_disk = disk
        self.prev_net = net
        self.prev_time = now

    def get_latest(self) -> Optional[Dict[str, Any]]:
        """Get the most recent metric point."""
        with self.lock:
            if not self.buffer:
                return None
            point = self.buffer[-1]
            return asdict(point)

    def get_window(self, seconds: int = 300) -> List[Dict[str, Any]]:
        """Get metrics for the last N seconds."""
        cutoff = time.time() - seconds

        with self.lock:
            points = [p for p in self.buffer if p.timestamp >= cutoff]
            return [asdict(p) for p in points]

    def is_gpu_engaged(self) -> bool:
        """Check if GPU is actively engaged (>10% util for 3+ consecutive samples)."""
        if len(self.gpu_util_history) < 3:
            return False

        recent = list(self.gpu_util_history)[-3:]
        return all(u > 10.0 for u in recent)


class PipelineTimeline:
    """Track pipeline stage timing and GPU engagement with file-based persistence."""

    def __init__(
        self,
        system_monitor: Optional[SystemMonitor] = None,
        state_file: str = "/app/data/pipeline_state.json",
    ):
        self.system_monitor = system_monitor
        self.state_file = state_file
        self.lock = threading.Lock()
        self.current_stage: Optional[PipelineStage] = None
        self.completed_stages: List[PipelineStage] = []
        self.current_job_id: Optional[str] = None

    def _save_state(self):
        """Persist pipeline state to file for cross-process sharing."""
        try:
            state = {
                "current_job_id": self.current_job_id,
                "current_stage": None,
                "completed_stages": [],
            }

            if self.current_stage:
                state["current_stage"] = {
                    "stage": self.current_stage.stage,
                    "job_id": self.current_stage.job_id,
                    "filename": self.current_stage.filename,
                    "started_at": self.current_stage.started_at,
                    "ended_at": self.current_stage.ended_at,
                    "gpu_engaged": self.current_stage.gpu_engaged,
                }

            state["completed_stages"] = [
                {
                    "stage": s.stage,
                    "job_id": s.job_id,
                    "filename": s.filename,
                    "started_at": s.started_at,
                    "ended_at": s.ended_at,
                    "gpu_engaged": s.gpu_engaged,
                }
                for s in self.completed_stages
            ]

            import os
            import json

            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            with open(self.state_file, "w") as f:
                json.dump(state, f)
        except Exception:
            pass  # Don't let persistence errors break pipeline execution

    def _load_state(self):
        """Load pipeline state from file."""
        try:
            import json

            with open(self.state_file, "r") as f:
                state = json.load(f)

            self.current_job_id = state.get("current_job_id")

            current = state.get("current_stage")
            if current:
                self.current_stage = PipelineStage(
                    stage=current["stage"],
                    job_id=current["job_id"],
                    filename=current["filename"],
                    started_at=current["started_at"],
                )
                self.current_stage.ended_at = current.get("ended_at")
                self.current_stage.gpu_engaged = current.get("gpu_engaged", False)

            # Only load completed stages that match current job
            # This prevents showing stale data from previous jobs
            self.completed_stages = [
                PipelineStage(
                    stage=s["stage"],
                    job_id=s["job_id"],
                    filename=s["filename"],
                    started_at=s["started_at"],
                )
                for s in state.get("completed_stages", [])
                if s.get("job_id") == self.current_job_id
            ]
            for i, s in enumerate(
                [
                    s
                    for s in state.get("completed_stages", [])
                    if s.get("job_id") == self.current_job_id
                ]
            ):
                if i < len(self.completed_stages):
                    self.completed_stages[i].ended_at = s.get("ended_at")
                    self.completed_stages[i].gpu_engaged = s.get("gpu_engaged", False)

        except (FileNotFoundError, json.JSONDecodeError):
            pass  # Start fresh if no valid state file

    def stage_start(self, stage: str, job_id: str, filename: str):
        """Start tracking a new pipeline stage."""
        with self.lock:
            # If starting a new job, clear old completed stages
            if self.current_job_id != job_id:
                self.completed_stages = []

            # End previous stage if any
            if self.current_stage and not self.current_stage.ended_at:
                self.current_stage.ended_at = time.time()
                if self.system_monitor:
                    self.current_stage.gpu_engaged = (
                        self.system_monitor.is_gpu_engaged()
                    )
                self.completed_stages.append(self.current_stage)

            # Start new stage
            self.current_stage = PipelineStage(
                stage=stage, job_id=job_id, filename=filename, started_at=time.time()
            )
            self.current_job_id = job_id
            self._save_state()

    def stage_end(self, stage: str, job_id: str):
        """End the current stage."""
        with self.lock:
            if (
                self.current_stage
                and self.current_stage.stage == stage
                and self.current_stage.job_id == job_id
            ):
                self.current_stage.ended_at = time.time()
                if self.system_monitor:
                    self.current_stage.gpu_engaged = (
                        self.system_monitor.is_gpu_engaged()
                    )
                self.completed_stages.append(self.current_stage)
                self.current_stage = None
                self._save_state()

    def job_complete(self, job_id: str):
        """Mark entire job as complete."""
        with self.lock:
            if self.current_stage and self.current_stage.job_id == job_id:
                self.current_stage.ended_at = time.time()
                if self.system_monitor:
                    self.current_stage.gpu_engaged = (
                        self.system_monitor.is_gpu_engaged()
                    )
                self.completed_stages.append(self.current_stage)
                self.current_stage = None

            # Clear completed stages for this job older than 5 minutes
            cutoff = time.time() - 300
            self.completed_stages = [
                s
                for s in self.completed_stages
                if s.started_at >= cutoff or s.job_id == job_id
            ]

            # Keep current_job_id set so completed stages remain visible
            # It will be cleared when the next job starts in stage_start()

            self._save_state()

    def get_status(self) -> Dict[str, Any]:
        """Get current pipeline status from file (cross-process visibility)."""
        with self.lock:
            # Load latest state from file (updated by subprocess)
            self._load_state()

            # Auto-clear completed jobs older than 30 seconds
            if self.current_job_id and not self.current_stage and self.completed_stages:
                # Find the last completed stage for this job
                job_stages = [
                    s for s in self.completed_stages if s.job_id == self.current_job_id
                ]
                if job_stages:
                    last_stage = max(job_stages, key=lambda s: s.ended_at)
                    completion_age = time.time() - last_stage.ended_at
                    if completion_age > 30:  # 30 seconds
                        # Clear the completed job
                        old_job_id = self.current_job_id
                        self.current_job_id = None
                        self.completed_stages = [
                            s for s in self.completed_stages if s.job_id != old_job_id
                        ]
                        self._save_state()

            result = {
                "active": self.current_stage is not None,
                "current_job_id": self.current_job_id,
                "current_stage": None,
                "stages": [],
            }

            if self.current_stage:
                result["current_stage"] = {
                    "stage": self.current_stage.stage,
                    "filename": self.current_stage.filename,
                    "elapsed": self.current_stage.elapsed,
                    "gpu_engaged": (
                        self.system_monitor.is_gpu_engaged()
                        if self.system_monitor
                        else False
                    ),
                }

            # CRITICAL: Only include completed stages for the CURRENT job
            # This prevents showing stale data from previous jobs
            if self.current_job_id:
                job_stages = [
                    s for s in self.completed_stages if s.job_id == self.current_job_id
                ]
                result["stages"] = [
                    {
                        "stage": s.stage,
                        "duration": s.duration,
                        "gpu_engaged": s.gpu_engaged,
                        "ended_at": s.ended_at,  # For frontend age calculation
                    }
                    for s in job_stages
                ]

            return result


# Global singletons (initialized in web_app.py)
_system_monitor: Optional[SystemMonitor] = None
_pipeline_timeline: Optional[PipelineTimeline] = None


def get_system_monitor() -> SystemMonitor:
    """Get the system monitor singleton."""
    global _system_monitor
    if _system_monitor is None:
        _system_monitor = SystemMonitor()
    return _system_monitor


def get_pipeline_timeline() -> PipelineTimeline:
    """Get the pipeline timeline singleton."""
    global _pipeline_timeline
    if _pipeline_timeline is None:
        _pipeline_timeline = PipelineTimeline(get_system_monitor())
    return _pipeline_timeline
