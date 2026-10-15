"""
Verbum Transcription Engine
Standalone ASR engine using faster-whisper (CTranslate2).
Supports Windows CUDA 12 GPU acceleration with graceful CPU (int8) fallback.
Models are stored in %APPDATA%/Verbum/models.
"""

import gc
import os
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

# ---------------------------------------------------------------------------
# 1. Environment & CUDA Setup
# ---------------------------------------------------------------------------

def _setup_cuda_dlls() -> None:
    """Ensure Windows finds NVIDIA CUDA 12 and cuDNN DLLs from site-packages."""
    if sys.platform != "win32":
        return
    try:
        import site
        site_packages = site.getsitepackages()
        user_site = site.getusersitepackages() if hasattr(site, "getusersitepackages") else ""
        all_sites = list(site_packages)
        if user_site and user_site not in all_sites:
            all_sites.append(user_site)

        for p in all_sites:
            nvidia_dir = os.path.join(p, "nvidia")
            if os.path.isdir(nvidia_dir):
                for sub in os.listdir(nvidia_dir):
                    bin_dir = os.path.join(nvidia_dir, sub, "bin")
                    if os.path.isdir(bin_dir):
                        try:
                            os.add_dll_directory(bin_dir)
                        except Exception:
                            pass
                        cur_path = os.environ.get("PATH", "")
                        if bin_dir not in cur_path:
                            os.environ["PATH"] = bin_dir + os.pathsep + cur_path
    except Exception:
        pass

_setup_cuda_dlls()

# Patch PyAV if metadata_errors kwarg was passed
try:
    import av
    _orig_av_open = av.open

    def _safe_av_open(*args: Any, **kwargs: Any) -> Any:
        try:
            return _orig_av_open(*args, **kwargs)
        except TypeError as e:
            if "metadata_errors" in str(e) or "metadata_errors" in kwargs:
                kwargs.pop("metadata_errors", None)
                return _orig_av_open(*args, **kwargs)
            raise

    av.open = _safe_av_open
except Exception:
    pass

import ctranslate2
from faster_whisper import WhisperModel

# ---------------------------------------------------------------------------
# 2. Configuration & Model Registry
# ---------------------------------------------------------------------------

def get_models_dir() -> str:
    """Return local model storage path in %APPDATA%/Verbum/models."""
    appdata = os.environ.get("APPDATA")
    if not appdata:
        appdata = os.path.expanduser("~")
    path = os.path.join(appdata, "Verbum", "models")
    os.makedirs(path, exist_ok=True)
    return path

AVAILABLE_MODELS: Dict[str, Dict[str, Any]] = {
    "tiny": {
        "repo_id": "Systran/faster-whisper-tiny",
        "size_mb": 75,
        "approx_vram_mb": 200,
        "default_gpu_compute": "float16",
    },
    "base": {
        "repo_id": "Systran/faster-whisper-base",
        "size_mb": 145,
        "approx_vram_mb": 300,
        "default_gpu_compute": "float16",
    },
    "small": {
        "repo_id": "Systran/faster-whisper-small",
        "size_mb": 480,
        "approx_vram_mb": 800,
        "default_gpu_compute": "float16",
    },
    "medium": {
        "repo_id": "Systran/faster-whisper-medium",
        "size_mb": 1500,
        "approx_vram_mb": 2000,
        "default_gpu_compute": "int8_float16",
    },
}

DEFAULT_MODEL_NAME = "small"


def is_cuda_available() -> bool:
    """Check if CUDA device is present and functional via CTranslate2."""
    try:
        if ctranslate2.get_cuda_device_count() <= 0:
            return False
        # On Windows, verify that CUDA 12 / 11 runtime DLLs can actually be loaded
        if sys.platform == "win32":
            import ctypes
            try:
                ctypes.CDLL("cublas64_12.dll")
            except OSError:
                try:
                    ctypes.CDLL("cublas64_11.dll")
                except OSError:
                    return False
        return True
    except Exception:
        return False


def get_model_dir(name: str) -> str:
    """Get absolute path to a specific model's directory."""
    return os.path.join(get_models_dir(), name)


def is_model_installed(name: str) -> bool:
    """Check if model binary files exist locally."""
    model_dir = get_model_dir(name)
    bin_path = os.path.join(model_dir, "model.bin")
    return os.path.isfile(bin_path) and os.path.getsize(bin_path) > 0


