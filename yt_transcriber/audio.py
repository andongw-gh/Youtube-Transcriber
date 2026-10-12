"""Decode downloaded media to the 16 kHz mono float32 PCM Whisper expects."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16000


class AudioDecodeError(RuntimeError):
    """The media file could not be decoded."""


def ffmpeg_path() -> str | None:
    return shutil.which("ffmpeg")


def load_audio(path: str | Path, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Decode any audio/video container to a mono float32 array in [-1, 1].

    Uses the ffmpeg binary when present (fast, handles every format YouTube
    serves) and falls back to faster-whisper's PyAV-based decoder otherwise.
    """
    path = Path(path)
    if not path.exists():
        raise AudioDecodeError(f"Audio file not found: {path}")

    ffmpeg = ffmpeg_path()
    if ffmpeg:
        cmd = [
            ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
            "-i", str(path),
            "-vn", "-ac", "1", "-ar", str(sample_rate),
            "-f", "s16le", "-acodec", "pcm_s16le", "-",
        ]
        proc = subprocess.run(cmd, capture_output=True)
        if proc.returncode != 0:
            detail = proc.stderr.decode("utf-8", errors="replace").strip()
            raise AudioDecodeError(f"ffmpeg could not decode {path.name}: {detail}")
        pcm = np.frombuffer(proc.stdout, dtype=np.int16)
        return pcm.astype(np.float32) / 32768.0

    try:
        from faster_whisper import decode_audio
    except ImportError as exc:  # pragma: no cover - faster-whisper is a hard dependency
        raise AudioDecodeError("Neither ffmpeg nor faster-whisper is available to decode audio") from exc
    try:
        return decode_audio(str(path), sampling_rate=sample_rate)
    except Exception as exc:
        raise AudioDecodeError(
            f"Could not decode {path.name} ({exc}). Installing ffmpeg fixes this on most systems."
        ) from exc


def duration_seconds(audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> float:
    return float(len(audio)) / float(sample_rate)
