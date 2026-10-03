from __future__ import annotations

import multiprocessing as mp
import traceback

from .transcriber import load_model, resolve_runtime, transcribe_loaded_model


def _run(settings: dict, commands: mp.Queue, results: mp.Queue) -> None:
    """Keep one Whisper model loaded and accept recordings until asked to stop."""
    requested_device, requested_compute = resolve_runtime(settings["device"], settings["compute_type"])
    try:
        model = load_model(settings["model"], requested_device, requested_compute)
        active_device = requested_device
        if active_device == "cuda":
            # Test if CUDA inference actually works (fails if cuBLAS DLLs are missing)
            import numpy as np
            try:
                transcribe_loaded_model(model, np.zeros(16000, dtype=np.float32), "en")
            except Exception:
                model = load_model(settings["model"], "cpu", "int8")
                active_device = "cpu"
        results.put(("ready", ""))
    except Exception:
        results.put(("startup_error", traceback.format_exc()))
        return

    while True:
        command = commands.get()
        if command is None:
            return
        request_id, audio = command
        try:
            text = transcribe_loaded_model(model, audio, settings["language"])
            results.put(("result", request_id, "ok", text))
        except Exception:
            # Explicit CUDA can load but fail on the first audio segment if its
            # inference DLLs are missing. Keep the CPU fallback for later use.
            if active_device == "cuda":
                try:
                    model = load_model(settings["model"], "cpu", "int8")
                    active_device = "cpu"
                    text = transcribe_loaded_model(model, audio, settings["language"])
                    results.put(("result", request_id, "ok", text))
                    continue
                except Exception:
                    pass
            results.put(("result", request_id, "error", traceback.format_exc()))


def start_worker(settings: dict) -> tuple[mp.Process, mp.Queue, mp.Queue]:
    commands: mp.Queue = mp.Queue()
    results: mp.Queue = mp.Queue()
    process = mp.Process(target=_run, args=(settings, commands, results), daemon=True)
    process.start()
    return process, commands, results
