import threading
import time

import pytest

from yt_transcriber.jobs import JobManager, JobStatus
from yt_transcriber.pipeline import TranscribeOptions


def make_runner(transcript, delay=0.0, fail=False, steps=3):
    def runner(url, options, progress):
        for i in range(steps):
            progress("transcribe", i / steps, f"step {i}")
            if delay:
                time.sleep(delay)
        if fail:
            raise RuntimeError("boom")
        progress("done", 1.0, "Done")
        return transcript
    return runner


def test_job_runs_to_completion(sample_transcript):
    saved = []
    manager = JobManager(runners=make_runner(sample_transcript), on_complete=saved.append)
    job = manager.submit("https://www.youtube.com/watch?v=dQw4w9WgXcQ", TranscribeOptions())
    assert job.status is JobStatus.QUEUED
    done = manager.wait(job.id, timeout=5)
    assert done.status is JobStatus.DONE
    assert done.result is sample_transcript
    assert done.progress == 1.0
    assert done.started_at and done.finished_at
    assert saved == [done]
    data = done.to_dict(include_result=True)
    assert data["title"] == sample_transcript.title
    assert data["result"]["segments"]


def test_job_error_is_recorded(sample_transcript):
    manager = JobManager(runners=make_runner(sample_transcript, fail=True))
    job = manager.submit("u", TranscribeOptions())
    done = manager.wait(job.id, timeout=5)
    assert done.status is JobStatus.ERROR
    assert done.error == "boom"
    assert done.result is None
    assert "result" not in done.to_dict(include_result=True)


def test_jobs_run_sequentially_in_order(sample_transcript):
    order = []

    def runner(url, options, progress):
        order.append(url)
        time.sleep(0.05)
        return sample_transcript

    manager = JobManager(runners=runner)
    jobs = [manager.submit(f"u{i}", TranscribeOptions()) for i in range(3)]
    for job in jobs:
        manager.wait(job.id, timeout=5)
    assert order == ["u0", "u1", "u2"]
    assert [j.id for j in manager.list()] == [j.id for j in reversed(jobs)]


def test_cancel_queued_job(sample_transcript):
    gate = threading.Event()

    def slow_runner(url, options, progress):
        gate.wait(5)
        return sample_transcript

    manager = JobManager(runners=slow_runner)
    first = manager.submit("first", TranscribeOptions())
    second = manager.submit("second", TranscribeOptions())
    time.sleep(0.05)
    assert manager.cancel(second.id) is True
    assert second.status is JobStatus.CANCELLED
    gate.set()
    assert manager.wait(first.id, timeout=5).status is JobStatus.DONE
    assert manager.wait(second.id, timeout=5).status is JobStatus.CANCELLED


def test_cancel_running_job_stops_at_next_progress(sample_transcript):
    started = threading.Event()
    release = threading.Event()

    def runner(url, options, progress):
        progress("download", 0.1, "going")
        started.set()
        release.wait(5)
        progress("download", 0.5, "still going")  # raises Cancelled
        raise AssertionError("should not get here")

    manager = JobManager(runners=runner)
    job = manager.submit("u", TranscribeOptions())
    assert started.wait(5)
    assert manager.cancel(job.id) is True
    assert job.message == "Cancelling…"
    release.set()
    done = manager.wait(job.id, timeout=5)
    assert done.status is JobStatus.CANCELLED
    assert manager.cancel(job.id) is False  # already finished


def test_unknown_job(sample_transcript):
    manager = JobManager(runners=make_runner(sample_transcript))
    assert manager.get("nope") is None
    assert manager.cancel("nope") is False
    with pytest.raises(KeyError):
        manager.wait("nope", timeout=0.1)


def test_prunes_old_finished_jobs(sample_transcript):
    manager = JobManager(runners=make_runner(sample_transcript), max_jobs=2)
    ids = []
    for i in range(4):
        job = manager.submit(f"u{i}", TranscribeOptions())
        manager.wait(job.id, timeout=5)
        ids.append(job.id)
    remaining = {job.id for job in manager.list()}
    assert len(remaining) <= 3
    assert ids[-1] in remaining


def test_on_complete_runs_before_job_is_marked_done(sample_transcript):
    seen = []

    def hook(job):
        seen.append(job.status)

    manager = JobManager(runners=make_runner(sample_transcript), on_complete=hook)
    job = manager.submit("u", TranscribeOptions())
    done = manager.wait(job.id, timeout=5)
    assert seen == [JobStatus.RUNNING]
    assert done.status is JobStatus.DONE


def test_failing_on_complete_does_not_fail_job(sample_transcript):
    def hook(job):
        raise OSError("disk full")

    manager = JobManager(runners=make_runner(sample_transcript), on_complete=hook)
    job = manager.submit("u", TranscribeOptions())
    done = manager.wait(job.id, timeout=5)
    assert done.status is JobStatus.DONE
    assert done.result is sample_transcript


def test_kinds_run_on_separate_workers(sample_transcript):
    gate = threading.Event()

    def slow(url, options, progress):
        gate.wait(5)
        return sample_transcript

    def fast(url, options, progress):
        return sample_transcript

    manager = JobManager(runners={"transcribe": slow, "download": fast})
    assert manager.kinds == ("transcribe", "download")
    first = manager.submit("a", TranscribeOptions(), kind="transcribe")
    second = manager.submit("b", TranscribeOptions(), kind="download")
    assert manager.wait(second.id, timeout=5).status is JobStatus.DONE  # not blocked by the transcription
    assert first.status is JobStatus.RUNNING
    gate.set()
    assert manager.wait(first.id, timeout=5).status is JobStatus.DONE
    assert [job.id for job in manager.list("download")] == [second.id]
    assert [job.id for job in manager.list()] == [second.id, first.id]
    assert second.to_dict()["kind"] == "download"
    assert second.to_dict()["language"] == "en"  # summary() fields are merged in
    with pytest.raises(ValueError):
        manager.submit("c", TranscribeOptions(), kind="nope")
