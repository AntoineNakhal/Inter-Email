"""Frame extraction + scene detection + OCR.

The spec's optimization rules require us to be smart about which frames
to look at:
  * default 1 frame every 10 s
  * extra frames at scene boundaries (slide change, UI change)
  * extra frames at timestamps the transcript explicitly references
  * skip near-duplicate frames so we don't re-OCR the same screen

This file owns that selection logic. It does NOT do vision-API
analysis — that's the orchestrator's job, and it's optional.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


logger = logging.getLogger(__name__)


# Frames closer together than this collapse to one. Keeps us from
# emitting "scene change at 12.3s" and "scene change at 12.5s" as
# separate samples.
_MIN_FRAME_SPACING_SECONDS = 1.5

# Phrases in the transcript that signal "look at the screen now". Used
# to bias frame extraction toward moments the speaker references visuals.
_VISUAL_REFERENCE_PHRASES = (
    "on screen",
    "on the screen",
    "as you can see",
    "you can see",
    "click here",
    "this button",
    "this menu",
    "this slide",
    "this diagram",
    "this chart",
    "this graph",
    "look at",
    "here we have",
    "here you see",
    "shown here",
)


@dataclass(frozen=True)
class FrameSelection:
    """A timestamp we want to extract a frame at, with provenance.

    `reason` is one of: "baseline", "scene_change", "transcript_ref".
    Used purely for diagnostics — we log it so we can tune the strategy
    after seeing real outputs.
    """

    timestamp: float
    reason: str


@dataclass(frozen=True)
class ExtractedFrame:
    """A frame written to disk, with metadata we keep for downstream OCR."""

    timestamp: float
    path: Path
    reason: str


@dataclass
class TranscriptSegmentLite:
    """Local view of a transcript segment to avoid circular imports."""

    start: float
    end: float
    text: str


# ── Selection ──────────────────────────────────────────────────────────
def select_frames(
    *,
    duration_seconds: float,
    transcript_segments: list[TranscriptSegmentLite],
    scene_change_seconds: list[float],
    baseline_interval_seconds: int,
) -> list[FrameSelection]:
    """Combine all three sources into a deduplicated, ordered list.

    Strategy:
      1. Sample every `baseline_interval_seconds` from t=0 — coarse coverage.
      2. Add scene-change timestamps for high-information moments.
      3. Add transcript-referenced timestamps (when the speaker says
         "look at the screen", probably worth a frame).
      4. Sort + dedupe within MIN_FRAME_SPACING_SECONDS.
    """
    selections: list[FrameSelection] = []

    if duration_seconds <= 0:
        # Unknown duration — just sample scene changes + transcript refs.
        duration_seconds = max(
            (seg.end for seg in transcript_segments), default=0.0
        )

    # 1) Baseline
    t = 0.0
    while t < duration_seconds:
        selections.append(FrameSelection(timestamp=t, reason="baseline"))
        t += max(1, baseline_interval_seconds)

    # 2) Scene changes
    for ts in scene_change_seconds:
        selections.append(FrameSelection(timestamp=ts, reason="scene_change"))

    # 3) Transcript references
    for seg in transcript_segments:
        text_lower = seg.text.lower()
        if any(phrase in text_lower for phrase in _VISUAL_REFERENCE_PHRASES):
            # Sample slightly INTO the segment so we capture what the
            # speaker is gesturing at, not the moment they start talking.
            ts = seg.start + max(0.5, (seg.end - seg.start) / 2.0)
            selections.append(
                FrameSelection(timestamp=ts, reason="transcript_ref")
            )

    return _dedupe(selections)


def _dedupe(selections: list[FrameSelection]) -> list[FrameSelection]:
    """Drop near-duplicates; keep the highest-information reason."""
    priority = {"scene_change": 0, "transcript_ref": 1, "baseline": 2}
    selections_sorted = sorted(selections, key=lambda s: s.timestamp)
    out: list[FrameSelection] = []
    for sel in selections_sorted:
        if out and sel.timestamp - out[-1].timestamp < _MIN_FRAME_SPACING_SECONDS:
            # Replace the previous one only if this is a higher-info reason.
            if priority[sel.reason] < priority[out[-1].reason]:
                out[-1] = sel
            continue
        out.append(sel)
    return out


# ── Scene detection ────────────────────────────────────────────────────
def detect_scene_changes(video_path: Path) -> list[float]:
    """Return scene-change timestamps in seconds via scenedetect.

    Returns [] if scenedetect isn't installed or fails — scene detection
    is an enrichment, not a hard requirement, so we degrade gracefully
    to baseline+transcript sampling.
    """
    try:
        from scenedetect import ContentDetector, SceneManager, open_video
    except ImportError:
        logger.warning(
            "scenedetect not available — falling back to baseline sampling."
        )
        return []

    try:
        video = open_video(str(video_path))
        scene_manager = SceneManager()
        # threshold=27 is the scenedetect default tuned for talking-head
        # content; lower would over-detect, higher under-detect.
        scene_manager.add_detector(ContentDetector(threshold=27.0))
        scene_manager.detect_scenes(video, show_progress=False)
        scene_list = scene_manager.get_scene_list()
    except Exception:
        logger.exception("Scene detection failed; continuing without it.")
        return []

    return [scene[0].get_seconds() for scene in scene_list]


# ── Frame extraction ───────────────────────────────────────────────────
def extract_frames(
    video_path: Path,
    selections: list[FrameSelection],
    output_dir: Path,
) -> list[ExtractedFrame]:
    """Write one JPEG per selection to `output_dir`.

    ffmpeg is invoked once per selection because seeking + single-frame
    output is the cheapest pattern for non-contiguous timestamps. For
    100 frames over a 1-hour video this is ~30 s of wall time.
    """
    if not shutil.which("ffmpeg"):
        logger.error("ffmpeg missing — cannot extract frames.")
        return []
    output_dir.mkdir(parents=True, exist_ok=True)

    extracted: list[ExtractedFrame] = []
    for sel in selections:
        out_path = output_dir / f"frame_{int(round(sel.timestamp * 1000))}.jpg"
        cmd = [
            "ffmpeg",
            "-y",
            "-ss", f"{sel.timestamp:.3f}",
            "-i", str(video_path),
            "-frames:v", "1",
            "-q:v", "4",
            "-loglevel", "error",
            str(out_path),
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30
            )
        except subprocess.TimeoutExpired:
            logger.warning("Frame extract timeout at t=%.2f", sel.timestamp)
            continue
        if result.returncode != 0 or not out_path.exists():
            logger.warning(
                "Frame extract failed at t=%.2f: %s",
                sel.timestamp,
                result.stderr.strip(),
            )
            continue
        extracted.append(
            ExtractedFrame(
                timestamp=sel.timestamp,
                path=out_path,
                reason=sel.reason,
            )
        )
    return extracted


# ── OCR ────────────────────────────────────────────────────────────────
def ocr_frame(image_path: Path) -> str:
    """Return text read from `image_path` via Tesseract.

    Empty string when pytesseract/tesseract aren't installed or the
    frame contains no readable text. We never raise from this function:
    OCR is supplementary, and a single failed frame shouldn't break the
    pipeline.
    """
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        logger.warning("pytesseract / PIL not available — skipping OCR.")
        return ""
    try:
        with Image.open(image_path) as image:
            text = pytesseract.image_to_string(image)
    except Exception:
        logger.exception("OCR failed on %s", image_path)
        return ""
    return text.strip()


# ── Filtering ──────────────────────────────────────────────────────────
def is_text_heavy(ocr_text: str, *, min_chars: int = 40) -> bool:
    """Heuristic: did OCR pull enough real text to be worth surfacing?

    `min_chars` is intentionally low — 40 characters is roughly one
    short slide title, which is exactly the kind of thing we want to
    capture. Higher thresholds drop useful headings; lower lets in
    OCR noise from non-text frames.
    """
    if not ocr_text:
        return False
    stripped = ocr_text.replace(" ", "").replace("\n", "")
    return len(stripped) >= min_chars
