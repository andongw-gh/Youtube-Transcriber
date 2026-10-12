"""Fetch the audio track of a YouTube video with yt-dlp."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Callable

ProgressCallback = Callable[[float | None, str], None]

log = logging.getLogger(__name__)


class DownloadError(RuntimeError):
    """The audio could not be downloaded; the message is safe to show to users."""


@dataclass
class DownloadedAudio:
    path: Path
    video_id: str
    title: str
    url: str
    duration: float | None = None
    uploader: str | None = None


def _human_size(num_bytes: float) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


_ANSI = re.compile(r"\x1b\[[0-9;]*m")
# yt-dlp appends bug-report instructions to many errors; they only confuse end users.
_YTDLP_BOILERPLATE = re.compile(
    r";?\s*please report this issue on\s+\S+.*(?:yt-dlp -U|issue template\.?)\s*", re.I | re.S
)


def friendly_message(raw: str) -> str:
    """Turn a yt-dlp error into something a person can act on."""
    msg = _ANSI.sub("", raw).strip()
    msg = re.sub(r"^ERROR:\s*", "", msg)
    msg = re.sub(r"^\[youtube\]\s*[\w-]{11}:\s*", "", msg)
    msg = _YTDLP_BOILERPLATE.sub("", msg).strip().rstrip(";").strip()
    lower = msg.lower()
    if "unable to download" in lower or "urlopen error" in lower or "connection" in lower or "timed out" in lower:
        msg += (
            "\n\nYouTube could not be reached. Check your internet connection, VPN or proxy and try again."
        )
    elif "sign in to confirm" in lower or "not a bot" in lower or "cookies" in lower:
        msg += (
            "\n\nYouTube is asking for a signed-in browser. Fix: run with "
            "--cookies-from-browser chrome (or firefox/edge/safari), or set the "
            "YT_TRANSCRIBER_COOKIES_FROM_BROWSER environment variable before starting the app."
        )
    elif "private video" in lower:
        msg += "\n\nThis video is private, so its audio cannot be fetched."
    elif "video unavailable" in lower or "has been removed" in lower:
        msg += "\n\nCheck that the link is correct and the video is still online."
    elif "live event" in lower or "is live" in lower:
        msg += "\n\nLive streams can only be transcribed after they have ended."
    elif "unsupported url" in lower:
        msg += "\n\nOnly YouTube video links are supported."
    return msg


def download_audio(
    url: str,
    out_dir: str | Path,
    progress: ProgressCallback | None = None,
    cookies_from_browser: str | None = None,
    cookies_file: str | None = None,
) -> DownloadedAudio:
    """Download the best audio-only stream for `url` into `out_dir`."""
    import yt_dlp  # slow import, so it is deferred until needed

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    def hook(status: dict) -> None:
        if progress is None:
            return
        state = status.get("status")
        if state == "downloading":
            total = status.get("total_bytes") or status.get("total_bytes_estimate")
            done = status.get("downloaded_bytes") or 0
            fraction = min(done / total, 1.0) if total else None
            label = _human_size(done) + (f" / {_human_size(total)}" if total else "")
            progress(fraction, f"Downloading audio… {label}")
        elif state == "finished":
            progress(1.0, "Download finished")

    options: dict = {
        "format": "bestaudio/best",
        "outtmpl": str(out_dir / "%(id)s.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "logger": logging.getLogger("yt_transcriber.yt_dlp"),
        "progress_hooks": [hook],
        "retries": 3,
        "fragment_retries": 3,
        "overwrites": True,
    }
    if cookies_from_browser:
        options["cookiesfrombrowser"] = (cookies_from_browser,)
    if cookies_file:
        options["cookiefile"] = str(cookies_file)

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
            if info is None:
                raise DownloadError("yt-dlp returned nothing for this link.")
            if info.get("_type") == "playlist":
                entries = [entry for entry in (info.get("entries") or []) if entry]
                if not entries:
                    raise DownloadError("No downloadable video was found at this link.")
                info = entries[0]
            downloads = info.get("requested_downloads") or []
            filepath = downloads[0].get("filepath") if downloads else None
            if not filepath:
                filepath = ydl.prepare_filename(info)
    except yt_dlp.utils.DownloadError as exc:
        raise DownloadError(friendly_message(str(exc))) from exc

    path = Path(filepath)
    if not path.exists():
        raise DownloadError(f"The download finished but the file is missing: {path}")

    video_id = info.get("id") or path.stem
    return DownloadedAudio(
        path=path,
        video_id=video_id,
        title=info.get("title") or video_id,
        url=info.get("webpage_url") or url,
        duration=info.get("duration"),
        uploader=info.get("uploader") or info.get("channel"),
    )
