from __future__ import annotations

import threading
from typing import Callable
import numpy as np
import sounddevice as sd


class Recorder:
    """An in-memory 16 kHz mono recorder; stream exists only while recording."""
    sample_rate = 16000

    def __init__(self, device: str = "default") -> None:
        self.device = None if device == "default" else device
        self._chunks: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._stream: sd.InputStream | None = None
        self._level_callback: Callable[[float], None] | None = None

    @property
    def recording(self) -> bool:
        return self._stream is not None

    def set_level_callback(self, callback: Callable[[float], None] | None) -> None:
        """Receive RMS measurements from this recorder's existing input stream."""
        self._level_callback = callback

    def start(self) -> None:
        if self.recording:
            return
        with self._lock:
            self._chunks.clear()

        def callback(indata, frames, time, status):
            if status:
                # Capture remains usable; sounddevice surfaces recoverable flags here.
                pass
            with self._lock:
                self._chunks.append(indata.copy())
            level_callback = self._level_callback
            if level_callback is not None:
                try:
                    # A scalar RMS is inexpensive and avoids sending samples to the UI.
                    rms = float(np.sqrt(np.mean(np.square(indata, dtype=np.float32))))
                    level_callback(rms)
                except Exception:
                    # Audio capture must never be interrupted by a visual update.
                    pass

        stream = sd.InputStream(device=self.device, samplerate=self.sample_rate,
                                channels=1, dtype="float32", callback=callback)
        stream.start()
        self._stream = stream

    def stop(self) -> np.ndarray:
        stream, self._stream = self._stream, None
        if stream is not None:
            stream.stop()
            stream.close()
        with self._lock:
            if not self._chunks:
                return np.empty(0, dtype=np.float32)
            return np.concatenate(self._chunks, axis=0).reshape(-1).copy()
