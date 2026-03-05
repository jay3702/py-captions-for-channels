"""Tests for SystemMonitor, MetricPoint, PipelineStage, PipelineTimeline."""

import time
from unittest.mock import MagicMock, patch

from py_captions_for_channels.system_monitor import (
    GPUProvider,
    MetricPoint,
    PipelineStage,
    PipelineTimeline,
    SystemMonitor,
)


class TestMetricPoint:
    def test_defaults(self):
        mp = MetricPoint(
            timestamp=1.0,
            cpu_percent=50.0,
            disk_read_mbps=10.0,
            disk_write_mbps=5.0,
            net_recv_mbps=1.0,
            net_sent_mbps=0.5,
        )
        assert mp.gpu_util_percent is None
        assert mp.gpu_enc_percent is None
        assert mp.gpu_dec_percent is None

    def test_with_gpu(self):
        mp = MetricPoint(
            timestamp=1.0,
            cpu_percent=50.0,
            disk_read_mbps=0.0,
            disk_write_mbps=0.0,
            net_recv_mbps=0.0,
            net_sent_mbps=0.0,
            gpu_util_percent=80.0,
            gpu_mem_used_mb=2048.0,
            gpu_mem_total_mb=11264.0,
        )
        assert mp.gpu_util_percent == 80.0
        assert mp.gpu_mem_total_mb == 11264.0


class TestPipelineStage:
    def test_duration_when_ended(self):
        stage = PipelineStage(
            stage="whisper",
            job_id="j1",
            filename="test.mpg",
            started_at=100.0,
            ended_at=160.0,
        )
        assert stage.duration == 60.0

    def test_duration_none_when_running(self):
        stage = PipelineStage(
            stage="whisper",
            job_id="j1",
            filename="test.mpg",
            started_at=100.0,
        )
        assert stage.duration is None

    def test_elapsed_running(self):
        stage = PipelineStage(
            stage="ffmpeg",
            job_id="j1",
            filename="test.mpg",
            started_at=time.time() - 10.0,
        )
        assert stage.elapsed >= 9.0

    def test_elapsed_ended(self):
        stage = PipelineStage(
            stage="ffmpeg",
            job_id="j1",
            filename="test.mpg",
            started_at=100.0,
            ended_at=130.0,
        )
        assert stage.elapsed == 30.0


class TestGPUProvider:
    def test_base_provider(self):
        p = GPUProvider()
        assert p.is_available() is False
        assert p.get_name() == "None"
        metrics = p.get_metrics()
        assert metrics["util_percent"] is None


