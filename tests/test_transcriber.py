from types import SimpleNamespace

import numpy as np
import pytest

from yt_transcriber.audio import SAMPLE_RATE
from yt_transcriber.transcriber import (
    MODEL_CHOICES,
    MODEL_DESCRIPTIONS,
    load_model,
    resolve_compute_type,
    resolve_device,
    transcribe_audio,
)


class _FakeModel:
    def __init__(self):
        self.calls = []

    def transcribe(self, audio, **kwargs):
        self.calls.append(kwargs)
        segments = iter([
            SimpleNamespace(start=0.0, end=2.0, text=" 大家好 "),
            SimpleNamespace(start=2.0, end=4.0, text="   "),
            SimpleNamespace(start=4.0, end=8.0, text="欢迎"),
        ])
        info = SimpleNamespace(language="zh", language_probability=0.91, duration=8.0)
        return segments, info


def test_transcribe_audio_collects_segments_and_progress():
    model = _FakeModel()
    audio = np.zeros(SAMPLE_RATE * 8, dtype=np.float32)
    events = []
    result = transcribe_audio(audio, model, language="zh", hotwords="以下是普通话的句子。",
                              progress=lambda f, m: events.append(f))
    assert [seg.text for seg in result.segments] == ["大家好", "欢迎"]
    assert result.language == "zh"
    assert result.language_probability == pytest.approx(0.91)
    assert result.duration == 8.0
    assert events == [0.25, 0.5, 1.0]
    kwargs = model.calls[0]
    assert kwargs["language"] == "zh"
    assert kwargs["hotwords"] == "以下是普通话的句子。"
    assert kwargs["vad_filter"] is True
    assert kwargs["condition_on_previous_text"] is False


def test_transcribe_audio_auto_language_passes_none():
    model = _FakeModel()
    transcribe_audio(np.zeros(SAMPLE_RATE, dtype=np.float32), model)
    assert model.calls[0]["language"] is None


def test_resolve_device_and_compute_type(monkeypatch):
    import yt_transcriber.transcriber as t

    monkeypatch.setattr(t, "cuda_available", lambda: False)
    assert resolve_device("auto") == "cpu"
    assert resolve_device("cuda") == "cuda"
    assert resolve_compute_type("auto", "cpu") == "int8"
    assert resolve_compute_type("auto", "cuda") == "float16"
    assert resolve_compute_type("float32", "cpu") == "float32"
    monkeypatch.setattr(t, "cuda_available", lambda: True)
    assert resolve_device("auto") == "cuda"


def test_load_model_rejects_unknown_name():
    with pytest.raises(ValueError):
        load_model("gigantic")


def test_every_model_has_a_description():
    assert set(MODEL_CHOICES) == set(MODEL_DESCRIPTIONS)
