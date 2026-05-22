"""Video ingestion pipeline.

Public surface:
    VideoIngestionExtractor — the only thing the rest of the app needs.
        Hands it raw video bytes; gets back a structured text document
        that flows through the existing chunker/embedder/metadata stack
        unchanged.

The pipeline lives under its own subpackage because it pulls in heavy
deps (ffmpeg subprocess, scenedetect, opencv, pytesseract, yt-dlp) that
are irrelevant to the other extractors. Keeping them isolated here
means a bug in the video path can never break PDF ingestion.
"""

from backend.knowledge.video.extractor import (
    VideoIngestionError,
    VideoIngestionExtractor,
)
from backend.knowledge.video.youtube import YouTubeDownloadError, download_youtube_audio

__all__ = [
    "VideoIngestionError",
    "VideoIngestionExtractor",
    "YouTubeDownloadError",
    "download_youtube_audio",
]
