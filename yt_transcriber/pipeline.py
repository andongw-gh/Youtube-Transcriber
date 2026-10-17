"""Link in, transcript out: download, decode, transcribe, post-process."""

from __future__ import annotations

import logging
import tempfile
from dataclasses import asdict, dataclass
from typing import Any
from collections.abc import Callable

from . import audio as audio_mod
from . import downloader, transcriber, zh
from .formats import Segment, join_text
from .urls import normalize_url

log = logging.getLogger(__name__)

# (stage, fraction 0..1 or None when unknown, human-readable message)
StageProgress = Callable[[str, "float | None", str], None]

STAGES = ("download", "decode", "load_model", "transcribe", "done")
STAGE_LABELS = {
    "queued": "Queued",
    "resolve": "Fetching info",
    "download": "Downloading",
    "convert": "Converting",
    "decode": "Decoding",
    "load_model": "Loading model",
    "transcribe": "Transcribing",
    "done": "Done",
    "error": "Failed",
    "cancelled": "Cancelled",
}


class Cancelled(Exception):
    """Raised from a progress callback to stop a run cleanly."""


@dataclass
class TranscribeOptions:
    language: str = "auto"          # auto | zh | en
    model: str = "small"            # see transcriber.MODEL_CHOICES
    chinese_script: str = "keep"    # keep | simplified | traditional
    device: str = "auto"            # auto | cpu | cuda
    compute_type: str = "auto"
    model_dir: str | None = None
    cookies_from_browser: str | None = None
    cookies_file: str | None = None
    beam_size: int = 5

    def validate(self) -> None:
        if self.language not in transcriber.LANGUAGE_CHOICES:
            raise ValueError(f"language must be one of {transcriber.LANGUAGE_CHOICES}")
        if self.model not in transcriber.MODEL_CHOICES:
            raise ValueError(f"model must be one of {transcriber.MODEL_CHOICES}")
        if self.chinese_script not in zh.SCRIPT_CHOICES:
            raise ValueError(f"chinese_script must be one of {zh.SCRIPT_CHOICES}")
        if self.device not in transcriber.DEVICE_CHOICES:
            raise ValueError(f"device must be one of {transcriber.DEVICE_CHOICES}")
        if self.compute_type not in transcriber.COMPUTE_TYPE_CHOICES:
            raise ValueError(f"compute_type must be one of {transcriber.COMPUTE_TYPE_CHOICES}")
        if self.beam_size < 1:
            raise ValueError("beam_size must be at least 1")

    def public_dict(self) -> dict[str, Any]:
        """Options safe to echo back to a browser (no cookie paths)."""
        data = asdict(self)
        data.pop("cookies_from_browser", None)
        data.pop("cookies_file", None)
        data.pop("model_dir", None)
        return data


@dataclass
class Transcript:
    video_id: str
    title: str
    url: str
    uploader: str | None
    duration: float
    language: str
    language_probability: float
    model: str
    segments: list[Segment]

    @property
    def text(self) -> str:
        return join_text(self.segments, self.language)

    def metadata(self) -> dict[str, Any]:
        return {
            "video_id": self.video_id,
            "title": self.title,
            "url": self.url,
            "uploader": self.uploader,
            "duration": round(self.duration, 3),
            "language": self.language,
            "language_probability": round(self.language_probability, 4),
            "model": self.model,
        }

    def summary(self) -> dict[str, Any]:
        """Light fields shown in job listings."""
        return {"language": self.language, "duration": round(self.duration, 3)}

    def to_dict(self) -> dict[str, Any]:
        data = self.metadata()
        data["text"] = self.text
        data["segments"] = [seg.to_dict() for seg in self.segments]
        return data


def run(
    url: str,
    options: TranscribeOptions | None = None,
    progress: StageProgress | None = None,
    work_dir: str | None = None,
) -> Transcript:
    """Transcribe one YouTube video. Raises on bad links, download or decode failures."""
    options = options or TranscribeOptions()
    options.validate()
    url = normalize_url(url)
    report: StageProgress = progress or (lambda stage, fraction, message: None)

    with tempfile.TemporaryDirectory(prefix="yt-transcriber-", dir=work_dir) as tmp:
        report("download", 0.0, "Contacting YouTube…")
        downloaded = downloader.download_audio(
            url,
            tmp,
            progress=lambda fraction, message: report("download", fraction, message),
            cookies_from_browser=options.cookies_from_browser,
            cookies_file=options.cookies_file,
        )
        report("decode", None, "Decoding audio…")
        pcm = audio_mod.load_audio(downloaded.path)

    report("load_model", None, f"Loading Whisper model “{options.model}”… (downloaded on first use)")
    model = transcriber.load_model(
        options.model,
        device=options.device,
        compute_type=options.compute_type,
        download_root=options.model_dir,
    )

    language = None if options.language == "auto" else options.language
    prompt = zh.SCRIPT_PROMPTS.get(options.chinese_script) if language == "zh" else None

    report("transcribe", 0.0, "Transcribing…")
    result = transcriber.transcribe_audio(
        pcm,
        model=model,
        language=language,
        hotwords=prompt,
        initial_prompt=prompt,
        beam_size=options.beam_size,
        progress=lambda fraction, message: report("transcribe", fraction, message),
    )

    segments = result.segments
    if options.chinese_script != "keep" and zh.is_chinese(result.language):
        segments = [
            Segment(seg.start, seg.end, zh.convert_script(seg.text, options.chinese_script))
            for seg in segments
        ]

    report("done", 1.0, "Done")
    return Transcript(
        video_id=downloaded.video_id,
        title=downloaded.title,
        url=downloaded.url,
        uploader=downloaded.uploader,
        duration=result.duration,
        language=result.language,
        language_probability=result.language_probability,
        model=options.model,
        segments=segments,
    )
