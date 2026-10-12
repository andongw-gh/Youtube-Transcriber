import json
import threading

import pytest
from fastapi.testclient import TestClient

from yt_transcriber.config import Settings
from yt_transcriber.jobs import JobManager
from yt_transcriber.server import create_app

URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


@pytest.fixture
def app_and_manager(tmp_path, sample_transcript):
    captured = {}

    def runner(url, options, progress):
        captured["url"] = url
        captured["options"] = options
        progress("transcribe", 0.5, "half way")
        return sample_transcript

    settings = Settings(output_dir=tmp_path / "out", default_model="base", cookies_from_browser="chrome")
    manager = JobManager(runner=runner)
    app = create_app(settings=settings, manager=manager)
    return app, manager, captured


@pytest.fixture
def client(app_and_manager):
    app, _, _ = app_and_manager
    return TestClient(app)


def test_index_serves_ui(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "YouTube Transcriber" in res.text
    assert "/api/jobs" in res.text


def test_config(client):
    cfg = client.get("/api/config").json()
    assert cfg["default_model"] == "base"
    assert {m["name"] for m in cfg["models"]} >= {"tiny", "small", "large-v3-turbo"}
    assert [lang["value"] for lang in cfg["languages"]] == ["auto", "zh", "en"]
    assert [s["value"] for s in cfg["chinese_scripts"]] == ["keep", "simplified", "traditional"]
    assert cfg["device"] in ("cpu", "cuda")


def test_create_job_and_fetch_result(client, app_and_manager):
    _, manager, captured = app_and_manager
    res = client.post("/api/jobs", json={"url": "https://youtu.be/dQw4w9WgXcQ?t=5", "language": "zh",
                                         "chinese_script": "simplified"})
    assert res.status_code == 202, res.text
    job = res.json()
    assert job["status"] == "queued"
    assert job["url"] == URL
    assert job["options"]["model"] == "base"  # server default applied
    assert "cookies_from_browser" not in job["options"]

    manager.wait(job["id"], timeout=5)
    assert captured["url"] == URL
    assert captured["options"].language == "zh"
    assert captured["options"].chinese_script == "simplified"
    assert captured["options"].cookies_from_browser == "chrome"  # server-side setting is applied

    detail = client.get(f"/api/jobs/{job['id']}").json()
    assert detail["status"] == "done"
    assert detail["title"] == "Test: Video / Title?"
    assert detail["result"]["text"].startswith("Hello everyone,")
    assert len(detail["result"]["segments"]) == 3

    listing = client.get("/api/jobs").json()
    assert [j["id"] for j in listing] == [job["id"]]
    assert "result" not in listing[0]


def test_create_job_with_explicit_model(client, app_and_manager):
    _, manager, captured = app_and_manager
    res = client.post("/api/jobs", json={"url": URL, "model": "large-v3-turbo"})
    assert res.status_code == 202
    manager.wait(res.json()["id"], timeout=5)
    assert captured["options"].model == "large-v3-turbo"


def test_create_job_rejects_bad_url(client):
    res = client.post("/api/jobs", json={"url": "https://example.com/watch?v=dQw4w9WgXcQ"})
    assert res.status_code == 400
    assert "YouTube" in res.json()["detail"]


def test_create_job_rejects_bad_choices(client):
    assert client.post("/api/jobs", json={"url": URL, "language": "fr"}).status_code == 422
    assert client.post("/api/jobs", json={"url": URL, "model": "huge"}).status_code == 422
    assert client.post("/api/jobs", json={"url": ""}).status_code == 422


def test_unknown_job_is_404(client):
    assert client.get("/api/jobs/nope").status_code == 404
    assert client.post("/api/jobs/nope/cancel").status_code == 404
    assert client.get("/api/jobs/nope/download").status_code == 404


def test_download_formats(client, app_and_manager):
    _, manager, _ = app_and_manager
    job = client.post("/api/jobs", json={"url": URL}).json()
    manager.wait(job["id"], timeout=5)

    txt = client.get(f"/api/jobs/{job['id']}/download?format=txt")
    assert txt.status_code == 200
    assert txt.text.startswith("Hello everyone,")
    assert 'filename="Test Video Title [dQw4w9WgXcQ].txt"' in txt.headers["content-disposition"]
    assert "filename*=UTF-8''" in txt.headers["content-disposition"]

    srt = client.get(f"/api/jobs/{job['id']}/download?format=srt")
    assert srt.text.startswith("1\n00:00:00,000 --> 00:00:02,500")

    vtt = client.get(f"/api/jobs/{job['id']}/download?format=vtt")
    assert vtt.text.startswith("WEBVTT")

    data = client.get(f"/api/jobs/{job['id']}/download?format=json").json()
    assert data["video_id"] == "dQw4w9WgXcQ"
    assert data["segments"][0]["text"] == "Hello everyone,"

    assert client.get(f"/api/jobs/{job['id']}/download?format=pdf").status_code == 422


def test_download_before_done_is_409(sample_transcript, tmp_path):
    gate = threading.Event()

    def runner(url, options, progress):
        gate.wait(5)
        return sample_transcript

    manager = JobManager(runner=runner)
    client = TestClient(create_app(settings=Settings(output_dir=tmp_path), manager=manager))
    job = client.post("/api/jobs", json={"url": URL}).json()
    assert client.get(f"/api/jobs/{job['id']}/download").status_code == 409
    cancel = client.post(f"/api/jobs/{job['id']}/cancel")
    assert cancel.status_code == 200
    gate.set()
    manager.wait(job["id"], timeout=5)
    assert client.post(f"/api/jobs/{job['id']}/cancel").status_code == 409


def test_default_manager_saves_files(tmp_path, sample_transcript, monkeypatch):
    """Without an injected manager, finished transcripts are written to output_dir."""
    import yt_transcriber.server as server

    def runner(url, options, progress):
        return sample_transcript

    created = {}
    real_manager = server.JobManager

    def factory(**kwargs):
        created["manager"] = real_manager(runner=runner, on_complete=kwargs["on_complete"])
        return created["manager"]

    monkeypatch.setattr(server, "JobManager", factory)
    settings = Settings(output_dir=tmp_path / "saved")
    client = TestClient(create_app(settings=settings))
    job = client.post("/api/jobs", json={"url": URL}).json()
    created["manager"].wait(job["id"], timeout=5)
    files = sorted(p.name for p in (tmp_path / "saved").iterdir())
    assert files == [
        "Test Video Title [dQw4w9WgXcQ].json",
        "Test Video Title [dQw4w9WgXcQ].srt",
        "Test Video Title [dQw4w9WgXcQ].txt",
        "Test Video Title [dQw4w9WgXcQ].vtt",
    ]
    assert json.loads((tmp_path / "saved" / files[0]).read_text(encoding="utf-8"))["language"] == "en"