def get_installed_models() -> List[str]:
    """Return list of model names currently installed locally."""
    return [name for name in AVAILABLE_MODELS if is_model_installed(name)]


def download_model(
    name: str,
    on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> str:
    """
    Explicitly download a model to %APPDATA%/Verbum/models/<name>.
    on_progress callback receives dict: {"percent": float, "downloaded_bytes": int, "total_bytes": int, "status": str}
    """
    if name not in AVAILABLE_MODELS:
        raise ValueError(f"Unknown model name '{name}'. Available: {list(AVAILABLE_MODELS.keys())}")

    import tqdm
    from huggingface_hub import snapshot_download

    target_dir = get_model_dir(name)
    repo_id = AVAILABLE_MODELS[name]["repo_id"]

    class DownloadProgressTqdm(tqdm.tqdm):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self._report()

        def update(self, n: int = 1) -> None:
            super().update(n)
            self._report()

        def _report(self) -> None:
            if on_progress and self.total:
                pct = round((self.n / self.total) * 100, 1)
                on_progress({
                    "percent": pct,
                    "downloaded_bytes": self.n,
                    "total_bytes": self.total,
                    "status": f"Downloading {name} ({pct}%)",
                })

    if on_progress:
        on_progress({"percent": 0.0, "status": f"Starting download for {name}..."})

    snapshot_download(
        repo_id=repo_id,
        local_dir=target_dir,
        tqdm_class=DownloadProgressTqdm if on_progress else None,
    )

    if on_progress:
        on_progress({"percent": 100.0, "status": f"Download complete for {name}"})

    return target_dir


# ---------------------------------------------------------------------------
# 3. Transcription Engine
# ---------------------------------------------------------------------------

class TranscriptionCancelledError(Exception):
    """Raised when transcription is aborted by user/cancellation flag."""
    pass


class TranscriptionEngine:
    """
    Manages Whisper model lifecycle and transcription execution.
    Handles lazy loading, VRAM cleanup, CUDA fallback, and progress reporting.
    """

    def __init__(self) -> None:
        self.current_model: Optional[WhisperModel] = None
        self.current_model_name: Optional[str] = None
        self.current_device: str = "cpu"
        self.current_compute_type: str = "int8"
        self.state: str = "unloaded"  # unloaded | downloading | loading | ready | error
        self.error_message: Optional[str] = None
        self.cuda_fallback: bool = False

    def unload_model(self) -> None:
        """Unload loaded model and reclaim VRAM / RAM."""
        if self.current_model is not None:
            del self.current_model
            self.current_model = None
            self.current_model_name = None
            self.state = "unloaded"
            self.error_message = None
            gc.collect()

    def load_model(
        self,
        name: str,
        preferred_device: Optional[str] = None,
        preferred_compute_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Load a model by name. Unloads previous model first.
        Falls back to CPU (int8) if CUDA fails.
        """
        if name not in AVAILABLE_MODELS:
            raise ValueError(f"Unknown model name '{name}'. Must be one of {list(AVAILABLE_MODELS.keys())}")

        if not is_model_installed(name):
            raise FileNotFoundError(
                f"Model '{name}' is not downloaded yet. Please trigger an explicit download first."
            )

        self.unload_model()
        self.state = "loading"
        self.cuda_fallback = False

        model_path = get_model_dir(name)
        target_device = preferred_device or ("cuda" if is_cuda_available() else "cpu")

        if target_device == "cuda":
            compute = preferred_compute_type or AVAILABLE_MODELS[name]["default_gpu_compute"]
            try:
                self.current_model = WhisperModel(
                    model_path,
                    device="cuda",
                    compute_type=compute,
                )
                self.current_device = "cuda"
                self.current_compute_type = compute
                self.current_model_name = name
                self.state = "ready"
                self.error_message = None
                return {
                    "model": name,
                    "device": "cuda",
                    "compute_type": compute,
                    "state": "ready",
                    "cuda_fallback": False,
                }
            except Exception as e:
                # Fall back to CPU
                self.cuda_fallback = True
                self.error_message = f"CUDA failed ({e}); falling back to CPU."

        # CPU fallback / execution
        try:
            compute = "int8"
            self.current_model = WhisperModel(
                model_path,
                device="cpu",
                compute_type=compute,
            )
            self.current_device = "cpu"
            self.current_compute_type = compute
            self.current_model_name = name
            self.state = "ready"
            return {
                "model": name,
                "device": "cpu",
                "compute_type": compute,
                "state": "ready",
                "cuda_fallback": self.cuda_fallback,
                "fallback_reason": self.error_message if self.cuda_fallback else None,
            }
        except Exception as e:
            self.state = "error"
            self.error_message = f"Failed to load model '{name}' on CPU: {e}"
            raise RuntimeError(self.error_message) from e

    def transcribe(
        self,
        audio_source: Union[str, Any],
        language: Optional[str] = None,
        vad: bool = True,
        initial_prompt: Optional[str] = None,
        on_progress: Optional[Callable[[float], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        """
        Transcribe audio file or audio array.
        Reports progress between segments.
        Returns detailed dict with text, language, segments, and metadata.
        """
        if self.current_model is None:
            # Auto-load default model if installed, otherwise load first available
            if is_model_installed(DEFAULT_MODEL_NAME):
                self.load_model(DEFAULT_MODEL_NAME)
            else:
                installed = get_installed_models()
                if installed:
                    self.load_model(installed[0])
                else:
                    raise RuntimeError("No models are installed. Please download a model first.")

        if isinstance(audio_source, str):
            if not os.path.isfile(audio_source):
                raise FileNotFoundError(f"Audio file not found: {audio_source}")
            if os.path.getsize(audio_source) == 0:
                raise ValueError(f"Audio file is empty (0 bytes): {audio_source}")

        if cancel_check and cancel_check():
            raise TranscriptionCancelledError("Transcription cancelled before start.")

        start_time = time.perf_counter()

        # Execute transcribe
        lang_arg = None if (not language or language.lower() in ("auto", "none")) else language

        def _run_transcribe():
            segments_gen, info = self.current_model.transcribe(
                audio_source,
                language=lang_arg,
                vad_filter=vad,
                initial_prompt=initial_prompt,
            )
            duration_s = float(info.duration) if hasattr(info, "duration") and info.duration else 0.0
            segments_list: List[Dict[str, Any]] = []

            for seg in segments_gen:
                if cancel_check and cancel_check():
                    raise TranscriptionCancelledError("Transcription cancelled by user.")

                segments_list.append({
                    "start": round(float(seg.start), 2),
                    "end": round(float(seg.end), 2),
                    "text": seg.text.strip(),
                    "avg_logprob": round(float(seg.avg_logprob), 3) if hasattr(seg, "avg_logprob") else 0.0,
                    "no_speech_prob": round(float(seg.no_speech_prob), 3) if hasattr(seg, "no_speech_prob") else 0.0,
                })

                if on_progress and duration_s > 0:
                    pct = min(1.0, float(seg.end) / duration_s)
                    on_progress(pct)

            return segments_list, info, duration_s

        try:
            segments_list, info, duration_s = _run_transcribe()
        except TranscriptionCancelledError:
            raise
        except Exception as e:
            # If CUDA failed (missing DLLs, driver mismatch, OOM), fall back to CPU int8 gracefully
            if self.current_device == "cuda":
                print(f"[Engine] CUDA transcription failed ({e}); falling back to CPU (int8)...", flush=True)
                self.load_model(self.current_model_name or DEFAULT_MODEL_NAME, preferred_device="cpu")
                return self.transcribe(
                    audio_source,
                    language=language,
                    vad=vad,
                    initial_prompt=initial_prompt,
                    on_progress=on_progress,
                    cancel_check=cancel_check,
                )
            raise RuntimeError(f"Audio decoding or transcription failed: {e}") from e

        elapsed_s = time.perf_counter() - start_time

        # Extract combined text
        combined_text = " ".join(s["text"] for s in segments_list if s["text"]).strip()

        # Check for no speech condition
        is_no_speech = False
        if not combined_text:
            is_no_speech = True
        elif len(segments_list) > 0 and all(s.get("no_speech_prob", 0) > 0.85 for s in segments_list):
            is_no_speech = True
            combined_text = ""

        if on_progress:
            on_progress(1.0)

        return {
            "text": combined_text,
            "no_speech": is_no_speech,
            "language": info.language if hasattr(info, "language") else "en",
            "language_prob": round(float(info.language_probability), 3) if hasattr(info, "language_probability") else 1.0,
            "duration_s": round(duration_s, 2),
            "segments": segments_list if not is_no_speech else [],
            "model": self.current_model_name,
            "device": self.current_device,
            "compute_type": self.current_compute_type,
            "elapsed_s": round(elapsed_s, 3),
            "cuda_fallback": self.cuda_fallback,
        }
