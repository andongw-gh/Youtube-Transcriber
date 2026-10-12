from __future__ import annotations

import pytest

from yt_transcriber.formats import Segment
from yt_transcriber.pipeline import Transcript


@pytest.fixture
def sample_segments() -> list[Segment]:
    return [
        Segment(0.0, 2.5, "Hello everyone,"),
        Segment(2.5, 5.0, "welcome back to the channel."),
        Segment(8.0, 10.2, "Today we talk about Whisper."),
    ]


@pytest.fixture
def sample_transcript(sample_segments) -> Transcript:
    return Transcript(
        video_id="dQw4w9WgXcQ",
        title="Test: Video / Title?",
        url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        uploader="Someone",
        duration=10.2,
        language="en",
        language_probability=0.98,
        model="small",
        segments=sample_segments,
    )
