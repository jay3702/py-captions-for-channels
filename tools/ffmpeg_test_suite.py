#!/usr/bin/env python3
"""
FFmpeg Caption-Mux Test Suite

A self-contained benchmark harness for testing different ffmpeg conversion/muxing
strategies when embedding captions into video files.

Usage:
    python -m tools.ffmpeg_test_suite \
        --input-video /path/to/test.mpg \
        --input-srt /path/to/test.srt \
        --out-dir /path/to/out \
        --report-json report.json \
        --report-csv report.csv

Purpose:
    Tests multiple ffmpeg variants to find optimal encoding/muxing strategies
    for Channels DVR recordings with embedded captions. Measures performance
    and compatibility without requiring actual playback testing.

Author: py-captions-for-channels project
License: MIT
"""

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable


@dataclass
class FFmpegCapabilities:
    """Detected ffmpeg/ffprobe capabilities."""

    ffmpeg_version: str
    ffprobe_version: str
    has_nvenc: bool
    has_cuvid: bool
    has_yadif_cuda: bool
    has_mpeg2_cuvid: bool


@dataclass
class Variant:
    """Defines a single ffmpeg test variant."""

    name: str
    description: str
    ffmpeg_args_builder: Callable[[Path, Path, Path, FFmpegCapabilities], List[str]]
    requires_h264_or_hevc: bool = False
    requires_nvenc: bool = False
    requires_cuvid: bool = False
    skip_reason: Optional[str] = None


@dataclass
class TestResult:
    """Results from running a single test variant."""

    name: str
    description: str
    command_line: List[str]
    start_time: str
    end_time: str
    elapsed_seconds: float
    exit_code: int
    output_path: str
    file_size_bytes: int
    skipped: bool = False
    skip_reason: Optional[str] = None

    # ffprobe results
    container_format: Optional[str] = None
    duration: Optional[float] = None
    video_codec: Optional[str] = None
    audio_codec: Optional[str] = None
    subtitle_codec: Optional[str] = None
    video_width: Optional[int] = None
    video_height: Optional[int] = None
    video_fps: Optional[str] = None
    field_order: Optional[str] = None
    audio_channels: Optional[int] = None
    stream_counts: Dict[str, int] = field(default_factory=dict)
    probe_error: Optional[str] = None

    # Log excerpts
    stderr_first_lines: List[str] = field(default_factory=list)
    stderr_last_lines: List[str] = field(default_factory=list)


