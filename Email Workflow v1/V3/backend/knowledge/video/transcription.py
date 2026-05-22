"""OpenAI Whisper API wrapper.

We use the API rather than running Whisper locally for three reasons:
  1. No 1+GB model downloads at container build time.
  2. CPU inference is slow (~real-time); API latency is much better.
  3. The hosted model is more robust to noise / accents than the small
     local variants we'd realistically use on a CPU.

Cost: $0.006 per minute of audio. For 1 hour of video that's $0.36.

The API has a 25 MB upload limit; for long videos we'd need to split.
A 1-hour WAV at 16kHz mono PCM-16 is roughly 110 MB, which exceeds the
limit. We re-encode to ogg/opus before upload for compression; that
brings a 1-hour audio under 10 MB while keeping Whisper's transcription
quality.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from backend.core.config import AppSettings


logger = logging.getLogger(__name__)


# Whisper API hard limit. We re-encode to fit comfortably under this.
_WHISPER_MAX_UPLOAD_BYTES = 24 * 1024 * 1024  # 24 MB to leave headroom
_WHISPER_TIMEOUT_SECONDS = 600  # 10 minutes — covers very long audio


class TranscriptionError(RuntimeError):
    """Raised when Whisper transcription fails."""


@dataclass(frozen=True)
class TranscriptSegment:
    """One Whisper segment — a contiguous slice of audio with timing.

    `start` and `end` are seconds from the beginning of the audio.
    Whisper's API returns these natively when we request
    `response_format='verbose_json'`.
    """

    start: float
    end: float
    text: str


class TranscriptionService:
    """Thin wrapper around OpenAI's audio transcription endpoint."""

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    @property
    def model(self) -> str:
        return self.settings.kb_whisper_model

    def transcribe(
        self,
        audio_path: Path,
        *,
        language: str | None = None,
    ) -> list[TranscriptSegment]:
        """Transcribe `audio_path` and return timed segments.

        `language` is an ISO 639-1 hint (en, fr, es, ...). When None,
        Whisper auto-detects.
        """
        if not self.settings.openai_api_key.strip():
            raise TranscriptionError(
                "OPENAI_API_KEY is missing — cannot transcribe audio."
            )

        prepared_audio = self._prepare_for_upload(audio_path)
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise TranscriptionError(
                "openai package is not installed."
            ) from exc

        client = OpenAI(
            api_key=self.settings.openai_api_key,
            timeout=_WHISPER_TIMEOUT_SECONDS,
        )
        try:
            with prepared_audio.open("rb") as fp:
                response = client.audio.transcriptions.create(
                    model=self.model,
                    file=fp,
                    response_format="verbose_json",
                    language=language,
                    timestamp_granularities=["segment"],
                )
        except Exception as exc:
            raise TranscriptionError(
                f"Whisper API request failed: {exc}"
            ) from exc
        finally:
            # Clean up the compressed copy if we made one.
            if prepared_audio != audio_path:
                try:
                    prepared_audio.unlink(missing_ok=True)
                except OSError:
                    pass

        # The SDK returns a Pydantic-like object; access via getattr to
        # remain tolerant to schema drift across SDK versions.
        segments_raw = getattr(response, "segments", None) or []
        if not segments_raw:
            # Fall back to a single segment using the top-level text. Rare
            # but happens for very short audio.
            text = (getattr(response, "text", "") or "").strip()
            if not text:
                raise TranscriptionError(
                    "Whisper returned no segments and no text."
                )
            return [TranscriptSegment(start=0.0, end=0.0, text=text)]

        segments: list[TranscriptSegment] = []
        for seg in segments_raw:
            start = float(getattr(seg, "start", 0.0) or 0.0)
            end = float(getattr(seg, "end", start) or start)
            text = (getattr(seg, "text", "") or "").strip()
            if text:
                segments.append(TranscriptSegment(start=start, end=end, text=text))
        return segments

    def _prepare_for_upload(self, audio_path: Path) -> Path:
        """Compress to ogg/opus if the WAV exceeds the API upload cap.

        Opus at 32kbps is plenty for speech transcription — Whisper
        rarely benefits from higher bitrates. A 1-hour file compresses
        from ~110 MB WAV to ~15 MB ogg.

        Returns either the original path (if under the cap) or a new
        compressed file in the same directory.
        """
        size = audio_path.stat().st_size if audio_path.exists() else 0
        if size <= _WHISPER_MAX_UPLOAD_BYTES:
            return audio_path
        if not shutil.which("ffmpeg"):
            raise TranscriptionError(
                f"Audio is too large for the Whisper API ({size} bytes > "
                f"{_WHISPER_MAX_UPLOAD_BYTES}) and ffmpeg is not available "
                f"to compress it."
            )

        compressed = audio_path.with_suffix(".ogg")
        cmd = [
            "ffmpeg",
            "-y",
            "-i", str(audio_path),
            "-c:a", "libopus",
            "-b:a", "32k",
            "-vn",
            "-loglevel", "error",
            str(compressed),
        ]
        logger.info(
            "Audio exceeds Whisper limit (%s bytes); compressing to opus.",
            size,
        )
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=900
        )
        if result.returncode != 0 or not compressed.exists():
            raise TranscriptionError(
                f"Failed to compress audio for Whisper: {result.stderr.strip()}"
            )
        return compressed


def format_timestamp(seconds: float) -> str:
    """Render seconds as [HH:MM:SS] for embedding in the transcript text."""
    total = int(round(max(0.0, seconds)))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"
