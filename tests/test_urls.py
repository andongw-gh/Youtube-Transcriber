import pytest

from yt_transcriber.urls import InvalidYouTubeURL, canonical_url, extract_video_id, normalize_url

VID = "dQw4w9WgXcQ"


@pytest.mark.parametrize(
    "url",
    [
        f"https://www.youtube.com/watch?v={VID}",
        f"http://youtube.com/watch?v={VID}",
        f"https://m.youtube.com/watch?v={VID}&list=PL123&index=2",
        f"https://music.youtube.com/watch?v={VID}&feature=share",
        f"https://www.youtube.com/watch?feature=share&v={VID}",
        f"https://youtu.be/{VID}",
        f"https://youtu.be/{VID}?t=42",
        f"youtu.be/{VID}",
        f"www.youtube.com/watch?v={VID}",
        f"https://www.youtube.com/shorts/{VID}",
        f"https://www.youtube.com/live/{VID}?feature=share",
        f"https://www.youtube.com/embed/{VID}",
        f"https://www.youtube-nocookie.com/embed/{VID}",
        f"https://www.youtube.com/v/{VID}",
        f"  https://www.youtube.com/watch?v={VID}  ",
    ],
)
def test_extracts_video_id(url):
    assert extract_video_id(url) == VID


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "not a url",
        "https://example.com/watch?v=dQw4w9WgXcQ",
        "https://vimeo.com/12345",
        "https://www.youtube.com/playlist?list=PL123",
        "https://www.youtube.com/watch?list=PL123",
        "https://www.youtube.com/watch?v=tooshort",
        "https://www.youtube.com/channel/UC12345",
        "https://notyoutube.com/watch?v=dQw4w9WgXcQ",
        "dQw4w9WgXcQ",
    ],
)
def test_rejects_non_video_links(text):
    assert extract_video_id(text) is None


def test_normalize_url_round_trips():
    assert normalize_url(f"https://youtu.be/{VID}?t=1") == canonical_url(VID)
    assert normalize_url(f"https://youtu.be/{VID}") == f"https://www.youtube.com/watch?v={VID}"


def test_normalize_url_raises_for_bad_input():
    with pytest.raises(InvalidYouTubeURL):
        normalize_url("https://example.com")


PLID = "PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf"


@pytest.mark.parametrize(
    "url,video,playlist",
    [
        (f"https://www.youtube.com/playlist?list={PLID}", None, PLID),
        (f"https://youtube.com/playlist?list={PLID}&si=abc", None, PLID),
        (f"https://www.youtube.com/watch?v={VID}&list={PLID}&index=3", VID, PLID),
        (f"https://youtu.be/{VID}?list={PLID}", VID, PLID),
        (f"https://music.youtube.com/playlist?list={PLID}", None, PLID),
        (f"https://www.youtube.com/watch?v={VID}", VID, None),
    ],
)
def test_parse_link(url, video, playlist):
    from yt_transcriber.urls import extract_playlist_id, parse_link

    link = parse_link(url)
    assert link is not None
    assert link.video_id == video
    assert link.playlist_id == playlist
    assert extract_playlist_id(url) == playlist


def test_parse_link_kinds_and_targets():
    from yt_transcriber.urls import parse_link

    both = parse_link(f"https://www.youtube.com/watch?v={VID}&list={PLID}")
    assert both.kind == "video_in_playlist"
    assert both.target_url() == f"https://www.youtube.com/watch?v={VID}"
    assert both.target_url(whole_playlist=True) == f"https://www.youtube.com/playlist?list={PLID}"

    only_list = parse_link(f"https://www.youtube.com/playlist?list={PLID}")
    assert only_list.kind == "playlist"
    assert only_list.target_url() == f"https://www.youtube.com/playlist?list={PLID}"
    assert only_list.video_url is None

    only_video = parse_link(f"https://youtu.be/{VID}")
    assert only_video.kind == "video"
    assert only_video.target_url(whole_playlist=True) == f"https://www.youtube.com/watch?v={VID}"
    assert only_video.playlist_url is None


@pytest.mark.parametrize("text", ["", "https://example.com/playlist?list=PL123456789012", "https://www.youtube.com/channel/UC1", "https://www.youtube.com/playlist?list=short"])
def test_parse_link_rejects(text):
    from yt_transcriber.urls import parse_link

    assert parse_link(text) is None
