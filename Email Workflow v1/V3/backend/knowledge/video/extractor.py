"""Top-level video ingestion orchestrator.

Implements the spec's pipeline:

    1. Extract audio with ffmpeg.
    2. Transcribe with Whisper (timestamps included).
    3. Detect scene changes (scenedetect).
    4. Select frames (baseline interval + scene changes + transcript refs).
    5. Extract those frames with ffmpeg.
    6. OCR text-heavy frames with Tesseract.
    7. Assemble a single structured text document that the existing
       chunker/embedder pipeline can consume unchanged.

The output is a markdown-flavoured transcript with frame OCR text
interleaved at the right timestamps. The downstream chunker, embedder,
metadata extractor, and chunk explorer all keep working without any
video-specific code paths.
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path

from backend.core.config import AppSettings
from backend.knowledge.video.audio import (
    AudioExtractionError,
    extract_audio_to_wav,
    probe_duration_seconds,
)
from backend.knowledge.video.frames import (
    TranscriptSegmentLite,
    detect_scene_changes,
    extract_frames,
    is_text_heavy,
    ocr_frame,
    select_frames,
)
from backend.knowledge.video.transcription import (
    TranscriptionError,
    TranscriptionService,
    TranscriptSegment,
    format_timestamp,
)


logger = logging.getLogger(__name__)


class VideoIngestionError(RuntimeError):
    """Raised when the video pipeline fails — any layer."""


@dataclass(frozen=True)
class VideoIngestionResult:
    """Everything the caller needs after a successful run.

    `text` is the consolidated document — that's what the chunker
    receives. The other fields are diagnostic so the UI can surface
    "transcribed 47 minutes, OCR'd 9 frames" or similar.
    """

    text: str
    duration_seconds: float
    transcript_segments: int
    frames_extracted: int
    frames_with_text: int


class VideoIngestionExtractor:
    """Runs the spec's pipeline end-to-end for a single video file.

    Caller responsibility:
      * Stage the bytes to disk somewhere we can re-open them by path
        (ffmpeg needs a real file, not a stream).
      * Pass that path here.
      * Delete the file when done — we don't.
    """

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.transcription = TranscriptionService(settings)

    def ingest(self, video_path: Path) -> VideoIngestionResult:
        """Run all 7 stages. Raises VideoIngestionError on any failure
        whose recovery isn't graceful (audio missing, transcription
        unauthorised, etc.). Scene detection and OCR are best-effort —
        they log + skip rather than abort."""
        if not video_path.exists():
            raise VideoIngestionError(f"Video file not found: {video_path}")

        # We do all intermediate work in a fresh temp dir so a failure
        # mid-pipeline never leaves orphan files around the data volume.
        with tempfile.TemporaryDirectory(prefix="kbvideo_") as scratch:
            scratch_dir = Path(scratch)
            return self._run(video_path, scratch_dir)

    # ────────────────────────────────────────────────────────────────
    def _run(self, video_path: Path, scratch_dir: Path) -> VideoIngestionResult:
        duration = probe_duration_seconds(video_path)

        # Stage 1: audio
        audio_path = scratch_dir / "audio.wav"
        try:
            extract_audio_to_wav(video_path, audio_path)
        except AudioExtractionError as exc:
            raise VideoIngestionError(str(exc)) from exc

        # Stage 2: transcription
        try:
            segments = self.transcription.transcribe(audio_path)
        except TranscriptionError as exc:
            raise VideoIngestionError(str(exc)) from exc

        # If we never got the duration from ffprobe, infer it from the
        # final segment's end time. Used by frame selection.
        if duration <= 0 and segments:
            duration = max(seg.end for seg in segments)

        # Stage 3: scene detection (best-effort)
        scene_changes = detect_scene_changes(video_path)
        logger.info(
            "Video pipeline: %.1fs duration, %s segments, %s scenes.",
            duration, len(segments), len(scene_changes),
        )

        # Stage 4: frame selection
        seg_lite = [
            TranscriptSegmentLite(start=s.start, end=s.end, text=s.text)
            for s in segments
        ]
        frame_selections = select_frames(
            duration_seconds=duration,
            transcript_segments=seg_lite,
            scene_change_seconds=scene_changes,
            baseline_interval_seconds=self.settings.kb_video_frame_interval_sec,
        )

        # Stage 5: frame extraction
        frames_dir = scratch_dir / "frames"
        extracted_frames = extract_frames(
            video_path, frame_selections, frames_dir
        )

        # Stage 6: OCR — best-effort, skip empties.
        frame_ocr_text: dict[float, str] = {}
        for frame in extracted_frames:
            text = ocr_frame(frame.path)
            if is_text_heavy(text):
                frame_ocr_text[frame.timestamp] = text

        # Stage 7: build the consolidated document
        document_text = _build_document_text(
            segments=segments,
            frame_ocr_text=frame_ocr_text,
            duration_seconds=duration,
        )

        return VideoIngestionResult(
            text=document_text,
            duration_seconds=duration,
            transcript_segments=len(segments),
            frames_extracted=len(extracted_frames),
            frames_with_text=len(frame_ocr_text),
        )


# ── Document assembly ──────────────────────────────────────────────────
def _build_document_text(
    *,
    segments: list[TranscriptSegment],
    frame_ocr_text: dict[float, str],
    duration_seconds: float,
) -> str:
    """Compose the chunker-ready document.

    We interleave OCR snippets at their timestamps so a chunk that spans
    minute 12 of the video carries both what was *said* in minute 12 and
    what was *shown on screen* — the embedding then captures both axes.
    """
    lines: list[str] = []
    lines.append(f"# Video transcript")
    if duration_seconds > 0:
        lines.append(f"Duration: {format_timestamp(duration_seconds)}")
    lines.append("")

    # We merge segments and OCR snippets into a single timeline sorted
    # by timestamp. Each transcript segment is a "spoken" entry; each
    # OCR snippet is a "[On screen at HH:MM:SS]" entry inserted at the
    # right point so chunkers see them in context.
    timeline: list[tuple[float, str]] = []
    for seg in segments:
        timeline.append(
            (seg.start, f"[{format_timestamp(seg.start)}] {seg.text.strip()}")
        )
    for timestamp, ocr_text in frame_ocr_text.items():
        flattened = " ".join(ocr_text.split())
        timeline.append(
            (
                timestamp,
                f"[{format_timestamp(timestamp)}] [On-screen text] {flattened}",
            )
        )
    timeline.sort(key=lambda row: row[0])

    for _, line in timeline:
        lines.append(line)

    return "\n".join(lines).strip()
