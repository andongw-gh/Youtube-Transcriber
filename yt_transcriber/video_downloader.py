"""Download YouTube videos or whole playlists, as video (MP4) or audio only."""

from __future__ import annotations

import logging
import os
import re
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .downloader import DownloadError, friendly_message
from .formats import format_clock
from .pipeline import Cancelled, StageProgress
from .urls import InvalidYouTubeURL, parse_link

log = logging.getLogger(__name__)

MODE_CHOICES = ("video", "audio")
MODE_LABELS = {"video": "Video (MP4)", "audio": "Audio only"}
QUALITY_CHOICES = ("best", "2160", "1440", "1080", "720", "480", "360")
QUALITY_LABELS = {
    "best": "Best available (up to 4K / 8K)",
    "2160": "4K (2160p)",
    "1440": "1440p",
    "1080": "1080p (recommended)",
    "720": "720p",
    "480": "480p",
    "360": "360p",
}
AUDIO_FORMAT_CHOICES = ("mp3", "m4a")
AUDIO_FORMAT_LABELS = {"mp3": "MP3", "m4a": "M4A (original AAC, no re-encoding)"}

SINGLE_TEMPLATE = "%(title)s [%(id)s].%(ext)s"
PLAYLIST_TEMPLATE = "%(playlist_title|Playlist)s/%(playlist_index)s - %(title)s [%(id)s].%(ext)s"

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_PREFIX = re.compile(r"^(?:WARNING|ERROR):\s*", re.I)
_VIDEO_PREFIX = re.compile(r"^\[[\w:.-]+\]\s*([A-Za-z0-9_-]{11}):\s*")


@dataclass
class DownloadOptions:
    mode: str = "video"            # video | audio
    quality: str = "1080"          # best | 2160 | 1440 | 1080 | 720 | 480 | 360 (video only)
    audio_format: str = "mp3"      # mp3 | m4a (audio only)
    output_dir: str = "downloads"
    cookies_from_browser: str | None = None
    cookies_file: str | None = None

    def validate(self) -> None:
        if self.mode not in MODE_CHOICES:
            raise ValueError(f"mode must be one of {MODE_CHOICES}")
        if self.quality not in QUALITY_CHOICES:
            raise ValueError(f"quality must be one of {QUALITY_CHOICES}")
        if self.audio_format not in AUDIO_FORMAT_CHOICES:
            raise ValueError(f"audio_format must be one of {AUDIO_FORMAT_CHOICES}")

    def public_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("cookies_from_browser", None)
        data.pop("cookies_file", None)
        return data


@dataclass
class DownloadedItem:
    title: str
    path: str
    size_bytes: int
    video_id: str | None = None
    index: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "filename": Path(self.path).name,
            "path": self.path,
            "size_bytes": self.size_bytes,
            "video_id": self.video_id,
            "index": self.index,
        }


@dataclass
class DownloadResult:
    title: str
    url: str
    kind: str                       # video | playlist
    output_dir: str
    mode: str
    quality: str
    audio_format: str
    items: list[DownloadedItem] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    expected_count: int | None = None

    @property
    def total_bytes(self) -> int:
        return sum(item.size_bytes for item in self.items)

    def summary(self) -> dict[str, Any]:
        return {
            "download_kind": self.kind,
            "item_count": len(self.items),
            "failed_count": len(self.failures),
            "total_bytes": self.total_bytes,
            "output_dir": self.output_dir,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "kind": self.kind,
            "output_dir": self.output_dir,
            "mode": self.mode,
            "quality": self.quality,
            "audio_format": self.audio_format,
            "expected_count": self.expected_count,
            "item_count": len(self.items),
            "total_bytes": self.total_bytes,
            "items": [item.to_dict() for item in self.items],
            "failures": self.failures,
            "warnings": self.warnings,
        }


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def human_size(num_bytes: float) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def build_ydl_options(options: DownloadOptions, out_dir: Path, is_playlist: bool, ffmpeg: bool) -> dict[str, Any]:
    """The yt-dlp parameters for one run (hooks and logger are added by run())."""
    opts: dict[str, Any] = {
        "paths": {"home": str(out_dir)},
        "outtmpl": PLAYLIST_TEMPLATE if is_playlist else SINGLE_TEMPLATE,
        "noplaylist": True,                 # URLs handed to yt-dlp are already unambiguous
        "ignoreerrors": "only_download",    # a broken video must not stop the playlist
        "quiet": True,
        "no_warnings": False,
        "noprogress": True,
        "retries": 5,
        "fragment_retries": 5,
        "concurrent_fragment_downloads": 4,
        "windowsfilenames": True,           # files may end up on Windows or in OneDrive
        "trim_file_name": 120,
        "postprocessors": [],
    }
    if options.mode == "audio":
        if ffmpeg:
            opts["format"] = "bestaudio/best"
            opts["postprocessors"].append(
                {"key": "FFmpegExtractAudio", "preferredcodec": options.audio_format, "preferredquality": "0"}
            )
        else:
            opts["format"] = "bestaudio[ext=m4a]/bestaudio/best"
    else:
        resolution = "res" if options.quality == "best" else f"res:{options.quality}"
        # Resolution first, then h264 over vp9/av1, then mp4/m4a containers: the most
        # compatible file at the requested size.
        opts["format_sort"] = [resolution, "vcodec:h264", "ext:mp4:m4a"]
        if ffmpeg:
            opts["format"] = "bv*+ba/b"
            opts["merge_output_format"] = "mp4"
        else:
            opts["format"] = "b"            # single-file streams only (YouTube: up to 720p)
    if options.cookies_from_browser:
        opts["cookiesfrombrowser"] = (options.cookies_from_browser,)
    if options.cookies_file:
        opts["cookiefile"] = str(options.cookies_file)
    return opts


