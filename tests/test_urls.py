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
