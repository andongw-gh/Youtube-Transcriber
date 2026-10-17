import json
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from yt_transcriber.config import Settings
from yt_transcriber.jobs import JobManager
from yt_transcriber.server import create_app
from yt_transcriber.video_downloader import DownloadResult, DownloadedItem

URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


@pytest.fixture
def app_and_manager(tmp_path, sample_transcript):
    captured = {}

    def runner(url, options, progress):
        captured["url"] = url
        captured["options"] = options
        progress("transcribe", 0.5, "half way")
        return sample_transcript

    def dl_runner(url, options, progress):
        captured["dl_url"] = url
        captured["dl_options"] = options
        folder = Path(options.output_dir) / "My Playlist"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "1 - First [aaaaaaaaaaa].mp4"
        path.write_bytes(b"abc")
        return DownloadResult(
            title="My Playlist", url=url, kind="playlist", output_dir=str(folder), mode=options.mode,
            quality=options.quality, audio_format=options.audio_format,
            items=[DownloadedItem(title="First", path=str(path), size_bytes=3, video_id="aaaaaaaaaaa", index=1)],
            failures=["Video unavailable"], warnings=[], expected_count=2,
        )

    settings = Settings(output_dir=tmp_path / "out", download_dir=tmp_path / "dl", default_model="base",
                        cookies_from_browser="chrome")
    manager = JobManager(runners={"transcribe": runner, "download": dl_runner})
    app = create_app(settings=settings, manager=manager, folder_opener=lambda path: captured.setdefault("opened", []).append(path))
    return app, manager, captured


@pytest.fixture
def client(app_and_manager):
    app, _, _ = app_and_manager
    return TestClient(app)


def test_index_serves_ui(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "YouTube Download &amp; Transcribe" in res.text
    assert "/api/downloads" in res.text
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

    manager = JobManager(runners=runner)
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
        created["manager"] = real_manager(runners={"transcribe": runner}, on_complete=kwargs["on_complete"])
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


PLAYLIST = "https://www.youtube.com/playlist?list=PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf"


def test_config_has_download_fields(client):
    cfg = client.get("/api/config").json()
    assert [m["value"] for m in cfg["modes"]] == ["video", "audio"]
    assert "1080" in [q["value"] for q in cfg["qualities"]]
    assert [a["value"] for a in cfg["audio_formats"]] == ["mp3", "m4a"]
    assert isinstance(cfg["ffmpeg"], bool)
    assert cfg["download_dir"].endswith("dl")
    assert cfg["stages"]["resolve"] == "Fetching info"


def test_download_job_flow(client, app_and_manager, tmp_path):
    _, manager, captured = app_and_manager
    res = client.post("/api/downloads", json={"url": PLAYLIST, "mode": "audio", "audio_format": "m4a"})
    assert res.status_code == 202, res.text
    job = res.json()
    assert job["kind"] == "download"
    assert job["url"] == PLAYLIST
    assert job["options"]["mode"] == "audio"
    assert "cookies_from_browser" not in job["options"]

    manager.wait(job["id"], timeout=5)
    assert captured["dl_url"] == PLAYLIST
    assert captured["dl_options"].audio_format == "m4a"
    assert captured["dl_options"].cookies_from_browser == "chrome"
    assert captured["dl_options"].output_dir == str(tmp_path / "dl")

    detail = client.get(f"/api/jobs/{job['id']}").json()
    assert detail["status"] == "done"
    assert detail["title"] == "My Playlist"
    assert detail["item_count"] == 1 and detail["failed_count"] == 1 and detail["total_bytes"] == 3
    assert detail["result"]["items"][0]["filename"] == "1 - First [aaaaaaaaaaa].mp4"
    assert detail["result"]["failures"] == ["Video unavailable"]

    assert [j["kind"] for j in client.get("/api/jobs?kind=download").json()] == ["download"]
    assert client.get("/api/jobs?kind=transcribe").json() == []
    assert client.get("/api/jobs?kind=other").status_code == 422

    # no transcript formats for a download job; open-folder works
    assert client.get(f"/api/jobs/{job['id']}/download").status_code == 409
    opened = client.post(f"/api/jobs/{job['id']}/open-folder")
    assert opened.status_code == 200
    assert Path(opened.json()["path"]) == (tmp_path / "dl" / "My Playlist").resolve()
    assert captured["opened"] == [(tmp_path / "dl" / "My Playlist").resolve()]


def test_download_video_inside_playlist(client, app_and_manager):
    _, manager, captured = app_and_manager
    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf"
    job = client.post("/api/downloads", json={"url": url, "quality": "720"}).json()
    manager.wait(job["id"], timeout=5)
    assert captured["dl_url"] == URL  # just the video
    assert captured["dl_options"].quality == "720"
    job = client.post("/api/downloads", json={"url": url, "playlist": True}).json()
    manager.wait(job["id"], timeout=5)
    assert captured["dl_url"] == PLAYLIST


def test_download_rejects_bad_input(client):
    assert client.post("/api/downloads", json={"url": "https://example.com/x"}).status_code == 400
    assert client.post("/api/downloads", json={"url": URL, "quality": "999"}).status_code == 422
    assert client.post("/api/downloads", json={"url": URL, "mode": "gif"}).status_code == 422


def test_open_folder_for_transcribe_job_and_errors(client, app_and_manager, tmp_path):
    _, manager, captured = app_and_manager
    job = client.post("/api/jobs", json={"url": URL}).json()
    manager.wait(job["id"], timeout=5)
    # the transcript folder is created by the save hook only with the default manager; here it is missing
    assert client.post(f"/api/jobs/{job['id']}/open-folder").status_code == 404
    (tmp_path / "out").mkdir()
    assert client.post(f"/api/jobs/{job['id']}/open-folder").status_code == 200
    assert client.post("/api/jobs/nope/open-folder").status_code == 404
