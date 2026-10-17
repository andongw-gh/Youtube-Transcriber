import functools
import http.server
import shutil
import subprocess
import threading
from pathlib import Path

import pytest
import yt_dlp
from yt_dlp.utils import DownloadCancelled

import yt_transcriber.video_downloader as vd
from yt_transcriber.downloader import DownloadError
from yt_transcriber.pipeline import Cancelled
from yt_transcriber.urls import InvalidYouTubeURL
from yt_transcriber.video_downloader import DownloadOptions, build_ydl_options, download_url, human_size

PL = "https://www.youtube.com/playlist?list=PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf"


# ---- options -------------------------------------------------------------------------

def test_options_validate_and_public_dict():
    DownloadOptions().validate()
    for bad in (DownloadOptions(mode="gif"), DownloadOptions(quality="999"), DownloadOptions(audio_format="wav")):
        with pytest.raises(ValueError):
            bad.validate()
    data = DownloadOptions(cookies_file="/secret", cookies_from_browser="chrome").public_dict()
    assert "cookies_file" not in data and "cookies_from_browser" not in data
    assert data["quality"] == "1080"


def test_build_video_options_with_ffmpeg(tmp_path):
    opts = build_ydl_options(DownloadOptions(quality="1080"), tmp_path, is_playlist=False, ffmpeg=True)
    assert opts["format"] == "bv*+ba/b"
    assert opts["format_sort"] == ["res:1080", "vcodec:h264", "ext:mp4:m4a"]
    assert opts["merge_output_format"] == "mp4"
    assert opts["outtmpl"] == vd.SINGLE_TEMPLATE
    assert opts["paths"] == {"home": str(tmp_path)}
    assert opts["ignoreerrors"] == "only_download"
    assert opts["noplaylist"] is True
    assert opts["postprocessors"] == []


def test_build_video_options_best_and_playlist(tmp_path):
    opts = build_ydl_options(DownloadOptions(quality="best"), tmp_path, is_playlist=True, ffmpeg=True)
    assert opts["format_sort"][0] == "res"
    assert opts["outtmpl"] == vd.PLAYLIST_TEMPLATE
    assert "%(playlist_index)s" in opts["outtmpl"]


def test_build_video_options_without_ffmpeg(tmp_path):
    opts = build_ydl_options(DownloadOptions(quality="720"), tmp_path, is_playlist=False, ffmpeg=False)
    assert opts["format"] == "b"
    assert "merge_output_format" not in opts
    assert opts["format_sort"][0] == "res:720"


def test_build_audio_options(tmp_path):
    opts = build_ydl_options(DownloadOptions(mode="audio", audio_format="mp3"), tmp_path, False, ffmpeg=True)
    assert opts["format"] == "bestaudio/best"
    assert opts["postprocessors"] == [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "0"}]
    no_ffmpeg = build_ydl_options(DownloadOptions(mode="audio"), tmp_path, False, ffmpeg=False)
    assert no_ffmpeg["format"].startswith("bestaudio[ext=m4a]")
    assert no_ffmpeg["postprocessors"] == []


def test_build_options_cookies(tmp_path):
    opts = build_ydl_options(DownloadOptions(cookies_from_browser="firefox", cookies_file="/c.txt"), tmp_path, False, True)
    assert opts["cookiesfrombrowser"] == ("firefox",)
    assert opts["cookiefile"] == "/c.txt"


def test_human_size():
    assert human_size(512) == "512 B"
    assert human_size(2048) == "2.0 KB"
    assert human_size(5 * 1024 ** 3) == "5.0 GB"


# ---- run() link handling --------------------------------------------------------------

def test_run_rejects_non_youtube_links():
    with pytest.raises(InvalidYouTubeURL):
        vd.run("https://example.com/video.mp4")


def test_run_resolves_targets(monkeypatch):
    calls = []
    monkeypatch.setattr(vd, "download_url", lambda target, options, progress, is_playlist: calls.append((target, is_playlist)))
    vd.run("https://youtu.be/dQw4w9WgXcQ?list=PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf")
    vd.run(PL)
    assert calls == [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", False),  # video inside a playlist: just the video
        (PL, True),
    ]


