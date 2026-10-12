"""Run Whisper (via faster-whisper) over decoded audio."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any
from collections.abc import Callable

import numpy as np

from .audio import SAMPLE_RATE
from .formats import Segment, format_clock

log = logging.getLogger(__name__)

ProgressCallback = Callable[[float | None, str], None]

MODEL_CHOICES = ("tiny", "base", "small", "medium", "large-v3", "large-v3-turbo")
MODEL_DESCRIPTIONS = {
    "tiny": "Fastest, rough. English only really usable.",
    "base": "Fast, basic quality.",
    "small": "Good balance on a laptop CPU. Fine for clear English; OK for Chinese.",
    "medium": "Noticeably better Chinese. Slow on CPU, fine on GPU.",
    "large-v3": "Best accuracy. Needs a GPU or a lot of patience.",
    "large-v3-turbo": "Near large-v3 accuracy, several times faster. Best pick with a GPU or a strong CPU.",
}
LANGUAGE_CHOICES = ("auto", "zh", "en")
LANGUAGE_LABELS = {"auto": "Auto-detect / 自动识别", "zh": "Chinese / 中文", "en": "English"}
DEVICE_CHOICES = ("auto", "cpu", "cuda")
COMPUTE_TYPE_CHOICES = ("auto", "int8", "int8_float16", "float16", "float32")


@dataclass
class TranscriptResult:
    language: str
    language_probability: float
    duration: float
    segments: list[Segment]


def cuda_available() -> bool:
    try:
        import ctranslate2

        return ctranslate2.get_cuda_device_count() > 0
    except Exception:  # pragma: no cover - depends on the machine
        return False


def resolve_device(device: str = "auto") -> str:
    if device == "auto":
        return "cuda" if cuda_available() else "cpu"
    return device


def resolve_compute_type(compute_type: str, device: str) -> str:
    if compute_type != "auto":
        return compute_type
    return "float16" if device == "cuda" else "int8"


_model_cache: dict[tuple, Any] = {}
_model_lock = threading.Lock()


def load_model(
    model_size: str = "small",
    device: str = "auto",
    compute_type: str = "auto",
    download_root: str | None = None,
    cpu_threads: int = 0,
):
    """Load (and cache) a faster-whisper model. The first call downloads it."""
    if model_size not in MODEL_CHOICES:
        raise ValueError(f"Unknown model {model_size!r}; choose from {', '.join(MODEL_CHOICES)}")
    resolved_device = resolve_device(device)
    resolved_compute = resolve_compute_type(compute_type, resolved_device)
    key = (model_size, resolved_device, resolved_compute, download_root, cpu_threads)
    with _model_lock:
        model = _model_cache.get(key)
        if model is None:
            from faster_whisper import WhisperModel

            log.info("Loading Whisper model %s on %s (%s)", model_size, resolved_device, resolved_compute)
            model = WhisperModel(
                model_size,
                device=resolved_device,
                compute_type=resolved_compute,
                download_root=download_root,
                cpu_threads=cpu_threads,
            )
            _model_cache.clear()  # keep a single model in memory
            _model_cache[key] = model
    return model


def transcribe_audio(
    audio: np.ndarray,
    model,
    language: str | None = None,
    hotwords: str | None = None,
    initial_prompt: str | None = None,
    beam_size: int = 5,
    progress: ProgressCallback | None = None,
) -> TranscriptResult:
    """Transcribe a 16 kHz mono float32 array.

    `language` None means auto-detect. `hotwords` is re-injected into every
    30-second window, which is how we keep Chinese in the requested script.
    """
    duration = float(len(audio)) / SAMPLE_RATE
    segments_iter, info = model.transcribe(
        audio,
        language=language,
        beam_size=beam_size,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        # Not feeding the previous window back avoids the repetition loops Whisper
        # is prone to on long Chinese audio; hotwords carry the style instead.
        condition_on_previous_text=False,
        initial_prompt=initial_prompt,
        hotwords=hotwords,
        language_detection_segments=3,
    )

    segments: list[Segment] = []
    for seg in segments_iter:
        text = seg.text.strip()
        if text:
            segments.append(Segment(start=float(seg.start), end=float(seg.end), text=text))
        if progress is not None:
            fraction = min(float(seg.end) / duration, 1.0) if duration > 0 else None
            progress(fraction, f"Transcribing… {format_clock(seg.end)} / {format_clock(duration)}")

    return TranscriptResult(
        language=info.language,
        language_probability=float(info.language_probability),
        duration=float(info.duration or duration),
        segments=segments,
    )
