from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class MediaProcessingError(RuntimeError):
    """Raised when probing, separating, or remuxing a video fails."""


class InputValidationError(ValueError):
    """Raised when the input cannot be processed within configured limits."""


@dataclass(frozen=True)
class MediaInfo:
    duration_seconds: float
    size_bytes: int
    has_video: bool
    has_audio: bool


def parse_probe_json(raw: str, fallback_size_bytes: int = 0) -> MediaInfo:
    try:
        payload: dict[str, Any] = json.loads(raw)
        format_info = payload.get("format", {})
        duration = float(format_info.get("duration", 0))
        size = int(format_info.get("size") or fallback_size_bytes)
        streams = payload.get("streams", [])
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise MediaProcessingError("ffprobe returned invalid media information") from exc

    stream_types = {stream.get("codec_type") for stream in streams}
    return MediaInfo(
        duration_seconds=duration,
        size_bytes=size,
        has_video="video" in stream_types,
        has_audio="audio" in stream_types,
    )


def validate_media(
    media: MediaInfo,
    *,
    max_size_bytes: int,
    max_duration_seconds: int,
) -> None:
    if not media.has_video:
        raise InputValidationError("ফাইলে ভিডিও ট্র্যাক পাওয়া যায়নি।")
    if not media.has_audio:
        raise InputValidationError("ভিডিওতে অডিও ট্র্যাক নেই।")
    if media.duration_seconds <= 0:
        raise InputValidationError("ভিডিওর দৈর্ঘ্য পড়া যায়নি।")
    if media.size_bytes > max_size_bytes:
        max_mb = max_size_bytes // (1024 * 1024)
        raise InputValidationError(f"ভিডিওটি {max_mb} MB সীমার চেয়ে বড়।")
    if media.duration_seconds > max_duration_seconds:
        raise InputValidationError(
            f"ভিডিওটি {max_duration_seconds // 60} মিনিটের বেশি।"
        )


def _require_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise MediaProcessingError(
            f"Required system tool '{name}' is not installed. Install FFmpeg."
        )
    return path


def _run(
    command: list[str],
    *,
    purpose: str,
    timeout_seconds: int,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise MediaProcessingError(f"{purpose} exceeded its time limit") from exc
    except OSError as exc:
        raise MediaProcessingError(f"{purpose} could not be started") from exc

    if result.returncode:
        details = result.stderr.strip()[-1200:]
        raise MediaProcessingError(
            f"{purpose} failed (exit {result.returncode}): {details}"
        )
    return result


def probe_media(path: Path) -> MediaInfo:
    ffprobe = _require_tool("ffprobe")
    try:
        fallback_size = path.stat().st_size
    except OSError as exc:
        raise MediaProcessingError("The uploaded video is not available") from exc

    result = _run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration,size",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "json",
            str(path),
        ],
        purpose="Video inspection",
        timeout_seconds=60,
    )
    return parse_probe_json(result.stdout, fallback_size_bytes=fallback_size)


def _run_demucs(
    source_audio: Path,
    separation_dir: Path,
    *,
    timeout_seconds: int,
) -> Path:
    model = os.getenv("DEMUCS_MODEL", "htdemucs").strip() or "htdemucs"
    device = os.getenv("DEMUCS_DEVICE", "cpu").strip() or "cpu"
    try:
        shifts = max(1, min(10, int(os.getenv("DEMUCS_SHIFTS", "1"))))
    except ValueError:
        shifts = 1
    threads = max(1, min(4, os.cpu_count() or 1))

    env = os.environ.copy()
    env.setdefault("OMP_NUM_THREADS", str(threads))
    env.setdefault("MKL_NUM_THREADS", str(threads))

    _run(
        [
            sys.executable,
            "-m",
            "demucs.separate",
            "--name",
            model,
            "--two-stems",
            "vocals",
            "--device",
            device,
            "--shifts",
            str(shifts),
            "-j",
            "1",
            "--out",
            str(separation_dir),
            str(source_audio),
        ],
        purpose="AI music separation",
        timeout_seconds=timeout_seconds,
        env=env,
    )

    vocals = separation_dir / model / source_audio.stem / "vocals.wav"
    if not vocals.is_file() or vocals.stat().st_size == 0:
        raise MediaProcessingError("The AI model did not produce a vocal track")
    return vocals