class _Collector:
    """yt-dlp logger that keeps warnings and per-video errors for the result."""

    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.errors: list[str] = []

    @staticmethod
    def _clean(message: str) -> str:
        return _PREFIX.sub("", _ANSI.sub("", str(message)).strip())

    def debug(self, message: str) -> None:
        log.debug("%s", message)

    def info(self, message: str) -> None:
        log.debug("%s", message)

    def warning(self, message: str) -> None:
        text = self._clean(message)
        if text and text not in self.warnings:
            self.warnings.append(text)

    def error(self, message: str) -> None:
        text = self._clean(message)
        if not text:
            return
        friendly = friendly_message(text)
        # Keep the video id so a failure inside a playlist can be traced to its video.
        match = _VIDEO_PREFIX.match(text)
        if match and not friendly.startswith(match.group(1)):
            friendly = f"{match.group(1)}: {friendly}"
        self.errors.append(friendly)


def _expected_bytes(info: dict[str, Any]) -> int | None:
    """Total size of a merged (video + audio) download when every part reports one."""
    formats = info.get("requested_formats")
    if not formats:
        return None
    total = 0
    for fmt in formats:
        size = fmt.get("filesize") or fmt.get("filesize_approx")
        if not size:
            return None
        total += int(size)
    return total


class _Tracker:
    """Turns yt-dlp hook calls into stage progress and remembers finished files."""

    def __init__(self, report: StageProgress, is_playlist: bool, cancel_exception: type[BaseException]):
        self.report = report
        self.is_playlist = is_playlist
        self.cancel_exception = cancel_exception
        self.files: list[str] = []
        self.current_id: str | None = None
        self.current_title: str = ""
        self.current_index: int | None = None
        self.total: int | None = None
        self.finished_bytes = 0

    def _track_entry(self, info: dict[str, Any]) -> None:
        video_id = info.get("id")
        if video_id != self.current_id:
            self.current_id = video_id
            self.current_title = info.get("title") or video_id or ""
            self.finished_bytes = 0
            self.current_index = info.get("playlist_index")
            self.total = info.get("n_entries") or info.get("playlist_count") or self.total

    def _overall(self, entry_fraction: float | None) -> float | None:
        if entry_fraction is None:
            return None
        if self.is_playlist and self.total and self.current_index:
            return min(((self.current_index - 1) + entry_fraction) / self.total, 1.0)
        return min(entry_fraction, 1.0)

    def _prefix(self) -> str:
        if not self.is_playlist or not self.current_index:
            return ""
        return f"{self.current_index}/{self.total} · " if self.total else f"#{self.current_index} · "

    def _emit(self, stage: str, fraction: float | None, message: str) -> None:
        try:
            self.report(stage, fraction, message)
        except Cancelled as exc:
            # Only DownloadCancelled escapes yt-dlp's ignoreerrors handling.
            raise self.cancel_exception("Cancelled by user") from exc

    def on_progress(self, status: dict[str, Any]) -> None:
        state = status.get("status")
        info = status.get("info_dict") or {}
        self._track_entry(info)
        if state == "downloading":
            downloaded = status.get("downloaded_bytes") or 0
            total = status.get("total_bytes") or status.get("total_bytes_estimate")
            expected = _expected_bytes(info)
            if expected:
                fraction: float | None = min((self.finished_bytes + downloaded) / expected, 1.0)
            elif total:
                fraction = min(downloaded / total, 1.0)
            else:
                fraction = None
            bits = [f"{int(fraction * 100)}%" if fraction is not None else human_size(downloaded)]
            speed = status.get("speed")
            eta = status.get("eta")
            if speed:
                bits.append(f"{human_size(speed)}/s")
            if eta:
                bits.append(f"{format_clock(eta)} left")
            self._emit("download", self._overall(fraction), f"{self._prefix()}{' · '.join(bits)} · {self.current_title}")
        elif state == "finished":
            self.finished_bytes += status.get("total_bytes") or status.get("downloaded_bytes") or 0
            self._emit("download", self._overall(1.0), f"{self._prefix()}Downloaded · {self.current_title}")

    def on_postprocess(self, status: dict[str, Any]) -> None:
        if status.get("status") != "started":
            return
        info = status.get("info_dict") or {}
        self._track_entry(info)
        name = status.get("postprocessor") or ""
        if name == "MoveFiles":
            return
        if name == "Merger":
            message = "Merging video and audio…"
        elif name == "ExtractAudio":
            message = "Converting audio…"
        else:
            message = f"Processing ({name})…"
        self._emit("convert", self._overall(1.0), f"{self._prefix()}{message} · {self.current_title}")

    def on_file_done(self, filepath: str) -> None:
        self.files.append(filepath)


