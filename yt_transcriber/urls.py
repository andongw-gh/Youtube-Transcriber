"""Recognise YouTube links and pull the video id out of them."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

_YOUTUBE_DOMAINS = ("youtube.com", "youtube-nocookie.com")
_HOST_PREFIXES = ("www.", "m.", "music.")
_PATH_PREFIXES = ("/shorts/", "/live/", "/embed/", "/v/", "/e/")


class InvalidYouTubeURL(ValueError):
    """The text is not a link to a single YouTube video."""


def _strip_host_prefix(host: str) -> str:
    for prefix in _HOST_PREFIXES:
        if host.startswith(prefix):
            return host[len(prefix):]
    return host


def extract_video_id(text: str) -> str | None:
    """Return the 11-character video id from a YouTube URL, or None.

    Handles youtube.com/watch?v=, youtu.be/, /shorts/, /live/, /embed/ and
    mobile / music / nocookie hosts, with or without a scheme. Playlist-only
    links and non-YouTube links return None.
    """
    if not text:
        return None
    candidate = text.strip()
    if not candidate:
        return None
    if "://" not in candidate:
        candidate = "https://" + candidate
    try:
        parsed = urlparse(candidate)
    except ValueError:
        return None

    host = _strip_host_prefix((parsed.hostname or "").lower())
    path = parsed.path or ""
    video_id: str | None = None

    if host == "youtu.be":
        trimmed = path.strip("/")
        video_id = trimmed.split("/")[0] if trimmed else None
    elif host in _YOUTUBE_DOMAINS:
        if path.rstrip("/") == "/watch":
            video_id = parse_qs(parsed.query).get("v", [None])[0]
        else:
            for prefix in _PATH_PREFIXES:
                if path.startswith(prefix):
                    video_id = path[len(prefix):].split("/")[0]
                    break

    if video_id and VIDEO_ID_RE.match(video_id):
        return video_id
    return None


def canonical_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def normalize_url(text: str) -> str:
    """Turn any accepted YouTube link into its canonical watch URL.

    Raises InvalidYouTubeURL when the text is not a single-video link.
    """
    video_id = extract_video_id(text)
    if video_id is None:
        raise InvalidYouTubeURL(
            "That doesn't look like a link to a YouTube video. "
            "Paste a link such as https://www.youtube.com/watch?v=... or https://youtu.be/..."
        )
    return canonical_url(video_id)
