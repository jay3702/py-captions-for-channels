#!/usr/bin/env python3
"""Test the system monitor functionality."""

import sys
import time

sys.path.insert(0, ".")

from py_captions_for_channels.system_monitor import SystemMonitor, PipelineTimeline

# Test SystemMonitor
print("Testing System Monitor...")
monitor = SystemMonitor(max_seconds=60)

# Check GPU provider
gpu_info = monitor.get_gpu_provider_info()
print(f"\nGPU Provider: {gpu_info['name']} (Available: {gpu_info['available']})")

# Start monitoring
monitor.start()
print("Monitor started, collecting samples...")

# Collect a few samples
time.sleep(3)

# Get latest
latest = monitor.get_latest()
if latest:
    print(f"\nLatest metrics:")
    print(f"  Timestamp: {latest['timestamp']}")
    print(f"  CPU: {latest['cpu_percent']:.1f}%")
    print(f"  Disk Read: {latest['disk_read_mbps']:.2f} MB/s")
    print(f"  Disk Write: {latest['disk_write_mbps']:.2f} MB/s")
    print(f"  Net RX: {latest['net_recv_mbps']:.2f} Mbps")
    print(f"  Net TX: {latest['net_sent_mbps']:.2f} Mbps")

    if latest["gpu_util_percent"] is not None:
        print(f"  GPU Util: {latest['gpu_util_percent']:.1f}%")
        print(
            f"  GPU Mem: {latest['gpu_mem_used_mb']:.0f} / {latest['gpu_mem_total_mb']:.0f} MB"
        )
    else:
        print("  GPU: Not available")

# Get window
window = monitor.get_window(seconds=10)
print(f"\nCollected {len(window)} samples in last 10 seconds")

# Test PipelineTimeline
print("\n\nTesting Pipeline Timeline...")
timeline = PipelineTimeline(monitor)

timeline.stage_start("validate", "job123", "test_video.mp4")
time.sleep(0.5)
timeline.stage_end("validate", "job123")

timeline.stage_start("transcribe", "job123", "test_video.mp4")
time.sleep(1)

status = timeline.get_status()
print(f"\nPipeline Status:")
print(f"  Active: {status['active']}")
print(f"  Job ID: {status['current_job_id']}")
if status["current_stage"]:
    print(f"  Current Stage: {status['current_stage']['stage']}")
    print(f"  Filename: {status['current_stage']['filename']}")
    print(f"  Elapsed: {status['current_stage']['elapsed']:.1f}s")
print(f"  Completed Stages: {len(status['stages'])}")

timeline.stage_end("transcribe", "job123")
timeline.job_complete("job123")

# Stop monitor
monitor.stop()
print("\n✓ Monitor stopped successfully")
print("\nAll tests passed!")
