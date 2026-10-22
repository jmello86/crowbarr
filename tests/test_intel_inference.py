"""Intel integration preserves timing, confidence, and honest fallback reporting."""
import sys
from types import SimpleNamespace

import pytest

from crowbarr import inference, intel_inference
from crowbarr.config import Settings
from crowbarr.media import ReviewRequired
from crowbarr.subtitles import Word


@pytest.fixture
def intel_settings():
    return Settings(device="xpu", compute_type="float16")


@pytest.fixture
def backend(monkeypatch):
    state = SimpleNamespace(options={}, speech=[{"start": 32000, "end": 96000}], result={
        "segments": [
            {"start": 2.1, "end": 3, "avg_logprob": -0.2,
             "words": [{"start": 2.1, "end": 3, "word": " Hello", "probability": 0.94}]},
            {"start": 4, "end": 5, "avg_logprob": -1.2,
             "words": [{"start": 4, "end": 5, "word": " uncertain", "probability": 0.98}]},
        ]
    })

    def recognize(samples, **kwargs):
        state.options = kwargs
        return state.result

    model = SimpleNamespace(is_multilingual=False, transcribe=recognize)
    monkeypatch.setattr(intel_inference, "_load_model", lambda *a: model)
    monkeypatch.setattr(inference.transcribe, "progress", None, raising=False)
    monkeypatch.setitem(sys.modules, "whisper", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "faster_whisper.audio", SimpleNamespace(
        decode_audio=lambda *a, **kw: [0] * 160000,
    ))
    monkeypatch.setitem(sys.modules, "faster_whisper.vad", SimpleNamespace(
        VadOptions=lambda **kw: kw, get_speech_timestamps=lambda *a: state.speech,
    ))
    return state


def test_intel_recognition_retains_timeline_and_confidence(backend, tmp_path, intel_settings, monkeypatch):
    progress = []
    monkeypatch.setattr(inference.transcribe, "progress", lambda *values: progress.append(values))
    words, warnings = inference.transcribe(tmp_path / "audio.wav", intel_settings, tmp_path)
    assert words == [Word(2.1, 3, "Hello", 0.94), Word(4, 5, "uncertain", 0)]
    assert backend.options["clip_timestamps"] == [2, 6]
    assert backend.options["word_timestamps"] is True
    assert backend.options["condition_on_previous_text"] is False
    assert backend.options["fp16"] is True
    assert "Uncertain speech near 4.0s" in warnings
    assert progress[-1] == (5, 10)
    assert inference.transcribe.runtime == {
        "backend": "xpu", "compute_type": "float16", "requested_backend": "xpu", "fallback_reason": None,
    }


def test_silence_requires_review_without_cpu_retry(backend, monkeypatch, tmp_path, intel_settings):
    backend.speech = []
    with pytest.raises(ReviewRequired, match="No speech"):
        inference.transcribe(tmp_path / "audio.wav", intel_settings, tmp_path)
    assert inference.transcribe.runtime["backend"] == "xpu"


@pytest.mark.parametrize("samples", [193886, 160001, 160159, 160160])
def test_final_vad_endpoint_cannot_exceed_whisper_frames(
    backend, monkeypatch, tmp_path, intel_settings, samples
):
    monkeypatch.setitem(sys.modules, "faster_whisper.audio", SimpleNamespace(
        decode_audio=lambda *a, **kw: [0] * samples,
    ))
    backend.speech = [{"start": 0, "end": samples}]
    inference.transcribe(tmp_path / "audio.wav", intel_settings, tmp_path)
    assert round(backend.options["clip_timestamps"][-1] * 100) == samples // 160


def test_subframe_vad_span_requires_review(backend, tmp_path, intel_settings):
    backend.speech = [{"start": 160, "end": 161}]
    with pytest.raises(ReviewRequired, match="No speech"):
        inference.transcribe(tmp_path / "audio.wav", intel_settings, tmp_path)


