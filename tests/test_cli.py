import io

import pytest

import yt_transcriber.cli as cli
from yt_transcriber.downloader import DownloadError
from yt_transcriber.video_downloader import DownloadResult, DownloadedItem


def test_bare_url_is_transcribe(monkeypatch, sample_transcript, tmp_path, capsys):
    calls = []

    def fake_run(url, options, progress=None):
        calls.append((url, options))
        progress("download", 0.5, "half")
        progress("transcribe", 1.0, "done")
        return sample_transcript

    monkeypatch.setattr(cli, "run_pipeline", fake_run)
    code = cli.main(["https://youtu.be/dQw4w9WgXcQ", "-o", str(tmp_path), "-l", "zh", "-s", "traditional",
                     "-m", "medium", "-f", "txt,json", "--print"])
    assert code == 0
    assert calls[0][0] == "https://youtu.be/dQw4w9WgXcQ"
    assert calls[0][1].language == "zh"
    assert calls[0][1].chinese_script == "traditional"
    assert calls[0][1].model == "medium"
    out = capsys.readouterr().out
    assert "Test: Video / Title?" in out
    assert "Hello everyone," in out
    assert sorted(p.suffix for p in tmp_path.iterdir()) == [".json", ".txt"]


def test_failure_sets_exit_code_and_continues(monkeypatch, sample_transcript, tmp_path, capsys):
    def fake_run(url, options, progress=None):
        if "bad" in url:
            raise DownloadError("Video unavailable")
        return sample_transcript

    monkeypatch.setattr(cli, "run_pipeline", fake_run)
    code = cli.main(["transcribe", "https://youtu.be/badbadbadba", "https://youtu.be/dQw4w9WgXcQ",
                     "-o", str(tmp_path)])
    assert code == 1
    captured = capsys.readouterr()
    assert "Video unavailable" in captured.err
    assert "Test: Video / Title?" in captured.out
    assert (tmp_path / "Test Video Title [dQw4w9WgXcQ].srt").exists()


def test_bad_format_is_rejected(tmp_path, capsys):
    code = cli.main(["https://youtu.be/dQw4w9WgXcQ", "-f", "docx", "-o", str(tmp_path)])
    assert code == 2
    assert "Unknown format" in capsys.readouterr().err


def test_no_args_means_serve(monkeypatch):
    called = {}

    def fake_serve(settings, open_browser=True):
        called["settings"] = settings
        called["open_browser"] = open_browser

    import yt_transcriber.server as server

    monkeypatch.setattr(server, "serve", fake_serve)
    assert cli.main([]) == 0
    assert called["open_browser"] is True
    assert cli.main(["serve", "--no-browser", "--port", "9001"]) == 0
    assert called["open_browser"] is False
    assert called["settings"].port == 9001


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert "yt-transcriber" in capsys.readouterr().out


def test_console_progress_prints_stage_changes():
    stream = io.StringIO()
    progress = cli.ConsoleProgress(stream)
    progress("download", 0.5, "half")
    progress("download", None, "unknown")
    progress("transcribe", 0.25, "going")
    progress.finish()
    text = stream.getvalue()
    assert "Downloading" in text and "50.0%" in text
    assert "Transcribing" in text and "25.0%" in text
    assert text.count("\n") == 2


def test_download_command(monkeypatch, tmp_path, capsys):
    calls = []

    def fake_download(url, options, progress=None):
        calls.append((url, options))
        progress("download", 0.5, "half")
        path = tmp_path / "Vid [dQw4w9WgXcQ].mp4"
        path.write_bytes(b"abc")
        return DownloadResult(title="Vid", url=url, kind="video", output_dir=str(tmp_path), mode=options.mode,
                              quality=options.quality, audio_format=options.audio_format,
                              items=[DownloadedItem(title="Vid", path=str(path), size_bytes=3)],
                              failures=[], warnings=["note one"])

    monkeypatch.setattr(cli, "run_download", fake_download)
    url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf"
    code = cli.main(["download", url, "-a", "--audio-format", "m4a", "-o", str(tmp_path)])
    assert code == 0
    assert calls[0][0] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"  # no --playlist: just the video
    assert calls[0][1].mode == "audio" and calls[0][1].audio_format == "m4a"
    assert calls[0][1].output_dir == str(tmp_path)
    out = capsys.readouterr().out
    assert "part of a playlist" in out and "Vid" in out and "Vid [dQw4w9WgXcQ].mp4" in out and "note one" in out

    code = cli.main(["download", url, "--playlist", "-q", "720", "-o", str(tmp_path)])
    assert code == 0
    assert calls[1][0] == "https://www.youtube.com/playlist?list=PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf"
    assert calls[1][1].mode == "video" and calls[1][1].quality == "720"


def test_download_command_bad_link(tmp_path, capsys):
    assert cli.main(["download", "https://example.com", "-o", str(tmp_path)]) == 1
    assert "Not a YouTube" in capsys.readouterr().err
