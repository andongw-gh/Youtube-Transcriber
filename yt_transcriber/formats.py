"""Transcript segments and the TXT / SRT / VTT / JSON renderers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from collections.abc import Iterable, Sequence

FORMATS = ("txt", "srt", "vtt", "json")
MEDIA_TYPES = {
    "txt": "text/plain; charset=utf-8",
    "srt": "application/x-subrip; charset=utf-8",
    "vtt": "text/vtt; charset=utf-8",
    "json": "application/json; charset=utf-8",
}

# Languages written without spaces between words.
_NO_SPACE_LANGUAGES = {"zh", "yue", "ja"}

# A pause at least this long starts a new paragraph in the plain-text rendering.
PARAGRAPH_GAP_SECONDS = 2.0
PARAGRAPH_MAX_CHARS = 1200


@dataclass
class Segment:
    start: float
    end: float
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {"start": round(self.start, 3), "end": round(self.end, 3), "text": self.text}


def format_timestamp(seconds: float, decimal_sep: str = ",") -> str:
    """HH:MM:SS,mmm (SRT) or HH:MM:SS.mmm (VTT)."""
    total_ms = max(0, int(round(seconds * 1000)))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{decimal_sep}{millis:03d}"


def format_clock(seconds: float) -> str:
    """Compact H:MM:SS / MM:SS for display."""
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _joiner(language: str | None) -> str:
    code = (language or "").lower().split("-")[0]
    return "" if code in _NO_SPACE_LANGUAGES else " "


def join_text(segments: Sequence[Segment], language: str | None = None) -> str:
    """Plain prose: segments joined into paragraphs, split at long pauses."""
    joiner = _joiner(language)
    paragraphs: list[str] = []
    current: list[str] = []
    current_len = 0
    previous_end: float | None = None

    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        long_pause = previous_end is not None and (seg.start - previous_end) >= PARAGRAPH_GAP_SECONDS
        too_long = current_len >= PARAGRAPH_MAX_CHARS
        if current and (long_pause or too_long):
            paragraphs.append(joiner.join(current))
            current, current_len = [], 0
        current.append(text)
        current_len += len(text)
        previous_end = seg.end

    if current:
        paragraphs.append(joiner.join(current))
    return "\n\n".join(paragraphs)


def to_txt(segments: Sequence[Segment], language: str | None = None) -> str:
    text = join_text(segments, language)
    return text + "\n" if text else ""


def to_timestamped_txt(segments: Sequence[Segment]) -> str:
    lines = [f"[{format_clock(seg.start)}] {seg.text.strip()}" for seg in segments if seg.text.strip()]
    return "\n".join(lines) + ("\n" if lines else "")


def to_srt(segments: Sequence[Segment]) -> str:
    blocks = []
    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        blocks.append(
            f"{len(blocks) + 1}\n"
            f"{format_timestamp(seg.start, ',')} --> {format_timestamp(seg.end, ',')}\n"
            f"{text}\n"
        )
    return "\n".join(blocks)


def to_vtt(segments: Sequence[Segment]) -> str:
    lines = ["WEBVTT", ""]
    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        lines.append(f"{format_timestamp(seg.start, '.')} --> {format_timestamp(seg.end, '.')}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)


def to_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def render(fmt: str, segments: Sequence[Segment], language: str | None, metadata: dict[str, Any]) -> str:
    """Render a transcript in one of FORMATS."""
    if fmt == "txt":
        return to_txt(segments, language)
    if fmt == "srt":
        return to_srt(segments)
    if fmt == "vtt":
        return to_vtt(segments)
    if fmt == "json":
        payload = dict(metadata)
        payload["language"] = language
        payload["text"] = join_text(segments, language)
        payload["segments"] = [seg.to_dict() for seg in segments]
        return to_json(payload)
    raise ValueError(f"Unknown format {fmt!r}; expected one of {', '.join(FORMATS)}")


_UNSAFE_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


def safe_filename(name: str, max_length: int = 80) -> str:
    """Make a title usable as a file name on Windows, macOS and Linux."""
    cleaned = _UNSAFE_CHARS.sub(" ", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip(" .")
    return cleaned or "transcript"


def output_basename(title: str, video_id: str) -> str:
    return f"{safe_filename(title)} [{video_id}]"


def write_outputs(
    output_dir: str | Path,
    basename: str,
    segments: Sequence[Segment],
    language: str | None,
    metadata: dict[str, Any],
    formats: Iterable[str] = FORMATS,
) -> list[Path]:
    """Write the transcript in each requested format; returns the written paths."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for fmt in formats:
        if fmt not in FORMATS:
            raise ValueError(f"Unknown format {fmt!r}; expected one of {', '.join(FORMATS)}")
        path = output_dir / f"{basename}.{fmt}"
        path.write_text(render(fmt, segments, language, metadata), encoding="utf-8")
        written.append(path)
    return written
