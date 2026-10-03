from __future__ import annotations

import logging
import numpy as np

LOG = logging.getLogger(__name__)


def resolve_runtime(device: str, compute_type: str) -> tuple[str, str]:
    requested_device = "cpu" if device == "auto" else device
    requested_compute = "int8" if compute_type == "auto" and requested_device == "cpu" else (
        "float16" if compute_type == "auto" else compute_type)
    return requested_device, requested_compute


def load_model(model_name: str, device: str, compute_type: str):
    from faster_whisper import WhisperModel
    return WhisperModel(model_name, device=device, compute_type=compute_type)


def transcribe_loaded_model(model, audio: np.ndarray, language: str) -> str:
    language_arg = None if language == "auto" else language
    segments, _ = model.transcribe(audio, language=language_arg, vad_filter=True)
    text = "".join(segment.text for segment in segments).strip()
    if not text:
        segments, _ = model.transcribe(audio, language=language_arg, vad_filter=False)
        text = "".join(segment.text for segment in segments).strip()
    return text


def _transcribe_with_device(audio: np.ndarray, model_name: str, language: str, device: str, compute_type: str) -> str:
    return transcribe_loaded_model(load_model(model_name, device, compute_type), audio, language)


def transcribe(audio: np.ndarray, model_name: str, language: str, device: str, compute_type: str) -> str:
    """Transcribe locally, favouring reliable CPU inference for Auto.

    CTranslate2 can construct a CUDA model even when CUDA inference DLLs are
    missing, then fail only on the first audio segment.  Auto therefore uses
    CPU int8; an explicit CUDA choice still falls back safely if that runtime
    is incomplete.
    """
    requested_device, requested_compute = resolve_runtime(device, compute_type)
    try:
        return _transcribe_with_device(audio, model_name, language, requested_device, requested_compute)
    except Exception as exc:
        if requested_device != "cuda":
            raise
        LOG.warning("CUDA inference failed, falling back to CPU int8: %s", exc)
        return _transcribe_with_device(audio, model_name, language, "cpu", "int8")
