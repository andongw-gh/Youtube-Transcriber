from pathlib import Path

import pytest
import yt_dlp

from yt_transcriber.downloader import DownloadError, download_audio, friendly_message


def test_friendly_message_bot_check():
    msg = friendly_message("ERROR: [youtube] abcdefghijk: Sign in to confirm you’re not a bot. Use --cookies")
    assert msg.startswith("Sign in to confirm")
    assert "--cookies-from-browser" in msg


def test_friendly_message_private():
    msg = friendly_message("ERROR: [youtube] abcdefghijk: Private video.")
    assert "private" in msg.lower()


def test_friendly_message_strips_ansi():
    assert friendly_message("\x1b[0;31mERROR:\x1b[0m boom") == "boom"


class _FakeYDL:
    """Stands in for yt_dlp.YoutubeDL: writes a file and reports progress."""

    def __init__(self, params):
        self.params = params

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=True):
        out = Path(self.params["outtmpl"].replace("%(id)s", "abcdefghijk").replace("%(ext)s", "webm"))
        out.write_bytes(b"audio")
        for hook in self.params["progress_hooks"]:
            hook({"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100})
            hook({"status": "downloading", "downloaded_bytes": 10, "total_bytes": None})
            hook({"status": "finished"})
        return {
            "id": "abcdefghijk",
            "title": "Fake video",
            "webpage_url": url,
            "duration": 12.5,
            "uploader": "Fake channel",
            "requested_downloads": [{"filepath": str(out)}],
        }


class _FailingYDL(_FakeYDL):
    def extract_info(self, url, download=True):
        raise yt_dlp.utils.DownloadError("ERROR: [youtube] abcdefghijk: Video unavailable")


def test_download_audio_success(tmp_path, monkeypatch):
    monkeypatch.setattr(yt_dlp, "YoutubeDL", _FakeYDL)
    events = []
    result = download_audio("https://www.youtube.com/watch?v=abcdefghijk", tmp_path,
                            progress=lambda f, m: events.append((f, m)), cookies_from_browser="chrome")
    assert result.path.exists()
    assert result.video_id == "abcdefghijk"
    assert result.title == "Fake video"
    assert result.duration == 12.5
    assert result.uploader == "Fake channel"
    assert events[0][0] == 0.5 and "50" in events[0][1]
    assert events[1][0] is None  # unknown total size
    assert events[-1] == (1.0, "Download finished")


def test_download_audio_passes_cookie_options(tmp_path, monkeypatch):
    captured = {}

    class _Capture(_FakeYDL):
        def __init__(self, params):
            super().__init__(params)
            captured.update(params)

    monkeypatch.setattr(yt_dlp, "YoutubeDL", _Capture)
    download_audio("https://youtu.be/abcdefghijk", tmp_path, cookies_from_browser="firefox",
                   cookies_file="/tmp/cookies.txt")
    assert captured["cookiesfrombrowser"] == ("firefox",)
    assert captured["cookiefile"] == "/tmp/cookies.txt"
    assert captured["noplaylist"] is True
    assert captured["format"] == "bestaudio/best"


def test_download_audio_wraps_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(yt_dlp, "YoutubeDL", _FailingYDL)
    with pytest.raises(DownloadError) as info:
        download_audio("https://youtu.be/abcdefghijk", tmp_path)
    assert "Video unavailable" in str(info.value)
    assert "ERROR:" not in str(info.value)


def test_friendly_message_strips_bug_report_boilerplate():
    raw = ("ERROR: Unable to download API page: <urlopen error Tunnel connection failed: 403 Forbidden>; "
           "please report this issue on  https://github.com/yt-dlp/yt-dlp/issues?q= , filling out the "
           "appropriate issue template. Confirm you are on the latest version using  yt-dlp -U")
    msg = friendly_message(raw)
    assert "please report" not in msg
    assert "yt-dlp -U" not in msg
    assert msg.startswith("Unable to download API page: <urlopen error Tunnel connection failed: 403 Forbidden>")
    assert "internet connection" in msg
