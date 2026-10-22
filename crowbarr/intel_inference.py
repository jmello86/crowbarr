"""Reference Whisper on PyTorch XPU; imported only by the inference subprocess."""

from __future__ import annotations

import gc
import logging
import math
from pathlib import Path

from .config import Settings
from .media import ReviewRequired
from .subtitles import Word

log = logging.getLogger(__name__)
_model = None
_key = None


def download_model(name: str, directory: Path) -> None:
    import whisper

    directory.mkdir(parents=True, exist_ok=True)
    # Upstream verifies the checkpoint's SHA256, including on repeated downloads.
    whisper._download(whisper._MODELS[name], str(directory), in_memory=False)
    (directory / f"{name}.ready").touch()


def _load_model(settings: Settings, cache: Path):
    import torch
    import whisper
    import whisper.timing as timing

    global _model, _key
    key = (settings.model, settings.compute_type)
    if _key == key and _model is not None:
        return _model
    _model, _key = None, None
    gc.collect()
    if not torch.xpu.is_available():
        raise RuntimeError("No Intel GPU is available to PyTorch XPU")
    torch.set_num_threads(settings.cpu_threads)
    directory = cache / "whisper-xpu"
    directory.mkdir(parents=True, exist_ok=True)
    model = whisper.load_model(settings.model, device="cpu", download_root=str(directory))
    (directory / f"{settings.model}.ready").touch()
    # Whisper stores alignment heads as a sparse CPU buffer. XPU cannot move sparse
    # tensors; keep these small indices on the CPU while moving all model weights.
    heads = model.alignment_heads
    del model._buffers["alignment_heads"]
    if settings.compute_type == "float16":
        model.half()
    model.to("xpu")
    model.register_buffer("alignment_heads", heads, persistent=False)
    # Arc has no FP64. Upstream DTW converts to double before moving to the CPU,
    # so move first. The alignment algorithm and its probabilities stay unchanged.
    if not getattr(timing.dtw, "_crowbarr_xpu", False):
        original = timing.dtw

        def dtw(matrix):
            return original(matrix.cpu() if matrix.device.type == "xpu" else matrix)

        dtw._crowbarr_xpu = True
        timing.dtw = dtw
    _model, _key = model, key
    return model


def _recognize(audio: Path, settings: Settings, cache: Path):
    import whisper
    from faster_whisper.audio import decode_audio
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    from .inference import transcribe

    model = _load_model(settings, cache)
    samples = decode_audio(str(audio), sampling_rate=16000)
    duration = len(samples) / 16000
    speech = get_speech_timestamps(samples, VadOptions(min_silence_duration_ms=2000))
    if not speech:
        raise ReviewRequired("No speech found in the selected audio track")
    # Use the same Silero VAD as faster-whisper, retaining original timestamps by
    # passing clip boundaries instead of concatenating speech and losing offsets.
    clips = [sample / 16000 for span in speech for sample in (span["start"], span["end"])]
    if model.is_multilingual:
        mel = whisper.log_mel_spectrogram(
            whisper.pad_or_trim(samples), n_mels=model.dims.n_mels
        ).to(model.device)
        if settings.compute_type == "float16":
            mel = mel.half()
        _, probabilities = model.detect_language(mel)
        language = max(probabilities, key=probabilities.get)
        if language != settings.language or probabilities[language] < 0.65:
            raise ReviewRequired(
                f"Audio was heard as {language} with {probabilities[language]:.0%} confidence, "
                f"not {settings.language}"
            )
    # English-only models still use Crowbarr's separate multilingual CPU preflight.
    result = model.transcribe(
        samples, language=settings.language, task="transcribe", word_timestamps=True,
        condition_on_previous_text=False, beam_size=5, temperature=0,
        fp16=settings.compute_type == "float16", verbose=None, clip_timestamps=clips,
        hallucination_silence_threshold=2.0,
    )
    words, issues = [], []
    for segment in result["segments"]:
        uncertain = segment["avg_logprob"] < -1.0
        if uncertain:
            issues.append(f"Uncertain speech near {segment['start']:.1f}s")
        for word in segment.get("words", []):
            start, end, probability = word["start"], word["end"], word["probability"]
            if not all(math.isfinite(value) for value in (start, end, probability)):
                raise ReviewRequired("Intel Whisper returned invalid word timestamps or confidence")
            if 0 <= start < end <= duration + 0.1 and word["word"].strip():
                words.append(Word(start, end, word["word"].strip(), 0.0 if uncertain else probability))
        callback = getattr(transcribe, "progress", None)
        if callback:
            callback(segment["end"], duration)
    if not words:
        raise ReviewRequired("No speech found in the selected audio track")
    if sum(word.probability < 0.5 for word in words) / len(words) > 0.1:
        issues.append("More than 10% of recognized words have low confidence")
    return words, issues


def transcribe_intel(audio: Path, settings: Settings, cache: Path):
    from .inference import transcribe

    global _model, _key
    if settings.compute_type not in {"float16", "float32"}:
        raise ValueError("Intel GPU processing requires float16 or float32 compute")
    transcribe.runtime = {
        "backend": "xpu", "compute_type": settings.compute_type,
        "requested_backend": "xpu", "fallback_reason": None,
    }
    try:
        return _recognize(audio, settings, cache)
    except (RuntimeError, ValueError, ImportError):
        if not settings.cpu_fallback:
            raise
        log.warning("Intel GPU recognition failed; retrying on CPU", exc_info=True)
        _model, _key = None, None
        gc.collect()
        # Retrying the entire bounded audio chunk also handles failures during decode,
        # rather than only failures while the model is being initialized.
        result = transcribe(audio, settings.model_copy(update={"device": "cpu", "compute_type": "int8"}), cache)
        transcribe.runtime.update(
            requested_backend="xpu", fallback_reason="Intel GPU recognition failed; retried on CPU"
        )
        return result
