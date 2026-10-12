import shutil
import subprocess

import numpy as np
import pytest

from yt_transcriber.audio import SAMPLE_RATE, AudioDecodeError, duration_seconds, load_audio

ffmpeg = shutil.which("ffmpeg")
pytestmark = pytest.mark.skipif(ffmpeg is None, reason="ffmpeg not installed")


def _tone(path, codec, seconds=2):
    subprocess.run(
        [ffmpeg, "-loglevel", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
         "-c:a", codec, str(path)],
        check=True,
    )


@pytest.mark.parametrize("name,codec", [("tone.webm", "libopus"), ("tone.m4a", "aac")])
def test_decodes_youtube_style_containers(tmp_path, name, codec):
    path = tmp_path / name
    _tone(path, codec)
    audio = load_audio(path)
    assert audio.dtype == np.float32
    assert audio.ndim == 1
    assert abs(duration_seconds(audio) - 2.0) < 0.2
    assert 0.1 < float(np.abs(audio).max()) <= 1.0
    assert len(audio) > SAMPLE_RATE  # at least a second of samples


def test_missing_file(tmp_path):
    with pytest.raises(AudioDecodeError):
        load_audio(tmp_path / "nope.webm")


def test_garbage_file(tmp_path):
    bad = tmp_path / "bad.webm"
    bad.write_bytes(b"this is not audio")
    with pytest.raises(AudioDecodeError):
        load_audio(bad)