def _collect_items(info: dict[str, Any], tracker: _Tracker, is_playlist: bool) -> tuple[str, list[DownloadedItem], int | None]:
    if is_playlist or info.get("_type") == "playlist":
        title = info.get("title") or "Playlist"
        raw_entries = info.get("entries") or []
        entries = [entry for entry in raw_entries if entry]
        expected = info.get("playlist_count") or len(raw_entries) or None
    else:
        title = info.get("title") or info.get("id") or "Video"
        entries = [info]
        expected = 1

    by_path: dict[str, dict[str, Any]] = {}
    for entry in entries:
        candidates = [d.get("filepath") for d in (entry.get("requested_downloads") or [])]
        candidates.append(entry.get("filepath"))
        for path in candidates:
            if path:
                by_path[os.path.abspath(path)] = entry

    items: list[DownloadedItem] = []
    seen: set[str] = set()

    def add(path: str, entry: dict[str, Any]) -> None:
        key = os.path.abspath(path)
        if key in seen or not os.path.exists(key):
            return
        seen.add(key)
        items.append(
            DownloadedItem(
                title=entry.get("title") or Path(path).stem,
                path=key,
                size_bytes=os.path.getsize(key),
                video_id=entry.get("id"),
                index=entry.get("playlist_index"),
            )
        )

    for path in tracker.files:                       # completion order, from post_hooks
        add(path, by_path.get(os.path.abspath(path), {}))
    for path, entry in by_path.items():              # anything the hooks missed
        add(path, entry)
    items.sort(key=lambda item: ((item.index or 0), item.title))
    return title, items, expected


def run(url: str, options: DownloadOptions | None = None, progress: StageProgress | None = None) -> DownloadResult:
    """Download one video or a whole playlist. `url` must be a YouTube video or playlist link."""
    link = parse_link(url)
    if link is None:
        raise InvalidYouTubeURL(
            "That doesn't look like a YouTube video or playlist link. "
            "Paste a link such as https://www.youtube.com/watch?v=… or https://www.youtube.com/playlist?list=…"
        )
    is_playlist = link.kind == "playlist"
    return download_url(link.target_url(whole_playlist=is_playlist), options, progress, is_playlist=is_playlist)


def download_url(
    target: str,
    options: DownloadOptions | None = None,
    progress: StageProgress | None = None,
    is_playlist: bool = False,
) -> DownloadResult:
    """Run yt-dlp on an already-validated URL (any site yt-dlp supports)."""
    options = options or DownloadOptions()
    options.validate()
    report: StageProgress = progress or (lambda stage, fraction, message: None)

    import yt_dlp  # slow import, deferred until needed
    from yt_dlp.utils import DownloadCancelled

    out_dir = Path(options.output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    ffmpeg = ffmpeg_available()
    collector = _Collector()
    tracker = _Tracker(report, is_playlist, DownloadCancelled)
    if not ffmpeg:
        collector.warnings.append(
            "ffmpeg is not installed, so video is limited to 720p single-file streams and audio is "
            "saved as M4A without conversion. Install ffmpeg for full quality."
        )

    ydl_opts = build_ydl_options(options, out_dir, is_playlist, ffmpeg)
    ydl_opts.update(
        logger=collector,
        progress_hooks=[tracker.on_progress],
        postprocessor_hooks=[tracker.on_postprocess],
        post_hooks=[tracker.on_file_done],
    )

    report("resolve", None, "Fetching information from YouTube…")
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(target, download=True)
    except DownloadCancelled as exc:
        raise Cancelled() from exc
    except yt_dlp.utils.DownloadError as exc:
        raise DownloadError(friendly_message(str(exc))) from exc

    if info is None:
        detail = collector.errors[-1] if collector.errors else "yt-dlp returned nothing for this link."
        raise DownloadError(detail)

    title, items, expected = _collect_items(info, tracker, is_playlist)
    if not items:
        detail = collector.errors[-1] if collector.errors else "Nothing was downloaded."
        raise DownloadError(detail)

    report("done", 1.0, "Done")
    return DownloadResult(
        title=title,
        url=target,
        kind="playlist" if is_playlist else "video",
        output_dir=str(Path(items[0].path).parent),
        mode=options.mode,
        quality=options.quality,
        audio_format=options.audio_format,
        items=items,
        failures=collector.errors,
        warnings=collector.warnings,
        expected_count=expected,
    )
