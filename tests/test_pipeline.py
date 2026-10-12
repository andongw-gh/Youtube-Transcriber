from pathlib import Path

import numpy as np
import pytest

import yt_transcriber.pipeline as pipeline
from yt_transcriber.downloader import DownloadedAudio
from yt_transcriber.formats import Segment
from yt_transcriber.transcriber import TranscriptResult
from yt_transcriber.urls import InvalidYouTubeURL


@pytest.fixture
def fake_backend(monkeypatch):
    """Replace download / decode / Whisper with fakes and record what was called."""
    calls = {}

    def fake_download(url, out_dir, progress=None, cookies_from_browser=None, cookies_file=None):
        calls["download"] = {"url": url, "cookies_from_browser": cookies_from_browser}
        path = Path(out_dir) / "abcdefghijk.webm"
        path.write_bytes(b"x")
        if progress:
            progress(0.5, "half")
            progress(1.0, "Download finished")
        return DownloadedAudio(path=path, video_id="abcdefghijk", title="繁體標題", url=url,
                               duration=4.0, uploader="up")

    def fake_load_audio(path):
        calls["decoded"] = Path(path).exists()
        return np.zeros(16000 * 4, dtype=np.float32)

    def fake_load_model(model, device="auto", compute_type="auto", download_root=None):
        calls["model"] = {"model": model, "device": device, "download_root": download_root}
        return object()

    def fake_transcribe(audio, model, language=None, hotwords=None, initial_prompt=None,
                        beam_size=5, progress=None):
        calls["transcribe"] = {"language": language, "hotwords": hotwords, "beam_size": beam_size}
        if progress:
            progress(0.5, "mid")
        return TranscriptResult(language=calls.get("detected", "zh"), language_probability=0.9, duration=4.0,
                                segments=[Segment(0, 2, "電腦軟體"), Segment(2, 4, "繁體")])

    monkeypatch.setattr(pipeline.downloader, "download_audio", fake_download)
    monkeypatch.setattr(pipeline.audio_mod, "load_audio", fake_load_audio)
    monkeypatch.setattr(pipeline.transcriber, "load_model", fake_load_model)
    monkeypatch.setattr(pipeline.transcriber, "transcribe_audio", fake_transcribe)
    return calls


def test_run_end_to_end_with_simplified_conversion(fake_backend):
    events = []
    options = pipeline.TranscribeOptions(language="zh", chinese_script="simplified", model="medium",
                                         cookies_from_browser="chrome", model_dir="/models")
    transcript = pipeline.run("https://youtu.be/abcdefghijk?t=3", options,
                              progress=lambda s, f, m: events.append((s, f)))

    assert fake_backend["download"]["url"] == "https://www.youtube.com/watch?v=abcdefghijk"
    assert fake_backend["download"]["cookies_from_browser"] == "chrome"
    assert fake_backend["decoded"] is True
    assert fake_backend["model"] == {"model": "medium", "device": "auto", "download_root": "/models"}
    assert fake_backend["transcribe"]["language"] == "zh"
    assert "简体" in fake_backend["transcribe"]["hotwords"]

    assert [seg.text for seg in transcript.segments] == ["电脑软体", "繁体"]
    assert transcript.text == "电脑软体繁体"
    assert transcript.title == "繁體標題"  # the title is left alone
    assert transcript.model == "medium"
    assert transcript.language == "zh"

    stages = [stage for stage, _ in events]
    assert stages[0] == "download"
    assert "decode" in stages and "load_model" in stages and "transcribe" in stages
    assert stages[-1] == "done" and events[-1][1] == 1.0


def test_run_keeps_script_by_default(fake_backend):
    transcript = pipeline.run("https://youtu.be/abcdefghijk")
    assert [seg.text for seg in transcript.segments] == ["電腦軟體", "繁體"]
    assert fake_backend["transcribe"]["language"] is None
    assert fake_backend["transcribe"]["hotwords"] is None


def test_no_chinese_prompt_when_auto_detecting(fake_backend):
    pipeline.run("https://youtu.be/abcdefghijk", pipeline.TranscribeOptions(chinese_script="simplified"))
    # Auto-detect: no prompt (it would bias English videos) but conversion still applies after detection.
    assert fake_backend["transcribe"]["hotwords"] is None


def test_english_result_is_not_converted(fake_backend):
    fake_backend["detected"] = "en"
    transcript = pipeline.run("https://youtu.be/abcdefghijk",
                              pipeline.TranscribeOptions(language="en", chinese_script="simplified"))
    assert [seg.text for seg in transcript.segments] == ["電腦軟體", "繁體"]
    assert fake_backend["transcribe"]["hotwords"] is None


def test_run_rejects_bad_url(fake_backend):
    with pytest.raises(InvalidYouTubeURL):
        pipeline.run("https://example.com/video")
    assert "download" not in fake_backend


def test_options_validate():
    pipeline.TranscribeOptions().validate()
    with pytest.raises(ValueError):
        pipeline.TranscribeOptions(language="fr").validate()
    with pytest.raises(ValueError):
        pipeline.TranscribeOptions(model="huge").validate()
    with pytest.raises(ValueError):
        pipeline.TranscribeOptions(chinese_script="pinyin").validate()
    with pytest.raises(ValueError):
        pipeline.TranscribeOptions(beam_size=0).validate()


def test_public_dict_hides_cookie_paths():
    data = pipeline.TranscribeOptions(cookies_file="/secret", model_dir="/m").public_dict()
    assert "cookies_file" not in data and "cookies_from_browser" not in data and "model_dir" not in data
    assert data["model"] == "small"


def test_transcript_to_dict(sample_transcript):
    data = sample_transcript.to_dict()
    assert data["video_id"] == "dQw4w9WgXcQ"
    assert data["text"].startswith("Hello everyone,")
    assert len(data["segments"]) == 3