def check_command_exists(command: str) -> bool:
    """Check if a command exists in PATH."""
    try:
        subprocess.run(
            [command, "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        return True
    except FileNotFoundError:
        return False


def get_version(command: str) -> str:
    """Get version string from ffmpeg/ffprobe."""
    try:
        result = subprocess.run(
            [command, "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        first_line = result.stdout.split("\n")[0]
        return first_line.strip()
    except Exception as e:
        return f"unknown ({e})"


def detect_ffmpeg_capabilities() -> FFmpegCapabilities:
    """Detect available ffmpeg encoders, decoders, and filters."""
    # Get versions
    ffmpeg_version = get_version("ffmpeg")
    ffprobe_version = get_version("ffprobe")

    # Check for NVENC encoder
    has_nvenc = False
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        has_nvenc = "h264_nvenc" in result.stdout
    except Exception:
        pass

    # Check for CUVID decoders
    has_cuvid = False
    has_mpeg2_cuvid = False
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-decoders"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        has_cuvid = "cuvid" in result.stdout
        has_mpeg2_cuvid = "mpeg2_cuvid" in result.stdout
    except Exception:
        pass

    # Check for yadif_cuda filter
    has_yadif_cuda = False
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-filters"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        has_yadif_cuda = "yadif_cuda" in result.stdout
    except Exception:
        pass

    return FFmpegCapabilities(
        ffmpeg_version=ffmpeg_version,
        ffprobe_version=ffprobe_version,
        has_nvenc=has_nvenc,
        has_cuvid=has_cuvid,
        has_yadif_cuda=has_yadif_cuda,
        has_mpeg2_cuvid=has_mpeg2_cuvid,
    )


def probe_input_codec(input_path: Path) -> Optional[str]:
    """Probe input video codec using ffprobe."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_streams",
                "-select_streams",
                "v:0",
                str(input_path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
        data = json.loads(result.stdout)
        if data.get("streams"):
            codec = data["streams"][0].get("codec_name", "").lower()
            return codec
        return None
    except Exception:
        return None


def probe_output(output_path: Path) -> Dict[str, Any]:
    """
    Probe output file using ffprobe and return structured metadata.

    Args:
        output_path: Path to output file

    Returns:
        Dictionary with container format, codecs, streams, etc.
    """
    result = {
        "container_format": None,
        "duration": None,
        "video_codec": None,
        "audio_codec": None,
        "subtitle_codec": None,
        "video_width": None,
        "video_height": None,
        "video_fps": None,
        "field_order": None,
        "audio_channels": None,
        "stream_counts": {},
        "probe_error": None,
    }

    if not output_path.exists():
        result["probe_error"] = "File does not exist"
        return result

    try:
        # Run ffprobe
        probe_result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(output_path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )

        data = json.loads(probe_result.stdout)

        # Extract format info
        if "format" in data:
            result["container_format"] = data["format"].get("format_name")
            duration_str = data["format"].get("duration")
            if duration_str:
                try:
                    result["duration"] = float(duration_str)
                except ValueError:
                    pass

        # Count streams by type
        stream_counts = {"video": 0, "audio": 0, "subtitle": 0, "data": 0}

        # Extract stream info
        if "streams" in data:
            for stream in data["streams"]:
                codec_type = stream.get("codec_type")
                if codec_type:
                    stream_counts[codec_type] = stream_counts.get(codec_type, 0) + 1

                if codec_type == "video" and result["video_codec"] is None:
                    result["video_codec"] = stream.get("codec_name")
                    result["video_width"] = stream.get("width")
                    result["video_height"] = stream.get("height")
                    result["field_order"] = stream.get("field_order")

                    # Get FPS
                    avg_fps = stream.get("avg_frame_rate", "")
                    r_fps = stream.get("r_frame_rate", "")
                    result["video_fps"] = avg_fps or r_fps

                elif codec_type == "audio" and result["audio_codec"] is None:
                    result["audio_codec"] = stream.get("codec_name")
                    result["audio_channels"] = stream.get("channels")

                elif codec_type == "subtitle" and result["subtitle_codec"] is None:
                    result["subtitle_codec"] = stream.get("codec_name")

        result["stream_counts"] = stream_counts

    except subprocess.CalledProcessError as e:
        result["probe_error"] = f"ffprobe failed: {e}"
    except json.JSONDecodeError as e:
        result["probe_error"] = f"JSON parse error: {e}"
    except Exception as e:
        result["probe_error"] = f"Unexpected error: {e}"

    return result


# =============================================================================
# Variant Builders
# =============================================================================


def build_copy_h264_or_hevc_mp4_movtext(
    input_video: Path, input_srt: Path, output: Path, caps: FFmpegCapabilities
) -> List[str]:
    """Variant A: Copy video/audio if H.264/HEVC, embed mov_text subs."""
    return [
        "ffmpeg",
        "-y",
        "-progress",
        "pipe:2",
        "-fflags",
        "+genpts",
        "-i",
        str(input_video),
        "-i",
        str(input_srt),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-map",
        "1:0",
        "-c:v",
        "copy",
        "-c:a",
        "copy",
        "-c:s",
        "mov_text",
        str(output),
    ]


def build_copy_h264_or_hevc_mp4_movtext_aac(
    input_video: Path, input_srt: Path, output: Path, caps: FFmpegCapabilities
) -> List[str]:
    """Variant B: Copy video if H.264/HEVC, reencode to AAC, mov_text subs."""
    return [
        "ffmpeg",
        "-y",
        "-progress",
        "pipe:2",
        "-fflags",
        "+genpts",
        "-i",
        str(input_video),
        "-i",
        str(input_srt),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-map",
        "1:0",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        "-c:s",
        "mov_text",
        str(output),
    ]


def build_transcode_mpeg2_to_h264_nvenc_mp4_movtext_aac_fast(
    input_video: Path, input_srt: Path, output: Path, caps: FFmpegCapabilities
) -> List[str]:
    """Variant C: MPEG-2 to H.264 NVENC with speed-first settings."""
    return [
        "ffmpeg",
        "-y",
        "-progress",
        "pipe:2",
        "-fflags",
        "+genpts",
        "-i",
        str(input_video),
        "-i",
        str(input_srt),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-map",
        "1:0",
        "-c:v",
        "h264_nvenc",
        "-preset",
        "p1",
        "-tune",
        "ull",
        "-rc",
        "constqp",
        "-qp",
        "23",
        "-bf",
        "0",
        "-g",
        "120",
        "-rc-lookahead",
        "0",
        "-spatial_aq",
        "0",
        "-temporal_aq",
        "0",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        "-c:s",
        "mov_text",
        str(output),
    ]


def build_transcode_mpeg2_to_h264_nvenc_mp4_movtext_aac_hp(
    input_video: Path, input_srt: Path, output: Path, caps: FFmpegCapabilities
) -> List[str]:
    """Variant D: MPEG-2 to H.264 NVENC with hp preset."""
    return [
        "ffmpeg",
        "-y",
        "-progress",
        "pipe:2",
        "-fflags",
        "+genpts",
        "-i",
        str(input_video),
        "-i",
        str(input_srt),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-map",
        "1:0",
        "-c:v",
        "h264_nvenc",
        "-preset",
        "hp",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        "-c:s",
        "mov_text",
        str(output),
    ]


def build_transcode_mpeg2_cuvid_yadif_cuda_to_h264_nvenc_mp4_movtext_aac(
    input_video: Path, input_srt: Path, output: Path, caps: FFmpegCapabilities
) -> List[str]:
    """Variant E: GPU decode + deinterlace + NVENC encode."""
    return [
        "ffmpeg",
        "-y",
        "-progress",
        "pipe:2",
        "-fflags",
        "+genpts",
        "-hwaccel",
        "cuda",
        "-hwaccel_output_format",
        "cuda",
        "-c:v",
        "mpeg2_cuvid",
        "-i",
        str(input_video),
        "-i",
        str(input_srt),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-map",
        "1:0",
        "-vf",
        "yadif_cuda=mode=send_frame:parity=auto:deint=all",
        "-c:v",
        "h264_nvenc",
        "-preset",
        "p1",
        "-tune",
        "ull",
        "-rc",
        "constqp",
        "-qp",
        "23",
        "-bf",
        "0",
        "-g",
        "120",
        "-rc-lookahead",
        "0",
        "-spatial_aq",
        "0",
        "-temporal_aq",
        "0",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "48000",
        "-c:s",
        "mov_text",
        str(output),
    ]


def build_mkv_srt_copy_video_copy_audio(
    input_video: Path, input_srt: Path, output: Path, caps: FFmpegCapabilities
) -> List[str]:
    """Variant F: MKV container with embedded SRT, copy streams."""
    return [
        "ffmpeg",
        "-y",
        "-progress",
        "pipe:2",
        "-fflags",
        "+genpts",
        "-i",
        str(input_video),
        "-i",
        str(input_srt),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-map",
        "1:0",
        "-c:v",
        "copy",
        "-c:a",
        "copy",
        "-c:s",
        "srt",
        str(output),
    ]


# =============================================================================
# Variant Definitions
# =============================================================================


def get_all_variants() -> List[Variant]:
    """Return list of all test variants to run."""
    return [
        Variant(
            name="COPY_H264_OR_HEVC__MP4_MOVTEXT",
            description="Copy H.264/H.265 video/audio, MP4 container, mov_text subs",
            ffmpeg_args_builder=build_copy_h264_or_hevc_mp4_movtext,
            requires_h264_or_hevc=True,
        ),
        Variant(
            name="COPY_H264_OR_HEVC__MP4_MOVTEXT__AAC",
            description="Copy H.264/H.265 video, reencode AAC audio, mov_text subs",
            ffmpeg_args_builder=build_copy_h264_or_hevc_mp4_movtext_aac,
            requires_h264_or_hevc=True,
        ),
        Variant(
            name="TRANSCODE_MPEG2_TO_H264_NVENC__MP4_MOVTEXT__AAC_FAST",
            description="NVENC transcode speed-first (preset p1)",
            ffmpeg_args_builder=(
                build_transcode_mpeg2_to_h264_nvenc_mp4_movtext_aac_fast
            ),
            requires_nvenc=True,
        ),
        Variant(
            name="TRANSCODE_MPEG2_TO_H264_NVENC__MP4_MOVTEXT__AAC_HP",
            description="NVENC transcode with hp preset",
            ffmpeg_args_builder=build_transcode_mpeg2_to_h264_nvenc_mp4_movtext_aac_hp,
            requires_nvenc=True,
        ),
        Variant(
            name="TRANSCODE_MPEG2_CUVID_YADIF_CUDA_TO_H264_NVENC__MP4_MOVTEXT__AAC",
            description="GPU decode + deinterlace + NVENC encode",
            ffmpeg_args_builder=(
                build_transcode_mpeg2_cuvid_yadif_cuda_to_h264_nvenc_mp4_movtext_aac
            ),
            requires_cuvid=True,
        ),
        Variant(
            name="MKV_SRT__COPY_VIDEO_COPY_AUDIO",
            description="MKV container with SRT subs, copy streams",
            ffmpeg_args_builder=build_mkv_srt_copy_video_copy_audio,
            requires_h264_or_hevc=True,
        ),
    ]


# =============================================================================
# Core Test Functions
# =============================================================================


def run_variant(
    variant: Variant,
    input_video: Path,
    input_srt: Path,
    out_dir: Path,
    caps: FFmpegCapabilities,
    keep_temp: bool = False,
) -> TestResult:
    """
    Run a single test variant.

    Args:
        variant: Variant to test
        input_video: Input video file path
        input_srt: Input SRT file path
        out_dir: Output directory
        caps: FFmpeg capabilities
        keep_temp: Keep temporary log files

    Returns:
        TestResult with performance and compatibility data
    """
    # Check if variant should be skipped
    skip_reason = None

    # Check capability requirements
    if variant.requires_nvenc and not caps.has_nvenc:
        skip_reason = "NVENC not available"
    elif variant.requires_cuvid and not caps.has_mpeg2_cuvid:
        skip_reason = "CUVID/mpeg2_cuvid not available"
    elif variant.requires_cuvid and not caps.has_yadif_cuda:
        skip_reason = "yadif_cuda filter not available"

    # Check codec requirements
    if variant.requires_h264_or_hevc and skip_reason is None:
        input_codec = probe_input_codec(input_video)
        if input_codec not in ["h264", "hevc", "h265"]:
            skip_reason = f"Input codec is {input_codec}, not h264/hevc"

    # Build output path
    input_basename = input_video.stem
    output_filename = f"{input_basename}__{variant.name}.mpg"
    output_path = out_dir / output_filename
    log_path = out_dir / f"{input_basename}__{variant.name}.log"

    # Initialize result
    start_time = datetime.now().isoformat()
    result = TestResult(
        name=variant.name,
        description=variant.description,
        command_line=[],
        start_time=start_time,
        end_time=start_time,
        elapsed_seconds=0.0,
        exit_code=-1,
        output_path=str(output_path),
        file_size_bytes=0,
        skipped=skip_reason is not None,
        skip_reason=skip_reason,
    )

    if skip_reason:
        result.end_time = datetime.now().isoformat()
        return result

    # Build command
    try:
        cmd = variant.ffmpeg_args_builder(input_video, input_srt, output_path, caps)
        result.command_line = cmd
    except Exception as e:
        result.skip_reason = f"Failed to build command: {e}"
        result.skipped = True
        result.end_time = datetime.now().isoformat()
        return result

    # Run ffmpeg
    start = time.time()
    try:
        with open(log_path, "w", encoding="utf-8") as log_file:
            process = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
            log_file.write(process.stdout)
            result.exit_code = process.returncode

            # Extract stderr excerpts
            lines = process.stdout.split("\n")
            result.stderr_first_lines = lines[:10]
            result.stderr_last_lines = lines[-10:]

    except Exception as e:
        result.skip_reason = f"Execution failed: {e}"
        result.skipped = True

    elapsed = time.time() - start
    result.elapsed_seconds = elapsed
    result.end_time = datetime.now().isoformat()

    # Get file size
    if output_path.exists():
        result.file_size_bytes = output_path.stat().st_size

    # Probe output
    if result.exit_code == 0 and output_path.exists():
        probe_data = probe_output(output_path)
        result.container_format = probe_data["container_format"]
        result.duration = probe_data["duration"]
        result.video_codec = probe_data["video_codec"]
        result.audio_codec = probe_data["audio_codec"]
        result.subtitle_codec = probe_data["subtitle_codec"]
        result.video_width = probe_data["video_width"]
        result.video_height = probe_data["video_height"]
        result.video_fps = probe_data["video_fps"]
        result.field_order = probe_data["field_order"]
        result.audio_channels = probe_data["audio_channels"]
        result.stream_counts = probe_data["stream_counts"]
        result.probe_error = probe_data["probe_error"]

    # Clean up log if not keeping temp files
    if not keep_temp and log_path.exists():
        log_path.unlink()

    return result


# =============================================================================
# Reporting
# =============================================================================


def write_json_report(results: List[TestResult], output_path: Path, metadata: Dict):
    """Write JSON report with full test results."""
    report = {
        "metadata": metadata,
        "results": [asdict(r) for r in results],
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)


def write_csv_report(results: List[TestResult], output_path: Path):
    """Write CSV report with flattened results."""
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        # Write header
        headers = [
            "name",
            "exit_code",
            "elapsed_seconds",
            "file_size_bytes",
            "container",
            "vcodec",
            "acodec",
            "scodec",
            "width",
            "height",
            "fps",
            "field_order",
            "audio_channels",
            "skipped",
            "skip_reason",
        ]
        f.write(",".join(headers) + "\n")

        # Write rows
        for r in results:
            row = [
                r.name,
                str(r.exit_code),
                f"{r.elapsed_seconds:.2f}",
                str(r.file_size_bytes),
                r.container_format or "",
                r.video_codec or "",
                r.audio_codec or "",
                r.subtitle_codec or "",
                str(r.video_width or ""),
                str(r.video_height or ""),
                r.video_fps or "",
                r.field_order or "",
                str(r.audio_channels or ""),
                str(r.skipped),
                r.skip_reason or "",
            ]
            f.write(",".join(row) + "\n")


def print_summary(results: List[TestResult]):
    """Print human-readable summary to console."""
    print("\n" + "=" * 80)
    print("TEST SUITE SUMMARY")
    print("=" * 80)

    total = len(results)
    skipped = sum(1 for r in results if r.skipped)
    failed = sum(1 for r in results if not r.skipped and r.exit_code != 0)
    passed = total - skipped - failed

    print(f"\nTotal variants: {total}")
    print(f"  Passed:  {passed}")
    print(f"  Failed:  {failed}")
    print(f"  Skipped: {skipped}")

    print("\n" + "-" * 80)
    print(f"{'Variant':<50} {'Status':<10} {'Time':<10} {'Size'}")
    print("-" * 80)

    for r in results:
        if r.skipped:
            status = "SKIPPED"
            time_str = "-"
            size_str = f"({r.skip_reason})"
        elif r.exit_code != 0:
            status = "FAILED"
            time_str = f"{r.elapsed_seconds:.1f}s"
            size_str = f"exit={r.exit_code}"
        else:
            status = "PASSED"
            time_str = f"{r.elapsed_seconds:.1f}s"
            size_mb = r.file_size_bytes / (1024 * 1024)
            size_str = f"{size_mb:.1f} MB"

        print(f"{r.name:<50} {status:<10} {time_str:<10} {size_str}")

    print("-" * 80)

    # Show codec/container info for passed tests
    print("\nCODEC/CONTAINER DETAILS (Passed Tests):")
    print("-" * 80)
    for r in results:
        if not r.skipped and r.exit_code == 0:
            codec_info = (
                f"V:{r.video_codec or 'N/A'} "
                f"A:{r.audio_codec or 'N/A'} "
                f"S:{r.subtitle_codec or 'N/A'} "
                f"Container:{r.container_format or 'N/A'}"
            )
            print(f"{r.name:<50} {codec_info}")

    print("=" * 80 + "\n")


# =============================================================================
# CLI Interface
# =============================================================================


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="FFmpeg Caption-Mux Test Suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example usage:
  python -m tools.ffmpeg_test_suite \\
    --input-video /path/to/test.mpg \\
    --input-srt /path/to/test.srt \\
    --out-dir /path/to/output \\
    --report-json report.json \\
    --report-csv report.csv

This will test multiple ffmpeg encoding strategies and generate performance
and compatibility reports.
        """,
    )

    parser.add_argument(
        "--input-video", required=True, type=Path, help="Input video file (.mpg)"
    )
    parser.add_argument(
        "--input-srt", required=True, type=Path, help="Input subtitle file (.srt)"
    )
    parser.add_argument(
        "--out-dir", required=True, type=Path, help="Output directory for test files"
    )
    parser.add_argument(
        "--limit-variants",
        help="Comma-separated list of variant names to run (default: all)",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep temporary log files after test",
    )
    parser.add_argument(
        "--overwrite", action="store_true", help="Overwrite existing output files"
    )
    parser.add_argument("--report-json", type=Path, help="Path for JSON report output")
    parser.add_argument("--report-csv", type=Path, help="Path for CSV report output")

    args = parser.parse_args()

    # Validate inputs
    if not args.input_video.exists():
        print(f"Error: Input video not found: {args.input_video}", file=sys.stderr)
        return 1

    if not args.input_srt.exists():
        print(f"Error: Input SRT not found: {args.input_srt}", file=sys.stderr)
        return 1

    # Check for ffmpeg/ffprobe
    if not check_command_exists("ffmpeg"):
        print("Error: ffmpeg not found in PATH", file=sys.stderr)
        return 1

    if not check_command_exists("ffprobe"):
        print("Error: ffprobe not found in PATH", file=sys.stderr)
        return 1

    # Create output directory
    args.out_dir.mkdir(parents=True, exist_ok=True)

    # Check overwrite
    if not args.overwrite:
        existing = list(args.out_dir.glob("*.mpg"))
        if existing:
            print(
                "Error: Output directory contains .mpg files. "
                "Use --overwrite to replace.",
                file=sys.stderr,
            )
            return 1

    # Detect capabilities
    print("Detecting ffmpeg capabilities...")
    caps = detect_ffmpeg_capabilities()
    print(f"  FFmpeg version: {caps.ffmpeg_version}")
    print(f"  FFprobe version: {caps.ffprobe_version}")
    print(f"  NVENC available: {caps.has_nvenc}")
    print(f"  CUVID available: {caps.has_cuvid}")
    print(f"  mpeg2_cuvid available: {caps.has_mpeg2_cuvid}")
    print(f"  yadif_cuda available: {caps.has_yadif_cuda}")

    # Get variants
    all_variants = get_all_variants()

    # Filter variants if requested
    if args.limit_variants:
        variant_names = {v.strip() for v in args.limit_variants.split(",")}
        variants_to_run = [v for v in all_variants if v.name in variant_names]
        if not variants_to_run:
            print(
                f"Error: No matching variants found for: {args.limit_variants}",
                file=sys.stderr,
            )
            print(
                f"Available variants: {', '.join(v.name for v in all_variants)}",
                file=sys.stderr,
            )
            return 1
    else:
        variants_to_run = all_variants

    print(f"\nRunning {len(variants_to_run)} test variant(s)...\n")

    # Run tests
    results = []
    for i, variant in enumerate(variants_to_run, 1):
        print(f"[{i}/{len(variants_to_run)}] Running: {variant.name}")
        result = run_variant(
            variant,
            args.input_video,
            args.input_srt,
            args.out_dir,
            caps,
            args.keep_temp,
        )
        results.append(result)

        if result.skipped:
            print(f"  → SKIPPED: {result.skip_reason}")
        elif result.exit_code != 0:
            print(f"  → FAILED: exit code {result.exit_code}")
        else:
            size_mb = result.file_size_bytes / (1024 * 1024)
            print(
                f"  → PASSED: {result.elapsed_seconds:.1f}s, {size_mb:.1f} MB, "
                f"{result.video_codec}/{result.audio_codec}/{result.subtitle_codec}"
            )

    # Generate reports
    metadata = {
        "timestamp": datetime.now().isoformat(),
        "input_video": str(args.input_video),
        "input_srt": str(args.input_srt),
        "ffmpeg_capabilities": asdict(caps),
    }

    if args.report_json:
        write_json_report(results, args.report_json, metadata)
        print(f"\nJSON report written to: {args.report_json}")

    if args.report_csv:
        write_csv_report(results, args.report_csv)
        print(f"CSV report written to: {args.report_csv}")

    # Print summary
    print_summary(results)

    return 0


if __name__ == "__main__":
    sys.exit(main())