# ---- fake yt-dlp: playlist mechanics ---------------------------------------------------

class _FakePlaylistYDL:
    """Plays back what yt-dlp does for a 3-video playlist where the last one is broken."""

    def __init__(self, params):
        self.params = params

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=True):
        home = Path(self.params["paths"]["home"])
        hooks = self.params["progress_hooks"]
        pp_hooks = self.params["postprocessor_hooks"]
        post = self.params["post_hooks"]
        logger = self.params["logger"]
        entries = []
        for idx, (vid, title) in enumerate([("aaaaaaaaaaa", "First"), ("bbbbbbbbbbb", "Second")], start=1):
            info = {"id": vid, "title": title, "playlist_index": idx, "n_entries": 3,
                    "requested_formats": [{"filesize": 60}, {"filesize": 40}]}
            for h in hooks:
                h({"status": "downloading", "downloaded_bytes": 30, "total_bytes": 60, "speed": 1024.0, "eta": 3, "info_dict": info})
                h({"status": "finished", "total_bytes": 60, "info_dict": info})
                h({"status": "downloading", "downloaded_bytes": 20, "total_bytes": 40, "info_dict": info})
                h({"status": "finished", "total_bytes": 40, "info_dict": info})
            for h in pp_hooks:
                h({"status": "started", "postprocessor": "Merger", "info_dict": info})
                h({"status": "finished", "postprocessor": "Merger", "info_dict": info})
            path = home / "My Playlist" / f"{idx} - {title} [{vid}].mp4"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x" * (100 * idx))
            for p in post:
                p(str(path))
            entry = dict(info)
            entry["requested_downloads"] = [{"filepath": str(path)}]
            entries.append(entry)
        logger.warning("WARNING: [youtube] something minor")
        logger.error("ERROR: [youtube] ccccccccccc: Video unavailable")
        entries.append(None)
        return {"_type": "playlist", "title": "My Playlist", "playlist_count": 3, "entries": entries}


def test_playlist_download_collects_items_failures_and_progress(tmp_path, monkeypatch):
    monkeypatch.setattr(yt_dlp, "YoutubeDL", _FakePlaylistYDL)
    monkeypatch.setattr(vd, "ffmpeg_available", lambda: True)
    events = []
    result = download_url(PL, DownloadOptions(output_dir=str(tmp_path)), lambda s, f, m: events.append((s, f, m)), is_playlist=True)

    assert result.kind == "playlist"
    assert result.title == "My Playlist"
    assert result.expected_count == 3
    assert [(i.index, i.title, i.size_bytes, i.video_id) for i in result.items] == [
        (1, "First", 100, "aaaaaaaaaaa"), (2, "Second", 200, "bbbbbbbbbbb")]
    assert result.total_bytes == 300
    assert result.output_dir == str(tmp_path / "My Playlist")
    assert result.failures == ["ccccccccccc: Video unavailable\n\nCheck that the link is correct and the video is still online."]
    assert result.warnings == ["[youtube] something minor"]
    assert result.summary()["item_count"] == 2 and result.summary()["failed_count"] == 1
    assert result.to_dict()["items"][0]["filename"] == "1 - First [aaaaaaaaaaa].mp4"

    assert events[0] == ("resolve", None, "Fetching information from YouTube…")
    stage, fraction, message = events[1]
    assert stage == "download"
    assert fraction == pytest.approx((0 + 30 / 100) / 3)                     # 30 of 100 expected bytes, video 1 of 3
    assert message == "1/3 · 30% · 1.0 KB/s · 00:03 left · First"
    # second part of the first video: 60 finished + 20 of 40 -> 80 of 100
    assert events[3][1] == pytest.approx((0 + 80 / 100) / 3)
    merge = [e for e in events if e[0] == "convert"]
    assert merge[0][2] == "1/3 · Merging video and audio… · First"
    assert merge[0][1] == pytest.approx(1 / 3)
    second = [e for e in events if e[2].startswith("2/3")]
    assert second and second[0][1] == pytest.approx((1 + 0.3) / 3)
    assert events[-1] == ("done", 1.0, "Done")