@pytest.mark.parametrize("fallback", [True, False])
@pytest.mark.parametrize("error", [RuntimeError("decode failed"), ImportError("missing runtime")])
def test_gpu_failures_obey_fallback_and_report_actual_backend(
    monkeypatch, tmp_path, intel_settings, fallback, error
):
    def fail(*args):
        raise error

    monkeypatch.setattr(intel_inference, "_recognize", fail)
    calls = []

    def cpu_transcribe(audio, settings, cache):
        calls.append(settings)
        cpu_transcribe.runtime = {"backend": "cpu", "compute_type": "int8", "requested_backend": "cpu"}
        return [Word(1, 2, "Hello", 0.9)], []

    monkeypatch.setattr(inference, "transcribe", cpu_transcribe)
    settings = intel_settings.model_copy(update={"cpu_fallback": fallback})
    if fallback:
        words, _ = intel_inference.transcribe_intel(tmp_path / "audio.wav", settings, tmp_path)
        assert words[0].text == "Hello"
        assert calls[0].device == "cpu" and calls[0].compute_type == "int8"
        assert cpu_transcribe.runtime["backend"] == "cpu"
        assert cpu_transcribe.runtime["requested_backend"] == "xpu"
        assert "retried on CPU" in cpu_transcribe.runtime["fallback_reason"]
    else:
        with pytest.raises(type(error)):
            intel_inference.transcribe_intel(tmp_path / "audio.wav", settings, tmp_path)
        assert not calls


def test_multilingual_wrong_language_still_requires_review(backend, monkeypatch, tmp_path, intel_settings):
    tensor = SimpleNamespace(to=lambda *a: tensor, half=lambda: tensor)
    model = SimpleNamespace(
        is_multilingual=True, dims=SimpleNamespace(n_mels=80), device="xpu",
        detect_language=lambda mel: (None, {"ja": 0.95, "en": 0.05}),
    )
    monkeypatch.setattr(intel_inference, "_load_model", lambda *a: model)
    monkeypatch.setitem(sys.modules, "whisper", SimpleNamespace(
        pad_or_trim=lambda samples: samples, log_mel_spectrogram=lambda *a, **kw: tensor,
    ))
    with pytest.raises(ReviewRequired, match="ja with 95% confidence"):
        inference.transcribe(tmp_path / "audio.wav", intel_settings, tmp_path)


def test_xpu_model_keeps_sparse_heads_on_cpu_and_moves_dtw_before_double(monkeypatch, tmp_path, intel_settings):
    import types

    events = []
    heads = object()

    class Model:
        _buffers = {"alignment_heads": heads}
        alignment_heads = heads

        def to(self, device):
            assert "alignment_heads" not in self._buffers
            events.append(device)

        def register_buffer(self, name, value, **kwargs):
            assert name == "alignment_heads" and value is heads

        def half(self):
            events.append("half")

    whisper = types.ModuleType("whisper")
    timing = types.ModuleType("whisper.timing")
    timing.dtw = lambda tensor: tensor
    whisper.timing = timing
    whisper.load_model = lambda *a, **kw: Model()
    monkeypatch.setitem(sys.modules, "whisper", whisper)
    monkeypatch.setitem(sys.modules, "whisper.timing", timing)
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(
        xpu=SimpleNamespace(is_available=lambda: True), set_num_threads=lambda *a: None,
    ))
    monkeypatch.setattr(intel_inference, "_key", None)
    monkeypatch.setattr(intel_inference, "_model", None)
    model = intel_inference._load_model(intel_settings, tmp_path)
    assert intel_inference._load_model(intel_settings, tmp_path) is model
    assert events == ["half", "xpu"]
    tensor = SimpleNamespace(device=SimpleNamespace(type="xpu"), cpu=lambda: "cpu tensor")
    assert timing.dtw(tensor) == "cpu tensor"
