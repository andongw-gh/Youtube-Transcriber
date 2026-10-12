import json

import pytest

from yt_transcriber.formats import (
    FORMATS,
    Segment,
    format_clock,
    format_timestamp,
    join_text,
    output_basename,
    render,
    safe_filename,
    to_srt,
    to_timestamped_txt,
    to_txt,
    to_vtt,
    write_outputs,
)


def test_format_timestamp():
    assert format_timestamp(0) == "00:00:00,000"
    assert format_timestamp(1.5) == "00:00:01,500"
    assert format_timestamp(3661.0421, ".") == "01:01:01.042"
    assert format_timestamp(-3) == "00:00:00,000"


def test_format_clock():
    assert format_clock(5) == "00:05"
    assert format_clock(65) == "01:05"
    assert format_clock(3725) == "1:02:05"


def test_join_text_english_paragraphs(sample_segments):
    text = join_text(sample_segments, "en")
    assert text == "Hello everyone, welcome back to the channel.\n\nToday we talk about Whisper."


def test_join_text_chinese_has_no_spaces():
    segments = [Segment(0, 1, "大家好，"), Segment(1, 2, "欢迎回来。")]
    assert join_text(segments, "zh") == "大家好，欢迎回来。"
    assert join_text(segments, "yue") == "大家好，欢迎回来。"


def test_join_text_skips_blank_segments():
    segments = [Segment(0, 1, "  "), Segment(1, 2, "one"), Segment(2, 3, "")]
    assert join_text(segments, "en") == "one"
    assert to_txt([], "en") == ""


def test_srt(sample_segments):
    srt = to_srt(sample_segments)
    assert srt.startswith("1\n00:00:00,000 --> 00:00:02,500\nHello everyone,\n\n2\n")
    assert "3\n00:00:08,000 --> 00:00:10,200\nToday we talk about Whisper.\n" in srt


def test_srt_renumbers_after_skipping_blank():
    srt = to_srt([Segment(0, 1, ""), Segment(1, 2, "a"), Segment(2, 3, "b")])
    assert srt.split("\n")[0] == "1"
    assert "\n2\n00:00:02,000" in srt
    assert "\n3\n" not in srt


def test_vtt(sample_segments):
    vtt = to_vtt(sample_segments)
    assert vtt.startswith("WEBVTT\n\n00:00:00.000 --> 00:00:02.500\nHello everyone,\n")


def test_timestamped_txt(sample_segments):
    out = to_timestamped_txt(sample_segments)
    assert out.splitlines()[0] == "[00:00] Hello everyone,"
    assert out.splitlines()[2] == "[00:08] Today we talk about Whisper."


def test_render_json_includes_metadata(sample_segments):
    out = render("json", sample_segments, "en", {"title": "T", "video_id": "x"})
    data = json.loads(out)
    assert data["title"] == "T"
    assert data["language"] == "en"
    assert data["segments"][0] == {"start": 0.0, "end": 2.5, "text": "Hello everyone,"}
    assert data["text"].startswith("Hello everyone,")


def test_render_json_keeps_unicode(sample_segments):
    out = render("json", [Segment(0, 1, "中文")], "zh", {"title": "标题"})
    assert "中文" in out and "标题" in out


def test_render_unknown_format(sample_segments):
    with pytest.raises(ValueError):
        render("docx", sample_segments, "en", {})


def test_safe_filename():
    assert safe_filename('a/b\\c:d*e?f"g<h>i|j') == "a b c d e f g h i j"
    assert safe_filename("   ...   ") == "transcript"
    assert safe_filename("x" * 200) == "x" * 80
    assert safe_filename("中文 标题：测试") == "中文 标题：测试"  # full-width colon is fine


def test_output_basename():
    assert output_basename("My: Video", "abc123DEF45") == "My Video [abc123DEF45]"


def test_write_outputs(tmp_path, sample_segments):
    paths = write_outputs(tmp_path / "out", "name", sample_segments, "en", {"title": "T"}, FORMATS)
    assert sorted(p.name for p in paths) == ["name.json", "name.srt", "name.txt", "name.vtt"]
    assert (tmp_path / "out" / "name.txt").read_text(encoding="utf-8").startswith("Hello everyone,")
    with pytest.raises(ValueError):
        write_outputs(tmp_path, "name", sample_segments, "en", {}, ["pdf"])