def test_cancel_during_download(tmp_path, monkeypatch):
    monkeypatch.setattr(yt_dlp, "YoutubeDL", _FakePlaylistYDL)
    monkeypatch.setattr(vd, "ffmpeg_available", lambda: True)
    calls = {"n": 0}

    def progress(stage, fraction, message):
        calls["n"] += 1
        if stage == "download":
            raise Cancelled()

    with pytest.raises(Cancelled):
        download_url(PL, DownloadOptions(output_dir=str(tmp_path)), progress, is_playlist=True)
    assert calls["n"] == 2  # resolve, then the first download tick


def test_tracker_converts_cancel_to_download_cancelled():
    def progress(stage, fraction, message):
        raise Cancelled()

    tracker = vd._Tracker(progress, is_playlist=False, cancel_exception=DownloadCancelled)
    with pytest.raises(DownloadCancelled):
        tracker.on_progress({"status": "downloading", "downloaded_bytes": 1, "total_bytes": 2, "info_dict": {"id": "x"}})


class _NothingYDL(_FakePlaylistYDL):
    def extract_info(self, url, download=True):
        self.params["logger"].error("ERROR: [youtube] abcdefghijk: Private video. Sign in if you've been granted access")
        return None


def test_nothing_downloaded_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(yt_dlp, "YoutubeDL", _NothingYDL)
    with pytest.raises(DownloadError) as info:
        download_url("https://www.youtube.com/watch?v=abcdefghijk", DownloadOptions(output_dir=str(tmp_path)))
    assert "Private video" in str(info.value)


def test_without_ffmpeg_adds_warning(tmp_path, monkeypatch):
    monkeypatch.setattr(yt_dlp, "YoutubeDL", _FakePlaylistYDL)
    monkeypatch.setattr(vd, "ffmpeg_available", lambda: False)
    result = download_url(PL, DownloadOptions(output_dir=str(tmp_path)), is_playlist=True)
    assert any("ffmpeg is not installed" in w for w in result.warnings)


# ---- real yt-dlp against a local HTTP server ------------------------------------------

ffmpeg = shutil.which("ffmpeg")


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):  # noqa: D102 - silence request logging
        pass


@pytest.fixture(scope="module")
def media_url(tmp_path_factory):
    if ffmpeg is None:
        pytest.skip("ffmpeg not installed")
    root = tmp_path_factory.mktemp("media")
    clip = root / "Sample Clip.mp4"
    subprocess.run(
        [ffmpeg, "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10:duration=1",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(clip)],
        check=True,
    )
    handler = functools.partial(_QuietHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}/Sample%20Clip.mp4", clip.stat().st_size
    server.shutdown()


def test_real_video_download(tmp_path, media_url):
    url, size = media_url
    events = []
    result = download_url(url, DownloadOptions(mode="video", quality="best", output_dir=str(tmp_path)),
                          lambda s, f, m: events.append((s, f, m)))
    assert result.kind == "video"
    assert result.title == "Sample Clip"
    assert len(result.items) == 1
    item = result.items[0]
    assert item.path.endswith(".mp4") and Path(item.path).parent == tmp_path
    assert item.size_bytes == size
    assert result.failures == []
    stages = [e[0] for e in events]
    assert stages[0] == "resolve" and "download" in stages and stages[-1] == "done"
    assert events[-1][1] == 1.0


def test_real_audio_extraction(tmp_path, media_url):
    url, _ = media_url
    events = []
    result = download_url(url, DownloadOptions(mode="audio", audio_format="mp3", output_dir=str(tmp_path)),
                          lambda s, f, m: events.append((s, f, m)))
    assert len(result.items) == 1
    item = result.items[0]
    assert item.path.endswith(".mp3")
    assert Path(item.path).exists() and item.size_bytes > 1000
    assert "convert" in [e[0] for e in events]
    assert not list(tmp_path.glob("*.mp4"))  # the intermediate video is removed after extraction
