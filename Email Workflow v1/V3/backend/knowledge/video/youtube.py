"""yt-dlp wrapper for ingesting YouTube videos.

For YouTube we deliberately download only the audio stream:
  * Audio is enough for transcription, which is the load-bearing piece
    of our pipeline. Video frames would add hundreds of MB per video
    and we'd extract frames from them anyway — pointless round-trip.
  * Downloading raw video also runs into more YouTube anti-bot
    friction than audio-only does.

If the user later wants real frame analysis on a YouTube video, the
upgrade path is: re-run yt-dlp asking for the video stream too.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path


logger = logging.getLogger(__name__)


class YouTubeDownloadError(RuntimeError):
    """Raised when yt-dlp can't fetch the requested URL."""


@dataclass(frozen=True)
class YouTubeDownloadResult:
    """Where the downloaded file ended up and what to call it.

    `audio_path` always points at an m4a/webm file inside `output_dir` —
    the exact extension depends on what YouTube serves. Callers should
    treat the file as opaque audio and pass it straight to the audio
    extractor (which re-encodes to a uniform WAV).
    """

    audio_path: Path
    title: str
    duration_seconds: float
    source_url: str


def download_youtube_audio(
    url: str,
    output_dir: Path,
    *,
    cookies_file: str | None = None,
) -> YouTubeDownloadResult:
    """Download the audio stream of `url` into `output_dir`.

    Defends against YouTube's "sign in to confirm you're not a bot"
    challenge in two stages:

      1. Prefer the android player client when extracting. YouTube
         applies its anti-bot heuristics most aggressively to web
         clients; the android variant typically succeeds without any
         user action.

      2. If a `cookies_file` path is supplied (set via the
         `KB_YOUTUBE_COOKIES_FILE` env var), yt-dlp uses it. Users
         export cookies from a logged-in browser, mount the file into
         the container, and the bot challenge stops appearing.

    Raises YouTubeDownloadError with a human-actionable message when
    both routes fail — the user can either upload the file directly or
    set up a cookies file.
    """
    try:
        import yt_dlp  # type: ignore
    except ImportError as exc:
        raise YouTubeDownloadError(
            "yt-dlp is not installed — run `pip install yt-dlp`."
        ) from exc

    output_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(output_dir / "%(id)s.%(ext)s")

    base_options: dict[str, object] = {
        "format": "bestaudio/best",
        "outtmpl": output_template,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "extract_flat": False,
        # Most YouTube anti-bot signals key off User-Agent + TLS
        # fingerprint. We can't change TLS easily but a realistic UA
        # often gets us past the heuristic.
        "http_headers": {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        },
        # Try android first, then web. The android player path tends
        # to bypass the bot-detection prompt on datacenter IPs.
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
    }
    if cookies_file:
        cookies_path = Path(cookies_file)
        if cookies_path.exists():
            base_options["cookiefile"] = str(cookies_path)
        else:
            logger.warning(
                "KB_YOUTUBE_COOKIES_FILE points to %s but the file does not "
                "exist — proceeding without cookies.",
                cookies_path,
            )

    try:
        with yt_dlp.YoutubeDL(base_options) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as exc:
        message = str(exc)
        # Translate yt-dlp's "sign in to confirm" message into something
        # the user can actually act on. The original is a wall of text
        # ending with two doc URLs that doesn't tell them what to do
        # in the context of THIS app.
        if "sign in to confirm" in message.lower() or "not a bot" in message.lower():
            raise YouTubeDownloadError(
                "YouTube blocked the download because it doesn't trust the "
                "server's IP (common on datacenter / VPS hosts). Two options:\n"
                "  1) Upload the video file directly instead of using a URL.\n"
                "  2) Export YouTube cookies from a signed-in browser to a "
                "cookies.txt file, mount it into the container, and set "
                "KB_YOUTUBE_COOKIES_FILE to its path. Restart the API and "
                "retry."
            ) from exc
        raise YouTubeDownloadError(
            f"yt-dlp failed for {url}: {exc}"
        ) from exc

    if info is None:
        raise YouTubeDownloadError(
            f"yt-dlp returned no metadata for {url}."
        )

    # yt-dlp 2024+ returns the resolved filepath inside `requested_downloads`;
    # older versions only populate the format dict. Cover both.
    audio_path: Path | None = None
    requested = info.get("requested_downloads") or []
    if requested:
        downloaded = requested[0].get("filepath")
        if downloaded:
            audio_path = Path(downloaded)
    if audio_path is None:
        # Fall back to glob — the video id is unique in our temp dir.
        video_id = info.get("id", "")
        candidates = list(output_dir.glob(f"{video_id}.*"))
        if candidates:
            audio_path = candidates[0]

    if audio_path is None or not audio_path.exists():
        raise YouTubeDownloadError(
            f"yt-dlp reported success but no audio file was found for {url}."
        )

    title = str(info.get("title") or audio_path.stem)
    duration = float(info.get("duration") or 0.0)
    return YouTubeDownloadResult(
        audio_path=audio_path,
        title=title,
        duration_seconds=duration,
        source_url=url,
    )
