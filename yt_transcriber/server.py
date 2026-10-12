"""Local web app: a FastAPI JSON API plus the single-page UI in static/."""

from __future__ import annotations

import logging
import threading
import webbrowser
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from . import __version__
from .config import Settings
from .formats import FORMATS, MEDIA_TYPES, output_basename, render, write_outputs
from .jobs import Job, JobManager, JobStatus
from .pipeline import STAGE_LABELS, TranscribeOptions
from .transcriber import (
    LANGUAGE_CHOICES,
    LANGUAGE_LABELS,
    MODEL_CHOICES,
    MODEL_DESCRIPTIONS,
    resolve_device,
)
from .urls import extract_video_id, canonical_url
from .zh import SCRIPT_CHOICES, SCRIPT_LABELS

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

ModelName = Literal["tiny", "base", "small", "medium", "large-v3", "large-v3-turbo"]
FormatName = Literal["txt", "srt", "vtt", "json"]


class JobRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    language: Literal["auto", "zh", "en"] = "auto"
    chinese_script: Literal["keep", "simplified", "traditional"] = "keep"
    model: ModelName | None = None  # None -> server default


def _save_transcript(settings: Settings, job: Job) -> None:
    transcript = job.result
    if transcript is None:
        return
    paths = write_outputs(
        settings.output_dir,
        output_basename(transcript.title, transcript.video_id),
        transcript.segments,
        transcript.language,
        transcript.metadata(),
    )
    log.info("Saved %s", ", ".join(str(p) for p in paths))


def create_app(settings: Settings | None = None, manager: JobManager | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    if manager is None:
        manager = JobManager(on_complete=lambda job: _save_transcript(settings, job))

    app = FastAPI(title="YouTube Transcriber", version=__version__, docs_url="/api/docs", redoc_url=None)
    app.state.settings = settings
    app.state.manager = manager

    def get_job_or_404(job_id: str) -> Job:
        job = manager.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="No such job")
        return job

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index() -> str:
        return (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    @app.get("/api/config")
    def config() -> dict:
        return {
            "version": __version__,
            "device": resolve_device(settings.device),
            "default_model": settings.default_model,
            "output_dir": str(settings.output_dir),
            "models": [{"name": name, "description": MODEL_DESCRIPTIONS[name]} for name in MODEL_CHOICES],
            "languages": [{"value": code, "label": LANGUAGE_LABELS[code]} for code in LANGUAGE_CHOICES],
            "chinese_scripts": [{"value": code, "label": SCRIPT_LABELS[code]} for code in SCRIPT_CHOICES],
            "stages": STAGE_LABELS,
        }

    @app.post("/api/jobs", status_code=202)
    def create_job(request: JobRequest) -> dict:
        video_id = extract_video_id(request.url)
        if video_id is None:
            raise HTTPException(
                status_code=400,
                detail="That doesn't look like a YouTube video link. "
                "Paste something like https://www.youtube.com/watch?v=… or https://youtu.be/…",
            )
        options = TranscribeOptions(
            language=request.language,
            model=request.model or settings.default_model,
            chinese_script=request.chinese_script,
            device=settings.device,
            compute_type=settings.compute_type,
            model_dir=str(settings.model_dir) if settings.model_dir else None,
            cookies_from_browser=settings.cookies_from_browser,
            cookies_file=settings.cookies_file,
        )
        try:
            options.validate()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        job = manager.submit(canonical_url(video_id), options)
        return job.to_dict()

    @app.get("/api/jobs")
    def list_jobs() -> list[dict]:
        return [job.to_dict() for job in manager.list()]

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict:
        return get_job_or_404(job_id).to_dict(include_result=True)

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str) -> dict:
        job = get_job_or_404(job_id)
        if not manager.cancel(job_id):
            raise HTTPException(status_code=409, detail="This job has already finished")
        return job.to_dict()

    @app.get("/api/jobs/{job_id}/download")
    def download(job_id: str, format: FormatName = "txt") -> Response:
        job = get_job_or_404(job_id)
        if job.status is not JobStatus.DONE or job.result is None:
            raise HTTPException(status_code=409, detail="The transcript is not ready yet")
        transcript = job.result
        body = render(format, transcript.segments, transcript.language, transcript.metadata())
        filename = f"{output_basename(transcript.title, transcript.video_id)}.{format}"
        ascii_name = filename.encode("ascii", "ignore").decode("ascii").strip() or f"transcript.{format}"
        headers = {
            "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}",
        }
        return Response(content=body, media_type=MEDIA_TYPES[format], headers=headers)

    return app


def serve(settings: Settings | None = None, open_browser: bool = True) -> None:
    """Run the web app with uvicorn (blocks until Ctrl+C)."""
    import uvicorn

    settings = settings or Settings.from_env()
    app = create_app(settings)
    url = f"http://{settings.host}:{settings.port}"
    print(f"YouTube Transcriber is running at {url}  (Ctrl+C to stop)")
    print(f"Transcripts are saved to: {settings.output_dir.resolve()}")
    if open_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="warning")


# Keep the Pydantic Literal in sync with the single source of truth.
assert set(ModelName.__args__) == set(MODEL_CHOICES)  # type: ignore[attr-defined]
assert set(FormatName.__args__) == set(FORMATS)  # type: ignore[attr-defined]
