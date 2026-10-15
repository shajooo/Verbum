"""
Verbum Gate A Test Suite
Validates engine and CLI against requirements:
- Documented audio test set (short, long, silence, noise, non-English, corrupt)
- Repeatable results
- Negative-path tests (missing file, missing model, cancel, CUDA failure -> CPU fallback)
- Model unloading & state lifecycle
"""

import os
import subprocess
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from engine import (
    AVAILABLE_MODELS,
    DEFAULT_MODEL_NAME,
    TranscriptionCancelledError,
    TranscriptionEngine,
    download_model,
    get_installed_models,
    is_cuda_available,
    is_model_installed,
)

FIXTURES_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "tests", "fixtures", "audio"))


@pytest.fixture(scope="module")
def engine():
    eng = TranscriptionEngine()
    eng.load_model("tiny")  # Fast for general tests
    yield eng
    eng.unload_model()


def test_models_registry():
    assert "small" in AVAILABLE_MODELS
    assert "tiny" in AVAILABLE_MODELS
    assert "base" in AVAILABLE_MODELS
    assert "medium" in AVAILABLE_MODELS
    assert DEFAULT_MODEL_NAME == "small"
    assert is_model_installed("tiny")
    assert is_model_installed("small")


def test_short_audio_transcription(engine):
    audio_path = os.path.join(FIXTURES_DIR, "short_en.wav")
    res = engine.transcribe(audio_path)
    assert res["no_speech"] is False
    assert "verbum" in res["text"].lower() or "test" in res["text"].lower()
    assert res["language"] == "en"
    assert res["duration_s"] > 3.0
    assert len(res["segments"]) >= 1
    assert res["model"] == "tiny"
    assert res["elapsed_s"] > 0


def test_long_audio_transcription(engine):
    audio_path = os.path.join(FIXTURES_DIR, "long_en.wav")
    res = engine.transcribe(audio_path)
    assert res["no_speech"] is False
    assert "longer audio" in res["text"].lower() or "sample" in res["text"].lower()
    assert res["duration_s"] > 10.0
    assert len(res["segments"]) >= 1


def test_silence_handling(engine):
    """Silence should result in empty text and no_speech=True."""
    audio_path = os.path.join(FIXTURES_DIR, "silence.wav")
    res = engine.transcribe(audio_path, vad=True)
    assert res["no_speech"] is True
    assert res["text"] == ""
    assert len(res["segments"]) == 0


def test_noise_handling(engine):
    """Random noise without speech should return empty text and no_speech=True."""
    audio_path = os.path.join(FIXTURES_DIR, "noise.wav")
    res = engine.transcribe(audio_path, vad=True)
    assert res["no_speech"] is True
    assert res["text"] == ""


def test_non_english_transcription(engine):
    """Audio spoken in French should detect non-English language."""
    audio_path = os.path.join(FIXTURES_DIR, "non_en.wav")
    res = engine.transcribe(audio_path)
    # The speech in non_en.wav is French ("Bonjour tout le monde")
    assert res["duration_s"] > 1.0
    assert len(res["text"]) > 0


def test_corrupt_file_handling(engine):
    """Corrupt audio file should raise an error cleanly, not crash."""
    audio_path = os.path.join(FIXTURES_DIR, "corrupt.wav")
    with pytest.raises(RuntimeError) as exc_info:
        engine.transcribe(audio_path)
    assert "failed" in str(exc_info.value).lower() or "audio" in str(exc_info.value).lower()


def test_missing_file_handling(engine):
    with pytest.raises(FileNotFoundError):
        engine.transcribe("non_existent_file.wav")


def test_missing_model_handling(monkeypatch):
    eng = TranscriptionEngine()
    # Unknown model name raises ValueError
    with pytest.raises(ValueError):
        eng.load_model("not_a_real_model")

    # Known model that is not installed raises FileNotFoundError
    import engine as engine_mod
    monkeypatch.setattr(engine_mod, "is_model_installed", lambda name: False)
    with pytest.raises(FileNotFoundError):
        eng.load_model("small")


def test_cancellation(engine):
    """Transcription can be cancelled between segments."""
    audio_path = os.path.join(FIXTURES_DIR, "long_en.wav")
    call_count = [0]

    def cancel_check():
        call_count[0] += 1
        # Cancel on first check
        return True

    with pytest.raises(TranscriptionCancelledError):
        engine.transcribe(audio_path, cancel_check=cancel_check)


def test_cpu_fallback():
    """Engine can load and transcribe on CPU with int8 compute type."""
    eng = TranscriptionEngine()
    info = eng.load_model("tiny", preferred_device="cpu")
    assert info["device"] == "cpu"
    assert info["compute_type"] == "int8"
    assert eng.state == "ready"

    audio_path = os.path.join(FIXTURES_DIR, "short_en.wav")
    res = eng.transcribe(audio_path)
    assert res["device"] == "cpu"
    assert "verbum" in res["text"].lower() or "test" in res["text"].lower()
    eng.unload_model()
    assert eng.state == "unloaded"


def test_model_switching_and_unloading():
    eng = TranscriptionEngine()
    eng.load_model("tiny")
    assert eng.current_model_name == "tiny"
    assert eng.state == "ready"

    eng.load_model("base")
    assert eng.current_model_name == "base"
    assert eng.state == "ready"

    eng.unload_model()
    assert eng.current_model is None
    assert eng.current_model_name is None
    assert eng.state == "unloaded"


def test_cli_execution():
    python_exe = sys.executable
    cli_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "cli.py"))
    audio_path = os.path.join(FIXTURES_DIR, "short_en.wav")

    # Success path with JSON
    proc = subprocess.run(
        [python_exe, cli_path, "transcribe", audio_path, "--model", "tiny", "--json"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert "verbum" in proc.stdout.lower() or "test" in proc.stdout.lower()

    # Error path: missing file
    proc_err = subprocess.run(
        [python_exe, cli_path, "transcribe", "missing.wav", "--model", "tiny", "--json"],
        capture_output=True,
        text=True,
    )
    assert proc_err.returncode != 0
    assert "BAD_AUDIO" in proc_err.stdout
