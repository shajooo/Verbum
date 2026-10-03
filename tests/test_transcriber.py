import numpy as np

from app import transcriber


def test_auto_uses_cpu_int8(monkeypatch):
    calls = []

    def fake(audio, model, language, device, compute):
        calls.append((device, compute))
        return "ok"

    monkeypatch.setattr(transcriber, "_transcribe_with_device", fake)
    assert transcriber.transcribe(np.empty(0), "small", "auto", "auto", "auto") == "ok"
    assert calls == [("cpu", "int8")]


def test_explicit_cuda_falls_back_after_inference_error(monkeypatch):
    calls = []

    def fake(audio, model, language, device, compute):
        calls.append((device, compute))
        if device == "cuda":
            raise RuntimeError("missing CUDA runtime")
        return "ok"

    monkeypatch.setattr(transcriber, "_transcribe_with_device", fake)
    assert transcriber.transcribe(np.empty(0), "small", "auto", "cuda", "auto") == "ok"
    assert calls == [("cuda", "float16"), ("cpu", "int8")]
