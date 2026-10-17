"""Recognise YouTube links and pull video / playlist ids out of them."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
PLAYLIST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{10,}$")

_YOUTUBE_DOMAINS = ("youtube.com", "youtube-nocookie.com")
_HOST_PREFIXES = ("www.", "m.", "music.")
_PATH_PREFIXES = ("/shorts/", "/live/", "/embed/", "/v/", "/e/")


class InvalidYouTubeURL(ValueError):
    """The text is not a link to a YouTube video or playlist."""


def _strip_host_prefix(host: str) -> str:
    for prefix in _HOST_PREFIXES:
        if host.startswith(prefix):
            return host[len(prefix):]
    return host


def _parse(text: str):
    """Return (host, path, query dict) for a YouTube link, or None for anything else."""
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
    if host != "youtu.be" and host not in _YOUTUBE_DOMAINS:
        return None
    return host, parsed.path or "", parse_qs(parsed.query)


def extract_video_id(text: str) -> str | None:
    """Return the 11-character video id from a YouTube URL, or None.

    Handles youtube.com/watch?v=, youtu.be/, /shorts/, /live/, /embed/ and
    mobile / music / nocookie hosts, with or without a scheme. Playlist-only
    links and non-YouTube links return None.
    """
    parsed = _parse(text)
    if parsed is None:
        return None
    host, path, query = parsed
    video_id: str | None = None

    if host == "youtu.be":
        trimmed = path.strip("/")
        video_id = trimmed.split("/")[0] if trimmed else None
    elif path.rstrip("/") == "/watch":
        video_id = query.get("v", [None])[0]
    else:
        for prefix in _PATH_PREFIXES:
            if path.startswith(prefix):
                video_id = path[len(prefix):].split("/")[0]
                break

    if video_id and VIDEO_ID_RE.match(video_id):
        return video_id
    return None


def extract_playlist_id(text: str) -> str | None:
    """Return the playlist id carried in a YouTube link's `list=` parameter, or None."""
    parsed = _parse(text)
    if parsed is None:
        return None
    playlist_id = parsed[2].get("list", [None])[0]
    if playlist_id and PLAYLIST_ID_RE.match(playlist_id):
        return playlist_id
    return None


def canonical_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def playlist_url(playlist_id: str) -> str:
    return f"https://www.youtube.com/playlist?list={playlist_id}"


@dataclass(frozen=True)
class YouTubeLink:
    """What a pasted link points at: a video, a playlist, or a video inside a playlist."""

    video_id: str | None
    playlist_id: str | None

    @property
    def kind(self) -> str:
        if self.video_id and self.playlist_id:
            return "video_in_playlist"
        return "video" if self.video_id else "playlist"

    @property
    def video_url(self) -> str | None:
        return canonical_url(self.video_id) if self.video_id else None

    @property
    def playlist_url(self) -> str | None:
        return playlist_url(self.playlist_id) if self.playlist_id else None

    def target_url(self, whole_playlist: bool = False) -> str:
        """The unambiguous URL to hand to yt-dlp.

        A playlist-only link always means the playlist. A video that also
        carries a playlist id means the playlist only when asked for.
        """
        if self.playlist_id and (whole_playlist or not self.video_id):
            return playlist_url(self.playlist_id)
        assert self.video_id is not None
        return canonical_url(self.video_id)


def parse_link(text: str) -> YouTubeLink | None:
    """Classify a YouTube link; None when it is neither a video nor a playlist."""
    video_id = extract_video_id(text)
    playlist_id = extract_playlist_id(text)
    if video_id is None and playlist_id is None:
        return None
    return YouTubeLink(video_id=video_id, playlist_id=playlist_id)


def normalize_url(text: str) -> str:
    """Turn any accepted YouTube video link into its canonical watch URL.

    Raises InvalidYouTubeURL when the text is not a single-video link.
    """
    video_id = extract_video_id(text)
    if video_id is None:
        raise InvalidYouTubeURL(
            "That doesn't look like a link to a YouTube video. "
            "Paste a link such as https://www.youtube.com/watch?v=... or https://youtu.be/..."
        )
    return canonical_url(video_id)
