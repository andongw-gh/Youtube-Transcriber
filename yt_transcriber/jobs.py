"""A small in-process job queue: one worker thread per job kind.

Transcriptions are CPU-bound and downloads are network-bound, so each kind has
its own worker and queue; within a kind, jobs run one after another.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .pipeline import Cancelled, StageProgress
from .pipeline import run as run_pipeline

log = logging.getLogger(__name__)

# A runner takes (url, options, progress) and returns a result object exposing
# `.title`, `.summary() -> dict` and `.to_dict() -> dict`.
Runner = Callable[[str, Any, StageProgress], Any]

DEFAULT_KIND = "transcribe"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"

    @property
    def finished(self) -> bool:
        return self in (JobStatus.DONE, JobStatus.ERROR, JobStatus.CANCELLED)


@dataclass
class Job:
    id: str
    url: str
    options: Any
    kind: str = DEFAULT_KIND
    status: JobStatus = JobStatus.QUEUED
    stage: str = "queued"
    progress: float | None = 0.0
    message: str = "Waiting in queue"
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    result: Any = None
    error: str | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False, compare=False)

    def to_dict(self, include_result: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "url": self.url,
            "status": self.status.value,
            "stage": self.stage,
            "progress": self.progress,
            "message": self.message,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "options": self.options.public_dict() if hasattr(self.options, "public_dict") else {},
            "title": getattr(self.result, "title", None) if self.result is not None else None,
        }
        if self.result is not None and hasattr(self.result, "summary"):
            data.update(self.result.summary())
        if include_result and self.result is not None:
            data["result"] = self.result.to_dict()
        return data


class JobManager:
    """Queue jobs by kind and run each kind on its own worker thread."""

    def __init__(
        self,
        runners: Mapping[str, Runner] | Runner | None = None,
        on_complete: Callable[[Job], None] | None = None,
        max_jobs: int = 200,
    ):
        if runners is None:
            runners = {DEFAULT_KIND: run_pipeline}
        elif callable(runners):
            runners = {DEFAULT_KIND: runners}
        self._runners: dict[str, Runner] = dict(runners)
        self._on_complete = on_complete
        self._max_jobs = max_jobs
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._queues: dict[str, queue.Queue[str]] = {kind: queue.Queue() for kind in self._runners}
        for kind in self._runners:
            threading.Thread(
                target=self._loop, args=(kind,), name=f"yt-transcriber-{kind}", daemon=True
            ).start()

    # -- public API -----------------------------------------------------------------

    @property
    def kinds(self) -> tuple[str, ...]:
        return tuple(self._runners)

    def submit(self, url: str, options: Any, kind: str = DEFAULT_KIND) -> Job:
        if kind not in self._runners:
            raise ValueError(f"Unknown job kind {kind!r}; expected one of {', '.join(self._runners)}")
        job = Job(id=uuid.uuid4().hex[:12], url=url, options=options, kind=kind)
        with self._lock:
            self._jobs[job.id] = job
            self._prune_locked()
        self._queues[kind].put(job.id)
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self, kind: str | None = None) -> list[Job]:
        with self._lock:
            jobs = [job for job in self._jobs.values() if kind is None or job.kind == kind]
        return sorted(jobs, key=lambda job: job.created_at, reverse=True)

    def cancel(self, job_id: str) -> bool:
        """Ask a job to stop. Returns False if it does not exist or has already finished."""
        job = self.get(job_id)
        if job is None or job.status.finished:
            return False
        job.cancel_event.set()
        if job.status is JobStatus.QUEUED:
            self._finish(job, JobStatus.CANCELLED, stage="cancelled", message="Cancelled")
        else:
            job.message = "Cancelling…"
        return True

    def wait(self, job_id: str, timeout: float = 30.0) -> Job:
        """Block until the job finishes (handy for tests and scripts)."""
        deadline = time.monotonic() + timeout
        while True:
            job = self.get(job_id)
            if job is None:
                raise KeyError(job_id)
            if job.status.finished:
                return job
            if time.monotonic() > deadline:
                raise TimeoutError(f"Job {job_id} did not finish within {timeout}s")
            time.sleep(0.02)

    # -- internals ------------------------------------------------------------------

    def _prune_locked(self) -> None:
        if len(self._jobs) <= self._max_jobs:
            return
        finished = sorted(
            (job for job in self._jobs.values() if job.status.finished),
            key=lambda job: job.created_at,
        )
        for job in finished[: len(self._jobs) - self._max_jobs]:
            self._jobs.pop(job.id, None)

    @staticmethod
    def _finish(job: Job, status: JobStatus, stage: str, message: str, error: str | None = None) -> None:
        job.status = status
        job.stage = stage
        job.message = message
        job.error = error
        job.finished_at = time.time()

    def _loop(self, kind: str) -> None:
        pending = self._queues[kind]
        while True:
            job_id = pending.get()
            job = self.get(job_id)
            if job is None or job.status is not JobStatus.QUEUED:
                continue
            self._execute(job)

    def _execute(self, job: Job) -> None:
        job.status = JobStatus.RUNNING
        job.started_at = time.time()
        job.stage = "resolve" if job.kind != DEFAULT_KIND else "download"
        job.progress = 0.0
        job.message = "Starting…"

        def progress(stage: str, fraction: float | None, message: str) -> None:
            if job.cancel_event.is_set():
                raise Cancelled()
            job.stage = stage
            job.progress = fraction
            job.message = message

        try:
            if job.cancel_event.is_set():
                raise Cancelled()
            job.result = self._runners[job.kind](job.url, job.options, progress)
            job.progress = 1.0
            job.stage = "done"
            job.message = "Saving…"
            # Runs before the job is marked finished, so anyone waiting on "done"
            # (the UI, tests, scripts) can rely on the hook's side effects.
            if self._on_complete is not None:
                try:
                    self._on_complete(job)
                except Exception:  # noqa: BLE001 - a failed save must not lose the result
                    log.exception("on_complete hook failed for job %s", job.id)
            self._finish(job, JobStatus.DONE, stage="done", message="Done")
        except Cancelled:
            self._finish(job, JobStatus.CANCELLED, stage="cancelled", message="Cancelled")
        except Exception as exc:  # noqa: BLE001 - surface anything to the user
            log.exception("Job %s failed", job.id)
            self._finish(job, JobStatus.ERROR, stage="error", message="Failed", error=str(exc) or type(exc).__name__)
