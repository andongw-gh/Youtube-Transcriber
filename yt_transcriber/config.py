"""Settings, read from environment variables prefixed YT_TRANSCRIBER_."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ENV_PREFIX = "YT_TRANSCRIBER_"


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(ENV_PREFIX + name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


@dataclass
class Settings:
    output_dir: Path = Path("transcripts")
    download_dir: Path = Path("downloads")
    model_dir: Path | None = None
    default_model: str = "small"
    device: str = "auto"
    compute_type: str = "auto"
    cookies_from_browser: str | None = None
    cookies_file: str | None = None
    host: str = "127.0.0.1"
    port: int = 8000

    @classmethod
    def from_env(cls) -> Settings:
        model_dir = _env("MODEL_DIR")
        port_raw = _env("PORT", "8000") or "8000"
        try:
            port = int(port_raw)
        except ValueError:
            port = 8000
        return cls(
            output_dir=Path(_env("OUTPUT_DIR", "transcripts") or "transcripts"),
            download_dir=Path(_env("DOWNLOAD_DIR", "downloads") or "downloads"),
            model_dir=Path(model_dir) if model_dir else None,
            default_model=_env("MODEL", "small") or "small",
            device=_env("DEVICE", "auto") or "auto",
            compute_type=_env("COMPUTE_TYPE", "auto") or "auto",
            cookies_from_browser=_env("COOKIES_FROM_BROWSER"),
            cookies_file=_env("COOKIES_FILE"),
            host=_env("HOST", "127.0.0.1") or "127.0.0.1",
            port=port,
        )