def _clean_vocal_track(
    vocals_path: Path,
    clean_audio_path: Path,
    *,
    timeout_seconds: int,
) -> None:
    ffmpeg = _require_tool("ffmpeg")
    # A light filter removes low rumble and residual steady hiss without
    # replacing the source-separation result with aggressive gating.
    _run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(vocals_path),
            "-af",
            "highpass=f=70,afftdn=nr=5:nf=-45:tn=1,lowpass=f=15000",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-c:a",
            "pcm_s16le",
            str(clean_audio_path),
        ],
        purpose="Residual noise cleanup",
        timeout_seconds=timeout_seconds,
    )


def _mux_video(
    input_path: Path,
    clean_audio_path: Path,
    output_path: Path,
    *,
    timeout_seconds: int,
    reencode_video: bool,
) -> None:
    ffmpeg = _require_tool("ffmpeg")
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(input_path),
        "-i",
        str(clean_audio_path),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
    ]
    if reencode_video:
        command.extend(["-c:v", "libx264", "-preset", "veryfast", "-crf", "22"])
    else:
        command.extend(["-c:v", "copy"])
    command.extend(
        [
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-shortest",
            "-movflags",
            "+faststart",
            "-f",
            "mp4",
            str(output_path),
        ]
    )
    _run(
        command,
        purpose="Video export",
        timeout_seconds=timeout_seconds,
    )


def process_video(
    input_path: Path,
    output_path: Path,
    *,
    max_input_bytes: int,
    max_duration_seconds: int,
    max_output_bytes: int,
    timeout_seconds: int,
) -> None:
    input_path = Path(input_path)
    output_path = Path(output_path)
    media = probe_media(input_path)
    validate_media(
        media,
        max_size_bytes=max_input_bytes,
        max_duration_seconds=max_duration_seconds,
    )

    ffmpeg = _require_tool("ffmpeg")
    work_dir = output_path.parent
    source_audio = work_dir / "source-audio.wav"
    separation_dir = work_dir / "separated"
    clean_audio = work_dir / "clean-audio.wav"

    _run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(input_path),
            "-map",
            "0:a:0",
            "-vn",
            "-ac",
            "2",
            "-ar",
            "44100",
            "-c:a",
            "pcm_s16le",
            str(source_audio),
        ],
        purpose="Audio extraction",
        timeout_seconds=timeout_seconds,
    )

    vocals = _run_demucs(
        source_audio,
        separation_dir,
        timeout_seconds=timeout_seconds,
    )
    _clean_vocal_track(vocals, clean_audio, timeout_seconds=timeout_seconds)

    try:
        _mux_video(
            input_path,
            clean_audio,
            output_path,
            timeout_seconds=timeout_seconds,
            reencode_video=False,
        )
    except MediaProcessingError:
        # Some input codecs cannot be placed in an MP4 container by stream copy.
        output_path.unlink(missing_ok=True)
        _mux_video(
            input_path,
            clean_audio,
            output_path,
            timeout_seconds=timeout_seconds,
            reencode_video=True,
        )

    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise MediaProcessingError("Video export produced an empty file")
    if output_path.stat().st_size > max_output_bytes:
        output_path.unlink(missing_ok=True)
        raise InputValidationError(
            "প্রসেস করা ভিডিওটি Telegram-এ পাঠানোর সীমার চেয়ে বড় হয়েছে। "
            "আরও ছোট বা কম রেজল্যুশনের ভিডিও পাঠান।"
        )