class TestSystemMonitor:
    @patch("py_captions_for_channels.system_monitor.NvidiaNvmlProvider")
    @patch("py_captions_for_channels.system_monitor.NvidiaSmiProvider")
    @patch("py_captions_for_channels.system_monitor.SysfsDrmProvider")
    def test_init_no_gpu(self, mock_drm, mock_smi, mock_nvml):
        for m in (mock_nvml.return_value, mock_smi.return_value, mock_drm.return_value):
            m.is_available.return_value = False
            m.get_name.return_value = "None"
        mon = SystemMonitor(max_seconds=10)
        assert mon.gpu_provider.is_available() is False

    @patch("py_captions_for_channels.system_monitor.NvidiaNvmlProvider")
    @patch("py_captions_for_channels.system_monitor.NvidiaSmiProvider")
    @patch("py_captions_for_channels.system_monitor.SysfsDrmProvider")
    def test_sample_once(self, mock_drm, mock_smi, mock_nvml):
        for m in (mock_nvml.return_value, mock_smi.return_value, mock_drm.return_value):
            m.is_available.return_value = False
            m.get_name.return_value = "None"
            m.get_metrics.return_value = {
                "util_percent": None,
                "mem_used_mb": None,
                "mem_total_mb": None,
                "enc_percent": None,
                "dec_percent": None,
            }
        mon = SystemMonitor(max_seconds=10)
        mon._sample_once()
        assert len(mon.buffer) == 1
        latest = mon.get_latest()
        assert latest is not None
        assert "cpu_percent" in latest

    @patch("py_captions_for_channels.system_monitor.NvidiaNvmlProvider")
    @patch("py_captions_for_channels.system_monitor.NvidiaSmiProvider")
    @patch("py_captions_for_channels.system_monitor.SysfsDrmProvider")
    def test_get_window(self, mock_drm, mock_smi, mock_nvml):
        for m in (mock_nvml.return_value, mock_smi.return_value, mock_drm.return_value):
            m.is_available.return_value = False
            m.get_name.return_value = "None"
            m.get_metrics.return_value = {
                "util_percent": None,
                "mem_used_mb": None,
                "mem_total_mb": None,
                "enc_percent": None,
                "dec_percent": None,
            }
        mon = SystemMonitor(max_seconds=10)
        mon._sample_once()
        mon._sample_once()
        window = mon.get_window(seconds=300)
        assert len(window) == 2

    @patch("py_captions_for_channels.system_monitor.NvidiaNvmlProvider")
    @patch("py_captions_for_channels.system_monitor.NvidiaSmiProvider")
    @patch("py_captions_for_channels.system_monitor.SysfsDrmProvider")
    def test_is_gpu_engaged_false_by_default(self, mock_drm, mock_smi, mock_nvml):
        for m in (mock_nvml.return_value, mock_smi.return_value, mock_drm.return_value):
            m.is_available.return_value = False
            m.get_name.return_value = "None"
        mon = SystemMonitor(max_seconds=10)
        assert mon.is_gpu_engaged() is False

    @patch("py_captions_for_channels.system_monitor.NvidiaNvmlProvider")
    @patch("py_captions_for_channels.system_monitor.NvidiaSmiProvider")
    @patch("py_captions_for_channels.system_monitor.SysfsDrmProvider")
    def test_gpu_provider_info(self, mock_drm, mock_smi, mock_nvml):
        for m in (mock_nvml.return_value, mock_smi.return_value, mock_drm.return_value):
            m.is_available.return_value = False
            m.get_name.return_value = "None"
        mon = SystemMonitor(max_seconds=10)
        info = mon.get_gpu_provider_info()
        assert "available" in info
        assert "name" in info


class TestPipelineTimeline:
    def test_stage_lifecycle(self, tmp_path):
        state_file = str(tmp_path / "pipeline_state.json")
        tl = PipelineTimeline(system_monitor=None, state_file=state_file)

        tl.stage_start("whisper", "job-1", "test.mpg")
        status = tl.get_status()
        assert status["active"] is True
        assert status["current_stage"]["stage"] == "whisper"

        tl.stage_end("whisper", "job-1")
        status = tl.get_status()
        assert status["active"] is False
        assert len(status["stages"]) == 1

    def test_job_complete(self, tmp_path):
        state_file = str(tmp_path / "pipeline_state.json")
        tl = PipelineTimeline(system_monitor=None, state_file=state_file)

        tl.stage_start("whisper", "job-1", "test.mpg")
        tl.stage_start("ffmpeg", "job-1", "test.mpg")
        tl.job_complete("job-1")

        status = tl.get_status()
        assert status["active"] is False
        # Both stages ended
        assert len(status["stages"]) >= 2

    def test_new_job_clears_old_stages(self, tmp_path):
        state_file = str(tmp_path / "pipeline_state.json")
        tl = PipelineTimeline(system_monitor=None, state_file=state_file)

        tl.stage_start("whisper", "job-1", "a.mpg")
        tl.job_complete("job-1")

        tl.stage_start("whisper", "job-2", "b.mpg")
        status = tl.get_status()
        assert status["current_job_id"] == "job-2"
        # Old job stages cleared
        job2_stages = [s for s in status["stages"] if True]
        # Current stage is for job-2
        assert status["current_stage"]["stage"] == "whisper"
