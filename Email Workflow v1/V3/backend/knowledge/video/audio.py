"""ffmpeg wrapper for extracting audio from video.

We shell out to ffmpeg via subprocess rather than using a Python binding
(ffmpeg-python, av) because:
  1. Less surface area — no extra Python dep, no version-matching
     headaches between the binding and the system binary.
  2. ffmpeg's CLI is the canonical interface; any Stack Overflow
     answer translates 1:1.
  3. Easier to debug — failures produce stderr we can log verbatim.

Audio is downmixed to mono 16kHz WAV because that's what Whisper
expects and it minimizes file size for the API upload.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path


logger = logging.getLogger(__name__)


class AudioExtractionError(RuntimeError):
    """Raised when ffmpeg fails to extract audio."""


def extract_audio_to_wav(
    video_path: Path,
    output_path: Path,
    *,
    sample_rate: int = 16_000,
) -> Path:
    """Extract audio from `video_path` as mono PCM-16 WAV at `output_path`.

    Returns the output path on success. Raises AudioExtractionError on
    any ffmpeg failure — the message includes stderr so the user sees
    why (corrupted file, unsupported codec, etc.).
    """
    if not shutil.which("ffmpeg"):
        raise AudioExtractionError(
            "ffmpeg binary not found on PATH. Install it on the host or "
            "rebuild the Docker image."
        )
    if not video_path.exists():
        raise AudioExtractionError(f"Video file does not exist: {video_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-y",                    # overwrite output if it exists
        "-i", str(video_path),
        "-vn",                   # drop video stream
        "-ac", "1",              # mono
        "-ar", str(sample_rate), # 16kHz
        "-f", "wav",
        "-acodec", "pcm_s16le",
        "-loglevel", "error",    # quiet unless something breaks
        str(output_path),
    ]
    logger.info("Running ffmpeg audio extract: %s -> %s", video_path, output_path)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,  # 10 min max for audio extract; covers 4-hour videos
        )
    except subprocess.TimeoutExpired as exc:
        raise AudioExtractionError(
            f"ffmpeg timed out extracting audio from {video_path.name}."
        ) from exc
    if result.returncode != 0:
        raise AudioExtractionError(
            f"ffmpeg failed (exit {result.returncode}): {result.stderr.strip()}"
        )
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise AudioExtractionError(
            "ffmpeg reported success but produced no audio output. "
            "The video may have no audio track."
        )
    return output_path


def probe_duration_seconds(video_path: Path) -> float:
    """Return the video's duration in seconds via ffprobe.

    Returns 0.0 if probe fails — callers that need an exact value should
    check and decide; everything we do (frame extraction, chunking) is
    robust to a 0 here, just less efficient.
    """
    if not shutil.which("ffprobe"):
        return 0.0
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return 0.0
    if result.returncode != 0:
        return 0.0
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0
